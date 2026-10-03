import gc
import importlib.machinery
import itertools
import sys
import sysconfig
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from jetblack_memoryqueue import memoryqueue


def test_native_module():
    module = sys.modules[memoryqueue.__module__]
    assert any(module.__file__.endswith(suffix)
               for suffix in importlib.machinery.EXTENSION_SUFFIXES)
    if sys.version_info >= (3, 14) and sysconfig.get_config_var('Py_GIL_DISABLED'):
        assert not sys._is_gil_enabled()


@pytest.mark.parametrize('chunks', [(), (b'',), (b'', b'abc', b'', b'def', b'')])
def test_sequence_boundaries(chunks):
    queue = memoryqueue(*chunks)
    data = b''.join(chunks)
    assert bytes(queue) == data
    assert list(queue) == list(data)
    assert queue == data
    assert queue != data + b'x'
    for start, stop, step in itertools.product(
            [None, -100, -7, -1, 0, 1, 3, 6, 100],
            [None, -100, -7, -1, 0, 1, 3, 6, 100],
            [None, -3, -1, 1, 2, 3]):
        key = slice(start, stop, step)
        assert bytes(queue[key]) == data[key], key
    for index in range(-len(data) - 2, len(data) + 2):
        if -len(data) <= index < len(data):
            assert queue[index] == data[index]
        else:
            with pytest.raises(IndexError):
                queue[index]
    with pytest.raises(ValueError):
        queue[::0]


def test_zero_copy_and_view_lifetimes():
    source = bytearray(b'abc')
    queue = memoryqueue(source, b'def')
    part = queue[1:5]
    source[1] = ord('X')
    assert bytes(part) == b'Xcde'
    items = queue.items()
    iterator = iter(queue)
    exported = memoryview(queue)
    queue.clear()
    assert bytes(exported) == b'aXcdef'
    assert b''.join(items) == b'aXcdef'
    assert bytes(iterator) == b'aXcdef'
    assert bytes(part) == b'Xcde'
    assert bytes(queue) == b''
    assert memoryview(queue).tobytes() == b''


def test_single_chunk_export():
    source = bytearray(b'abc')
    queue = memoryqueue(source)
    view = memoryview(queue)
    view[0] = ord('X')
    assert bytes(queue) == b'Xbc'
    owner = view.obj
    view.release()
    owner.release()
    assert bytes(queue) == b'Xbc'
    queue._views[0].release()
    next(queue.items()).release()
    assert bytes(queue) == b'Xbc'
    view = memoryview(queue)
    queue.popleft().release()
    assert view.tobytes() == b'Xbc'


def test_strided_buffers():
    queue = memoryqueue(memoryview(b'abcdef')[::-2], b'!')
    assert bytes(queue) == b'fdb!'
    assert bytes(queue[1:]) == b'db!'
    assert memoryview(queue).tobytes() == b'fdb!'


def test_search_and_equality():
    queue = memoryqueue(b'', b'ab', b'cab', b'c', b'')
    for item in [b'', b'a', b'abc', b'bcab', b'abcdefg', b'z']:
        for start in range(7):
            for stop in range(start, 7):
                expected = b'abcabc'.find(item, start, stop)
                assert queue.find(item, i=start, j=stop) == expected
                if expected == -1:
                    with pytest.raises(ValueError):
                        queue.index(item, start, stop)
                else:
                    assert queue.index(item, start, stop) == expected
        assert (item in queue) == (item in b'abcabc')
    assert memoryqueue.equals(queue, memoryqueue(b'abcabc'))
    assert memoryqueue() == memoryqueue(b'', b'')
    assert memoryqueue(b'a') != memoryqueue(b'ab')
    assert queue != object()
    with pytest.raises(TypeError):
        hash(queue)
    for bounds in [(-1, 6), (0, 7), (4, 3)]:
        with pytest.raises(ValueError):
            queue.find(b'a', *bounds)


def test_invalid_input_and_reinitialization():
    queue = memoryqueue(b'original')
    with pytest.raises(TypeError):
        queue.__init__(b'new', object())
    assert bytes(queue) == b'original'
    with pytest.raises(TypeError):
        queue.append('text')
    with pytest.raises(TypeError):
        memoryqueue(memoryview(b'abcd').cast('H'))
    with pytest.raises(TypeError):
        queue['key']
    queue.__init__(b'new')
    assert queue.popleft().tobytes() == b'new'
    with pytest.raises(IndexError):
        queue.popleft()


def test_concurrent_append_pop_and_snapshots():
    queue = memoryqueue()
    barrier = Barrier(8)

    def worker(worker_id):
        barrier.wait()
        popped = []
        for i in range(300):
            queue.append(bytes([worker_id]))
            if i % 11 == 0:
                bytes(queue)
                list(queue.items())
                memoryview(queue).release()
                bytes(queue[:])
                gc.collect()
            popped.append(bytes(queue.popleft()))
        return popped

    with ThreadPoolExecutor(max_workers=8) as pool:
        popped = list(itertools.chain.from_iterable(pool.map(worker, range(8))))
    assert sorted(popped) == sorted(bytes([i]) for i in range(8) for _ in range(300))
    assert len(queue) == 0


def test_buffer_reference_cycle_is_collected():
    import weakref

    class Data(bytearray):
        pass

    source = Data(b'abc')
    queue = memoryqueue(source)
    source.queue = queue
    reference = weakref.ref(source)
    del source, queue
    gc.collect()
    assert reference() is None


def test_concurrent_clear_and_reinitialize():
    queue = memoryqueue(b'abc')
    barrier = Barrier(4)

    def worker(worker_id):
        barrier.wait()
        for _ in range(500):
            if worker_id == 0:
                queue.clear()
                queue.__init__(b'ab', b'c')
            elif worker_id == 1:
                queue.append(b'x')
                try:
                    queue.popleft().release()
                except IndexError:
                    pass
            else:
                bytes(queue)
                bytes(queue[:])
                list(queue)
                list(queue.items())
                memoryview(queue).release()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(worker, range(4)))
    assert len(queue) == len(bytes(queue))
