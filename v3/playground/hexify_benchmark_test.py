import pytest
import timeit
import random

raw = [random.randint(0, 255) for _ in range(0, 1024*256)]

setup = """
h = Hexify(16)
"""

stmt = """
list(h.hexify(raw, 0x1000_0000))
"""

def original():
    from hexify_original import Hexify
    print(timeit.timeit(stmt=stmt, setup=setup, number=4, globals={**globals(), **locals()}))


def current():
    from hexify import Hexify
    print(timeit.timeit(stmt=stmt, setup=setup, number=4, globals={**globals(), **locals()}))


def test_compare():
    original()
    current()
    assert False
