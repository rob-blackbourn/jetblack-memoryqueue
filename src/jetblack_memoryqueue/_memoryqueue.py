from __future__ import annotations

from collections import deque
from typing import Any, Iterator, Sized, cast


class memoryqueue(Sized):

    def __init__(self, *args: bytes | bytearray | memoryview) -> None:
        self._views = deque(memoryview(buf) for buf in args)
        self._len = sum(len(buf) for buf in self._views)

    def __len__(self) -> int:
        return self._len

    def __getitem__(self, key: Any) -> memoryqueue | int:
        if isinstance(key, int):
            return self._slice1(key)
        if not isinstance(key, slice):
            raise TypeError("Invalid argument")

        if key.step is not None:
            return self._slice3(key.start, key.stop, key.step)
        else:
            return self._slice2(key.start, key.stop)

    def _slice1(self, index: int) -> int:
        if index < 0:
            index += len(self)
        for view in self._views:
            if index < len(view):
                return view[index]
            else:
                index -= len(view)
        raise IndexError("index out of range")

    def _slice2(self, start: int | None, stop: int | None) -> memoryqueue:
        if start is None:
            start = 0
        elif start < 0:
            start += len(self)

        start = min(start, len(self))

        if stop is None:
            stop = len(self)
        elif stop < 0:
            stop += len(self)

        stop = min(stop, len(self))

        if (start == 0 and stop == 0) or len(self) == 0:
            return memoryqueue()

        view_iter = iter(self._views)
        while (view := next(view_iter, None)) is not None:
            if start < len(view):
                break
            start -= len(view)
            stop -= len(view)

        assert view is not None

        if stop <= len(view):
            return memoryqueue(view[max(start, 0):stop])

        stop -= len(view)
        views = [view[start:]]
        while (view := next(view_iter, None)) is not None:
            if stop < len(view):
                views.append(view[:stop])
                break
            stop -= len(view)
            views.append(view)

        return memoryqueue(*views)

    def _slice3(self, start: int | None, stop: int | None, step: int) -> memoryqueue:
        if step == 0:
            raise ValueError('step cannot be 0')

        if start is None:
            start = 0 if step > 0 else len(self) - 1

        if start > len(self):
            raise IndexError('start must be less than the total length')

        if stop is None:
            stop = len(self) if step > 0 else -1

        if start > len(self):
            raise IndexError('stop must be less than the total length')

        values = [
            cast(int, self[index])
            for index in range(start, stop, step)
        ]

        return memoryqueue(bytes(values))

    def __bytes__(self) -> bytes:
        assert len(self._views) > 0

        if len(self._views) == 1:
            return bytes(self._views[0])

        buf = bytearray(self._len)
        offset = 0
        for view in self._views:
            start, offset = offset, offset + len(view)
            buf[start:offset] = view

        return bytes(buf)

    def clear(self) -> None:
        self._views.clear()
        self._len = 0

    def append(self, buf: bytes | bytearray | memoryview) -> None:
        self._views.append(memoryview(buf))
        self._len += len(buf)

    def popleft(self) -> memoryview:
        view = self._views.popleft()
        self._len -= len(view)
        return view

    def __iter__(self) -> Iterator[memoryview]:
        return iter(self._views)

    @classmethod
    def equals(cls, lhs: memoryqueue, rhs: memoryqueue) -> bool:
        lhs_iter, rhs_iter = iter(lhs), iter(rhs)

        lhs_view: memoryview | None = next(lhs_iter)
        rhs_view: memoryview | None = next(rhs_iter)
        while lhs_view and rhs_view:

            n = min(len(lhs_view), len(rhs_view))
            if lhs_view[:n] != rhs_view[:n]:
                return False

            lhs_view = lhs_view[n:]
            rhs_view = rhs_view[n:]

            if len(lhs_view) == 0:
                lhs_view = next(lhs_iter, None)

            if len(rhs_view) == 0:
                rhs_view = next(rhs_iter, None)

        return not (lhs_view and rhs_view)

    def __eq__(self, value: object) -> bool:
        if isinstance(value, (bytes, bytearray)):
            value = memoryview(value)
        if isinstance(value, memoryview):
            value = memoryqueue(value)
        if not isinstance(value, memoryqueue):
            return NotImplemented

        return self.equals(self, value)

    def __contains__(self, item: bytes | bytearray) -> bool:
        return self.find(item) != -1

    def _find(self, item: bytes | bytearray | memoryview) -> int:
        if isinstance(item, (bytes, bytearray)):
            item = memoryview(item)

        views = list(self._views)
        index = 0
        while views:
            view, *views = views
            for i, value in enumerate(view):
                if value == item[0]:
                    if memoryqueue(view[i:], *views) == item:
                        return index + i
            index += len(view)
        return -1

    def find(
            self,
            item: bytes | bytearray | memoryview,
            i: int | None = None,
            j: int | None = None
    ) -> int:
        if i is None:
            i = 0
        if j is None:
            j = len(self)
        if i < 0 or i > len(self):
            raise ValueError('invalid j')
        if j < 0 or j > len(self) or j < i:
            raise ValueError('invalid j')

        if len(item) == 0:
            return 0

        index = self._slice2(i, j)._find(item)
        if index == -1:
            return -1
        return i + index

    def index(
            self,
            item: bytes | bytearray | memoryview,
            i: int | None = None,
            j: int | None = None
    ) -> int:
        i = self.find(item, i, j)
        if i == 0:
            raise ValueError('not found')
        return i
