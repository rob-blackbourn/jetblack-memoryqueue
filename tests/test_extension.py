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
        popped = list(itertools.chain.from_iterable(
            pool.map(worker, range(8))))
    assert sorted(popped) == sorted(bytes([i])
                                    for i in range(8) for _ in range(300))
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


@pytest.mark.parametrize('chunks', [(), (b'',), (b'', b'ab', b'cab', b'c', b''),
                                    (b'a', b'aa', b'a')])
@pytest.mark.parametrize('buffer_type', [bytes, bytearray, memoryview])
def test_reverse_search(chunks, buffer_type):
    queue = memoryqueue(*chunks)
    data = b''.join(chunks)
    for raw in [b'', b'a', b'aa', b'abc', b'bca', b'abcabc', b'abcdefg', b'z']:
        item = buffer_type(raw)
        assert queue.rfind(item) == data.rfind(raw)
        assert queue.rfind(item, None, None) == data.rfind(raw)
        for start in range(len(data) + 1):
            for stop in range(start, len(data) + 1):
                expected = data.rfind(raw, start, stop)
                assert queue.rfind(item=item, i=start, j=stop) == expected
                if expected == -1:
                    with pytest.raises(ValueError):
                        queue.rindex(item, start, stop)
                else:
                    assert queue.rindex(item=item, i=start, j=stop) == expected
        if raw in data:
            assert queue.rindex(item) == data.rindex(raw)
            assert queue.rindex(item, None, None) == data.rindex(raw)
        else:
            with pytest.raises(ValueError):
                queue.rindex(item)
    for method in [queue.rfind, queue.rindex]:
        for bounds in [(-1, len(data)), (0, len(data) + 1), (1, 0)]:
            with pytest.raises(ValueError):
                method(b'a', *bounds)
        with pytest.raises(TypeError):
            method('text')


def test_reverse_search_index_protocol_and_strided_needle():
    class Bound:
        def __index__(self):
            return 3

    queue = memoryqueue(b'ab', b'cab', b'c')
    needle = memoryview(b'a-b-c')[::2]
    for method in [queue.rfind, queue.rindex]:
        assert method(needle, Bound()) == 3
        assert method(needle, j=Bound()) == 0


@pytest.mark.parametrize('chunks', [(), (b'',), (b'', b'ab', b'cab', b'c', b'')])
@pytest.mark.parametrize('buffer_type', [bytes, bytearray, memoryview])
@pytest.mark.parametrize('method_name', ['startswith', 'endswith'])
def test_affix_matching(chunks, buffer_type, method_name):
    queue = memoryqueue(*chunks)
    data = b''.join(chunks)
    method = getattr(queue, method_name)
    expected_method = getattr(data, method_name)
    for raw in [b'', b'a', b'c', b'abc', b'bca', b'abcabc', b'abcdefg', b'z']:
        item = buffer_type(raw)
        assert method(item) is expected_method(raw)
        assert method(item, None, None) is expected_method(raw)
        for start in range(len(data) + 1):
            for stop in range(start, len(data) + 1):
                assert method(item, i=start, j=stop) is expected_method(
                    raw, start, stop)
    for alternatives in [(), (b'no', b'abc'), (b'abc', b'no'), (b'z', b''), (b'no', b'way')]:
        items = tuple(buffer_type(item) for item in alternatives)
        for start in range(len(data) + 1):
            for stop in range(start, len(data) + 1):
                assert method(items, start, stop) is expected_method(
                    alternatives, start, stop)
    for bounds in [(-1, len(data)), (0, len(data) + 1), (1, 0)]:
        with pytest.raises(ValueError):
            method(b'', *bounds)
    for invalid in ['text', [b'abc'], (b'no', object()), ((b'abc',),)]:
        with pytest.raises(TypeError):
            method(invalid)
    assert method((b'', object())) is True


def test_affix_keywords_and_strided_buffers():
    class Bound:
        def __index__(self):
            return 3

    queue = memoryqueue(b'ab', b'cab', b'c')
    needle = memoryview(b'a-b-c')[::2]
    assert queue.startswith(prefix=needle, i=Bound()) is True
    assert queue.endswith(suffix=needle, j=Bound()) is True
    assert queue.startswith((b'no', needle)) is True
    assert queue.endswith((b'no', needle)) is True


@pytest.mark.parametrize('method_name', ['partition', 'rpartition'])
@pytest.mark.parametrize('buffer_type', [bytes, bytearray, memoryview])
@pytest.mark.parametrize('chunks', [(), (b'', b''), (b'', b'ab', b'c', b'ab', b'c', b''),
                                    (b'a', b'aa', b'a'), (b'abab', b'abac', b'ababac')])
