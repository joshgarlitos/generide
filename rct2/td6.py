"""TD6 ride file decode/encode.

Sits on top of rct2.rle. A .td6 file is RLE-compressed; we decompress, parse
fields at fixed offsets and the 2-byte track elements (until a 0xFF terminator),
then parse entrance/exit structures and preserve scenery as opaque bytes.

Field offsets and the data model are documented in docs/phase1-spec.md.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

from rct2 import checksum, rle

# Header field offsets (into the decompressed byte array).
#
# Taken from OpenRCT2's `TD6Track` struct in src/openrct2/rct2/RCT2.h, which is
# the authoritative layout (the struct carries these offsets as comments and
# ends with `static_assert(sizeof(TD6Track) == 0xA3)`). Do not infer offsets
# from sample files — several of these are impossible to pin down from a
# handful of examples, and guessing produced two wrong answers before the
# struct settled them.
IDX_RIDE_TYPE = 0x00
IDX_OPERATING_MODE = 0x06
IDX_COLOR_SCHEME = 0x07
IDX_TOTAL_AIR_TIME = 0x4A
IDX_CONTROL_FLAGS = 0x4B
IDX_NUM_TRAINS = 0x4C
IDX_CARS_PER_TRAIN = 0x4D
IDX_MIN_WAIT_TIME = 0x4E
IDX_MAX_WAIT_TIME = 0x4F
IDX_MAX_SPEED = 0x51
IDX_AVERAGE_SPEED = 0x52
IDX_RIDE_LENGTH = 0x53  # uint16 little-endian, spans 0x53-0x54
LEN_RIDE_LENGTH = 2
IDX_MAX_POSITIVE_VERTICAL_G = 0x55
IDX_MAX_NEGATIVE_VERTICAL_G = 0x56  # signed
IDX_MAX_LATERAL_G = 0x57
IDX_INVERSIONS = 0x58  # union: inversions on coasters, holes on mini golf
IDX_DROPS = 0x59
IDX_HIGHEST_DROP_HEIGHT = 0x5A
IDX_EXCITEMENT = 0x5B
IDX_INTENSITY = 0x5C
IDX_NAUSEA = 0x5D
IDX_DAT_DATA = 0x70
LEN_DAT_DATA = 16
IDX_X_SPACE = 0x80
IDX_Y_SPACE = 0x81
IDX_CIRCUITS_AND_LIFT = 0xA2

# Bit masks, from RCT12.h.
DROPS_MASK = 0b00111111  # kRCT12RideNumDropsMask; upper 2 bits are not the count
INVERSIONS_MASK = 0b00011111  # kRCT12InversionAndHoleMask

# Scale factors for turning stored bytes into the numbers the game displays.
#
# Ratings and g-forces come from OpenRCT2's T6 exporter, which divides the
# runtime value by kTD46RatingsMultiplier (10) and kTD46GForcesMultiplier (32)
# respectively. Both runtime values are fixed-point hundredths, so the stored
# byte converts back by multiplying and dividing by 100.
RATING_PER_UNIT = 0.1  # stored 61 -> 6.1 excitement
G_PER_UNIT = 0.32  # 32 / 100
MPH_PER_SPEED_UNIT = 2.25  # Tech Depot; checked against simulation, see below
HEIGHT_UNITS_TO_M = 0.75  # matches physics.HEIGHT_UNIT_M

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
class Entrance:
    """Station entrance or exit position relative to track origin."""

    x: int  # signed, in sub-tile units (32 per tile)
    y: int  # signed, in sub-tile units
    z: int  # height offset
    direction: int  # 0-3, facing direction
    is_exit: bool


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
    elements: list[TrackElement]
    entrances: list[Entrance] = field(default_factory=list)
    scenery: bytes = b""  # opaque scenery data (preserved for round-trip)

    # Ride stats the game measured on its test lap, as stored. These are raw
    # bytes in the file's own units; the properties below convert them. Tracks
    # generide authors carry zeros here, because we never run a test lap — a
    # zero means "not measured", not "measured as zero".
    ride_length: int = 0  # meters
    max_positive_vertical_g: int = 0
    max_negative_vertical_g: int = 0  # signed; negative means airtime
    max_lateral_g: int = 0
    inversions: int = 0  # holes, on mini golf
    drops: int = 0  # low 6 bits are the count
    highest_drop_height: int = 0  # RCT2 height units
    total_air_time: int = 0

    @property
    def remainder(self) -> bytes:
        """Legacy accessor: returns entrances + scenery as raw bytes."""
        return _encode_entrances(self.entrances) + self.scenery

    # Converted views of the stats above. Ratings and g-forces are pinned to
    # OpenRCT2's own multipliers; see the constants at the top of this module.

    @property
    def excitement_rating(self) -> float:
        return self.excitement * RATING_PER_UNIT

    @property
    def intensity_rating(self) -> float:
        return self.intensity * RATING_PER_UNIT

    @property
    def nausea_rating(self) -> float:
        return self.nausea * RATING_PER_UNIT

    @property
    def max_positive_vertical_g_force(self) -> float:
        return self.max_positive_vertical_g * G_PER_UNIT

    @property
    def max_negative_vertical_g_force(self) -> float:
        return self.max_negative_vertical_g * G_PER_UNIT

    @property
    def max_lateral_g_force(self) -> float:
        return self.max_lateral_g * G_PER_UNIT

    @property
    def drop_count(self) -> int:
        """Number of drops, with the two flag bits above the count masked off."""
        return self.drops & DROPS_MASK

    @property
    def inversion_count(self) -> int:
        return self.inversions & INVERSIONS_MASK

    @property
    def highest_drop_height_m(self) -> float:
        return self.highest_drop_height * HEIGHT_UNITS_TO_M

    @property
    def max_speed_mph(self) -> float:
        return self.max_speed * MPH_PER_SPEED_UNIT

    @property
    def average_speed_mph(self) -> float:
        return self.average_speed * MPH_PER_SPEED_UNIT


def _signed_byte(value: int) -> int:
    """Interpret an unsigned byte as int8. Used for max negative vertical g."""
    return value - 256 if value > 127 else value


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


def _decode_entrances(data: bytes) -> tuple[list[Entrance], bytes]:
    """Parse entrance/exit structures, return (entrances, remaining_scenery)."""
    entrances = []
    i = 0
    while i < len(data) and data[i] != TERMINATOR:
        direction = data[i]
        flags = data[i + 1]
        x = int.from_bytes(data[i + 2 : i + 4], "little", signed=True)
        y = int.from_bytes(data[i + 4 : i + 6], "little", signed=True)
        is_exit = bool(flags & 0x80)
        z = flags & 0x7F
        entrances.append(Entrance(x=x, y=y, z=z, direction=direction, is_exit=is_exit))
        i += 6
    # Skip the terminator
    if i < len(data) and data[i] == TERMINATOR:
        i += 1
    return entrances, data[i:]


def _encode_entrances(entrances: list[Entrance]) -> bytes:
    """Serialize entrance/exit structures with terminator."""
    out = bytearray()
    for ent in entrances:
        flags = (0x80 if ent.is_exit else 0x00) | (ent.z & 0x7F)
        out.append(ent.direction)
        out.append(flags)
        out.extend(ent.x.to_bytes(2, "little", signed=True))
        out.extend(ent.y.to_bytes(2, "little", signed=True))
    out.append(TERMINATOR)
    return bytes(out)


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
    after_track = d[terminator_idx + 1 :]

    # Parse entrance/exit structures
    entrances, scenery = _decode_entrances(after_track)

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
        dat_data=d[IDX_DAT_DATA : IDX_DAT_DATA + LEN_DAT_DATA],
        x_space_required=d[IDX_X_SPACE],
        y_space_required=d[IDX_Y_SPACE],
        circuits_and_lift_speed=d[IDX_CIRCUITS_AND_LIFT],
        header=d[:IDX_TRACK_DATA],
        elements=elements,
        entrances=entrances,
        scenery=scenery,
        ride_length=int.from_bytes(
            d[IDX_RIDE_LENGTH : IDX_RIDE_LENGTH + LEN_RIDE_LENGTH], "little"
        ),
        max_positive_vertical_g=d[IDX_MAX_POSITIVE_VERTICAL_G],
        max_negative_vertical_g=_signed_byte(d[IDX_MAX_NEGATIVE_VERTICAL_G]),
        max_lateral_g=d[IDX_MAX_LATERAL_G],
        inversions=d[IDX_INVERSIONS],
        drops=d[IDX_DROPS],
        highest_drop_height=d[IDX_HIGHEST_DROP_HEIGHT],
        total_air_time=d[IDX_TOTAL_AIR_TIME],
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
    out[IDX_DAT_DATA : IDX_DAT_DATA + LEN_DAT_DATA] = ride.dat_data
    out[IDX_X_SPACE] = ride.x_space_required
    out[IDX_Y_SPACE] = ride.y_space_required
    out[IDX_CIRCUITS_AND_LIFT] = ride.circuits_and_lift_speed
    out[IDX_RIDE_LENGTH : IDX_RIDE_LENGTH + LEN_RIDE_LENGTH] = (
        ride.ride_length.to_bytes(LEN_RIDE_LENGTH, "little")
    )
    out[IDX_MAX_POSITIVE_VERTICAL_G] = ride.max_positive_vertical_g
    out[IDX_MAX_NEGATIVE_VERTICAL_G] = ride.max_negative_vertical_g & 0xFF
    out[IDX_MAX_LATERAL_G] = ride.max_lateral_g
    out[IDX_INVERSIONS] = ride.inversions
    out[IDX_DROPS] = ride.drops
    out[IDX_HIGHEST_DROP_HEIGHT] = ride.highest_drop_height
    out[IDX_TOTAL_AIR_TIME] = ride.total_air_time

    for el in ride.elements:
        out += _encode_element(el)
    out.append(TERMINATOR)
    out += _encode_entrances(ride.entrances)
    out += ride.scenery

    return rle.compress(bytes(out))


# --- File-level convenience functions ---


def load(path: Union[str, Path]) -> Ride:
    """Load a .td6 file, verify checksum, and decode into a Ride."""
    data = Path(path).read_bytes()
    content, expected = checksum.strip(data)
    if not checksum.verify(content, expected):
        raise ValueError(f"checksum mismatch: expected {expected}, got {checksum.compute(content)}")
    return decode(content)


def save(ride: Ride, path: Union[str, Path]) -> None:
    """Encode a Ride and write to a .td6 file with checksum."""
    compressed = encode(ride)
    Path(path).write_bytes(checksum.append(compressed))
