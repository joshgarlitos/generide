"""Driver for the headless OpenRCT2 oracle.

Builds a segment list piece by piece in the real game, running headless, and
reads back the ratings the game itself computes. See docs/research-plan.md
and issue #42.

A plugin has no file I/O and cannot quit the game, so results travel over
stdout behind a GENERIDE_ prefix and this module owns killing the child
process. There is no isolated plugin directory available (--user-data-path
is rejected by the subcommands and OPENRCT2_USER_DATA_PATH is ignored), so
the generated plugin is written to the user's real OpenRCT2 plugin folder
for the duration of one run and removed afterward.
"""

import json
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional, Set

from rct2 import construction
from rct2.geometry import Position, occupied_tiles
from rct2.segments import SEGMENTS

OPENRCT2_BINARY = "/Applications/OpenRCT2 2.app/Contents/MacOS/OpenRCT2"
PLUGIN_DIR = Path.home() / "Library/Application Support/OpenRCT2/plugin"
DEFAULT_PARK = Path.home() / "Library/Application Support/OpenRCT2/save/Forest Frontiers.park"

# The plugin API reports ratings x100 (652 -> 6.52). TD6 headers use x10.
# Mixing these up gives a silent 10x error -- see docs/headless-oracle-spike.md.
RATING_SCALE = 100

MINE_TRAIN_RIDE_TYPE = 17
# Manic Miner's dat_data identifies its vehicle as "AMT1", which OpenRCT2's
# legacy object-name mapping (src/openrct2/park/Legacy.cpp) resolves to
# rct2.ride.amt1 -- not the generic rct1 mine train object this used to
# reference. A mismatched vehicle can have a different clearance height,
# turning crossings that are fine in the real ride into false collisions.
MINE_TRAIN_OBJECT_IDENTIFIER = "rct2.ride.amt1"

# trackPlaceFlags bit that marks a piece as carrying the chain lift. Confirmed
# by querying the game: with this set, the 60-degree climb pieces come back
# "Too steep for lift hill" (the Mine Train's lift tops out at 25 degrees) and
# without it the same pieces place fine. Before this existed the oracle placed
# every piece with flags 0, so no track it built had a lift at all, no train
# had power to climb, and no lift rule could ever fire. See docs/devlog.md
# (2026-08-16).
TRACK_PLACE_FLAG_CHAIN_LIFT = 1

# Speed the game's own brake pieces are set to, in the units trackplace takes.
# The oracle used to pass 0, which is not what an exported design carries, so
# any track with brakes behaved differently here than in the player's game.
DEFAULT_BRAKE_SPEED = 30

# The ride is treated as stalled once *no* car on it has moved for this many
# consecutive ticks. Generous on purpose: with several trains, some sit at the
# station loading for a long stretch while another runs, and a full circuit
# takes a while. Only total stillness counts.
STALL_TICKS = 1200

# KNOWN LIMITATION, not yet worked around: this module places pieces one at a
# time via the scripting API's own trackplace action, which enforces vertical
# clearance against the ride's *own* already-placed track the same as it
# would against any other ride. A design placed the normal way, by loading a
# saved .td6 through the ride construction window, does not: OpenRCT2's
# TrackPlaceAction takes a `_fromTrackDesign` flag that tells its clearance
# check to ignore the ride under construction's own ID entirely
# (`ignoreRideId = _fromTrackDesign ? _rideIndex : RideId::GetNull()` in
# src/openrct2/actions/track/TrackPlaceAction.cpp), because a real coaster
# routinely crosses itself and that is expected. Confirmed 2026-08-29: a real
# evolved track (114 segments, docs/devlog.md) crosses itself with 2 height
# units of clearance at one point, which this module's piece-by-piece build
# rejects as "Mine Train Coaster 1 in the way" -- and the same file, loaded
# and ridden normally in-game, worked fine and rated 5.21/6.97/4.31.
# So a `placement_failed` result from this module does not mean the track is
# actually invalid; it means this build method is stricter than real design
# loading on self-crossings tighter than 3 height units apart. No fix is
# implemented yet -- the scripting API does not appear to expose an
# equivalent to `_fromTrackDesign`.


@dataclass(frozen=True)
class RideMeasurements:
    """The game's own measurement of the stats `physics.py` estimates.

    Read off the ride after its test lap, so these are ground truth for
    calibration rather than another model's opinion. See docs/research-plan.md
    ("Feed the game's answers back into the fast model").
    """

    highest_drop_height: Optional[int] = None
    num_drops: Optional[int] = None
    num_lift_hills: Optional[int] = None
    max_speed: Optional[float] = None
    average_speed: Optional[float] = None
    ride_length: Optional[float] = None
    ride_time: Optional[float] = None
    total_air_time: Optional[float] = None
    max_positive_vertical_gs: Optional[float] = None
    max_negative_vertical_gs: Optional[float] = None
    max_lateral_gs: Optional[float] = None


