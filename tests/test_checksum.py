"""Tests for RCT2 checksum computation."""

from pathlib import Path

from rct2 import checksum

FIXTURE = Path(__file__).parent.parent / "data" / "sample_rides" / "manic_miner_test.td6"


def test_compute_matches_fixture():
    raw = FIXTURE.read_bytes()
    content, expected = checksum.strip(raw)
    assert checksum.compute(content) == expected


def test_verify_returns_true_for_valid_checksum():
    raw = FIXTURE.read_bytes()
    content, expected = checksum.strip(raw)
    assert checksum.verify(content, expected)


def test_verify_returns_false_for_corrupted_data():
    raw = FIXTURE.read_bytes()
    content, expected = checksum.strip(raw)
    corrupted = bytes([content[0] ^ 0xFF]) + content[1:]
    assert not checksum.verify(corrupted, expected)


def test_append_creates_verifiable_data():
    original = b"hello world test data"
    with_checksum = checksum.append(original)
    assert len(with_checksum) == len(original) + 4
    content, cs = checksum.strip(with_checksum)
    assert content == original
    assert checksum.verify(content, cs)


def test_strip_extracts_content_and_checksum():
    raw = FIXTURE.read_bytes()
    content, cs = checksum.strip(raw)
    assert len(content) == len(raw) - 4
    assert isinstance(cs, int)


def test_round_trip_fixture():
    raw = FIXTURE.read_bytes()
    content, _ = checksum.strip(raw)
    rebuilt = checksum.append(content)
    assert rebuilt == raw
