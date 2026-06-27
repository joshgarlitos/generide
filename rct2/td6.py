"""TD6 ride file decode/encode.

Sits on top of rct2.rle. A .td6 file is RLE-compressed; we decompress, parse
fields at fixed offsets and the 2-byte track elements (until a 0xFF terminator),
and keep everything else as opaque bytes that round-trip verbatim.

Field offsets and the data model are documented in docs/phase1-spec.md.
"""

from dataclasses import dataclass

from rct2 import rle

# Header field offsets (into the decompressed byte array).
IDX_RIDE_TYPE = 0x00
IDX_OPERATING_MODE = 0x06
IDX_COLOR_SCHEME = 0x07
IDX_CONTROL_FLAGS = 0x4B
IDX_NUM_TRAINS = 0x4C
IDX_CARS_PER_TRAIN = 0x4D
IDX_MIN_WAIT_TIME = 0x4E
IDX_MAX_WAIT_TIME = 0x4F
IDX_MAX_SPEED = 0x51
IDX_AVERAGE_SPEED = 0x52
IDX_EXCITEMENT = 0x5B
IDX_INTENSITY = 0x5C
IDX_NAUSEA = 0x5D
IDX_DAT_DATA = 0x70
LEN_DAT_DATA = 16
IDX_X_SPACE = 0x80
IDX_Y_SPACE = 0x81
IDX_CIRCUITS_AND_LIFT = 0xA2

# Track element data starts here; the header is everything before it.
IDX_TRACK_DATA = 0xA3

# Track element flag bits (byte 1 of each 2-byte element).
BIT_CHAIN_LIFT = 7
BIT_INVERTED = 6
BIT_CABLE_LIFT = 0
COLOUR_SCHEME_SHIFT = 1
COLOUR_SCHEME_MASK = 0b11

TERMINATOR = 0xFF


@dataclass
class TrackElement:
    segment_type: int
    chain_lift: bool
    inverted: bool
    colour_scheme: int
    cable_lift: bool


@dataclass
class Ride:
    ride_type: int
    operating_mode: int
    color_scheme: int
    control_flags: int
    num_trains: int
    cars_per_train: int
    min_wait_time: int
    max_wait_time: int
    max_speed: int
    average_speed: int
    excitement: int
    intensity: int
    nausea: int
    dat_data: bytes
    x_space_required: int
    y_space_required: int
    circuits_and_lift_speed: int
    header: bytes
    elements: list
    remainder: bytes


def _decode_element(seg: int, flags: int) -> TrackElement:
    return TrackElement(
        segment_type=seg,
        chain_lift=bool(flags >> BIT_CHAIN_LIFT & 1),
        inverted=bool(flags >> BIT_INVERTED & 1),
        colour_scheme=flags >> COLOUR_SCHEME_SHIFT & COLOUR_SCHEME_MASK,
        cable_lift=bool(flags >> BIT_CABLE_LIFT & 1),
    )


def _encode_element(el: TrackElement) -> bytes:
    flags = 0
    if el.chain_lift:
        flags |= 1 << BIT_CHAIN_LIFT
    if el.inverted:
        flags |= 1 << BIT_INVERTED
    flags |= (el.colour_scheme & COLOUR_SCHEME_MASK) << COLOUR_SCHEME_SHIFT
    if el.cable_lift:
        flags |= 1 << BIT_CABLE_LIFT
    return bytes([el.segment_type, flags])


def decode(compressed: bytes) -> Ride:
    """Decompress and parse raw .td6 bytes (checksum already stripped) into a Ride."""
    d = rle.decompress(compressed)

    # Walk 2-byte track elements until the 0xFF terminator.
    elements = []
    i = IDX_TRACK_DATA
    while i < len(d) and d[i] != TERMINATOR:
        elements.append(_decode_element(d[i], d[i + 1]))
        i += 2
    terminator_idx = i
    remainder = d[terminator_idx + 1:]

    return Ride(
        ride_type=d[IDX_RIDE_TYPE],
        operating_mode=d[IDX_OPERATING_MODE],
        color_scheme=d[IDX_COLOR_SCHEME],
        control_flags=d[IDX_CONTROL_FLAGS],
        num_trains=d[IDX_NUM_TRAINS],
        cars_per_train=d[IDX_CARS_PER_TRAIN],
        min_wait_time=d[IDX_MIN_WAIT_TIME],
        max_wait_time=d[IDX_MAX_WAIT_TIME],
        max_speed=d[IDX_MAX_SPEED],
        average_speed=d[IDX_AVERAGE_SPEED],
        excitement=d[IDX_EXCITEMENT],
        intensity=d[IDX_INTENSITY],
        nausea=d[IDX_NAUSEA],
        dat_data=d[IDX_DAT_DATA:IDX_DAT_DATA + LEN_DAT_DATA],
        x_space_required=d[IDX_X_SPACE],
        y_space_required=d[IDX_Y_SPACE],
        circuits_and_lift_speed=d[IDX_CIRCUITS_AND_LIFT],
        header=d[:IDX_TRACK_DATA],
        elements=elements,
        remainder=remainder,
    )


def encode(ride: Ride) -> bytes:
    """Serialize a Ride back to raw compressed .td6 bytes (no checksum)."""
    # Start from the raw header so unparsed bytes survive, then overlay fields.
    out = bytearray(ride.header)
    out[IDX_RIDE_TYPE] = ride.ride_type
    out[IDX_OPERATING_MODE] = ride.operating_mode
    out[IDX_COLOR_SCHEME] = ride.color_scheme
    out[IDX_CONTROL_FLAGS] = ride.control_flags
    out[IDX_NUM_TRAINS] = ride.num_trains
    out[IDX_CARS_PER_TRAIN] = ride.cars_per_train
    out[IDX_MIN_WAIT_TIME] = ride.min_wait_time
    out[IDX_MAX_WAIT_TIME] = ride.max_wait_time
    out[IDX_MAX_SPEED] = ride.max_speed
    out[IDX_AVERAGE_SPEED] = ride.average_speed
    out[IDX_EXCITEMENT] = ride.excitement
    out[IDX_INTENSITY] = ride.intensity
    out[IDX_NAUSEA] = ride.nausea
    out[IDX_DAT_DATA:IDX_DAT_DATA + LEN_DAT_DATA] = ride.dat_data
    out[IDX_X_SPACE] = ride.x_space_required
    out[IDX_Y_SPACE] = ride.y_space_required
    out[IDX_CIRCUITS_AND_LIFT] = ride.circuits_and_lift_speed

    for el in ride.elements:
        out += _encode_element(el)
    out.append(TERMINATOR)
    out += ride.remainder

    return rle.compress(bytes(out))