@dataclass(frozen=True)
class OracleResult:
    excitement: Optional[float]
    intensity: Optional[float]
    nausea: Optional[float]
    status: str  # "rated" | "stalled" | "timeout" | "placement_failed"
    detail: str = ""
    # Where a stalled train stopped, so a failure names a piece rather than
    # just reporting that nothing happened.
    stalled_at_index: Optional[int] = None
    stalled_at_type: Optional[int] = None
    measurements: Optional[RideMeasurements] = None
    num_trains: int = 1
    cars_per_train: int = 2


def _joint_heights(segments: list[int]) -> list[int]:
    """Height of each piece's entry joint above the station, in game z-units.

    The game works in 8 z-units per height unit. Our elevation table agrees
    with the game's own `beginZ`/`endZ` figures on all 46 pieces we define
    (verified 2026-08-16), which is what makes it safe to drive placement from
    here rather than inferring heights from the game as pieces go down.
    """
    Z_PER_HEIGHT_UNIT = 8
    heights = []
    elevation = 0
    for segment in segments:
        heights.append(elevation * Z_PER_HEIGHT_UNIT)
        elevation += SEGMENTS.get(segment, SEGMENTS[0x00]).elevation_delta
    return heights


def _tiles_to_level(
    segments: list[int], base_x_tile: int, base_y_tile: int, margin: int = 3,
) -> list[list[int]]:
    """Tiles the track covers, plus `margin`, in tile coordinates.

    Flattening only what the ride needs keeps this to a few hundred game
    actions instead of the thousands a square big enough for a 30-tile ride
    would take. Heading 0 advances -x in the game, which is why x is negated.
    """
    covered = set()
    for tile in occupied_tiles(Position(), segments):
        # Our tracer's forward axis is +y and the game's heading 0 advances
        # -x, so the two frames are a quarter turn apart. Verified against
        # real placement coordinates: piece 100 of a 110-piece ride sits at
        # our (-7, 3) and the game put it on tile (97, 93).
        covered.add((base_x_tile - tile.y, base_y_tile + tile.x))
    grown = set()
    for x, y in covered:
        for dx in range(-margin, margin + 1):
            for dy in range(-margin, margin + 1):
                grown.add((x + dx, y + dy))
    return sorted([x, y] for x, y in grown)


