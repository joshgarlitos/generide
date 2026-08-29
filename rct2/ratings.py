"""Port of OpenRCT2's real ride rating calculation.

Derived work notice
-------------------
The algorithm, coefficients, and thresholds in this module are transcribed
from OpenRCT2, Copyright (c) 2014-2026 OpenRCT2 developers, which is licensed
under the GNU General Public License version 3. Sources:

    src/openrct2/ride/RideRatings.cpp
    src/openrct2/ride/rtd/coaster/MineTrainCoaster.h
    src/openrct2/ride/Ride.cpp          (turn count bucketing)

generide is itself GPL-3.0 (see LICENSE), so this derivation is permitted and
the license is unchanged by it. Translating the code from C++ to Python does
not make it a new work: it stays a derivative, which is why the attribution
above belongs here rather than only in a commit message.

What the module does
--------------------
This replaces guessing. OpenRCT2 is a decompilation of RCT2, so the original
calculation survives in `RideRatings.cpp` with its integer constants intact,
and each ride type's coefficients live in its own header. Everything here is
transcribed from that source rather than fitted; see docs/devlog.md
(2026-08-08) and issue #40.

`rct2/physics.py`'s `RATING_WEIGHTS` and `rate()` are the older least-squares
fit against 204 shipped designs. They are deliberately still there so the two
can be compared, but this module is the one that can express what that fit
structurally could not: the game applies threshold checks that *divide* all
three ratings, and a linear model has no way to represent a cliff.

Unit conventions, which are the game's rather than ours:
- Ratings are fixed point x100 held in an int16. 652 means 6.52. Every add
  clamps to [0, 32767], which `_add` reproduces.
- Coefficients are 16.16 fixed point, applied as `(value * coeff) >> 16`.
- G-forces are fixed point x100 (250 means 2.50g).
- Speeds are the game's internal unit, which is what a TD6 header stores:
  one unit is MPH_PER_SPEED_UNIT (2.25) miles per hour.
- Drop height is in RCT2 height units, matching `RideStats.highest_drop`.
"""

from dataclasses import dataclass
from typing import Optional

from rct2.physics import RideStats
from rct2.segments import SEGMENTS

RATING_MAX = 32767  # INT16_MAX, the clamp in RideRatingsAdd
MPH_PER_SPEED_UNIT = 2.25  # matches td6.MPH_PER_SPEED_UNIT


def make(whole: int, hundredths: int) -> int:
    """The game's RideRating::make(a, b) -- a.b as fixed point x100."""
    return whole * 100 + hundredths


@dataclass
class Tuple3:
    """The game's RideRating::Tuple. Values are fixed point x100."""

    excitement: int = 0
    intensity: int = 0
    nausea: int = 0


def _add(ratings: Tuple3, excitement: int, intensity: int, nausea: int) -> None:
    """RideRatingsAdd: add then clamp each axis to [0, INT16_MAX].

    The clamp is not decoration. Ratings are held in an int16 and the game
    saturates rather than wrapping, so a wildly intense track pins at the
    ceiling instead of going negative.
    """
    ratings.excitement = min(max(ratings.excitement + excitement, 0), RATING_MAX)
    ratings.intensity = min(max(ratings.intensity + intensity, 0), RATING_MAX)
    ratings.nausea = min(max(ratings.nausea + nausea, 0), RATING_MAX)


# Mine Train Coaster, transcribed from MineTrainCoaster.h. The tuple after each
# name is (threshold, excitement, intensity, nausea) exactly as the game stores
# it. Modifiers our tracks can never trigger (synchronisation, reversed trains)
# are kept in the table for fidelity but contribute nothing.
MINE_TRAIN_BASE = Tuple3(make(2, 90), make(2, 30), make(2, 10))

