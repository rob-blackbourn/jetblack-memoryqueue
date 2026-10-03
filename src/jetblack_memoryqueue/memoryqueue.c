#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <string.h>
#include <limits.h>

/* Chunks own private buffer exporters: callers cannot release our exports.
 * The mutex protects links and counters, never calls into Python. Allocations,
 * buffer callbacks and decrefs happen outside it to allow reentrant exporters.
 */
typedef struct Chunk {
    PyObject *view;
    struct Chunk *next;
} Chunk;

typedef struct {
    PyObject_HEAD
    Chunk *head, *tail;
    Py_ssize_t length, count;
#if PY_VERSION_HEX >= 0x030E0000
    PyMutex mutex;
#endif
} Queue;

#if PY_VERSION_HEX >= 0x030E0000
#define LOCK(q) PyMutex_Lock(&(q)->mutex)
#define UNLOCK(q) PyMutex_Unlock(&(q)->mutex)
#else
#define LOCK(q) ((void)0)
#define UNLOCK(q) ((void)0)
#endif

static void free_chunks(Chunk *node)
{
    while (node) {
        Chunk *next = node->next;
        Py_DECREF(node->view);
        PyMem_Free(node);
        node = next;
    }
}

static PyObject *byte_view(PyObject *obj)
{
    PyObject *view = PyMemoryView_FromObject(obj);
    if (!view) return NULL;
    Py_buffer *buf = PyMemoryView_GET_BUFFER(view);
    if (buf->ndim != 1 || buf->itemsize != 1 ||
        !buf->format || strcmp(buf->format, "B") != 0) {
        Py_DECREF(view);
        PyErr_SetString(PyExc_TypeError,
                        "expected a one-dimensional unsigned-byte buffer (format 'B')");
        return NULL;
    }
    return view;
}

/* Each public view gets its own CPython managed buffer. Sharing a memoryview's
 * managed-buffer export counter across threads is unsafe on CPython 3.14.
 * This immutable exporter pins one private view and exposes its metadata without
 * modifying that view or its managed buffer when readers export/release it. */
typedef struct {
    PyObject_HEAD
    PyObject *view;
} BufferOwner;

static Py_buffer *owner_buffer(PyObject *owner)
{ return PyMemoryView_GET_BUFFER(((BufferOwner *)owner)->view); }

static int owner_traverse(BufferOwner *self, visitproc visit, void *arg)
{ Py_VISIT(self->view); return 0; }
static int owner_clear(BufferOwner *self)
{ Py_CLEAR(self->view); return 0; }
static void owner_dealloc(BufferOwner *self)
{
    PyObject_GC_UnTrack(self);
    owner_clear(self);
    PyObject_GC_Del(self);
}
static int owner_getbuffer(BufferOwner *self, Py_buffer *out, int flags)
{
    Py_buffer *src = owner_buffer((PyObject *)self);
    if ((flags & PyBUF_WRITABLE) && src->readonly) {
        PyErr_SetString(PyExc_BufferError, "buffer is read-only"); return -1;
    }
    if ((((flags & PyBUF_C_CONTIGUOUS) == PyBUF_C_CONTIGUOUS) ||
         ((flags & PyBUF_F_CONTIGUOUS) == PyBUF_F_CONTIGUOUS) ||
         ((flags & PyBUF_ANY_CONTIGUOUS) == PyBUF_ANY_CONTIGUOUS) ||
         ((flags & PyBUF_STRIDES) != PyBUF_STRIDES)) &&
        !PyBuffer_IsContiguous(src, 'C')) {
        PyErr_SetString(PyExc_BufferError, "buffer is not contiguous"); return -1;
    }
    if ((flags & PyBUF_INDIRECT) != PyBUF_INDIRECT && src->suboffsets) {
        PyErr_SetString(PyExc_BufferError, "buffer requires suboffsets"); return -1;
    }
    *out = *src;
    out->obj = Py_NewRef((PyObject *)self);
    if (!(flags & PyBUF_FORMAT)) out->format = NULL;
    if ((flags & PyBUF_STRIDES) != PyBUF_STRIDES) out->strides = NULL;
    if (!(flags & PyBUF_ND)) { out->shape = NULL; out->ndim = 1; }
    return 0;
}
static PyObject *owner_item(BufferOwner *self, Py_ssize_t index)
{ return PySequence_GetItem(self->view, index); }
static PyBufferProcs owner_buffer_procs = { (getbufferproc)owner_getbuffer, NULL };
static PySequenceMethods owner_sequence = { .sq_item = (ssizeargfunc)owner_item };
static PyTypeObject owner_type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "jetblack_memoryqueue.memoryqueue._BufferOwner",
    .tp_basicsize = sizeof(BufferOwner),
    .tp_dealloc = (destructor)owner_dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
    .tp_traverse = (traverseproc)owner_traverse,
    .tp_clear = (inquiry)owner_clear,
    .tp_as_buffer = &owner_buffer_procs,
    .tp_as_sequence = &owner_sequence,
};

