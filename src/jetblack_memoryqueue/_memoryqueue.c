#define PY_SSIZE_T_CLEAN
#include <Python.h>

/* PyMemoryView_FromObject(memoryview) shares its managed buffer, whose view
 * count is not synchronized in CPython 3.14. Go through the buffer protocol
 * instead, giving each new view its own managed buffer and a pinned export.
 * The temporary proxy is never exposed and its target is borrowed for the call.
 */
typedef struct {
    PyObject_HEAD
    PyObject *target;
} BufferProxy;

static int
proxy_getbuffer(BufferProxy *self, Py_buffer *buffer, int flags)
{
    return PyObject_GetBuffer(self->target, buffer, flags);
}

static PyBufferProcs proxy_buffer = { .bf_getbuffer = (getbufferproc)proxy_getbuffer };
static PyTypeObject BufferProxyType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "jetblack_memoryqueue._memoryqueue._BufferProxy",
    .tp_basicsize = sizeof(BufferProxy),
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_as_buffer = &proxy_buffer,
};

static PyObject *
independent_view(PyObject *obj)
{
    BufferProxy *proxy = PyObject_New(BufferProxy, &BufferProxyType);
    if (proxy == NULL) return NULL;
    proxy->target = obj;
    PyObject *view = PyMemoryView_FromObject((PyObject *)proxy);
    Py_DECREF(proxy);
    return view;
}

typedef struct {
    PyObject_HEAD
#ifdef Py_GIL_DISABLED
    PyMutex mutex;
#endif
    PyObject *views;
    Py_ssize_t length;
} Queue;

static PyTypeObject QueueType;

#ifdef Py_GIL_DISABLED
#define QUEUE_LOCK(q) PyMutex_Lock(&(q)->mutex)
#define QUEUE_UNLOCK(q) PyMutex_Unlock(&(q)->mutex)
#else
#define QUEUE_LOCK(q) ((void)0)
#define QUEUE_UNLOCK(q) ((void)0)
#endif

/* The list and its memoryviews are private. Never invoke exporters, allocate
 * GC objects, or release the last reference to an exporter under this mutex.
 * Unlike a critical section, it stays held when list APIs acquire their locks.
 * GC traversal runs with the world stopped; deallocation has exclusive access.
 */

static int
queue_traverse(Queue *self, visitproc visit, void *arg)
{
    Py_VISIT(self->views);
    return 0;
}

static int
queue_gc_clear(Queue *self)
{
    Py_CLEAR(self->views);
    self->length = 0;
    return 0;
}

