"""Phase 1 success criterion: a real .td6 round-trips through decode/encode.

We compare *decompressed* bytes, not raw compressed bytes, because RLE has
multiple valid encodings of the same data (see docs/phase1-spec.md).
"""

import os
import tempfile
from pathlib import Path

import pytest

from rct2 import physics, rle, td6
from rct2.generate import create_simple_circuit, generate_ride

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


def test_ride_stats_decode_from_the_fixture():
    """Pin the raw stored stat bytes so an offset change can't slip through.

    Offsets come from OpenRCT2's TD6Track struct, not from inspecting samples.
    """
    ride = td6.load(FIXTURE)

    assert ride.max_speed == 16
    assert ride.average_speed == 7
    assert ride.ride_length == 691        # uint16 spanning 0x53-0x54
    assert ride.max_positive_vertical_g == 8
    assert ride.max_negative_vertical_g == -2   # signed byte
    assert ride.max_lateral_g == 4
    assert ride.inversions == 0
    assert ride.drops == 6
    assert ride.highest_drop_height == 10
    assert ride.total_air_time == 10      # 0x4A, not in the 0x53-0x5A block
    assert ride.excitement == 62
    assert ride.intensity == 65
    assert ride.nausea == 42


def test_ride_stat_conversions_match_openrct2_multipliers():
    """The converted values, with the scale each one rests on.

    Ratings divide by 10 (kTD46RatingsMultiplier) and g-forces multiply by
    32/100 (kTD46GForcesMultiplier over the runtime's fixed-point hundredths),
    both read off OpenRCT2's T6 exporter rather than guessed from samples.
    """
    ride = td6.load(FIXTURE)

    assert ride.excitement_rating == pytest.approx(6.2)
    assert ride.intensity_rating == pytest.approx(6.5)
    assert ride.nausea_rating == pytest.approx(4.2)

    assert ride.max_positive_vertical_g_force == pytest.approx(2.56)
    assert ride.max_negative_vertical_g_force == pytest.approx(-0.64)
    assert ride.max_lateral_g_force == pytest.approx(1.28)

    assert ride.max_speed_mph == pytest.approx(36.0)
    assert ride.highest_drop_height_m == pytest.approx(7.5)


def test_drop_count_masks_the_flag_bits():
    """The drops byte carries the count in its low 6 bits only.

    Without the mask a shipped design reads 70 drops where the real answer is
    6, which is how the packing was noticed in the first place.
    """
    ride = td6.load(FIXTURE)
    ride.drops = 70  # 0b01000110 — as stored in the shipped Manic Miner

    assert ride.drop_count == 6
    assert ride.inversion_count == 0


def test_decoded_drop_count_agrees_with_the_physics_model():
    """Independent check on the mask: our own simulation counts the same drops.

    Two unrelated derivations landing on 6 is what confirms the low-6-bits
    reading rather than the raw byte.
    """
    ride = td6.load(FIXTURE)
    segments = [element.segment_type for element in ride.elements]
    lifts = {i for i, element in enumerate(ride.elements) if element.chain_lift}

    assert physics.simulate(segments, lift_indices=lifts).drop_count == ride.drop_count


def test_ride_stats_survive_a_round_trip():
    ride = td6.load(FIXTURE)
    reloaded = td6.decode(td6.encode(ride))

    for name in (
        "ride_length", "max_positive_vertical_g", "max_negative_vertical_g",
        "max_lateral_g", "inversions", "drops", "highest_drop_height",
        "total_air_time",
    ):
        assert getattr(reloaded, name) == getattr(ride, name), name


def test_negative_vertical_g_survives_as_a_signed_byte():
    ride = td6.load(FIXTURE)
    ride.max_negative_vertical_g = -7

    assert td6.decode(td6.encode(ride)).max_negative_vertical_g == -7


def test_generated_rides_report_zero_because_nothing_measured_them():
    """generide never runs a test lap, so its files carry no stats.

    Zero here means "not measured", not "measured as zero" — worth pinning so
    a later calibration pass doesn't read our own output as ground truth.
    """
    ride = generate_ride(create_simple_circuit(), FIXTURE)

    assert ride.excitement == 0
    assert ride.max_positive_vertical_g == 0
    assert ride.drops == 0
    assert ride.ride_length == 0