static Chunk *make_chunk(PyObject *obj)
{
    PyObject *view = byte_view(obj);
    if (!view) return NULL;
    Chunk *node = PyMem_Malloc(sizeof(*node));
    if (!node) { Py_DECREF(view); PyErr_NoMemory(); return NULL; }
    BufferOwner *owner = PyObject_GC_New(BufferOwner, &owner_type);
    if (!owner) { Py_DECREF(view); PyMem_Free(node); return NULL; }
    owner->view = view;
    PyObject_GC_Track(owner);
    node->view = (PyObject *)owner;
    node->next = NULL;
    return node;
}

static int queue_clear(Queue *self)
{
    LOCK(self);
    Chunk *head = self->head;
    self->head = self->tail = NULL;
    self->length = self->count = 0;
    UNLOCK(self);
    free_chunks(head);
    return 0;
}

static int queue_traverse(Queue *self, visitproc visit, void *arg)
{
    /* GC traversal runs with the GIL or with all other threads stopped.
     * Taking a mutex here could deadlock with a stopped thread. */
    Py_VISIT(Py_TYPE(self));
    for (Chunk *p = self->head; p; p = p->next) Py_VISIT(p->view);
    return 0;
}

static void queue_dealloc(Queue *self)
{
    PyTypeObject *type = Py_TYPE(self);
    PyObject_GC_UnTrack(self);
    queue_clear(self);
    type->tp_free((PyObject *)self);
    Py_DECREF(type);
}

static int queue_init(Queue *self, PyObject *args, PyObject *kwargs)
{
    if (kwargs && PyDict_Size(kwargs)) {
        PyErr_SetString(PyExc_TypeError, "memoryqueue takes no keyword arguments");
        return -1;
    }
    Chunk *head = NULL, *tail = NULL;
    Py_ssize_t length = 0, count = PyTuple_GET_SIZE(args);
    for (Py_ssize_t i = 0; i < count; ++i) {
        Chunk *node = make_chunk(PyTuple_GET_ITEM(args, i));
        if (!node) { free_chunks(head); return -1; }
        Py_ssize_t size = owner_buffer(node->view)->len;
        if (size > PY_SSIZE_T_MAX - length) {
            free_chunks(node); free_chunks(head);
            PyErr_SetString(PyExc_OverflowError, "queue is too large"); return -1;
        }
        length += size;
        if (tail) tail->next = node; else head = node;
        tail = node;
    }
    LOCK(self);
    Chunk *old = self->head;
    self->head = head; self->tail = tail;
    self->length = length; self->count = count;
    UNLOCK(self);
    free_chunks(old);
    return 0;
}

static Py_ssize_t queue_length(Queue *self)
{
    LOCK(self);
    Py_ssize_t length = self->length;
    UNLOCK(self);
    return length;
}

