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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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


@dataclass(frozen=True)
class OracleResult:
    excitement: Optional[float]
    intensity: Optional[float]
    nausea: Optional[float]
    status: str  # "rated" | "stalled" | "timeout" | "placement_failed"
    detail: str = ""


def _build_plugin_source(
    segments: list[int],
    base_x_tile: int,
    base_y_tile: int,
    timeout_ticks: int,
    level_radius: int,
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

    Some piece types (confirmed in OpenRCT2's TrackPlaceAction.cpp: pieces
    flagged `startsAtHalfHeight`, which includes the up/down-slope
    transitions) must land on a height one half-step off the ordinary grid
    -- the height's raw value mod 16 must be 8 instead of 0. `nextPosition`
    doesn't shift for this; it hands back the plain successor height, which
    is only right for ordinary pieces. Rather than track which of dozens of
    piece types need the shift, retry once at height +8 whenever placement
    fails with exactly "Invalid height!" -- there are only two possible
    alignments, so one retry always finds the right one.
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
        var LEVEL_RADIUS = %(level_radius)d;
        var groundZ = map.getTile(BASE_X_TILE, BASE_Y_TILE).elements[0].baseZ;

        function fail(reason) {
            console.log('GENERIDE_RESULT|status=' + reason);
            console.log('GENERIDE_DONE');
        }

        // Real parks aren't billiard-table flat, and track placement rejects
        // uneven ground ("Raise or lower land first") even a few tiles from
        // where height was measured. Flatten a generous square around the
        // build site to groundZ before placing anything, rather than only
        // the exact tiles a first attempt happened to need.
        for (var lx = -LEVEL_RADIUS; lx <= LEVEL_RADIUS; lx++) {
            for (var ly = -LEVEL_RADIUS; ly <= LEVEL_RADIUS; ly++) {
                var tx = (BASE_X_TILE + lx) * 32, ty = (BASE_Y_TILE + ly) * 32;
                context.executeAction('landsetheight', {
                    x: tx, y: ty, height: groundZ, style: 0,
                }, function () {});
            }
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
                placeAt(cursor.z, false);

                function placeAt(z, isRetry) {
                    context.executeAction('trackplace', {
                        x: cursor.x, y: cursor.y, z: z, direction: cursor.direction,
                        ride: rideId, trackType: trackType, rideType: %(ride_type)d,
                        brakeSpeed: 0, colour: 0, seatRotation: 4,
                        trackPlaceFlags: 0, isFromTrackDesign: false,
                    }, function (r) {
                        console.log('GENERIDE_PLACE|i=' + i + '|type=' + trackType + '|error=' + r.error +
                                    '|msg=' + (r.errorMessage || '') + '|x=' + cursor.x + '|y=' + cursor.y +
                                    '|z=' + z + '|d=' + cursor.direction + '|retry=' + isRetry);
                        if (r.error !== 0) {
                            if (!isRetry && r.errorMessage === 'Invalid height!') {
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
                        onPlaced(i, before);
                    });
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
                // built. Place them one tile to either side of the first
                // station tile (perpendicular to the station's own
                // direction), facing back toward the station.
                var side = { x: stationOrigin.x, y: stationOrigin.y + 32 };
                var otherSide = { x: stationOrigin.x, y: stationOrigin.y - 32 };
                context.executeAction('rideentranceexitplace', {
                    x: side.x, y: side.y, direction: 3, ride: rideId, station: 0, isExit: false,
                }, function (rEntrance) {
                    console.log('GENERIDE_ENTRANCE|error=' + rEntrance.error + '|msg=' + (rEntrance.errorMessage || ''));
                    context.executeAction('rideentranceexitplace', {
                        x: otherSide.x, y: otherSide.y, direction: 1, ride: rideId, station: 0, isExit: true,
                    }, function (rExit) {
                        console.log('GENERIDE_EXIT|error=' + rExit.error + '|msg=' + (rExit.errorMessage || ''));
                        if (rEntrance.error !== 0 || rExit.error !== 0) {
                            fail('placement_failed:entrance_exit');
                            return;
                        }
                        openRide();
                    });
                });
            }

            function openRide() {
                context.executeAction('ridesetstatus', { ride: rideId, status: 2 }, function (r) {
                    if (r.error !== 0) {
                        fail('placement_failed:ridesetstatus:' + (r.errorMessage || 'unknown'));
                        return;
                    }
                    var ticks = 0;
                    var sub = context.subscribe('interval.tick', function () {
                        ticks++;
                        var ride = map.getRide(rideId);
                        if (ride.excitement >= 0) {
                            sub.dispose();
                            console.log('GENERIDE_RESULT|status=rated|E=' + ride.excitement +
                                        '|I=' + ride.intensity + '|N=' + ride.nausea);
                            console.log('GENERIDE_DONE');
                        } else if (ticks > TIMEOUT_TICKS) {
                            sub.dispose();
                            fail('timeout');
                        }
                    });
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
        "level_radius": level_radius,
        "object_id": MINE_TRAIN_OBJECT_IDENTIFIER,
        "ride_type": MINE_TRAIN_RIDE_TYPE,
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
    return OracleResult(
        excitement=None, intensity=None, nausea=None,
        status=status, detail=match.group("detail") or "",
    )


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
    timeout_ticks: int = 2000,  # ~50s of game time at normal speed
    process_timeout_s: float = 90.0,
) -> OracleResult:
    """Build `segments` in a real, headless OpenRCT2 and return its rating.

    Installs a generated plugin into the user's real plugin folder for the
    duration of this call and removes it afterward -- there is no isolated
    plugin directory available (see module docstring). Only one call should
    run at a time; concurrent calls would overwrite each other's plugin file.
    """
    PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
    plugin_path = PLUGIN_DIR / "generide-oracle.js"
    plugin_path.write_text(_build_plugin_source(
        segments, base_x_tile, base_y_tile, timeout_ticks, level_radius,
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
    result: Optional[OracleResult] = None
    try:
        deadline = time.time() + process_timeout_s
        for line in process.stdout:
            if "GENERIDE" in line:
                print(line.rstrip())
            if "GENERIDE_RESULT" in line:
                result = _parse_result(line)
                if result is not None:
                    break
            if time.time() > deadline:
                break
    finally:
        process.kill()
        process.wait()
        plugin_path.unlink(missing_ok=True)

    if result is None:
        return OracleResult(
            excitement=None, intensity=None, nausea=None,
            status="timeout", detail="no GENERIDE_RESULT line seen",
        )
    return result


if __name__ == "__main__":
    # Manual smoke test: python -m rct2.oracle data/sample_rides/manic_miner_test.td6
    from rct2 import td6

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/sample_rides/manic_miner_test.td6")
    ride = td6.load(path)
    segs = [e.segment_type for e in ride.elements]
    print(f"Scoring {path.name}: {len(segs)} segments")
    result = score_track(segs)
    print(result)
