import random
from pathlib import Path

from rct2.rle import compress, decompress


def test_decompress_single_literal():
    assert decompress(b"\x00\x11") == b"\x11"


def test_decompress_run():
    assert decompress(b"\xfc\x00") == b"\x00\x00\x00\x00\x00"


def test_decompress_max_run():
    # control 0x80 = 128 → repeat 257-128 = 129 times
    assert decompress(b"\x80\xab") == b"\xab" * 129


def test_decompress_min_run():
    # control 0xff = 255 → repeat 257-255 = 2 times
    assert decompress(b"\xff\xab") == b"\xab\xab"


def test_decompress_max_literal():
    # control 0x7f = 127 → next 128 bytes literal
    payload = bytes(range(128))
    assert decompress(b"\x7f" + payload) == payload


def test_decompress_fixture_prefix():
    # Real bytes from manic_miner_test.td6: 00 11 fc 00 ...
    # → literal(1)=[0x11] then run(5)=[0x00]
    assert decompress(b"\x00\x11\xfc\x00") == b"\x11\x00\x00\x00\x00\x00"


def test_round_trip_empty():
    assert decompress(compress(b"")) == b""


def test_round_trip_single_byte():
    assert decompress(compress(b"\x42")) == b"\x42"


def test_round_trip_all_same():
    data = b"\x00" * 500
    assert decompress(compress(data)) == data


def test_round_trip_mixed_runs_and_literals():
    data = b"\xaa\xbb\xcc" + b"\x00" * 300 + b"\xde\xad\xbe\xef" + b"\xff" * 50
    assert decompress(compress(data)) == data


def test_round_trip_random_bytes():
    rng = random.Random(42)
    data = bytes(rng.randint(0, 255) for _ in range(2000))
    assert decompress(compress(data)) == data


def test_round_trip_real_td6_fixture():
    fixture = Path(__file__).parent.parent / "data" / "sample_rides" / "manic_miner_test.td6"
    compressed = fixture.read_bytes()[:-4]  # strip 4-byte checksum
    plain = decompress(compressed)
    assert decompress(compress(plain)) == plain