def _build_plugin_source(
    segments: list[int],
    base_x_tile: int,
    base_y_tile: int,
    timeout_ticks: int,
    level_radius: int,
    lift_indices: Optional[Set[int]] = None,
    brake_speed: int = DEFAULT_BRAKE_SPEED,
    num_trains: int = 1,
    cars_per_train: int = 2,
) -> str:
    """Generate the JS plugin that builds one track and reports its rating.

    Positions are not precomputed in Python. An earlier version traced them
    with `rct2.geometry.trace_track`, our own model of piece displacement,
    and it disagreed with the game: a turn placed right after a straight
    piece collided with the ride's own track, because our forward/right/
    direction convention for that piece doesn't match the game's. Confirmed
    by testing the same piece as the very first element of a ride, where it
    placed without error.

    Instead, after each successful placement, the plugin asks the game
    itself where the next piece goes via `map.getTrackIterator(...)
    .nextPosition` -- the same lookup OpenRCT2's own construction UI uses.
    Python still supplies which piece type comes next (the genome); the game
    supplies where. `elementIndex` for the iterator is the position within
    the tile's *raw* element array (surface is usually index 0), and the
    location argument must be raw game coordinates (32 units per tile), not
    tile indices -- both confirmed by testing, since `map.getTile`'s doc
    comment says "tile coordinates" but `getTrackIterator`'s location turned
    out to need raw units to return anything but null.

    `nextPosition` reports the height of the *connection point* between two
    pieces, but `trackplace` takes the piece's *base* height. Those differ by
    the piece's own `beginZ` whenever it is not a whole 16-unit step, so the
    plugin subtracts `beginZ %% 16`, read from the game's own segment table.

    An earlier version instead retried at height +8 whenever placement failed
    with "Invalid height!", on the theory that there are only two alignments
    so one retry must find it. The retry does succeed, and it is wrong: the
    next position is then read from the shifted piece, so every retry raises
    the whole remainder of the track by 8 and the error compounds. A track
    with three such pieces came out 24 units high at the end, closed nowhere
    near its station, and the oracle reported it as "not a complete circuit"
    -- a track that closes perfectly well in the game when a player places it.
    The retry is kept only as a fallback, and it logs GENERIDE_WARN when it
    fires, because it firing now means the offset rule missed a case.

    Note `startsHalfHeightUp` looks like it should predict which pieces need
    the offset and does not: 0x0F has the flag false and still needs it, while
    0x04 has it true and does not. `beginZ %% 16` matched every piece tested.

    `lift_indices` marks which pieces carry the chain lift, and those are
    placed with TRACK_PLACE_FLAG_CHAIN_LIFT. Getting this wrong in either
    direction hides real failures: with no lift at all (what this did before)
    the train has no power and every rating is for a ride that could not run,
    and with a lift on too steep a piece the game refuses the whole ride with
    "Too steep for lift hill". Both were confirmed against the game rather
    than reasoned about -- see docs/devlog.md (2026-08-16).

    After the ride opens, every car is polled each tick. A train whose
    position stops changing for STALL_TICKS is reported as stalled, along with
    the piece it stopped on. Previously a stalled train and a slow game both
    came back as "timeout" with nothing to tell them apart.
    """
    return """
registerPlugin({
    name: 'generide-oracle', version: '1.0', authors: ['generide'],
    type: 'local', licence: 'MIT', targetApiVersion: 34,
    main: function () {
        context.paused = false;
        context.executeAction('gamesetspeed', { speed: 4 }, function () {});

        var segments = %(segments)s;
        var TIMEOUT_TICKS = %(timeout_ticks)d;
        var BASE_X_TILE = %(base_x_tile)d;
        var BASE_Y_TILE = %(base_y_tile)d;
        var LEVEL_TILES = %(level_tiles)s;
        var LIFT_INDICES = %(lift_indices)s;
        var BRAKE_SPEED = %(brake_speed)d;
        var NUM_TRAINS = %(num_trains)d;
        var CARS_PER_TRAIN = %(cars_per_train)d;
        var STALL_TICKS = %(stall_ticks)d;
        var STATION_TILES = %(station_tiles)d;
        var groundZ = map.getTile(BASE_X_TILE, BASE_Y_TILE).elements[0].baseZ;
        var GROUND_Z = groundZ;
        var JOINT_Z = %(joint_z)s;

        function fail(reason) {
            console.log('GENERIDE_RESULT|status=' + reason);
            console.log('GENERIDE_DONE');
        }

        // Real parks aren't billiard-table flat, and track placement rejects
        // uneven ground ("Raise or lower land first") even a few tiles from
        // where height was measured.
        //
        // LEVEL_TILES is the set of tiles the track actually covers, plus a
        // margin, worked out in Python from the same geometry that drives
        // placement. An earlier version flattened a square of radius
        // LEVEL_RADIUS instead, which was both too small for a 30-tile ride
        // (the track ran onto rough ground and was refused) and, once the
        // radius was raised to cover one, over 6,000 separate game actions,
        // which took longer than the whole rest of the run.
        for (var t = 0; t < LEVEL_TILES.length; t++) {
            context.executeAction('landsetheight', {
                x: LEVEL_TILES[t][0] * 32, y: LEVEL_TILES[t][1] * 32,
                height: groundZ, style: 0,
            }, function () {});
        }

        var obj = objectManager.load('%(object_id)s');
        if (!obj) { fail('placement_failed:no_object'); return; }

        context.executeAction('ridecreate', {
            rideType: %(ride_type)d, rideObject: obj.index, entranceObject: 0,
            colour1: 0, colour2: 0, inspectionInterval: 0,
        }, function (created) {
            if (created.error !== 0) { fail('placement_failed:ridecreate'); return; }
            var rideId = created.ride;
            var stationOrigin = { x: BASE_X_TILE * 32, y: BASE_Y_TILE * 32, z: groundZ };
            var cursor = { x: stationOrigin.x, y: stationOrigin.y, z: stationOrigin.z, direction: 0 };
            var stationTiles = [];
            placeNext(0);

            function trackSignature(tile) {
                // (type, baseZ) pairs identify every track element already
                // on the origin tile before we place the next piece, so we
                // can spot whichever one is new afterward -- see onPlaced.
                var sig = [];
                for (var e = 0; e < tile.numElements; e++) {
                    var el = tile.elements[e];
                    if (el.type === 'track') { sig.push(el.trackType + '@' + el.baseZ); }
                }
                return sig;
            }

            function placeNext(i) {
                if (i >= segments.length) { startTest(); return; }
                var trackType = segments[i];
                var before = trackSignature(map.getTile(cursor.x / 32, cursor.y / 32));
                // Height comes from Python, not from nextPosition.
                //
                // trackplace does not check that a piece joins the one before
                // it, so a wrong height is accepted silently and the track
                // quietly comes apart; the first symptom is a collision or
                // "Too high for supports" dozens of pieces later. Two attempts
                // to derive the base from nextPosition.z and the piece's own
                // beginZ both failed on some piece or other.
                //
                // JOINT_Z[i] is where the entry joint of piece i belongs,
                // computed in Python from the elevation table, which has been
                // checked against the game's own figures for all 46 pieces we
                // define. The base is that joint less the piece's beginZ,
                // which is how far its entry sits above its base. x, y and
                // direction still come from the game via nextPosition; only
                // height is ours.
                var geo = context.getTrackSegment(trackType);
                var jointZ = GROUND_Z + JOINT_Z[i];
                placeAt(jointZ - (geo ? geo.beginZ : 0), false);

                function placeAt(z, isRetry) {
                    // LIFT_INDICES decides which pieces carry the chain lift.
                    // Placing with the wrong answer here is not cosmetic: no
                    // lift means no power to climb, and a lift on too steep a
                    // piece makes the game reject the whole ride.
                    var wantsLift = LIFT_INDICES.indexOf(i) !== -1;
                    context.executeAction('trackplace', {
                        x: cursor.x, y: cursor.y, z: z, direction: cursor.direction,
                        ride: rideId, trackType: trackType, rideType: %(ride_type)d,
                        brakeSpeed: BRAKE_SPEED, colour: 0, seatRotation: 4,
                        trackPlaceFlags: wantsLift ? %(lift_flag)d : 0,
                        isFromTrackDesign: false,
                    }, function (r) {
                        console.log('GENERIDE_PLACE|i=' + i + '|type=' + trackType + '|error=' + r.error +
                                    '|msg=' + (r.errorMessage || '') + '|x=' + cursor.x + '|y=' + cursor.y +
                                    '|z=' + z + '|d=' + cursor.direction + '|retry=' + isRetry +
                                    '|lift=' + wantsLift);
                        if (r.error !== 0) {
                            // Fallback only. The baseOffset above should make
                            // this unnecessary; before it existed, this retry
                            // was the primary mechanism and it silently bent
                            // every track upward, because the next position is
                            // read from the shifted piece and the error then
                            // accumulates for the rest of the ride. That is
                            // what made the oracle report "not a complete
                            // circuit" on tracks that close perfectly well.
                            if (!isRetry && r.errorMessage === 'Invalid height!') {
                                console.log('GENERIDE_WARN|unexpected_height_retry|i=' + i +
                                            '|type=' + trackType + '|baseOffset=' + baseOffset);
                                placeAt(z + 8, true);
                                return;
                            }
                            if (r.errorMessage && r.errorMessage.indexOf('in the way') !== -1) {
                                var ctile = map.getTile(cursor.x / 32, cursor.y / 32);
                                var cdump = 'GENERIDE_COLLIDE|i=' + i + '|wantZ=' + z + '|numElements=' + ctile.numElements;
                                for (var c = 0; c < ctile.numElements; c++) {
                                    var cel = ctile.elements[c];
                                    cdump += '|[' + c + ']type=' + cel.type + ',baseZ=' + cel.baseZ + ',clearanceZ=' + cel.clearanceZ;
                                }
                                console.log(cdump);
                            }
                            fail('placement_failed:piece_' + i + '_type_' + trackType);
                            return;
                        }
                        rememberIfStation(i);
                        onPlaced(i, before);
                    });
                }
            }

            function rememberIfStation(i) {
                // Station tiles are wherever they land, not wherever our own
                // station_length() thinks. On the real Manic Miner the
                // platform wraps past the end of the piece list, so that
                // function correctly reports zero and an earlier version was
                // left with a single candidate spot for the exit.
                var t = segments[i];
                if (t === 1 || t === 2 || t === 3) {
                    stationTiles.push({ x: cursor.x, y: cursor.y });
                }
            }

            function onPlaced(i, before) {
                if (i === segments.length - 1) { startTest(); return; }
                // Neither the tile's element order nor the height/type we
                // asked for is trustworthy for finding the piece we just
                // placed: land leveling reorders elements (surface ended up
                // after track on a leveled tile during development, the
                // opposite of an untouched tile); a piece that changes
                // height across its length stores the origin tile at a
                // different baseZ than the z we passed to trackplace (that
                // argument turned out to be the lowest point across the
                // whole footprint, confirmed by scanning every tile a
                // 5-tile descending turn touched); and an isolated station
                // segment gets silently normalized to a different station
                // sub-type by the game regardless of what we requested
                // (confirmed: a lone "begin station" placement came back
                // reading as "end station"). None of type, height, or
                // position survive as a reliable fingerprint on their own.
                // What's reliable: diff the origin tile's track elements
                // from just before this placement to just after -- whatever
                // is new is what we placed, whatever it turned out to be.
                var tile = map.getTile(cursor.x / 32, cursor.y / 32);
                var after = trackSignature(tile);
                var newSig = null;
                for (var s = 0; s < after.length; s++) {
                    if (before.indexOf(after[s]) === -1) { newSig = after[s]; break; }
                }
                var elementIndex = -1;
                if (newSig !== null) {
                    for (var e = 0; e < tile.numElements; e++) {
                        var el = tile.elements[e];
                        if (el.type === 'track' && (el.trackType + '@' + el.baseZ) === newSig) {
                            elementIndex = e;
                            cursor.z = el.baseZ;
                            break;
                        }
                    }
                }
                if (elementIndex === -1) {
                    fail('placement_failed:element_not_found_at_' + i);
                    return;
                }
                var it = map.getTrackIterator({ x: cursor.x, y: cursor.y }, elementIndex);
                if (!it || !it.nextPosition) {
                    fail('placement_failed:no_iterator_at_' + i);
                    return;
                }
                cursor = it.nextPosition;
                placeNext(i + 1);
            }

            function startTest() {
                // A ride can't enter Testing without an entrance and exit
                // built. An earlier version put them beside the *first*
                // station tile only, which failed on the real Manic Miner
                // because the ride's own track occupies that spot. Try every
                // tile along the platform, on both sides, and take the first
                // that the game accepts.
                // Entrance and exit are placed as a *pair* on opposite sides
                // of one station tile, and the result is verified by reading
                // the station back.
                //
                // An earlier version placed each independently, taking the
                // first spot the game accepted for either. Both reported
                // success, on the same side of two different station tiles,
                // and the ride then refused to open with "Entrance not yet
                // built" -- so an accepted placement is not proof the station
                // actually holds one. Checking ride.stations[0] is.
                // Every station needs its own entrance and exit, not just
                // station 0. The real Manic Miner's track has station pieces
                // in two separate runs, so the game builds it two stations,
                // and an earlier version fitted out only the first and was
                // still told "Entrance not yet built" on opening.
                //
                // Each pair goes on opposite sides of one station tile, and
                // the result is verified by reading the station back: an
                // accepted placement is not proof the station holds one.
                var ride0 = map.getRide(rideId);
                var stationIds = [];
                for (var si = 0; si < ride0.stations.length; si++) {
                    if (ride0.stations[si] && ride0.stations[si].start) { stationIds.push(si); }
                }
                console.log('GENERIDE_STATIONS|count=' + stationIds.length +
                            '|ids=' + stationIds.join('.'));
                if (stationIds.length === 0) { fail('placement_failed:no_station'); return; }

                var spots = stationTiles.length ? stationTiles : [stationOrigin];
                function sidesFor(spot) {
                    return [
                        [{ x: spot.x, y: spot.y + 32, direction: 3 }, { x: spot.x, y: spot.y - 32, direction: 1 }],
                        [{ x: spot.x, y: spot.y - 32, direction: 1 }, { x: spot.x, y: spot.y + 32, direction: 3 }],
                        [{ x: spot.x + 32, y: spot.y, direction: 2 }, { x: spot.x - 32, y: spot.y, direction: 0 }],
                        [{ x: spot.x - 32, y: spot.y, direction: 0 }, { x: spot.x + 32, y: spot.y, direction: 2 }],
                    ];
                }
                var allPairs = [];
                for (var k = 0; k < spots.length; k++) {
                    allPairs = allPairs.concat(sidesFor(spots[k]));
                }

                fitStation(0);

                function fitStation(n) {
                    if (n >= stationIds.length) { openRide(); return; }
                    var stationId = stationIds[n];
                    tryPair(stationId, 0, function (ok) {
                        if (!ok) { fail('placement_failed:entrance_exit_station_' + stationId); return; }
                        fitStation(n + 1);
                    });
                }

                function tryPair(stationId, index, done) {
                    if (index >= allPairs.length) { done(false); return; }
                    var pair = allPairs[index];
                    context.executeAction('rideentranceexitplace', {
                        x: pair[0].x, y: pair[0].y, direction: pair[0].direction,
                        ride: rideId, station: stationId, isExit: false,
                    }, function (rEntrance) {
                        context.executeAction('rideentranceexitplace', {
                            x: pair[1].x, y: pair[1].y, direction: pair[1].direction,
                            ride: rideId, station: stationId, isExit: true,
                        }, function (rExit) {
                            var st = map.getRide(rideId).stations[stationId];
                            var ok = !!(st && st.entrance && st.exit);
                            if (ok) {
                                console.log('GENERIDE_EE|station=' + stationId + '|pair=' + index + '|ok');
                                done(true);
                                return;
                            }
                            tryPair(stationId, index + 1, done);
                        });
                    });
                }
            }

            function openRide() {
                // Train count and cars per train change whether a ride
                // completes at all, since a long train has cars still climbing
                // while its front is already braking.
                //
                // Every step here is best-effort and the run continues on
                // failure. An earlier version chained these as nested
                // callbacks that only opened the ride once all three
                // succeeded, and a wrong action name meant no callback ever
                // fired, so the whole run hung silently until it timed out
                // with no result at all. Whatever the ride ends up configured
                // as is reported back, rather than assumed.
                // The argument shape for ridesetvehicle is not documented
                // anywhere we can read, and four numeric guesses all threw
                // "Invalid action parameters". Try the plausible shapes and
                // keep whichever the game accepts; the run continues either
                // way, on the ride's default train setup.
                var steps = [
                    ['ridesetvehicle', { ride: rideId, type: 'numTrains', value: NUM_TRAINS }],
                    ['ridesetvehicle', { ride: rideId, type: 'numCarsPerTrain', value: CARS_PER_TRAIN }],
                    ['ridesetvehicle', { ride: rideId, type: 0, value: NUM_TRAINS }],
                    ['ridesetvehicle', { ride: rideId, type: 1, value: CARS_PER_TRAIN }],
                ];
                var i = 0;
                var settled = false;
                function proceed() {
                    if (settled) { return; }
                    settled = true;
                    reallyOpen();
                }
                function nextStep() {
                    if (i >= steps.length) { proceed(); return; }
                    var step = steps[i++];
                    var fired = false;
                    try {
                        context.executeAction(step[0], step[1], function (r) {
                            fired = true;
                            console.log('GENERIDE_CONFIG|' + step[0] + '|type=' + step[1].type +
                                        '|value=' + step[1].value + '|error=' + r.error +
                                        '|msg=' + (r.errorMessage || ''));
                            nextStep();
                        });
                    } catch (e) {
                        console.log('GENERIDE_CONFIG|' + step[0] + '|threw=' + e);
                        nextStep();
                        return;
                    }
                    // If the action name is unknown the callback may never
                    // run. Don't let that strand the whole evaluation.
                    context.setTimeout(function () { if (!fired) { nextStep(); } }, 500);
                }
                nextStep();
            }

            function reallyOpen() {
                context.executeAction('ridesetstatus', { ride: rideId, status: 2 }, function (r) {
                    if (r.error !== 0) {
                        fail('placement_failed:ridesetstatus:' + (r.errorMessage || 'unknown'));
                        return;
                    }
                    var ride0 = map.getRide(rideId);
                    console.log('GENERIDE_TRAINS|numTrains=' + (ride0.vehicles ? ride0.vehicles.length : -1) +
                                '|carsPerTrain=' + CARS_PER_TRAIN);
                    var ticks = 0;
                    var stillTicks = 0;
                    var lastPos = '';
                    var lastTrack = null;
                    var sub = context.subscribe('interval.tick', function () {
                        ticks++;
                        var ride = map.getRide(rideId);
                        if (ride.excitement >= 0) {
                            sub.dispose();
                            report(ride);
                            return;
                        }

                        // Stall detection watches *every* car on the ride,
                        // not one of them. An earlier version followed a
                        // single arbitrary car and reported the real Manic
                        // Miner as stalled within six seconds: with three
                        // trains, two sit at the station loading while the
                        // third runs, and a parked train is not a stuck ride.
                        // The ride is stalled only when nothing at all moves.
                        var cars = map.getAllEntities('car');
                        var mine = [];
                        for (var c = 0; c < cars.length; c++) {
                            if (cars[c].ride === rideId) mine.push(cars[c]);
                        }
                        if (mine.length > 0) {
                            var fingerprint = '';
                            for (var m = 0; m < mine.length; m++) {
                                fingerprint += mine[m].x + ',' + mine[m].y + ',' +
                                               mine[m].z + ',' + mine[m].trackProgress + ';';
                            }
                            if (fingerprint === lastPos) {
                                stillTicks++;
                            } else {
                                stillTicks = 0;
                                lastPos = fingerprint;
                            }
                            if (stillTicks > STALL_TICKS) {
                                sub.dispose();
                                // Report the car that got furthest from the
                                // station, since that is the one that died on
                                // the track rather than one still queued.
                                var worst = mine[0];
                                for (var w = 0; w < mine.length; w++) {
                                    if (mine[w].trackLocation && mine[w].trackLocation.z > (worst.trackLocation ? worst.trackLocation.z : -1)) {
                                        worst = mine[w];
                                    }
                                }
                                var loc = worst.trackLocation || {};
                                console.log('GENERIDE_RESULT|status=stalled:trackType=' + (loc.trackType === undefined ? -1 : loc.trackType) +
                                            '|x=' + worst.x + '|y=' + worst.y + '|z=' + worst.z +
                                            '|velocity=' + worst.velocity +
                                            '|carStatus=' + worst.status +
                                            '|cars=' + mine.length);
                                console.log('GENERIDE_DONE');
                                return;
                            }
                        }

                        if (ticks %% 2000 === 0) {
                            var lead = mine.length ? mine[0] : null;
                            console.log('GENERIDE_TICK|ticks=' + ticks +
                                        '|cars=' + mine.length +
                                        '|leadVelocity=' + (lead ? lead.velocity : 'n/a') +
                                        '|excitement=' + ride.excitement);
                        }
                        if (ticks > TIMEOUT_TICKS) {
                            sub.dispose();
                            fail('timeout:ticks=' + ticks);
                        }
                    });

                    function report(ride) {
                        console.log('GENERIDE_STATS' +
                            '|highestDropHeight=' + ride.highestDropHeight +
                            '|numDrops=' + ride.numDrops +
                            '|numLiftHills=' + ride.numLiftHills +
                            '|maxSpeed=' + ride.maxSpeed +
                            '|averageSpeed=' + ride.averageSpeed +
                            '|rideLength=' + ride.rideLength +
                            '|rideTime=' + ride.rideTime +
                            '|totalAirTime=' + ride.totalAirTime +
                            '|maxPositiveVerticalGs=' + ride.maxPositiveVerticalGs +
                            '|maxNegativeVerticalGs=' + ride.maxNegativeVerticalGs +
                            '|maxLateralGs=' + ride.maxLateralGs);
                        console.log('GENERIDE_RESULT|status=rated|E=' + ride.excitement +
                                    '|I=' + ride.intensity + '|N=' + ride.nausea);
                        console.log('GENERIDE_DONE');
                    }
                });
            }
        });
    },
});
""" % {
        "segments": json.dumps(segments),
        "timeout_ticks": timeout_ticks,
        "base_x_tile": base_x_tile,
        "base_y_tile": base_y_tile,
        "level_tiles": json.dumps(_tiles_to_level(segments, base_x_tile, base_y_tile, level_radius)),
        "object_id": MINE_TRAIN_OBJECT_IDENTIFIER,
        "ride_type": MINE_TRAIN_RIDE_TYPE,
        "lift_indices": json.dumps(sorted(
            construction.default_lift_indices(segments)
            if lift_indices is None else lift_indices
        )),
        "lift_flag": TRACK_PLACE_FLAG_CHAIN_LIFT,
        "brake_speed": brake_speed,
        "num_trains": num_trains,
        "cars_per_train": cars_per_train,
        "stall_ticks": STALL_TICKS,
        "joint_z": json.dumps(_joint_heights(segments)),
        "station_tiles": max(1, construction.station_length(segments)),
    }


