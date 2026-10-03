# jetblack-memoryqueue

A C extension for CPython 3.11 and later that stores incoming byte buffers as
chunks and exposes them as one byte sequence. Appending and popping chunks take
constant time and does not copy the underlying data.

```python
from jetblack_memoryqueue import memoryqueue

queue = memoryqueue(b"abc", b"def")
queue.append(b"ghi")
assert queue[3] == ord("d")
assert bytes(queue[2:5]) == b"cde"
assert queue.find(b"cde") == 2
assert queue.popleft().tobytes() == b"abc"
```

## Building

A C compiler and Python development headers are required to build from source.
The extension is configured entirely through `[tool.setuptools].ext-modules` in
`pyproject.toml`; there is no `setup.py` or Python fallback.

```sh
python -m pip install .
# Development:
python -m pip install -e '.[dev]' build
python -m pytest
python -m mypy
python -m build
```

The package includes `.pyi` stubs and a `py.typed` marker.

## Buffer and sequence behavior

Inputs must expose a one-dimensional unsigned-byte buffer (format `B`), such as
`bytes`, `bytearray`, or a byte-oriented `memoryview`. Strided byte views are
supported. Cast typed contiguous views with `view.cast('B')` before appending.
Mutable inputs remain shared, and resizing an input is prevented while exported.

- Integer indexing and slicing follow normal Python sequence bounds and steps.
- `items()` and iteration snapshot the chunks when called. Later appends, pops,
  and clears do not invalidate them. Changes to shared data remain visible.
- `popleft()` returns a memoryview and raises `IndexError` on an empty queue.
- `find(item, i=None, j=None)` returns the first match or `-1`; `index()` raises
  `ValueError` when absent. Bounds must satisfy `0 <= i <= j <= len(queue)`.
  `rfind()` and `rindex()` use the same bounds and return the last match.
  An empty needle matches at `i` for forward searches and `j` for reverse
  searches. Containment searches for a byte string.
- `startswith(prefix, i=None, j=None)` and `endswith(suffix, i=None, j=None)`
  return booleans and use the same bounds as searching. Accept a byte buffer or
  a tuple of alternatives; an empty tuple returns `False`, and an empty buffer
  matches even an empty range. Tuple matching stops at the first match.
- `partition(sep)` and `rpartition(sep)` return three new queues containing
  the bytes before, within, and after the first or last separator. They search
  across chunks without flattening the queue. Results share the original data,
  preserving chunk boundaries and strides, with slices only at the two cuts.
  The separator result also views the original queue data. An empty separator
  raises `ValueError`. If absent, `partition()` returns `(whole, empty, empty)`
  and `rpartition()` returns `(empty, empty, whole)`.
  Empty chunks are retained; those exactly at a cut belong to the following
  part. The original queue is unchanged, and results survive clearing it.
- Equality compares all bytes, independently of chunk boundaries. Queues are
  unhashable. `_views` is a read-only tuple snapshot for inspection.
- `memoryview(queue)` works on every supported Python version. A single chunk
  is exported without copying and preserves its writability and strides.
  Multiple chunks produce an immutable contiguous snapshot without changing
  the queue. Existing exports survive `clear()` and `popleft()`.

This fixes the former Python implementation's empty-queue, out-of-range slicing,
prefix-equality, and `index()` edge cases. The type is not subclassable.

## Free-threaded Python

Build and install with a free-threaded CPython 3.14+ interpreter to opt in:

```sh
python3.14t -m pip install .
python3.14t -X gil=0 -m pytest
```

These builds advertise that they do not require the GIL. Per-queue mutexes protect
chunk ownership and counters; readers take a consistent chunk snapshot. Regular
CPython builds work without any configuration. CPython 3.13 free-threaded builds
retain the GIL when importing the extension. Wheels must be built separately for
each Python version and for regular versus free-threaded interpreters.

Individual queue operations are safe concurrently; compound operations such as
checking length and then popping need caller synchronization. Callers must also
synchronize writes to shared mutable input buffers. Comparisons of two queues
snapshot each queue separately.