def test_partition_values(chunks, buffer_type, method_name):
    queue = memoryqueue(*chunks)
    data = b''.join(chunks)
    for separator in [b'a', b'aa', b'aaa', b'abc', b'bcab', b'ababac', b'abcabc', b'z', b'abcdefghijk']:
        parts = getattr(queue, method_name)(buffer_type(separator))
        assert isinstance(parts, tuple)
        assert len(parts) == 3
        assert all(isinstance(part, memoryqueue) for part in parts)
        assert tuple(map(bytes, parts)) == getattr(
            data, method_name)(separator)
        assert bytes(queue) == data
        assert [bytes(chunk) for chunk in queue.items()] == list(chunks)
    with pytest.raises(ValueError, match='empty separator'):
        getattr(queue, method_name)(buffer_type(b''))
    for invalid in ['abc', 1, (b'a',), None]:
        with pytest.raises(TypeError):
            getattr(queue, method_name)(invalid)


@pytest.mark.parametrize('method_name', ['partition', 'rpartition'])
def test_partition_preserves_chunks_and_shares_all_parts(method_name):
    chunks = [bytearray(part) for part in [b'ab', b'c<', b'=>', b'de', b'f']]
    queue = memoryqueue(*chunks)
    separator = bytearray(b'<=>')
    before, middle, after = getattr(queue, method_name)(separator)
    assert [[bytes(chunk) for chunk in part.items()] for part in (before, middle, after)] == [
        [b'ab', b'c'], [b'<', b'=>'], [b'de', b'f']]
    separator[:] = b'!!!'
    assert bytes(middle) == b'<=>'
    chunks[0][0] = ord('A')
    chunks[1][1] = ord('[')
    chunks[2][1] = ord(']')
    chunks[4][0] = ord('F')
    assert tuple(map(bytes, (before, middle, after))
                 ) == (b'Abc', b'[=]', b'deF')
    next(after.items())[0] = ord('D')
    assert chunks[3] == b'De'
    queue.clear()
    del queue, chunks
    gc.collect()
    assert tuple(map(bytes, (before, middle, after))
                 ) == (b'Abc', b'[=]', b'DeF')
    before.clear()
    assert bytes(middle) == b'[=]'


@pytest.mark.parametrize('method_name', ['partition', 'rpartition'])
def test_partition_strides_and_empty_chunks(method_name):
    queue = memoryqueue(b'', memoryview(b'a_b_c')[::2], b'', b'<', b'', b'=>', b'',
                        memoryview(b'f_e_d')[::-2], b'')
    parts = getattr(queue, method_name)(memoryview(b'<_=_>')[::2])
    assert [[bytes(chunk) for chunk in part.items()] for part in parts] == [
        [b'', b'abc'], [b'', b'<', b'', b'=>'], [b'', b'def', b'']]
    assert list(parts[0].items())[1].strides == (2,)
    assert list(parts[2].items())[1].strides == (-2,)
    absent = getattr(queue, method_name)(b'missing')
    whole = absent[0 if method_name == 'partition' else 2]
    assert whole is not queue
    assert [bytes(chunk) for chunk in whole.items()] == [
        bytes(chunk) for chunk in queue.items()]
    # Both cuts within one strided source chunk must also remain views.
    source = bytearray(b'a_b_c_d_e')
    queue = memoryqueue(memoryview(source)[::2])
    parts = getattr(queue, method_name)(b'bc')
    assert tuple(map(bytes, parts)) == (b'a', b'bc', b'de')
    assert [next(part.items()).strides for part in parts] == [(2,), (2,), (2,)]
    source[2] = ord('B')
    assert bytes(parts[1]) == b'Bc'


@pytest.mark.parametrize('method_name', ['partition', 'rpartition'])
def test_partition_does_not_materialize_queue(method_name):
    import tracemalloc

    # A large logical queue backed by one reused buffer makes any temporary
    # flattening visible without allocating a large input for the test itself.
    queue = memoryqueue(*([b'x' * (256 * 1024)] * 32))
    tracemalloc.start()
    try:
        parts = getattr(queue, method_name)(b'z')
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < len(queue) // 4
    whole = parts[0 if method_name == 'partition' else 2]
    assert len(whole) == len(queue)
    assert len(list(whole.items())) == 32


def test_partition_uses_one_snapshot():
    queue = memoryqueue(b'aa:', b':bb')
    barrier = Barrier(4)

    def worker(worker_id):
        barrier.wait()
        for _ in range(300):
            if worker_id == 0:
                queue.__init__(b'aa:', b':bb')
                queue.__init__(b'cc', b'::', b'dd')
            else:
                for method in [queue.partition, queue.rpartition]:
                    assert tuple(map(bytes, method(b'::'))) in [
                        (b'aa', b'::', b'bb'), (b'cc', b'::', b'dd')]

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(worker, range(4)))
