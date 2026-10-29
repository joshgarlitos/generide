// Throwaway probe for the train-length spike (docs/train-length-spike.md).
//
// Questions it answers:
//   1. Can the number of trains and cars per train be set in the headless game
//      (the oracle's `ridesetvehicle` calls all fail today)?
//   2. For every setting that takes, how far does the train roll out of the
//      station, and does it reach the first lift?
//
// Nothing here interprets what it reads. It prints raw values and the spike
// document does the interpreting from the output.
//
// It works on a park that already holds a finished ride. Easiest route: install
// a generated ride with the web UI, open it in the game, place it, and save the
// park. Then edit RIDE_ID and CONFIGS below and run it the way
// tools/oracle_probe.js is run. The plugin has to live in the game's one real
// plugin folder, so remove it again afterwards:
//
//   cp tools/train_probe.js ~/Library/Application\ Support/OpenRCT2/plugin/
//   "/Applications/OpenRCT2 2.app/Contents/MacOS/OpenRCT2" <your-park>.park --headless \
//       | grep '^GENERIDE_' > train-probe-output.txt
//   rm ~/Library/Application\ Support/OpenRCT2/plugin/train_probe.js
//
// The game keeps running after the probe prints GENERIDE_DONE (a plugin cannot
// quit it), so stop it with Ctrl-C once you see that line.

// The ride to test: its number in the game's ride list. null means the first
// ride in the park.
var RIDE_ID = null;

// Train settings to try, one run each, in order. The first entry is the game's
// default, so it is only measured and nothing is set.
var CONFIGS = [
    { trains: null, cars: null },
    { trains: 1, cars: 1 },
    { trains: 1, cars: 3 },
    { trains: 1, cars: 6 },
];

// How long to watch each run, in game ticks, and how often to sample.
var WATCH_TICKS = 1500;
var SAMPLE_EVERY = 25;