MINE_TRAIN = {
    "bonus_length": (6000, 764, 0, 0),
    "bonus_train_length": (0, 187245, 0, 0),
    "bonus_max_speed": (0, 44281, 88562, 35424),
    "bonus_average_speed": (0, 291271, 436906, 0),
    "bonus_duration": (150, 26214, 0, 0),
    "bonus_gforces": (0, 40960, 35746, 49648),
    "bonus_turns": (0, 29721, 34767, 45749),
    "bonus_drops": (0, 29127, 46811, 49152),
    "bonus_sheltered": (0, 19275, 32768, 35108),
    "bonus_proximity": (0, 21472, 0, 0),
    "bonus_scenery": (0, 16732, 0, 0),
    "requirement_drop_height": (8, 2, 2, 2),
    "requirement_max_speed": (0xA0000 >> 16, 2, 2, 2),
    "requirement_negative_gs": (make(0, 10), 2, 2, 2),
    "requirement_num_drops": (2, 2, 2, 2),
    "penalty_lateral_gs": (0, 40960, 35746, 49648),
}


# ---------------------------------------------------------------------------
# Ride-independent sub-ratings. These are the same for every ride type; the
# per-type coefficients above scale them afterwards.
# ---------------------------------------------------------------------------


def gforce_ratings(pos_g: int, neg_g: int, lat_g: int) -> Tuple3:
    """ride_ratings_get_gforce_ratings. All arguments are fixed point x100.

    `neg_g` is signed and negative when the train goes light over a crest,
    matching how the game stores it.
    """
    result = Tuple3()
    result.excitement += (pos_g * 5242) >> 16
    result.intensity += (pos_g * 52428) >> 16
    result.nausea += (pos_g * 17039) >> 16

    clamped = min(max(neg_g, -make(2, 50)), make(0, 0))
    result.excitement += (clamped * -15728) >> 16
    result.intensity += ((neg_g - make(1, 0)) * -52428) >> 16
    result.nausea += ((neg_g - make(1, 0)) * -14563) >> 16

    result.excitement += (min(make(1, 50), lat_g) * 26214) >> 16
    result.intensity += lat_g
    result.nausea += (lat_g * 21845) >> 16
    return result


def drop_ratings(num_drops: int, highest_drop_height: int) -> Tuple3:
    """ride_ratings_get_drop_ratings.

    Excitement stops rewarding drops past 9 of them; intensity and nausea
    keep climbing, which is why a track stuffed with drops gets punishing
    without getting more fun.
    """
    result = Tuple3()
    result.excitement += (min(9, num_drops) * 728177) >> 16
    result.intensity += (num_drops * 928426) >> 16
    result.nausea += (num_drops * 655360) >> 16

    _add(
        result,
        ((highest_drop_height * 2) * 16000) >> 16,
        ((highest_drop_height * 2) * 32000) >> 16,
        ((highest_drop_height * 2) * 10240) >> 16,
    )
    return result


@dataclass
class TurnCounts:
    """Turns bucketed by how many track elements long the run was.

    The game keeps three packed counters, one each for flat, banked, and
    sloped turns, and buckets a run by its element count. For flat and banked
    turns a run of 4 or more falls back into the 3-element bucket, so that
    bucket means "3 or more"; only sloped turns have a real 4+ bucket.
    """

    one: int = 0
    two: int = 0
    three_plus: int = 0
    four_plus: int = 0  # sloped only


def flat_turns_rating(t: TurnCounts) -> Tuple3:
    """get_flat_turns_rating."""
    r = Tuple3()
    r.excitement = (t.three_plus * 0x28000) >> 16
    r.excitement += (t.two * 0x30000) >> 16
    r.excitement += (t.one * 63421) >> 16
    r.intensity = (t.three_plus * 81920) >> 16
    r.intensity += (t.two * 49152) >> 16
    r.intensity += (t.one * 21140) >> 16
    r.nausea = (t.three_plus * 0x50000) >> 16
    r.nausea += (t.two * 0x32000) >> 16
    r.nausea += (t.one * 42281) >> 16
    return r