_RESULT_RE = re.compile(
    r"GENERIDE_RESULT\|status=(?P<status>\w+)(?::(?P<detail>[^'\x1b]+))?"
    r"(?:\|E=(?P<e>-?\d+)\|I=(?P<i>-?\d+)\|N=(?P<n>-?\d+))?"
)


def _parse_result(line: str) -> Optional[OracleResult]:
    # OpenRCT2 wraps each console.log line in its own quotes and trails it
    # with an ANSI reset code (visible in raw output as `...'[0m`), which a
    # plain \S+ detail match would swallow whole.
    match = _RESULT_RE.search(line)
    if not match:
        return None
    status = match.group("status")
    if status == "rated":
        return OracleResult(
            excitement=int(match.group("e")) / RATING_SCALE,
            intensity=int(match.group("i")) / RATING_SCALE,
            nausea=int(match.group("n")) / RATING_SCALE,
            status="rated",
        )
    detail = match.group("detail") or ""
    stalled_type = None
    if status == "stalled":
        found = re.search(r"trackType=(-?\d+)", detail)
        if found:
            stalled_type = int(found.group(1))
    return OracleResult(
        excitement=None, intensity=None, nausea=None,
        status=status, detail=detail, stalled_at_type=stalled_type,
    )


_STATS_RE = re.compile(r"GENERIDE_STATS\|(?P<body>[^'\x1b]+)")