static void
queue_dealloc(Queue *self)
{
    PyObject_GC_UnTrack(self);
    queue_gc_clear(self);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

static PyObject *
queue_new(PyTypeObject *type, PyObject *args, PyObject *kwargs)
{
    Queue *self = (Queue *)type->tp_alloc(type, 0);
    if (self == NULL) return NULL;
    self->views = PyList_New(0);
    if (self->views == NULL) { Py_DECREF(self); return NULL; }
    return (PyObject *)self;
}

/* Allocate outside the lock (allocation can run GC and Python callbacks),
 * then copy strong references and length together without calling Python.
 */
static Queue *
queue_snapshot(Queue *self)
{
    Queue *snapshot = (Queue *)queue_new(&QueueType, NULL, NULL);
    if (snapshot == NULL) return NULL;
    for (;;) {
        QUEUE_LOCK(self);
        Py_ssize_t count = PyList_GET_SIZE(self->views);
        QUEUE_UNLOCK(self);
        PyObject *views = PyList_New(count);
        if (views == NULL) { Py_DECREF(snapshot); return NULL; }
        QUEUE_LOCK(self);
        if (count != PyList_GET_SIZE(self->views)) {
            QUEUE_UNLOCK(self);
            Py_DECREF(views);
            continue;
        }
        for (Py_ssize_t i = 0; i < count; ++i) {
            PyList_SET_ITEM(views, i, Py_NewRef(PyList_GET_ITEM(self->views, i)));
        }
        snapshot->length = self->length;
        QUEUE_UNLOCK(self);
        Py_SETREF(snapshot->views, views);
        return snapshot;
    }
}

/* Each fragment owns its export, including strided one-dimensional views. */
static int
add_view(Queue *self, PyObject *obj)
{
    /* Clone caller-owned views so releasing the caller's handle remains valid.
     * Pin that private clone, never the caller's memoryview itself.
     */
    PyObject *source = PyMemoryView_FromObject(obj);
    if (source == NULL) return -1;
    PyObject *view = independent_view(source);
    Py_DECREF(source);
    if (view == NULL) return -1;
    Py_buffer *buffer = PyMemoryView_GET_BUFFER(view);
    if (buffer->ndim != 1 || buffer->itemsize != 1 ||
        buffer->format == NULL || strcmp(buffer->format, "B") != 0) {
        Py_DECREF(view);
        PyErr_SetString(PyExc_TypeError, "expected a one-dimensional unsigned-byte buffer");
        return -1;
    }
    Py_ssize_t n = buffer->len;
    QUEUE_LOCK(self);
    if (n > PY_SSIZE_T_MAX - self->length) {
        QUEUE_UNLOCK(self);
        Py_DECREF(view);
        PyErr_SetString(PyExc_OverflowError, "queue is too large");
        return -1;
    }
    int result = PyList_Append(self->views, view);
    if (result == 0) self->length += n;
    QUEUE_UNLOCK(self);
    Py_DECREF(view);
    return result;
}

static int
queue_init(Queue *self, PyObject *args, PyObject *kwargs)
{
    if (kwargs && PyDict_Size(kwargs)) {
        PyErr_SetString(PyExc_TypeError, "memoryqueue takes no keyword arguments");
        return -1;
    }
    Queue *temp = (Queue *)queue_new(&QueueType, NULL, NULL);
    if (temp == NULL) return -1;
    for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(args); ++i) {
        if (add_view(temp, PyTuple_GET_ITEM(args, i)) < 0) {
            Py_DECREF(temp); return -1;
        }
    }
    QUEUE_LOCK(self);
    PyObject *old = self->views;
    self->views = Py_NewRef(temp->views);
    self->length = temp->length;
    QUEUE_UNLOCK(self);
    Py_DECREF(old);
    Py_DECREF(temp);
    return 0;
}

static Py_ssize_t
queue_len(Queue *self)
{
    QUEUE_LOCK(self);
    Py_ssize_t length = self->length;
    QUEUE_UNLOCK(self);
    return length;
}

static PyObject *
queue_bytes_snapshot(Queue *self, PyObject *ignored)
{
    PyObject *result = PyBytes_FromStringAndSize(NULL, self->length);
    if (result == NULL) return NULL;
    char *dest = PyBytes_AS_STRING(result);
    for (Py_ssize_t i = 0; i < PyList_GET_SIZE(self->views); ++i) {
        Py_buffer *buf = PyMemoryView_GET_BUFFER(PyList_GET_ITEM(self->views, i));
        if (PyBuffer_ToContiguous(dest, buf, buf->len, 'C') < 0) {
            Py_DECREF(result); return NULL;
        }
        dest += buf->len;
    }
    return result;
}

static PyObject *
queue_bytes(Queue *self, PyObject *ignored)
{
    Queue *snapshot = queue_snapshot(self);
    if (snapshot == NULL) return NULL;
    PyObject *result = queue_bytes_snapshot(snapshot, ignored);
    Py_DECREF(snapshot);
    return result;
}

static PyObject *
queue_item(Queue *self, Py_ssize_t index)
{
    if (index < 0) index += self->length;
    if (index < 0 || index >= self->length) {
        PyErr_SetString(PyExc_IndexError, "index out of range"); return NULL;
    }
    for (Py_ssize_t i = 0; i < PyList_GET_SIZE(self->views); ++i) {
        PyObject *view = PyList_GET_ITEM(self->views, i);
        Py_ssize_t n = PyMemoryView_GET_BUFFER(view)->len;
        if (index < n) return PySequence_GetItem(view, index);
        index -= n;
    }
    PyErr_SetString(PyExc_IndexError, "index out of range");
    return NULL;
}

