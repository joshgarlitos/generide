"""Phase 1 success criterion: a real .td6 round-trips through decode/encode.

We compare *decompressed* bytes, not raw compressed bytes, because RLE has
multiple valid encodings of the same data (see docs/phase1-spec.md).
"""

import os
import tempfile
from pathlib import Path

from rct2 import rle, td6

FIXTURE = Path(__file__).parent.parent / "data" / "sample_rides" / "manic_miner_test.td6"


def _load_fixture_compressed() -> bytes:
    with open(FIXTURE, "rb") as f:
        original = f.read()
    return original[:-4]  # strip 4-byte checksum


def test_round_trip_decompressed_bytes_match():
    compressed = _load_fixture_compressed()
    ride = td6.decode(compressed)
    reencoded = td6.encode(ride)
    assert rle.decompress(reencoded) == rle.decompress(compressed)


def test_decoded_fields_match_known_values():
    # Cross-checked against the real fixture via REPL inspection.
    ride = td6.decode(_load_fixture_compressed())
    assert ride.ride_type == 0x11          # Mine Train
    assert ride.num_trains == 3
    assert ride.cars_per_train == 4
    assert ride.x_space_required == 18
    assert ride.y_space_required == 15
    assert ride.dat_data[4:12] == b"AMT1    "  # vehicle type string at 0x74
    assert len(ride.elements) == 89


def test_first_element_is_decoded():
    ride = td6.decode(_load_fixture_compressed())
    first = ride.elements[0]
    assert isinstance(first.segment_type, int)
    assert isinstance(first.chain_lift, bool)


def test_element_flag_round_trip():
    # Encoding then decoding a single element preserves all flags.
    el = td6.TrackElement(
        segment_type=0x04, chain_lift=True, inverted=False,
        colour_scheme=2, cable_lift=True,
    )
    raw = td6._encode_element(el)
    back = td6._decode_element(raw[0], raw[1])
    assert back == el


def test_entrances_are_parsed():
    ride = td6.decode(_load_fixture_compressed())
    assert len(ride.entrances) == 2
    # First is entrance, second is exit
    entrance = ride.entrances[0]
    exit_ = ride.entrances[1]
    assert entrance.is_exit is False
    assert exit_.is_exit is True


def test_entrance_round_trip():
    ent = td6.Entrance(x=-96, y=32, z=3, direction=0, is_exit=False)
    encoded = td6._encode_entrances([ent])
    decoded, remainder = td6._decode_entrances(encoded)
    assert len(decoded) == 1
    assert decoded[0] == ent
    assert remainder == b""


def test_load_verifies_checksum():
    ride = td6.load(FIXTURE)
    assert ride.ride_type == 0x11
    assert len(ride.elements) == 89


def test_save_creates_valid_file():
    ride = td6.load(FIXTURE)
    with tempfile.NamedTemporaryFile(suffix=".td6", delete=False) as f:
        temp_path = Path(f.name)
    try:
        td6.save(ride, temp_path)
        # Should load back without checksum error
        reloaded = td6.load(temp_path)
        assert reloaded.ride_type == ride.ride_type
        assert len(reloaded.elements) == len(ride.elements)
        assert len(reloaded.entrances) == len(ride.entrances)
    finally:
        temp_path.unlink()


def test_save_load_round_trip_preserves_scenery():
    ride = td6.load(FIXTURE)
    original_scenery_len = len(ride.scenery)
    with tempfile.NamedTemporaryFile(suffix=".td6", delete=False) as f:
        temp_path = Path(f.name)
    try:
        td6.save(ride, temp_path)
        reloaded = td6.load(temp_path)
        assert len(reloaded.scenery) == original_scenery_len
    finally:
        temp_path.unlink()