/* Snapshot chunk ownership without allocating while holding the mutex. */
static PyObject *snapshot(Queue *self)
{
    for (;;) {
        LOCK(self);
        Py_ssize_t count = self->count;
        UNLOCK(self);
        PyObject *result = PyTuple_New(count);
        if (!result) return NULL;
        LOCK(self);
        if (self->count != count) {
            UNLOCK(self); Py_DECREF(result); continue;
        }
        Py_ssize_t i = 0;
        for (Chunk *p = self->head; p; p = p->next)
            PyTuple_SET_ITEM(result, i++, Py_NewRef(p->view));
        UNLOCK(self);
        return result;
    }
}

static PyObject *queue_append(Queue *self, PyObject *obj)
{
    Chunk *node = make_chunk(obj);
    if (!node) return NULL;
    Py_ssize_t size = owner_buffer(node->view)->len;
    LOCK(self);
    if (size > PY_SSIZE_T_MAX - self->length || self->count == PY_SSIZE_T_MAX) {
        UNLOCK(self); free_chunks(node);
        PyErr_SetString(PyExc_OverflowError, "queue is too large"); return NULL;
    }
    if (self->tail) self->tail->next = node; else self->head = node;
    self->tail = node; self->length += size; ++self->count;
    UNLOCK(self);
    Py_RETURN_NONE;
}

static PyObject *queue_popleft(Queue *self, PyObject *unused)
{
    LOCK(self);
    Chunk *node = self->head;
    if (!node) {
        UNLOCK(self);
        PyErr_SetString(PyExc_IndexError, "pop from an empty memoryqueue"); return NULL;
    }
    self->head = node->next;
    if (!self->head) self->tail = NULL;
    self->length -= owner_buffer(node->view)->len;
    --self->count;
    UNLOCK(self);
    /* Return a separate view even if another reader holds a snapshot. */
    PyObject *result = PyMemoryView_FromObject(node->view);
    Py_DECREF(node->view); PyMem_Free(node);
    return result;
}

static PyObject *queue_clear_method(Queue *self, PyObject *unused)
{
    queue_clear(self);
    Py_RETURN_NONE;
}

static PyObject *public_views(Queue *self, void *unused)
{
    PyObject *views = snapshot(self);
    if (!views) return NULL;
    PyObject *result = PyTuple_New(PyTuple_GET_SIZE(views));
    if (!result) { Py_DECREF(views); return NULL; }
    for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(views); ++i) {
        PyObject *view = PyMemoryView_FromObject(PyTuple_GET_ITEM(views, i));
        if (!view) { Py_DECREF(views); Py_DECREF(result); return NULL; }
        PyTuple_SET_ITEM(result, i, view);
    }
    Py_DECREF(views);
    return result;
}

static PyObject *queue_items(Queue *self, PyObject *unused)
{
    PyObject *views = public_views(self, NULL);
    if (!views) return NULL;
    PyObject *result = PyObject_GetIter(views);
    Py_DECREF(views);
    return result;
}

static PyObject *flatten(PyObject *views)
{
    Py_ssize_t size = 0;
    for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(views); ++i)
        size += owner_buffer(PyTuple_GET_ITEM(views, i))->len;
    PyObject *result = PyBytes_FromStringAndSize(NULL, size);
    if (!result) return NULL;
    char *dest = PyBytes_AS_STRING(result);
    for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(views); ++i) {
        Py_buffer *buf = owner_buffer(PyTuple_GET_ITEM(views, i));
        if (PyBuffer_ToContiguous(dest, buf, buf->len, 'C') < 0) {
            Py_DECREF(result); return NULL;
        }
        dest += buf->len;
    }
    return result;
}

static PyObject *queue_bytes(Queue *self, PyObject *unused)
{
    PyObject *views = snapshot(self);
    if (!views) return NULL;
    PyObject *result = flatten(views);
    Py_DECREF(views);
    return result;
}

static PyObject *queue_iter(PyObject *self)
{
    /* chain.from_iterable holds a snapshot of chunks, without copying bytes. */
    PyObject *views = public_views((Queue *)self, NULL);
    if (!views) return NULL;
    PyObject *module = PyImport_ImportModule("itertools");
    PyObject *chain = module ? PyObject_GetAttrString(module, "chain") : NULL;
    Py_XDECREF(module);
    PyObject *result = chain ? PyObject_CallMethod(chain, "from_iterable", "(O)", views) : NULL;
    Py_XDECREF(chain); Py_DECREF(views);
    return result;
}

