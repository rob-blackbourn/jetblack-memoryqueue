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