def banked_turns_rating(t: TurnCounts) -> Tuple3:
    """get_banked_turns_rating."""
    r = Tuple3()
    r.excitement = (t.three_plus * 0x3C000) >> 16
    r.excitement += (t.two * 0x3C000) >> 16
    r.excitement += (t.one * 73992) >> 16
    r.intensity = (t.three_plus * 0x14000) >> 16
    r.intensity += (t.two * 49152) >> 16
    r.intensity += (t.one * 21140) >> 16
    r.nausea = (t.three_plus * 0x50000) >> 16
    r.nausea += (t.two * 0x32000) >> 16
    r.nausea += (t.one * 48623) >> 16
    return r


def sloped_turns_rating(t: TurnCounts) -> Tuple3:
    """get_sloped_turns_rating.

    Every term is capped, so sloped turns stop paying after a handful. They
    contribute no intensity at all.
    """
    r = Tuple3()
    r.excitement = (min(t.four_plus, 4) * 0x78000) >> 16
    r.excitement += (min(t.three_plus, 6) * 273066) >> 16
    r.excitement += (min(t.two, 6) * 0x3AAAA) >> 16
    r.excitement += (min(t.one, 7) * 187245) >> 16
    r.intensity = 0
    r.nausea = (min(t.four_plus, 8) * 0x78000) >> 16
    return r


def inversion_ratings(num_inversions: int) -> Tuple3:
    """getInversionsRatings. generide never builds these, so it is always 0."""
    return Tuple3(
        excitement=(min(6, num_inversions) * 0x1AAAAA) >> 16,
        intensity=(num_inversions * 0x320000) >> 16,
        nausea=(num_inversions * 0x1C0000) >> 16,
    )


def turns_ratings(flat: TurnCounts, banked: TurnCounts, sloped: TurnCounts,
                  num_inversions: int = 0) -> Tuple3:
    """ride_ratings_get_turns_ratings, minus special track elements.

    Special elements (water splashes, spinning tunnels, and the like) are
    omitted because our segment vocabulary contains none of them.
    """
    result = Tuple3()
    for part in (flat_turns_rating(flat), banked_turns_rating(banked),
                 sloped_turns_rating(sloped), inversion_ratings(num_inversions)):
        result.excitement += part.excitement
        result.intensity += part.intensity
        result.nausea += part.nausea
    return result


# ---------------------------------------------------------------------------
# Turn counting from a segment list
# ---------------------------------------------------------------------------

# Turn pieces that bank. Shared intent with physics._BANKED_TURNS; kept here
# because the game classifies a whole turn run by the flags of the piece that
# starts it, which is a rating concern rather than a physics one.
_BANKED_TURN_SEGMENTS = {0x16, 0x17, 0x2C, 0x2D, 0x5A, 0x5E}


def count_turns(segments: list[int]) -> tuple[TurnCounts, TurnCounts, TurnCounts]:
    """Bucket a segment list's turns into (flat, banked, sloped) counts.

    The game walks the track during its test lap, treats a maximal run of
    consecutive same-direction turn elements as one turn, and classifies the
    whole run by whether it is banked (type 1), otherwise sloped (type 2),
    otherwise flat (type 0). That order matters: a turn that is both banked
    and sloped counts as banked.

    This is an approximation in one respect. The game reads per-piece
    `TrackElementFlag` values we do not have, so banking comes from our own
    piece list and "sloped" is inferred from a non-zero elevation delta.
    """
    flat, banked, sloped = TurnCounts(), TurnCounts(), TurnCounts()

    index = 0
    while index < len(segments):
        segment = SEGMENTS.get(segments[index])
        if segment is None or segment.direction_delta == 0:
            index += 1
            continue

        direction = 1 if segment.direction_delta > 0 else -1
        run_banked = segments[index] in _BANKED_TURN_SEGMENTS
        run_sloped = segment.elevation_delta != 0
        run_length = 0

        while index < len(segments):
            current = SEGMENTS.get(segments[index])
            if current is None or current.direction_delta == 0:
                break
            if (1 if current.direction_delta > 0 else -1) != direction:
                break
            if segments[index] in _BANKED_TURN_SEGMENTS:
                run_banked = True
            if current.elevation_delta != 0:
                run_sloped = True
            run_length += 1
            index += 1

        if run_banked:
            counts = banked
        elif run_sloped:
            counts = sloped
        else:
            counts = flat

        if run_length == 1:
            counts.one += 1
        elif run_length == 2:
            counts.two += 1
        elif run_length == 3:
            counts.three_plus += 1
        elif counts is sloped:
            counts.four_plus += 1
        else:
            # Flat and banked turns have no 4+ bucket; the game falls back.
            counts.three_plus += 1

    return flat, banked, sloped


