from collections.abc import Iterator
from typing import SupportsIndex, final, overload


@final
class memoryqueue:

    def __init__(self, *args: bytes | bytearray | memoryview) -> None:
        """Initialize the queue with the specified buffers in order.

        Store the buffers as chunks without copying their data. Changes to mutable
        buffers are visible through the queue. With no arguments, create an empty queue.

        Args:
            *args (bytes | bytearray | memoryview): The buffers to add to the queue.

        Returns (None):
            None.
        """

    def __len__(self) -> int:
        """Return the total number of bytes in the queue.

        Returns (int):
            The combined length of all chunks.
        """

    @overload
    def __getitem__(self, key: SupportsIndex, /) -> int:
        """Return the byte at the specified index.

        Negative indices count from the end of the queued data.

        Args:
            key (SupportsIndex): The index of the byte to return.

        Returns (int):
            The byte value at the specified index, from 0 to 255.

        Raises:
            IndexError: If the index is out of range.
        """

    @overload
    def __getitem__(self, key: slice, /) -> memoryqueue:
        """Return a queue containing the specified slice of the data.

        Use the same slice bounds and steps as a bytes object. Slices with a
        step of 1 share the original buffers; other steps copy the selected data.

        Args:
            key (slice): The start, stop, and step of the slice.

        Returns (memoryqueue):
            A queue containing the selected bytes.

        Raises:
            ValueError: If the slice step is zero.
        """

    def __bytes__(self) -> bytes:
        """Return a copy of the queued data as a bytes object.

        Concatenate the chunks in queue order.

        Returns (bytes):
            A bytes object containing all the queued data.
        """

    def __buffer__(self, flags: int, /) -> memoryview:
        """Return a memoryview of the queued data with the requested buffer flags.

        A queue containing one chunk exports that chunk without copying its data.
        Otherwise, export a read-only copy of the concatenated data. The returned
        view remains valid when chunks are removed from the queue.

        Args:
            flags (int): The buffer protocol flags specifying the required access.

        Returns (memoryview):
            A view of the queued data.

        Raises:
            BufferError: If the buffer cannot satisfy the requested flags.
        """

    def __iter__(self) -> Iterator[int]:
        """Return an iterator over the bytes in queue order.

        Use a snapshot of the chunks without copying their data. Changes to mutable
        buffers are visible through the iterator.

        Returns (Iterator[int]):
            An iterator yielding byte values from 0 to 255.
        """

    def __eq__(self, value: object, /) -> bool:
        """Return True if the queued data equals the specified value.

        Compare byte contents with a memoryqueue, bytes, bytearray, or memoryview,
        regardless of chunk boundaries. For other types, return NotImplemented
        to allow the other object's comparison to run.

        Args:
            value (object): The value to compare with the queued data.

        Returns (bool):
            True if the byte contents are equal, otherwise False for supported types.
        """

    def __contains__(
        self,
        item: bytes | bytearray | memoryview,
        /
    ) -> bool:
        """Return True if the queued data contains the specified item.

        The item may span chunk boundaries.

        Args:
            item (bytes | bytearray | memoryview): The byte sequence to look for.

        Returns (bool):
            True if the item occurs in the queued data, otherwise False.
        """

    def __iadd__(self, buf: bytes | bytearray | memoryview, /) -> memoryqueue:
        """Append a buffer without copying its data and return this queue.

        Accept the same buffers as append, preserving their chunk boundaries.
        Changes to mutable buffers are visible through the queue.
        """

    def append(self, buf: bytes | bytearray | memoryview, /) -> None:
        """Append the specified buffer to the end of the queue.

        Store the buffer as a chunk without copying its data. Changes to a mutable
        buffer are visible through the queue.

        Args:
            buf (bytes | bytearray | memoryview): The buffer to append.

        Returns (None):
            None.
        """

    def popleft(self) -> memoryview:
        """Remove and return the first chunk in the queue.

        The returned view shares the original buffer without copying its data.

        Returns (memoryview):
            A view of the removed chunk.

        Raises:
            IndexError: If the queue has no chunks.
        """

    def clear(self) -> None:
        """Remove all chunks from the queue.

        Existing views of the removed chunks remain valid.

        Returns (None):
            None.
        """

    def items(self) -> Iterator[memoryview]:
        """Return an iterator over the chunks in queue order.

        Use a snapshot of the chunks without copying their data. Changes to mutable
        buffers are visible through the returned views.

        Returns (Iterator[memoryview]):
            An iterator yielding a view of each chunk.
        """

    @property
    def _views(self) -> tuple[memoryview, ...]:
        """Return a tuple of views of the chunks in queue order.

        Use a snapshot of the chunks without copying their data. Changes to mutable
        buffers are visible through the returned views.

        Returns (tuple[memoryview, ...]):
            A tuple containing a view of each chunk.
        """

    @classmethod
    def equals(cls, lhs: memoryqueue, rhs: memoryqueue, /) -> bool:
        """Return True if two queues contain the same byte data.

        Compare byte contents regardless of chunk boundaries.

        Args:
            lhs (memoryqueue): The first queue to compare.
            rhs (memoryqueue): The second queue to compare.

        Returns (bool):
            True if the byte contents are equal, otherwise False.

        Raises:
            TypeError: If either argument is not a memoryqueue.
        """

    def find(
        self,
        item: bytes | bytearray | memoryview,
        i: SupportsIndex | None = None,
        j: SupportsIndex | None = None
    ) -> int:
        """Return the lowest index where the specified item is found.

        Search within the optional start and end bounds. The item may span chunk
        boundaries. Bounds must satisfy 0 <= i <= j <= len(self), with None using the
        corresponding default.
        Return -1 if the item is not found.

        Args:
            item (bytes | bytearray | memoryview): The byte sequence to look for.
            i (SupportsIndex | None): The start index to check from, defaulting to 0.
            j (SupportsIndex | None): The end index to check to, defaulting to the data length.

        Returns (int):
            The lowest index of the item in the queue, or -1 if it is not found.

        Raises:
            ValueError: If the search bounds are invalid.
        """

    def index(
        self,
        item: bytes | bytearray | memoryview,
        i: SupportsIndex | None = None,
        j: SupportsIndex | None = None
    ) -> int:
        """Return the lowest index where the specified item is found.

        Search within the optional start and end bounds. The item may span chunk
        boundaries. Bounds must satisfy 0 <= i <= j <= len(self), with None using the
        corresponding default.
        Raise ValueError if the item is not found.

        Args:
            item (bytes | bytearray | memoryview): The byte sequence to look for.
            i (SupportsIndex | None): The start index to check from, defaulting to 0.
            j (SupportsIndex | None): The end index to check to, defaulting to the data length.

        Returns (int):
            The lowest index of the item in the queue.

        Raises:
            ValueError: If the search bounds are invalid or the item is not found.
        """

    def rfind(
        self,
        item: bytes | bytearray | memoryview,
        i: SupportsIndex | None = None,
        j: SupportsIndex | None = None
    ) -> int:
        """Return the highest index where the specified item is found.

        Search within the optional start and end bounds. The item may span chunk
        boundaries. Bounds must satisfy 0 <= i <= j <= len(self), with None using the
        corresponding default.
        Return -1 if the item is not found.

        Args:
            item (bytes | bytearray | memoryview): The byte sequence to look for.
            i (SupportsIndex | None): The start index to check from, defaulting to 0.
            j (SupportsIndex | None): The end index to check to, defaulting to the data length.

        Returns (int):
            The highest index of the item in the queue, or -1 if it is not found.

        Raises:
            ValueError: If the search bounds are invalid.
        """

    def rindex(
        self, item: bytes | bytearray | memoryview,
        i: SupportsIndex | None = None,
        j: SupportsIndex | None = None
    ) -> int:
        """Return the highest index where the specified item is found.

        Search within the optional start and end bounds. The item may span chunk
        boundaries. Bounds must satisfy 0 <= i <= j <= len(self), with None using the
        corresponding default.
        Raise ValueError if the item is not found.

        Args:
            item (bytes | bytearray | memoryview): The byte sequence to look for.
            i (SupportsIndex | None): The start index to check from, defaulting to 0.
            j (SupportsIndex | None): The end index to check to, defaulting to the data length.

        Returns (int):
            The highest index of the item in the queue.

        Raises:
            ValueError: If the search bounds are invalid or the item is not found.
        """

    def startswith(
        self,
        prefix: bytes | bytearray | memoryview | tuple[bytes | bytearray | memoryview, ...],
        i: SupportsIndex | None = None,
        j: SupportsIndex | None = None
    ) -> bool:
        """Return True if the data starts with the specified prefix, otherwise
        return False.

        The prefix can also be a tuple of prefixes to look for. With
        optional start, test beginning at that position. With optional end,
        stop comparing at that position.

        Args:
            prefix (bytes | bytearray | memoryview | tuple[bytes | bytearray | memoryview, ...]): The prefix to check for.
            i (SupportsIndex | None): The start index to check from.
            j (SupportsIndex | None): The end index to check to.

        Returns (bool):
            True if the data starts with the specified prefix, otherwise False.
        """

    def endswith(
        self,
        suffix: bytes | bytearray | memoryview | tuple[bytes | bytearray | memoryview, ...],
        i: SupportsIndex | None = None,
        j: SupportsIndex | None = None
    ) -> bool:
        """Return True if the data ends with the specified suffix, otherwise
        return False.

        The suffix can also be a tuple of suffixes to look for. With
        optional start, test beginning at that position. With optional end,
        stop comparing at that position. Bounds must satisfy
        0 <= i <= j <= len(self), with None using the corresponding default.

        Args:
            suffix (bytes | bytearray | memoryview | tuple[bytes | bytearray | memoryview, ...]): The suffix to check for.
            i (SupportsIndex | None): The start index to check from, defaulting to 0.
            j (SupportsIndex | None): The end index to check to, defaulting to the data length.

        Returns (bool):
            True if the data ends with the specified suffix, otherwise False.

        Raises:
            ValueError: If the search bounds are invalid.
        """

    def partition(
        self,
        sep: bytes | bytearray | memoryview,
        /
    ) -> tuple[memoryqueue, memoryqueue, memoryqueue]:
        """Split the data at the first occurrence of the specified separator.

        Return three queues containing the data before the separator, the
        separator itself, and the data after it. If the separator is not found,
        return a queue containing all the data followed by two empty queues.
        The returned queues share the original buffers without copying their data.

        Args:
            sep (bytes | bytearray | memoryview): The separator to split on.

        Returns (tuple[memoryqueue, memoryqueue, memoryqueue]):
            The data before the separator, the separator, and the data after it.

        Raises:
            ValueError: If the separator is empty.
        """

    def rpartition(
        self,
        sep: bytes | bytearray | memoryview,
        /
    ) -> tuple[memoryqueue, memoryqueue, memoryqueue]:
        """Split the data at the last occurrence of the specified separator.

        Return three queues containing the data before the separator, the
        separator itself, and the data after it. If the separator is not found,
        return two empty queues followed by a queue containing all the data.
        The returned queues share the original buffers without copying their data.

        Args:
            sep (bytes | bytearray | memoryview): The separator to split on.

        Returns (tuple[memoryqueue, memoryqueue, memoryqueue]):
            The data before the separator, the separator, and the data after it.

        Raises:
            ValueError: If the separator is empty.
        """
