from typing import cast, Iterator

from jetblack_memoryqueue import memoryqueue


def batched[T: (str, bytes, bytearray)](buf: T, n: int) -> Iterator[T]:
    return (
        buf[0+i:n+i]
        for i in range(0, len(buf), n)
    )


def test_points() -> None:
    alphabet = b'abcdefghijklmnopqrstuvwxyz'
    view = memoryqueue(*(batch for batch in batched(alphabet, 5)))

    tests = [
        (0, "start"),
        (-1, "end relative"),
        (len(view) - 1, "end absolute"),
        (4, "end of first block"),
        (5, "start of second block"),
    ]

    for i, msg in cast(list[tuple[int, str]], tests):
        actual = view[i]
        expected = alphabet[i]
        assert actual == expected, msg

def test_slices() -> None:
    alphabet = b'abcdefghijklmnopqrstuvwxyz'
    view = memoryqueue(*(batch for batch in batched(alphabet, 5)))

    tests = [
        (slice(None, 5), "whole first block"),
        (slice(5, 10), "whole second block"),
        (slice(None, None), "everything implicit"),
        (slice(0, len(view)), "everything explicit"),
        (slice(3, 8), "accross first and second"),
        (slice(7, 12), "accross seconds and third"),
        (slice(3, 12), "accross first and third"),
    ]

    for i, msg in cast(list[tuple[slice, str]], tests):
        actual = bytes(view[i])
        expected = alphabet[i]
        assert actual == expected, msg

def test_steps() -> None:
    alphabet = b'abcdefghijklmnopqrstuvwxyz'
    view = memoryqueue(*(batch for batch in batched(alphabet, 5)))

    tests = [
        (slice(None, None, 1), "all implicit forward"),
        (slice(None, None, -1), "all implicit forward"),
        (slice(3, 18, 1), "accross blocks"),
        (slice(18, 3, -1), "accross blocks backwards"),
    ]

    for i, msg in cast(list[tuple[slice, str]], tests):
        expected = alphabet[i]
        actual = bytes(view[i])
        assert actual == expected, msg

def test_equals() -> None:
    assert memoryqueue(b'abc', b'def') == memoryqueue(b'ab', b'cd', b'ef')
    assert memoryqueue(b'ab', b'cd', b'ef') == memoryqueue(b'abc', b'def')

def test_mutate() -> None:
    first = b'abcdef'
    view = memoryqueue(first)
    assert view == first

    second = b'ghijk'
    view.append(second)
    assert view == first + second

    buf = view.popleft()
    assert buf == first
    assert view == second

    buf = view.popleft()
    assert buf == second
    assert len(view) == 0

def test_empty() -> None:
    view = memoryqueue()
    assert len(view) == 0
    assert len(cast(memoryqueue, view[:])) == 0

def test_find() -> None:
    alphabet = b'abcdefghijklmnopqrstuvwxyz'
    view = memoryqueue(*(batch for batch in batched(alphabet, 5)))

    index = view.find(b'defgh')
    assert index == 3

def test_fragments() -> None:
    alphabet = b'abcdefghijklmnopqrstuvwxyz'
    view = memoryqueue(*(batch for batch in batched(alphabet, 5)))

    assert len(view._views) == 6

    view = cast(memoryqueue, view[5:])
    assert len(view._views) == 5

def test_buffer_protocol() -> None:
    alphabet = b'abcdefghijklmnopqrstuvwxyz'
    view = memoryqueue(*(batch for batch in batched(alphabet, 5)))

    try:
        buf = memoryview(view)
        assert buf == alphabet 
    except:
        assert False