# ---------------------------------------------------------------------------
# The full calculation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RatingInputs:
    """The game's own measured stats, in the game's own units.

    Separated from RideStats so the port can be driven either by our
    simulation or by a real design's stored header values, which is what
    makes it checkable against ground truth.
    """

    max_speed_units: int
    average_speed_units: int
    ride_length_m: int
    duration_s: int
    max_positive_g: int  # x100
    max_negative_g: int  # x100, signed
    max_lateral_g: int  # x100
    num_drops: int
    highest_drop_height: int  # RCT2 height units
    total_air_time: int = 0
    num_inversions: int = 0
    cars_per_train: int = 2
    flat_turns: TurnCounts = None
    banked_turns: TurnCounts = None
    sloped_turns: TurnCounts = None

    def turns(self) -> tuple[TurnCounts, TurnCounts, TurnCounts]:
        return (
            self.flat_turns or TurnCounts(),
            self.banked_turns or TurnCounts(),
            self.sloped_turns or TurnCounts(),
        )


def _apply_intensity_penalty(ratings: Tuple3) -> None:
    """RideRatingsApplyIntensityPenalty.

    Excitement loses a quarter at each intensity threshold crossed, and they
    compound. `physics.rate()` deliberately dropped this because our intensity
    ran 3.3x high and the penalty fired on every real coaster. With the real
    calculation the penalty belongs back in, because it is what the game does.
    """
    for bound in (1000, 1100, 1200, 1320, 1450):
        if ratings.intensity >= bound:
            ratings.excitement -= ratings.excitement // 4