_STAT_FIELDS = {
    "highestDropHeight": "highest_drop_height",
    "numDrops": "num_drops",
    "numLiftHills": "num_lift_hills",
    "maxSpeed": "max_speed",
    "averageSpeed": "average_speed",
    "rideLength": "ride_length",
    "rideTime": "ride_time",
    "totalAirTime": "total_air_time",
    "maxPositiveVerticalGs": "max_positive_vertical_gs",
    "maxNegativeVerticalGs": "max_negative_vertical_gs",
    "maxLateralGs": "max_lateral_gs",
}


def _parse_measurements(line: str) -> Optional[RideMeasurements]:
    """The game's own stats for the ride it just tested.

    These are what `physics.py` estimates, measured rather than modelled, so
    they are the calibration data the research plan asks for.
    """
    match = _STATS_RE.search(line)
    if not match:
        return None
    values = {}
    for pair in match.group("body").split("|"):
        key, _, raw = pair.partition("=")
        field = _STAT_FIELDS.get(key)
        if field is None or raw in ("", "null", "undefined"):
            continue
        try:
            values[field] = float(raw) if "." in raw else int(raw)
        except ValueError:
            continue
    return RideMeasurements(**values)


_TRAINS_RE = re.compile(r"GENERIDE_TRAINS\|numTrains=(?P<trains>-?\d+)\|carsPerTrain=(?P<cars>-?\d+)")

