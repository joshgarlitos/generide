"""Phase 1 success criterion: a real .td6 round-trips through decode/encode.

We compare *decompressed* bytes, not raw compressed bytes, because RLE has
multiple valid encodings of the same data (see docs/phase1-spec.md).
"""

import os

from rct2 import rle, td6

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "data", "sample_rides", "manic_miner_test.td6"
)


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
