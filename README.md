# jetblack-memoryqueue

A CPython C extension implementing a queue of byte-buffer fragments.

```python
from jetblack_memoryqueue import memoryqueue

queue = memoryqueue(b'hello', bytearray(b' world'))
queue.append(b'!')
assert bytes(queue[3:8]) == b'lo wo'
assert queue.find(b'o w') == 4
assert bytes(memoryview(queue)) == b'hello world!'
```

Install with `python -m pip install .`. Building requires a C compiler,
CPython development headers, and setuptools. For development:

```sh
python -m pip install -e '.[dev]'
python -m pytest
```

The public `memoryqueue` class uses the native implementation. Type stubs are included.

Construction and `append` accept one-dimensional unsigned-byte buffers
(format `B`), including strided memoryviews. Fragments retain their exporters;
ordinary slices share their storage. Stepped slices copy. Iteration yields a
snapshot of the fragment memoryviews; `popleft()` removes the first fragment.
`_views` is a read-only property returning a snapshot.

Indexing, slicing, equality, `find`, and `index` follow bytes semantics,
including empty inputs and negative search bounds. Search and equality
currently materialize bytes. Removing the first fragment takes linear time in
the number of fragments.

A buffer export of a single fragment shares that fragment, including its
writability and strides. Exporting multiple fragments coalesces the queue into
one immutable bytes buffer. Existing exports remain valid after queue mutation.
`bytes(queue)` always returns the concatenated contents without coalescing the
queue.

Regular CPython 3.12+ and free-threaded CPython 3.14 are supported. Support is
selected automatically when building with a free-threaded interpreter; importing
the extension does not enable the GIL. Build separately for each interpreter ABI:

```sh
python3.14t -m venv .venv-ft
.venv-ft/bin/python -m pip install -e '.[dev]'
.venv-ft/bin/python -X gil=0 -m pytest
```

Free-threaded builds use a per-queue mutex for fragment and length updates.
Reads capture a consistent snapshot of fragment references (O(number of
fragments) temporary storage); they do not copy the underlying buffer contents
unless the operation already requires it. Buffer exports remain valid during
mutation; coalescing is published only if the captured fragments are unchanged.
Comparisons capture each queue separately. Sequences of calls, such as checking
`len(queue)` before `popleft()`, require an application lock if they must be atomic.

Mutable exporters remain shared: callers must synchronize writes to bytearrays
or writable memoryviews with queue reads. The queue lock protects queue structure,
not externally owned buffer contents. Caller-owned memoryviews and their derived
views also require external synchronization when creating or releasing views
across threads, because CPython 3.14 shares unsynchronized managed-buffer state.
Use bytes/bytearray exporters directly when sharing inputs across worker threads.
Regular builds retain GIL-based locking.
