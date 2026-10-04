# jetblack-memoryqueue

This is a Python >=3.11 project which implements a "memory queue".

The memory queue is a container that presents chunks of data as a contiguous
sequence.

This can be useful when parsing streaming data. Typically the data is read in
blocks of equal size until the token is found. This leads to a lot of memory
allocation.

```python
data = b''

...

data += read_block() # memory allocation
i = data.index(b`\n\r')
if i != -1:
    line = data[:i+2] # memory allocation
    data = data[i+2:] # memory allocation
```

With a memory queue the block is wrapped in a memoryview and appended to an
internal queue.

```python
data = memoryqueue

...

data += read_block() # wrapped in memoryview and appended to internal queue.
i = data.index(b`\n\r')
if i != -1:
    line = data[:i+2] # memory allocation
    data = data[i+2:] # could drop a memoryview if i+2 is more than it's length.
```

## Example

Here is an example of parsing an http request.

```python
from typing import Iterator

from jetblack_memoryqueue import memoryqueue


def byte_stream(n: int) -> Iterator[bytes]:
    buf = b'\
POST /test HTTP/1.1\n\r\
Host: example.com\n\r\
Content-Type: multipart/form-data;boundary="delimiter12345"\n\r\
\n\r\
--delimiter12345\n\r\
Content-Disposition: form-data; name="field1"\n\r\
\n\r\
value1\n\r\
--delimiter12345\n\r\
Content-Disposition: form-data; name="field2"; filename="example.txt"\n\r\
\n\r\
value2\n\r\
--delimiter12345--'
    return (
        buf[0+i:n+i]
        for i in range(0, len(buf), n)
    )


def main() -> None:

    read_buf = iter(byte_stream(10))

    parts: list[bytes] = []

    # Use a memory queue to accumulate the data instead of a bytes object.
    # data = b''
    data = memoryqueue()

    while buf := next(read_buf, None):
        data += buf
        index = data.find(b"\n\r\n\r")
        if index >= 0:
            parts.append(bytes(data[:index]))
            data = data[index+4:]

    if len(data) > 0:
        parts.append(bytes(data))

    for part in parts:
        print(part)


if __name__ == "__main__":
    main()
```

## Installation

The package can be installed from the pypi.

```bash
pip install jetblack-memoryqueue
```