TICKS_PER_SECOND = 40  # measured at game speed 1, see docs/headless-oracle-spike.md


def _parse_trains(line: str) -> Optional[tuple[int, int]]:
    """Read back the train configuration the game actually gave the ride.

    `ridesetvehicle` rejects every argument shape tried so far, so the ride
    runs on the game's defaults and what we asked for is not what ran. The
    plugin reads `ride.vehicles.length` back after opening, and this is where
    that reaches the caller: a result that claimed 1 train when the game ran 3
    would quietly corrupt any calibration built on it.
    """
    match = _TRAINS_RE.search(line)
    if match is None:
        return None
    trains = int(match.group("trains"))
    cars = int(match.group("cars"))
    if trains < 0 or cars < 0:  # the plugin reports -1 when it cannot read them
        return None
    return trains, cars


def _default_timeout_ticks(segments: list[int]) -> int:
    """Budget the test lap from the track, not from a flat constant.

    The old default of 2000 ticks was 50 seconds of game time, and the real
    Manic Miner takes 83. It came back as a timeout: a ride that runs
    perfectly, reported as a failure, purely because the budget was shorter
    than the ride. Any track over about 50 seconds hit the same wall.

    The generous margin costs nothing on a ride that works, because the read
    loop stops the moment a rating arrives, and a genuinely stuck train is
    caught by the stall detector long before this. It is only the backstop for
    a ride that neither finishes nor sits still, so it should be too long
    rather than too short.
    """
    from rct2 import physics

    predicted = physics.simulate(segments).ride_time
    # 4x covers station dwell, several trains sharing the circuit, and our own
    # ride-time estimate reading low (65.7s predicted against the game's 83s
    # for Manic Miner). The fixed 120s floor covers a very short track whose
    # station dwell dominates.
    return max(4000, int((predicted * 4 + 120) * TICKS_PER_SECOND))


