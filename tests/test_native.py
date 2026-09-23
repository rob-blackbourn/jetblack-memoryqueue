from array import array
from itertools import product

import pytest

from jetblack_memoryqueue import memoryqueue


def test_native_type():
    assert memoryqueue.__module__ == 'jetblack_memoryqueue._memoryqueue'


def test_slices_match_bytes():
    data = b'abcdefgh'
    queue = memoryqueue(b'', data[:3], b'', data[3:], b'')
    bounds = [None, -100, -9, -3, -1, 0, 2, 8, 9, 100]
    for start, stop, step in product(bounds, bounds, [None, -3, -1, 1, 2, 3]):
        key = slice(start, stop, step)
        assert bytes(queue[key]) == data[key]
    for index in [-100, -9, 8, 100]:
        with pytest.raises(IndexError):
            queue[index]
    with pytest.raises(ValueError):
        queue[::0]


def test_empty_and_equality():
    assert bytes(memoryqueue()) == b''
    assert memoryqueue() == memoryqueue(b'', b'')
    assert memoryqueue(b'abc') != b'ab'
    assert memoryqueue(b'ab') != b'abc'
    assert memoryqueue.equals(memoryqueue(b'a', b'bc'), memoryqueue(b'ab', b'c'))
    with pytest.raises(IndexError):
        memoryqueue().popleft()


def test_search_matches_bytes():
    data = b'abcabc'
    queue = memoryqueue(b'a', b'bc', b'ab', b'c')
    for needle, start, stop in product([b'', b'a', b'bca', b'abcd', b'x'], [-20, -2, 0, 1, 6, 9], [-10, 0, 2, 6, 20]):
        assert queue.find(needle, start, stop) == data.find(needle, start, stop)
        if data.find(needle, start, stop) == -1:
            with pytest.raises(ValueError):
                queue.index(needle, start, stop)
        else:
            assert queue.index(needle, start, stop) == data.index(needle, start, stop)
    assert queue.index(b'a') == 0
    assert b'bca' in queue
    assert b'cabx' not in queue
    assert queue.find(b'b', i=1, j=3) == 1


def test_sharing_and_export_lifetime():
    data = bytearray(b'abcd')
    queue = memoryqueue(data)
    sliced = queue[1:3]
    export = memoryview(queue)
    data[1] = ord('X')
    assert bytes(sliced) == b'Xc'
    export[2] = ord('Y')
    assert data == b'aXYd'
    queue.clear()
    queue.append(b'new')
    assert bytes(export) == b'aXYd'
    assert bytes(queue) == b'new'
    export.release()


def test_coalescing_keeps_length():
    queue = memoryqueue(b'ab', b'cd')
    export = memoryview(queue)
    assert bytes(export) == b'abcd'
    assert len(queue) == 4
    assert len(queue._views) == 1
    queue.append(b'ef')
    assert bytes(export) == b'abcd'
    assert bytes(queue) == b'abcdef'
    assert bytes(memoryview(memoryqueue())) == b''


def test_released_external_views_do_not_break_storage():
    source = memoryview(b'abc')
    queue = memoryqueue(source)
    source.release()
    next(iter(queue)).release()
    queue._views[0].release()
    export = memoryview(queue)
    owner = export.obj
    export.release()
    owner.release()
    assert bytes(queue) == b'abc'


def test_strided_and_invalid_inputs():
    queue = memoryqueue(memoryview(b'abcdef')[::2])
    assert bytes(queue) == b'ace'
    assert queue[1] == ord('c')
    assert bytes(memoryview(queue)) == b'ace'
    for invalid in ['abc', 123, array('i', [1, 2]), memoryview(b'abcd').cast('B', (2, 2))]:
        with pytest.raises(TypeError):
            queue.append(invalid)
        assert bytes(queue) == b'ace'
    with pytest.raises(TypeError):
        queue.__init__(b'new', object())
    assert bytes(queue) == b'ace'