def calculate(inputs: RatingInputs, table: dict = None,
              base: Tuple3 = None) -> Tuple3:
    """Run the full rating calculation for a Mine Train Coaster.

    Order matches RideRatingsCalculate: base, then every bonus, then the
    requirement checks, then the intensity penalty.
    """
    table = table if table is not None else MINE_TRAIN
    source = base if base is not None else MINE_TRAIN_BASE
    ratings = Tuple3(source.excitement, source.intensity, source.nausea)

    flat, banked, sloped = inputs.turns()

    threshold, excite, _, _ = table["bonus_length"]
    _add(ratings, (min(inputs.ride_length_m, threshold) * excite) >> 16, 0, 0)

    _, excite, _, _ = table["bonus_train_length"]
    _add(ratings, (max(0, inputs.cars_per_train - 1) * excite) >> 16, 0, 0)

    _, e, i, n = table["bonus_max_speed"]
    speed = inputs.max_speed_units
    _add(ratings, (speed * e) >> 16, (speed * i) >> 16, (speed * n) >> 16)

    _, e, i, _ = table["bonus_average_speed"]
    avg = inputs.average_speed_units
    _add(ratings, (avg * e) >> 16, (avg * i) >> 16, 0)

    threshold, excite, _, _ = table["bonus_duration"]
    _add(ratings, (min(inputs.duration_s, threshold) * excite) >> 16, 0, 0)

    sub = gforce_ratings(inputs.max_positive_g, inputs.max_negative_g,
                         inputs.max_lateral_g)
    _, e, i, n = table["bonus_gforces"]
    _add(ratings, (sub.excitement * e) >> 16, (sub.intensity * i) >> 16,
         (sub.nausea * n) >> 16)

    sub = turns_ratings(flat, banked, sloped, inputs.num_inversions)
    _, e, i, n = table["bonus_turns"]
    _add(ratings, (sub.excitement * e) >> 16, (sub.intensity * i) >> 16,
         (sub.nausea * n) >> 16)

    sub = drop_ratings(inputs.num_drops, inputs.highest_drop_height)
    _, e, i, n = table["bonus_drops"]
    _add(ratings, (sub.excitement * e) >> 16, (sub.intensity * i) >> 16,
         (sub.nausea * n) >> 16)

    # bonus_sheltered, bonus_proximity and bonus_scenery are deliberately
    # skipped. Sheltered length and scenery are zero for a bare track in an
    # empty park, and proximity needs the game's map walk over the surrounding
    # tiles, which we cannot reproduce from a segment list alone. Proximity's
    # coefficient is 0.33 and scenery's is 0.26, so this is the main known
    # source of under-prediction; see issue #40.

    # Requirements divide rather than subtract, and they compound.
    threshold, e, i, n = table["requirement_drop_height"]
    if inputs.highest_drop_height < threshold:
        ratings.excitement //= e
        ratings.intensity //= i
        ratings.nausea //= n

    threshold, e, i, n = table["requirement_max_speed"]
    if inputs.max_speed_units < threshold:
        ratings.excitement //= e
        ratings.intensity //= i
        ratings.nausea //= n

    threshold, e, i, n = table["requirement_num_drops"]
    if inputs.num_drops < threshold:
        ratings.excitement //= e
        ratings.intensity //= i
        ratings.nausea //= n

    threshold, e, i, n = table["requirement_negative_gs"]
    if inputs.max_negative_g > -threshold:
        ratings.excitement //= e
        ratings.intensity //= i
        ratings.nausea //= n

    # requirement_length is omitted, but not for the reason this comment used
    # to give. It tests `ride.getStation().SegmentLength`, which is not a
    # platform measure: `Ride::getTotalLength()` sums that field across
    # stations to get the ride's total length, so it is track length per
    # station, and track length is something we do model. What we cannot yet
    # split is the length between stations, and the check reads station zero
    # alone, so a two-station ride sees roughly half its circuit.
    #
    # That matters more than it looks. Doubling the oracle's bare-ground
    # rating of Manic Miner lands within a few percent of the value the game
    # shipped for it, which is what one missed halving looks like. Implementing
    # it on that reasoning alone would be guessing, so it waits on the in-game
    # test named in docs/research-plan.md: build the same track with one
    # station and see whether the rating doubles.

    _apply_intensity_penalty(ratings)
    return ratings


def inputs_from_stats(stats: RideStats, segments: list[int],
                      cars_per_train: int = 2) -> RatingInputs:
    """Convert our simulation's output into the game's units."""
    flat, banked, sloped = count_turns(segments)
    mph = stats.max_speed * 2.23694
    avg_mph = stats.avg_speed * 2.23694
    return RatingInputs(
        max_speed_units=int(mph / MPH_PER_SPEED_UNIT),
        average_speed_units=int(avg_mph / MPH_PER_SPEED_UNIT),
        ride_length_m=int(stats.ride_length),
        duration_s=int(stats.ride_time),
        max_positive_g=int(stats.max_positive_g * 100),
        max_negative_g=int(-abs(stats.max_negative_g) * 100),
        max_lateral_g=int(stats.max_lateral_g * 100),
        num_drops=stats.drop_count,
        highest_drop_height=int(stats.highest_drop),
        num_inversions=0,
        cars_per_train=cars_per_train,
        flat_turns=flat,
        banked_turns=banked,
        sloped_turns=sloped,
    )


@dataclass(frozen=True)
class RideRatings:
    """Ratings as the game would display them, in ordinary decimal."""

    excitement: float
    intensity: float
    nausea: float


def rate(stats: RideStats, segments: list[int],
         cars_per_train: int = 2) -> RideRatings:
    """Predict what the game would rate this track, via the ported calculation."""
    result = calculate(inputs_from_stats(stats, segments, cars_per_train))
    return RideRatings(
        excitement=result.excitement / 100,
        intensity=result.intensity / 100,
        nausea=result.nausea / 100,
    )