static PyObject *queue_subscript(Queue *self, PyObject *key)
{
    /* Convert user-defined indices before taking the snapshot. */
    Py_ssize_t start = 0, stop = 0, step = 0, index = 0;
    int slice = PySlice_Check(key);
    if (slice) {
        if (PySlice_Unpack(key, &start, &stop, &step) < 0) return NULL;
    } else {
        index = PyNumber_AsSsize_t(key, PyExc_IndexError);
        if (index == -1 && PyErr_Occurred()) return NULL;
    }
    PyObject *views = snapshot(self);
    if (!views) return NULL;
    Py_ssize_t length = 0;
    for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(views); ++i)
        length += owner_buffer(PyTuple_GET_ITEM(views, i))->len;
    PyObject *result = NULL;
    if (!slice) {
        if (index < 0) index += length;
        if (index < 0 || index >= length) {
            PyErr_SetString(PyExc_IndexError, "index out of range"); goto done;
        }
        for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(views); ++i) {
            PyObject *view = PyTuple_GET_ITEM(views, i);
            Py_ssize_t size = owner_buffer(view)->len;
            if (index < size) { result = PySequence_GetItem(view, index); break; }
            index -= size;
        }
    } else if (step != 1) {
        PyObject *data = flatten(views);
        if (!data) goto done;
        /* Use normalized integers so index callbacks are not invoked twice. */
        PyObject *a = PyLong_FromSsize_t(start), *b = PyLong_FromSsize_t(stop);
        PyObject *c = PyLong_FromSsize_t(step);
        PyObject *normalized = a && b && c ? PySlice_New(a, b, c) : NULL;
        Py_XDECREF(a); Py_XDECREF(b); Py_XDECREF(c);
        PyObject *part = data && normalized ? PyObject_GetItem(data, normalized) : NULL;
        Py_XDECREF(normalized); Py_XDECREF(data);
        if (part) { result = PyObject_CallOneArg((PyObject *)Py_TYPE(self), part); Py_DECREF(part); }
    } else {
        Py_ssize_t remaining = PySlice_AdjustIndices(length, &start, &stop, step);
        result = PyObject_CallNoArgs((PyObject *)Py_TYPE(self));
        if (!result) goto done;
        for (Py_ssize_t i = 0; remaining && i < PyTuple_GET_SIZE(views); ++i) {
            PyObject *view = PyTuple_GET_ITEM(views, i);
            Py_ssize_t size = owner_buffer(view)->len;
            if (start >= size) { start -= size; continue; }
            Py_ssize_t take = Py_MIN(remaining, size - start);
            PyObject *local_view = PyMemoryView_FromObject(view);
            PyObject *part = local_view ? PySequence_GetSlice(local_view, start, start + take) : NULL;
            Py_XDECREF(local_view);
            PyObject *ok = part ? queue_append((Queue *)result, part) : NULL;
            Py_XDECREF(part);
            if (!ok) { Py_CLEAR(result); goto done; }
            Py_DECREF(ok); remaining -= take; start = 0;
        }
    }
done:
    Py_DECREF(views);
    return result;
}

static int queue_getbuffer(Queue *self, Py_buffer *buffer, int flags)
{
    PyObject *views = snapshot(self);
    if (!views) return -1;
    PyObject *owner;
    if (PyTuple_GET_SIZE(views) == 1)
        owner = PyMemoryView_FromObject(PyTuple_GET_ITEM(views, 0));
    else
        owner = flatten(views);
    Py_DECREF(views);
    if (!owner) return -1;
    /* Delegate ownership to the actual exporter, so clear/pop cannot invalidate
     * outstanding buffers. Multi-chunk exports are immutable snapshots. */
    int result = PyObject_GetBuffer(owner, buffer, flags);
    Py_DECREF(owner);
    return result;
}

#if PY_VERSION_HEX < 0x030C0000
/* Expose the typing Buffer protocol on 3.11 too. From 3.12, CPython generates
 * this method automatically from bf_getbuffer. */