static PyObject *
queue_subscript_snapshot(Queue *self, PyObject *key)
{
    if (PyIndex_Check(key)) {
        Py_ssize_t index = PyNumber_AsSsize_t(key, PyExc_IndexError);
        if (index == -1 && PyErr_Occurred()) return NULL;
        return queue_item(self, index);
    }
    if (!PySlice_Check(key)) {
        PyErr_SetString(PyExc_TypeError, "indices must be integers or slices"); return NULL;
    }
    Py_ssize_t start, stop, step, count;
    if (PySlice_GetIndicesEx(key, self->length, &start, &stop, &step, &count) < 0) return NULL;
    Queue *result = (Queue *)queue_new(&QueueType, NULL, NULL);
    if (result == NULL) return NULL;
    if (!count) return (PyObject *)result;
    if (step != 1) {
        PyObject *data = queue_bytes_snapshot(self, NULL);
        if (data == NULL) goto fail;
        PyObject *part = PyObject_GetItem(data, key);
        Py_DECREF(data);
        if (part == NULL) goto fail;
        int status = add_view(result, part);
        Py_DECREF(part);
        if (status < 0) goto fail;
    } else {
        Py_ssize_t offset = 0;
        for (Py_ssize_t i = 0; i < PyList_GET_SIZE(self->views) && offset < stop; ++i) {
            PyObject *view = PyList_GET_ITEM(self->views, i);
            Py_ssize_t n = PyMemoryView_GET_BUFFER(view)->len;
            if (n && offset + n > start) {
                Py_ssize_t lo = start > offset ? start - offset : 0;
                Py_ssize_t hi = stop - offset < n ? stop - offset : n;
                PyObject *private_view = independent_view(view);
                if (private_view == NULL) goto fail;
                PyObject *part = PySequence_GetSlice(private_view, lo, hi);
                Py_DECREF(private_view);
                if (part == NULL) goto fail;
                int status = add_view(result, part);
                Py_DECREF(part);
                if (status < 0) goto fail;
            }
            offset += n;
        }
    }
    return (PyObject *)result;
fail:
    Py_DECREF(result);
    return NULL;
}

static PyObject *
queue_subscript(Queue *self, PyObject *key)
{
    Queue *snapshot = queue_snapshot(self);
    if (snapshot == NULL) return NULL;
    PyObject *result = queue_subscript_snapshot(snapshot, key);
    Py_DECREF(snapshot);
    return result;
}

static PyObject *
queue_append(Queue *self, PyObject *obj)
{
    if (add_view(self, obj) < 0) return NULL;
    Py_RETURN_NONE;
}

static PyObject *
queue_clear(Queue *self, PyObject *ignored)
{
    PyObject *empty = PyList_New(0);
    if (empty == NULL) return NULL;
    QUEUE_LOCK(self);
    PyObject *old = self->views;
    self->length = 0;
    self->views = empty;
    QUEUE_UNLOCK(self);
    Py_DECREF(old);
    Py_RETURN_NONE;
}

static PyObject *
queue_popleft(Queue *self, PyObject *ignored)
{
    QUEUE_LOCK(self);
    if (!PyList_GET_SIZE(self->views)) {
        QUEUE_UNLOCK(self);
        PyErr_SetString(PyExc_IndexError, "pop from an empty queue"); return NULL;
    }
    PyObject *view = Py_NewRef(PyList_GET_ITEM(self->views, 0));
    if (PySequence_DelItem(self->views, 0) < 0) {
        QUEUE_UNLOCK(self);
        Py_DECREF(view); return NULL;
    }
    self->length -= PyMemoryView_GET_BUFFER(view)->len;
    QUEUE_UNLOCK(self);
    /* Readers may still hold this internal view in a snapshot. */
    PyObject *result = independent_view(view);
    Py_DECREF(view);
    return result;
}

/* Expose fresh views: releasing a returned view cannot invalidate storage. */
static PyObject *
queue_views_snapshot(Queue *self, void *closure)
{
    PyObject *result = PyList_New(PyList_GET_SIZE(self->views));
    if (result == NULL) return NULL;
    for (Py_ssize_t i = 0; i < PyList_GET_SIZE(self->views); ++i) {
        PyObject *view = independent_view(PyList_GET_ITEM(self->views, i));
        if (view == NULL) { Py_DECREF(result); return NULL; }
        PyList_SET_ITEM(result, i, view);
    }
    return result;
}

