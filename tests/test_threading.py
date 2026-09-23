"""Run on both regular and free-threaded CPython."""

from concurrent.futures import ThreadPoolExecutor
import os
import subprocess
import sys
import sysconfig
from threading import Barrier

import pytest

from jetblack_memoryqueue import memoryqueue


def run_threads(*functions):
    barrier = Barrier(len(functions))

    def run(function):
        barrier.wait(timeout=10)
        return function()

    with ThreadPoolExecutor(max_workers=len(functions)) as executor:
        futures = [executor.submit(run, function) for function in functions]
        return [future.result(timeout=30) for future in futures]


@pytest.mark.skipif(not sysconfig.get_config_var('Py_GIL_DISABLED'),
                    reason='requires a free-threaded interpreter')
def test_import_keeps_gil_disabled():
    # Do not force gil=0: that would hide a missing module declaration.
    env = os.environ.copy()
    env.pop('PYTHON_GIL', None)
    subprocess.run([sys.executable, '-W', 'error', '-c', '''
import sys
assert not sys._is_gil_enabled()
import jetblack_memoryqueue
assert not sys._is_gil_enabled()
'''], env=env, check=True, timeout=30)


def test_concurrent_append_and_pop():
    queue = memoryqueue()
    count = 1000

    def producer():
        for _ in range(count):
            queue.append(b'ab')

    run_threads(producer, producer, producer, producer)
    assert len(queue) == count * 8
    assert bytes(queue) == b'ab' * (count * 4)

    def consumer():
        items = []
        while True:
            try:
                view = queue.popleft()
            except IndexError:
                return items
            items.append(bytes(view))
            view.release()

    results = run_threads(consumer, consumer, consumer, consumer)
    assert sum(map(len, results)) == count * 4
    assert all(item == b'ab' for items in results for item in items)
    assert len(queue) == 0
    assert queue._views == []


def test_reads_during_mutation():
    queue = memoryqueue(b'ab', b'ab')

    def mutate():
        for _ in range(1000):
            queue.append(b'ab')
            try:
                queue.popleft().release()
            except IndexError:
                pass
            queue.clear()
            queue.__init__(b'ab', b'ab')

    def check(data):
        assert data == b'ab' * (len(data) // 2)

    def read():
        for _ in range(1000):
            check(bytes(queue))
            check(bytes(queue[:]))
            check(b''.join(queue))
            check(b''.join(queue._views))
            assert len(queue) % 2 == 0
            try:
                assert queue[0] == ord('a')
            except IndexError:
                pass
            assert queue.find(b'z') == -1
            assert b'z' not in queue
            assert queue != b'z'
            with memoryview(queue) as view:
                check(bytes(view))

    run_threads(mutate, mutate, read, read)
    assert len(queue) == len(bytes(queue))


def test_cross_queue_append_does_not_deadlock():
    left, right = memoryqueue(b'a'), memoryqueue(b'b')

    def copy(source, target):
        for _ in range(500):
            target.clear()
            target.append(source)
            assert isinstance(target == source, bool)

    run_threads(lambda: copy(left, right), lambda: copy(right, left))


def test_index_callback_can_mutate_queue_and_release_popped_view():
    queue = memoryqueue(b'abc')

    class Index:
        def __index__(self):
            queue.popleft().release()
            queue.append(b'new')
            return 1

    assert queue[Index()] == ord('b')
    assert bytes(queue) == b'new'


def test_exporter_callbacks_can_reenter_queue():
    queue = memoryqueue()

    class Exporter:
        def __buffer__(self, flags):
            queue.append(b'inner')
            return memoryview(b'outer')

        def __release_buffer__(self, view):
            queue.append(b'released')

    queue.append(Exporter())
    assert bytes(queue) == b'innerouter'
    queue.clear()
    assert bytes(queue) == b'released'


def test_coalescing_does_not_lose_concurrent_appends():
    queue = memoryqueue()

    def append():
        for _ in range(1000):
            queue.append(b'ab')

    def export():
        for _ in range(1000):
            with memoryview(queue) as view:
                data = bytes(view)
                assert data == b'ab' * (len(data) // 2)

    run_threads(append, append, export, export)
    assert bytes(queue) == b'ab' * 2000
    assert len(queue) == 4000