static PyObject *queue_buffer_method(Queue *self, PyObject *arg)
{
    long flags = PyLong_AsLong(arg);
    if (flags == -1 && PyErr_Occurred()) return NULL;
    if (flags < INT_MIN || flags > INT_MAX) {
        PyErr_SetString(PyExc_OverflowError, "buffer flags out of range"); return NULL;
    }
    Py_buffer buffer;
    if (queue_getbuffer(self, &buffer, (int)flags) < 0) return NULL;
    PyObject *result = PyMemoryView_FromObject(buffer.obj);
    PyBuffer_Release(&buffer);
    return result;
}
#endif

static PyObject *queue_compare(PyObject *self, PyObject *other, int op)
{
    if (op != Py_EQ && op != Py_NE) Py_RETURN_NOTIMPLEMENTED;
    PyObject *rhs;
    if (Py_IS_TYPE(other, Py_TYPE(self))) rhs = queue_bytes((Queue *)other, NULL);
    else if (PyBytes_Check(other) || PyByteArray_Check(other) || PyMemoryView_Check(other))
        rhs = PyObject_Bytes(other);
    else Py_RETURN_NOTIMPLEMENTED;
    if (!rhs) return NULL;
    PyObject *lhs = queue_bytes((Queue *)self, NULL);
    PyObject *result = lhs ? PyObject_RichCompare(lhs, rhs, op) : NULL;
    Py_XDECREF(lhs); Py_DECREF(rhs);
    return result;
}

static PyObject *queue_equals(PyObject *cls, PyObject *args)
{
    PyObject *lhs, *rhs;
    if (!PyArg_ParseTuple(args, "OO:equals", &lhs, &rhs)) return NULL;
    if (!PyObject_TypeCheck(lhs, (PyTypeObject *)cls) ||
        !PyObject_TypeCheck(rhs, (PyTypeObject *)cls)) {
        PyErr_SetString(PyExc_TypeError, "equals expects two memoryqueues"); return NULL;
    }
    return queue_compare(lhs, rhs, Py_EQ);
}

static PyObject *search(Queue *self, PyObject *args, PyObject *kwargs, const char *method)
{
    static char *names[] = {"item", "i", "j", NULL};
    PyObject *item, *i = Py_None, *j = Py_None;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|OO", names, &item, &i, &j)) return NULL;
    PyObject *view = byte_view(item);
    if (!view) return NULL;
    PyObject *needle = PyObject_Bytes(view);
    Py_DECREF(view);
    if (!needle) return NULL;
    Py_ssize_t start = 0, stop = PY_SSIZE_T_MAX;
    if (i != Py_None) start = PyNumber_AsSsize_t(i, PyExc_OverflowError);
    if (!PyErr_Occurred() && j != Py_None) stop = PyNumber_AsSsize_t(j, PyExc_OverflowError);
    if (PyErr_Occurred()) { Py_DECREF(needle); return NULL; }
    PyObject *data = queue_bytes(self, NULL);
    if (!data) { Py_DECREF(needle); return NULL; }
    if (j == Py_None) stop = PyBytes_GET_SIZE(data);
    PyObject *result = NULL;
    if (start < 0 || start > PyBytes_GET_SIZE(data) || stop < start || stop > PyBytes_GET_SIZE(data))
        PyErr_SetString(PyExc_ValueError, "invalid search bounds");
    else
        result = PyObject_CallMethod(data, method, "Onn", needle, start, stop);
    Py_DECREF(data); Py_DECREF(needle);
    return result;
}
static PyObject *queue_find(Queue *self, PyObject *args, PyObject *kwargs)
{ return search(self, args, kwargs, "find"); }
static PyObject *queue_index(Queue *self, PyObject *args, PyObject *kwargs)
{ return search(self, args, kwargs, "index"); }
static PyObject *queue_rfind(Queue *self, PyObject *args, PyObject *kwargs)
{ return search(self, args, kwargs, "rfind"); }
static PyObject *queue_rindex(Queue *self, PyObject *args, PyObject *kwargs)
{ return search(self, args, kwargs, "rindex"); }
static int queue_contains(Queue *self, PyObject *item)
{
    PyObject *args = PyTuple_Pack(1, item);
    if (!args) return -1;
    PyObject *result = search(self, args, NULL, "find");
    Py_DECREF(args);
    if (!result) return -1;
    Py_ssize_t index = PyLong_AsSsize_t(result);
    Py_DECREF(result);
    return index != -1;
}