static PyObject *
queue_views(Queue *self, void *closure)
{
    Queue *snapshot = queue_snapshot(self);
    if (snapshot == NULL) return NULL;
    PyObject *result = queue_views_snapshot(snapshot, closure);
    Py_DECREF(snapshot);
    return result;
}

static PyObject *
queue_iter(PyObject *self)
{
    PyObject *views = queue_views((Queue *)self, NULL);
    if (views == NULL) return NULL;
    PyObject *result = PyObject_GetIter(views);
    Py_DECREF(views);
    return result;
}

static int
queue_getbuffer(Queue *self, Py_buffer *buffer, int flags)
{
    Queue *snapshot = queue_snapshot(self);
    if (snapshot == NULL) return -1;
    PyObject *views = snapshot->views;
    PyObject *coalesced = NULL;
    if (PyList_GET_SIZE(views) != 1) {
        PyObject *data = queue_bytes_snapshot(snapshot, NULL);
        if (data == NULL) goto fail;
        PyObject *view = independent_view(data);
        Py_DECREF(data);
        if (view == NULL) goto fail;
        coalesced = PyList_New(1);
        if (coalesced == NULL) { Py_DECREF(view); goto fail; }
        PyList_SET_ITEM(coalesced, 0, view);

        /* Publish only if the queue still contains the captured fragments.
         * A concurrent mutation must never be overwritten by coalescing.
         */
        QUEUE_LOCK(self);
        int same = PyList_GET_SIZE(self->views) == PyList_GET_SIZE(views);
        for (Py_ssize_t i = 0; same && i < PyList_GET_SIZE(views); ++i) {
            same = PyList_GET_ITEM(self->views, i) == PyList_GET_ITEM(views, i);
        }
        PyObject *old = NULL;
        if (same) {
            old = self->views;
            self->views = Py_NewRef(coalesced);
        }
        QUEUE_UNLOCK(self);
        Py_XDECREF(old);
        views = coalesced;
    }
    /* A fresh memoryview owns the export independently of queue mutations. */
    PyObject *export = independent_view(PyList_GET_ITEM(views, 0));
    if (export == NULL) goto fail;
    int result = PyObject_GetBuffer(export, buffer, flags);
    Py_DECREF(export);
    Py_XDECREF(coalesced);
    Py_DECREF(snapshot);
    return result;
fail:
    Py_XDECREF(coalesced);
    Py_DECREF(snapshot);
    return -1;
}

static PyObject *
queue_compare(PyObject *lhs, PyObject *rhs, int op)
{
    if (op != Py_EQ && op != Py_NE) Py_RETURN_NOTIMPLEMENTED;
    if (!PyObject_TypeCheck(rhs, &QueueType) && !PyBytes_Check(rhs) &&
        !PyByteArray_Check(rhs) && !PyMemoryView_Check(rhs)) Py_RETURN_NOTIMPLEMENTED;
    PyObject *left = queue_bytes((Queue *)lhs, NULL);
    if (left == NULL) return NULL;
    PyObject *right = PyObject_TypeCheck(rhs, &QueueType)
        ? queue_bytes((Queue *)rhs, NULL) : PyObject_Bytes(rhs);
    if (right == NULL) { Py_DECREF(left); return NULL; }
    PyObject *result = PyObject_RichCompare(left, right, op);
    Py_DECREF(left); Py_DECREF(right);
    return result;
}

static PyObject *
queue_equals(PyObject *cls, PyObject *args)
{
    PyObject *lhs, *rhs;
    if (!PyArg_ParseTuple(args, "O!O!:equals", &QueueType, &lhs, &QueueType, &rhs)) return NULL;
    return queue_compare(lhs, rhs, Py_EQ);
}

