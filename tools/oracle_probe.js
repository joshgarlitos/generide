// Working probe from the headless-oracle spike (issue #6).
// See docs/headless-oracle-spike.md for the findings this came from.
//
// Install to the real user plugin folder -- an isolated --user-data-path is
// not available (the subcommands reject it and OPENRCT2_USER_DATA_PATH is
// ignored), so remove this again when you are done:
//
//   cp tools/oracle_probe.js ~/Library/Application\ Support/OpenRCT2/plugin/
//   "/Applications/OpenRCT2 2.app/Contents/MacOS/OpenRCT2" <park>.park --headless
//   rm ~/Library/Application\ Support/OpenRCT2/plugin/oracle_probe.js
//
// Launch with NO subcommand. `host --headless` loads plugins but leaves the
// game state immutable and never ticks; `simulate` ticks fast but never starts
// the scripting engine at all.
//
// Every result line is prefixed GENERIDE_ so the parent process can grep
// stdout: plugins have no file I/O and cannot quit the game, so stdout is the
// only channel out and the parent owns killing the child.

registerPlugin({
    name: 'generide-oracle-probe',
    version: '1.0',
    authors: ['generide'],
    type: 'local',
    licence: 'MIT',
    targetApiVersion: 34,
    main: function () {
        // Without this the park stays paused forever and no test lap runs.
        context.paused = false;

        // Speed 4 ("hyper") is the ceiling -- 8 is rejected outright rather
        // than clamped. Measured 318 ticks/sec against 40.7 at speed 1.
        context.executeAction('gamesetspeed', { speed: 4 }, function (r) {
            console.log('GENERIDE_SPEED|error=' + r.error);
        });

        // Parks only carry the objects they use, so the ride type we want
        // usually has to be loaded at runtime. 17 is Mine Train.
        var obj = objectManager.load('rct1.ride.mine_trains');
        if (!obj) {
            console.log('GENERIDE_ERROR|could not load mine train object');
            console.log('GENERIDE_DONE');
            return;
        }
        console.log('GENERIDE_OBJ|index=' + obj.index);

        // NOTE: the last field is inspectionInterval, not colour3. Guessing
        // colour3 (as the shape of colour1/colour2 suggests) fails with a bare
        // "Invalid action parameters".
        context.executeAction('ridecreate', {
            rideType: 17,
            rideObject: obj.index,
            entranceObject: 0,
            colour1: 0,
            colour2: 0,
            inspectionInterval: 0,
        }, function (r) {
            console.log('GENERIDE_RIDECREATE|error=' + r.error + '|ride=' + r.ride);
            if (r.error !== 0) {
                console.log('GENERIDE_DONE');
                return;
            }
            reportRide(r.ride);
        });

        function reportRide(rideId) {
            var ride = map.getRide(rideId);
            if (!ride) {
                console.log('GENERIDE_ERROR|no ride ' + rideId);
                console.log('GENERIDE_DONE');
                return;
            }
            // Ratings are x100 here (652 means 6.52). TD6 headers use x10 --
            // rct2/td6.py's RATING_PER_UNIT is 0.1 -- so anything comparing
            // the two has to convert. An unrated ride reports -1, which is
            // distinct from a genuinely bad one.
            console.log('GENERIDE_RATINGS|ride=' + rideId +
                        '|name=' + ride.name +
                        '|status=' + ride.status +
                        '|E=' + ride.excitement +
                        '|I=' + ride.intensity +
                        '|N=' + ride.nausea);
            console.log('GENERIDE_DONE');
        }
    },
});