registerPlugin({
    name: 'generide-train-probe',
    version: '1.0',
    authors: ['generide'],
    type: 'local',
    licence: 'MIT',
    targetApiVersion: 34,
    main: function () {
        context.paused = false;
        context.executeAction('gamesetspeed', { speed: 4 }, function () {});

        var ride = pickRide();
        if (!ride) {
            console.log('GENERIDE_ERROR|no ride found in this park');
            console.log('GENERIDE_DONE');
            return;
        }
        var rideId = ride.id;
        console.log('GENERIDE_RIDE|id=' + rideId + '|name=' + ride.name + '|type=' + ride.type);

        // Every property the plugin API exposes on a ride, so a writable
        // train-count property would show up here even if its name is not
        // what we expect.
        console.log('GENERIDE_RIDE_KEYS|' + Object.keys(ride).join(','));
        describeTrains('start');

        runConfig(0);

        function pickRide() {
            if (RIDE_ID !== null) {
                return map.getRide(RIDE_ID);
            }
            return map.rides.length ? map.rides[0] : null;
        }

        // The cars that belong to this ride, in the order the game lists them.
        function ownCars() {
            var all = map.getAllEntities('car');
            var mine = [];
            for (var i = 0; i < all.length; i++) {
                if (all[i].ride === rideId) {
                    mine.push(all[i]);
                }
            }
            return mine;
        }

        // Cars with nothing in front of them are the head of a train. Counting
        // them gives trains; the rest are cars.
        function describeTrains(label) {
            var cars = ownCars();
            var heads = 0;
            for (var i = 0; i < cars.length; i++) {
                if (cars[i].previousCarOnTrain === null || cars[i].previousCarOnTrain === undefined) {
                    heads++;
                }
            }
            var current = map.getRide(rideId);
            console.log('GENERIDE_TRAINS|' + label + '|cars=' + cars.length + '|heads=' + heads +
                        '|rideVehicles=' + (current.vehicles ? current.vehicles.length : -1));
        }

        function runConfig(index) {
            if (index >= CONFIGS.length) {
                console.log('GENERIDE_DONE');
                return;
            }
            var config = CONFIGS[index];
            console.log('GENERIDE_CONFIG_START|index=' + index + '|trains=' + config.trains +
                        '|cars=' + config.cars);
            // The ride has to be closed to change its trains, so close it first
            // in every run. If closing fails that is itself a finding.
            setStatus(0, function () {
                if (config.trains === null) {
                    afterSet(index, config);
                    return;
                }
                trySettings(config, function () { afterSet(index, config); });
            });
        }

        function afterSet(index, config) {
            describeTrains('after-set-' + index);
            setStatus(2, function () {
                watch(index, function () { runConfig(index + 1); });
            });
        }

        // ride status: 0 closed, 1 open, 2 testing (the oracle uses 2).
        function setStatus(status, done) {
            fire('ridesetstatus', { ride: rideId, status: status }, done);
        }

        // Run one action, print what the game said, and always continue. An
        // unknown action name may never call back, so a timer moves on.
        function fire(action, args, done) {
            var finished = false;
            function next() {
                if (!finished) {
                    finished = true;
                    done();
                }
            }
            try {
                context.executeAction(action, args, function (result) {
                    console.log('GENERIDE_ACTION|' + action + '|' + JSON.stringify(args) +
                                '|error=' + result.error + '|msg=' + (result.errorMessage || ''));
                    next();
                });
            } catch (e) {
                console.log('GENERIDE_ACTION|' + action + '|' + JSON.stringify(args) + '|threw=' + e);
                next();
                return;
            }
            context.setTimeout(function () {
                if (!finished) {
                    console.log('GENERIDE_ACTION|' + action + '|' + JSON.stringify(args) + '|no-callback');
                }
                next();
            }, 500);
        }

        // Every way we know to ask for a train count, in the order they are
        // tried. The first group repeats what the oracle already tried (type
        // given as text, then as 0 and 1, with no colour). The second adds a
        // `colour` field, because the game's action takes one and the oracle
        // never sent it: this is a guess at why the oracle's calls fail, and
        // the output says whether it was right. The third tries the numbers
        // the action's type values are believed to have in the game's source.
        // Each shape is applied for cars and for trains, then the property
        // writes at the end try the ride object itself.
        function trySettings(config, done) {
            var shapes = [];
            function add(typeTrains, typeCars, extra) {
                var a = { ride: rideId, type: typeTrains, value: config.trains };
                var b = { ride: rideId, type: typeCars, value: config.cars };
                for (var k in extra) { a[k] = extra[k]; b[k] = extra[k]; }
                shapes.push(a, b);
            }
            add('numTrains', 'numCarsPerTrain', {});
            add(0, 1, {});
            add(0, 1, { colour: 0 });
            add('numTrains', 'numCarsPerTrain', { colour: 0 });

            var i = 0;
            function nextShape() {
                if (i >= shapes.length) { tryProperties(config, done); return; }
                fire('ridesetvehicle', shapes[i++], nextShape);
            }
            nextShape();
        }

        // Last resort: assign the values straight onto the ride object. Each
        // attempt prints before and after so a silent no-op is visible.
        function tryProperties(config, done) {
            var current = map.getRide(rideId);
            var attempts = [
                ['numTrains', config.trains],
                ['numCarsPerTrain', config.cars],
                ['trains', config.trains],
                ['carsPerTrain', config.cars],
            ];
            for (var n = 0; n < attempts.length; n++) {
                var name = attempts[n][0];
                var wanted = attempts[n][1];
                var before = current[name];
                try {
                    current[name] = wanted;
                    console.log('GENERIDE_PROPERTY|' + name + '|before=' + before +
                                '|wanted=' + wanted + '|after=' + map.getRide(rideId)[name]);
                } catch (e) {
                    console.log('GENERIDE_PROPERTY|' + name + '|threw=' + e);
                }
            }
            done();
        }

        // Sample the lead car of every train as the run goes, so the output
        // shows how far each one rolls from the station and whether it climbs.
        function watch(index, done) {
            var ticks = 0;
            var sub = context.subscribe('interval.tick', function () {
                ticks++;
                if (ticks % SAMPLE_EVERY === 0) {
                    sample(index, ticks);
                }
                if (ticks >= WATCH_TICKS) {
                    sub.dispose();
                    done();
                }
            });
        }

        function sample(index, ticks) {
            var cars = ownCars();
            for (var i = 0; i < cars.length; i++) {
                var car = cars[i];
                var isHead = car.previousCarOnTrain === null || car.previousCarOnTrain === undefined;
                if (!isHead) { continue; }
                var location = car.trackLocation;
                console.log('GENERIDE_SAMPLE|config=' + index + '|tick=' + ticks + '|car=' + car.id +
                            '|x=' + car.x + '|y=' + car.y + '|z=' + car.z +
                            '|velocity=' + car.velocity + '|status=' + car.status +
                            '|trackProgress=' + car.trackProgress +
                            '|piece=' + (location ? location.x + ',' + location.y + ',' + location.z : 'none'));
            }
        }
    },
});
