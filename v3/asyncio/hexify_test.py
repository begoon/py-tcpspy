import pytest

import hexify

header1 = "######## ######## 00.01.02.03.04.05.06.07.08.09.0A.0B.0C.0D.0E.0F\n"
header2 = "-------- -------- -----------------------------------------------\n"


def test_constructor_parameters():
    h = hexify.Hexify(16)
    assert h.width == 16
    assert len(h.padding_legend) == len(h.padding_separator)
    assert isinstance(h.printables, list)
    assert len(h.printables) == 256


def test_header():
    h = hexify.Hexify(16).header()
    assert next(h) == header1
    assert next(h) == header2


def test_hexify_empty_data():
    h = hexify.Hexify(16).hexify_data("", -1)
    with pytest.raises(StopIteration):
        assert next(h)


def test_hexify_data():
    h = hexify.Hexify(16).hexify_data(b'*\xAB\xCD', 0x80001234)
    assert next(
        h
    ) == '80001234 00000000 2A AB CD                                        |*..|\n'


def test_hexify_multiline_data():
    h = hexify.Hexify(16).hexify_data(range(17), 0xC0DE)
    assert next(
        h
    ) == '0000C0DE 00000000 00 01 02 03 04 05 06 07 08 09 0A 0B 0C 0D 0E 0F |................|\n'
    assert next(
        h
    ) == '0000C0EE 00000010 10                                              |.|\n'


def test_hexify():
    h = hexify.Hexify(16).hexify(b'\xAB\xCD', 0xBEAF)
    assert next(h) == header1
    assert next(h) == header2
    assert next(
        h
    ) == '0000BEAF 00000000 AB CD                                           |..|\n'


def test_printable():
    h = hexify.Hexify(16)
    assert h.printable(0) == '.'
    assert h.printable(32) == ' '
    assert h.printable(255) == '.'