static PyMethodDef methods[] = {
#if PY_VERSION_HEX < 0x030C0000
    {"__buffer__", (PyCFunction)queue_buffer_method, METH_O, "Export a buffer with the requested flags."},
#endif
    {"append", (PyCFunction)queue_append, METH_O, "Append a buffer without copying its data."},
    {"popleft", (PyCFunction)queue_popleft, METH_NOARGS, "Remove and return the first chunk."},
    {"clear", (PyCFunction)queue_clear_method, METH_NOARGS, "Remove all chunks."},
    {"items", (PyCFunction)queue_items, METH_NOARGS, "Iterate over a snapshot of the chunks."},
    {"__bytes__", (PyCFunction)queue_bytes, METH_NOARGS, "Copy the queued bytes."},
    {"find", (PyCFunction)(void(*)(void))queue_find, METH_VARARGS | METH_KEYWORDS, "Find a byte string within optional bounds."},
    {"index", (PyCFunction)(void(*)(void))queue_index, METH_VARARGS | METH_KEYWORDS, "Find a byte string or raise ValueError."},
    {"rfind", (PyCFunction)(void(*)(void))queue_rfind, METH_VARARGS | METH_KEYWORDS, "Find the last occurrence of a byte string within optional bounds."},
    {"rindex", (PyCFunction)(void(*)(void))queue_rindex, METH_VARARGS | METH_KEYWORDS, "Find the last occurrence of a byte string or raise ValueError."},
    {"equals", (PyCFunction)queue_equals, METH_VARARGS | METH_CLASS, "Compare two queues."},
    {NULL}
};
static PyGetSetDef getsets[] = {
    {"_views", (getter)public_views, NULL, "Read-only snapshot of chunks.", NULL},
    {NULL}
};
static PyType_Slot type_slots[] = {
    {Py_tp_new, PyType_GenericNew}, {Py_tp_init, queue_init},
    {Py_tp_dealloc, queue_dealloc}, {Py_tp_traverse, queue_traverse},
    {Py_tp_clear, queue_clear}, {Py_tp_methods, methods}, {Py_tp_getset, getsets},
    {Py_tp_iter, queue_iter}, {Py_tp_richcompare, queue_compare},
    {Py_tp_hash, PyObject_HashNotImplemented},
    {Py_mp_length, queue_length}, {Py_mp_subscript, queue_subscript},
    {Py_sq_contains, queue_contains}, {Py_bf_getbuffer, queue_getbuffer},
    {0, NULL}
};
static PyType_Spec type_spec = {
    "jetblack_memoryqueue.memoryqueue.memoryqueue", sizeof(Queue), 0,
    Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC, type_slots
};
static int module_exec(PyObject *module)
{
    if (PyType_Ready(&owner_type) < 0) return -1;
    PyObject *type = PyType_FromModuleAndSpec(module, &type_spec, NULL);
    if (!type) return -1;
    int result = PyModule_AddObjectRef(module, "memoryqueue", type);
    Py_DECREF(type);
    return result;
}
static PyModuleDef_Slot module_slots[] = {
    {Py_mod_exec, module_exec},
#if PY_VERSION_HEX >= 0x030E0000
    {Py_mod_gil, Py_MOD_GIL_NOT_USED},
#endif
    {0, NULL}
};
static struct PyModuleDef module_def = {
    PyModuleDef_HEAD_INIT, "memoryqueue", "A chunked byte queue.", 0,
    NULL, module_slots, NULL, NULL, NULL
};
PyMODINIT_FUNC PyInit_memoryqueue(void) { return PyModuleDef_Init(&module_def); }