static PyObject *
queue_search(Queue *self, PyObject *args, PyObject *kwargs, const char *method)
{
    static char *names[] = {"item", "i", "j", NULL};
    PyObject *item, *start = Py_None, *stop = Py_None;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|OO", names, &item, &start, &stop)) return NULL;
    PyObject *data = queue_bytes(self, NULL);
    if (data == NULL) return NULL;
    PyObject *result = PyObject_CallMethod(data, method, "OOO", item, start, stop);
    Py_DECREF(data);
    return result;
}

static PyObject *queue_find(Queue *s, PyObject *a, PyObject *k) { return queue_search(s, a, k, "find"); }
static PyObject *queue_index(Queue *s, PyObject *a, PyObject *k) { return queue_search(s, a, k, "index"); }

static int
queue_contains(Queue *self, PyObject *item)
{
    PyObject *data = queue_bytes(self, NULL);
    if (data == NULL) return -1;
    int result = PySequence_Contains(data, item);
    Py_DECREF(data);
    return result;
}

static PyMethodDef queue_methods[] = {
    {"append", (PyCFunction)queue_append, METH_O, "Append a buffer without copying it."},
    {"popleft", (PyCFunction)queue_popleft, METH_NOARGS, "Remove and return the first fragment."},
    {"clear", (PyCFunction)queue_clear, METH_NOARGS, "Remove all fragments."},
    {"__bytes__", (PyCFunction)queue_bytes, METH_NOARGS, "Copy the queue to bytes."},
    {"find", (PyCFunction)(void(*)(void))queue_find, METH_VARARGS | METH_KEYWORDS, "Find a byte sequence."},
    {"index", (PyCFunction)(void(*)(void))queue_index, METH_VARARGS | METH_KEYWORDS, "Find a byte sequence or raise ValueError."},
    {"equals", queue_equals, METH_VARARGS | METH_CLASS, "Compare two queues."},
    {NULL}
};
static PyGetSetDef queue_getset[] = {
    {"_views", (getter)queue_views, NULL, "Snapshot of the fragments.", NULL},
    {NULL}
};
static PyMappingMethods queue_mapping = {
    .mp_length = (lenfunc)queue_len,
    .mp_subscript = (binaryfunc)queue_subscript,
};
static PySequenceMethods queue_sequence = {
    .sq_length = (lenfunc)queue_len,
    .sq_contains = (objobjproc)queue_contains,
};
static PyBufferProcs queue_buffer = { .bf_getbuffer = (getbufferproc)queue_getbuffer };
static PyTypeObject QueueType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "jetblack_memoryqueue._memoryqueue.memoryqueue",
    .tp_basicsize = sizeof(Queue),
    .tp_dealloc = (destructor)queue_dealloc,
    .tp_as_sequence = &queue_sequence,
    .tp_as_mapping = &queue_mapping,
    .tp_as_buffer = &queue_buffer,
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
    .tp_doc = "A queue of unsigned-byte memoryview fragments.",
    .tp_traverse = (traverseproc)queue_traverse,
    .tp_clear = (inquiry)queue_gc_clear,
    .tp_richcompare = queue_compare,
    .tp_hash = PyObject_HashNotImplemented,
    .tp_iter = queue_iter,
    .tp_methods = queue_methods,
    .tp_getset = queue_getset,
    .tp_init = (initproc)queue_init,
    .tp_new = queue_new,
};
static PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    .m_name = "_memoryqueue",
    .m_doc = "Native memoryqueue implementation.",
    .m_size = -1,
};
PyMODINIT_FUNC
PyInit__memoryqueue(void)
{
    if (PyType_Ready(&BufferProxyType) < 0) return NULL;
    if (PyType_Ready(&QueueType) < 0) return NULL;
    PyObject *m = PyModule_Create(&module);
    if (m == NULL) return NULL;
    if (PyModule_AddObjectRef(m, "memoryqueue", (PyObject *)&QueueType) < 0) {
        Py_DECREF(m); return NULL;
    }
#ifdef Py_GIL_DISABLED
    if (PyUnstable_Module_SetGIL(m, Py_MOD_GIL_NOT_USED) < 0) {
        Py_DECREF(m); return NULL;
    }
#endif
    return m;
}
