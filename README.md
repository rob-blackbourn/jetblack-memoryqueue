# jetblack-memoryqueue

A C extension for CPython 3.11 and later that stores incoming byte buffers as
chunks and exposes them as one byte sequence. Appending and popping chunks take
constant time and does not copy the underlying data.

## Example

```python
from jetblack_memoryqueue import memoryqueue

queue = memoryqueue(b"abc", b"def")
queue.append(b"ghi")
assert queue[3] == ord("d")
assert bytes(queue[2:5]) == b"cde"
assert queue.find(b"cde") == 2
assert queue.popleft().tobytes() == b"abc"
```

## Installation

The package can be installed from the pypi.

```bash
pip install jetblack-memoryqueue
```
