# jetblack-memoryqueue

This is a Python >=3.11 project which implements a "memory queue".

The memory queue is a container that presents chunks of data as a contiguous
sequence.

This can be useful when parsing streaming data. Typically the data is read in
blocks of equal size until the token is found. This leads to a lot of copying.

```python
data += buf
i = data.index(b`\n\r')
if i != -1:
    line = data[:i+2]
    data = data[i+2:]
```

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