def score_track(
    segments: list[int],
    park: Path = DEFAULT_PARK,
    base_x_tile: int = 100,
    base_y_tile: int = 100,
    # Forest Frontiers' starter area near (40, 40) has real paths, walls, and
    # ride entrances that land-leveling doesn't clear, causing false
    # collisions unrelated to the track itself. (100, 100) was confirmed
    # empty (bare surface only) during development.
    level_radius: int = 20,  # covers any track within the project's usual 30x30 max footprint
    timeout_ticks: Optional[int] = None,  # None sizes it from the track, see _default_timeout_ticks
    process_timeout_s: float = 90.0,
    lift_indices: Optional[Set[int]] = None,
    brake_speed: int = DEFAULT_BRAKE_SPEED,
    num_trains: int = 1,
    cars_per_train: int = 2,
) -> OracleResult:
    """Build `segments` in a real, headless OpenRCT2 and run a train on it.

    Returns the game's own excitement/intensity/nausea when the ride completes
    a test lap, and `status="stalled"` with the piece it stopped on when the
    train does not get round. A `rated` result also carries the game's measured
    ride stats in `.measurements`.

    `num_trains` and `cars_per_train` matter for whether a ride completes at
    all, not just for throughput: a long train has cars still climbing while
    its front is already braking. They default to the same 1 and 2 the rest of
    the project uses so results stay comparable.

    Installs a generated plugin into the user's real plugin folder for the
    duration of this call and removes it afterward -- there is no isolated
    plugin directory available (see module docstring). Only one call should
    run at a time; concurrent calls would overwrite each other's plugin file.
    """
    if timeout_ticks is None:
        timeout_ticks = _default_timeout_ticks(segments)

    PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
    plugin_path = PLUGIN_DIR / "generide-oracle.js"
    plugin_path.write_text(_build_plugin_source(
        segments, base_x_tile, base_y_tile, timeout_ticks, level_radius,
        lift_indices=lift_indices, brake_speed=brake_speed,
        num_trains=num_trains, cars_per_train=cars_per_train,
    ))

    process = subprocess.Popen(
        [OPENRCT2_BINARY, str(park), "--headless"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    # Break on a parsed result rather than a "done" marker string: any other
    # plugin sitting in the same real plugin folder (there is no isolated
    # one -- see module docstring) could print a similarly generic marker
    # and end the read loop before this plugin's own output ever arrives.
    # That happened once during development with a leftover probe script.
    # The reader below blocks on the game's stdout, and the deadline check
    # inside it only runs when a line actually arrives. A game that goes quiet
    # (the land-levelling loop used to take many minutes) would otherwise hang
    # forever, so a watchdog kills the process from the outside.
    watchdog = threading.Timer(process_timeout_s, process.kill)
    watchdog.daemon = True
    watchdog.start()

    result: Optional[OracleResult] = None
    measurements: Optional[RideMeasurements] = None
    # What the game actually gave the ride, which is not what we asked for
    # whenever ridesetvehicle rejects our arguments -- see _parse_trains.
    actual_trains: Optional[tuple[int, int]] = None
    try:
        deadline = time.time() + process_timeout_s
        for line in process.stdout:
            if "GENERIDE" in line:
                print(line.rstrip())
            if "GENERIDE_STATS" in line:
                measurements = _parse_measurements(line) or measurements
            if "GENERIDE_TRAINS" in line:
                actual_trains = _parse_trains(line) or actual_trains
            if "GENERIDE_RESULT" in line:
                result = _parse_result(line)
                if result is not None:
                    break
            if time.time() > deadline:
                break
    finally:
        watchdog.cancel()
        process.kill()
        process.wait()
        plugin_path.unlink(missing_ok=True)

    ran_trains, ran_cars = actual_trains or (num_trains, cars_per_train)

    if result is None:
        return OracleResult(
            excitement=None, intensity=None, nausea=None,
            status="timeout", detail="no GENERIDE_RESULT line seen",
            num_trains=ran_trains, cars_per_train=ran_cars,
        )
    return replace(
        result, measurements=measurements,
        num_trains=ran_trains, cars_per_train=ran_cars,
    )


if __name__ == "__main__":
    # Manual smoke test: python -m rct2.oracle data/sample_rides/manic_miner_test.td6
    from rct2 import td6

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/sample_rides/manic_miner_test.td6")
    ride = td6.load(path)
    segs = [e.segment_type for e in ride.elements]
    print(f"Scoring {path.name}: {len(segs)} segments")
    result = score_track(segs)
    print(result)
