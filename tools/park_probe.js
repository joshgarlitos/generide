// Throwaway probe for the park-read spike (docs/park-read-spike.md).
//
// Question it answers: can a plugin running in the headless game read the
// land and objects of a saved park, so a region of it could become a site?
// It reads a rectangle of tiles and prints, for each tile, every map element
// on it with the raw values the plugin API gives. Nothing here interprets
// those values: the spike document does that from the output.
//
// Run it the way tools/oracle_probe.js is run. The plugin has to live in the
// game's one real plugin folder, so remove it again afterwards:
//
//   cp tools/park_probe.js ~/Library/Application\ Support/OpenRCT2/plugin/
//   "/Applications/OpenRCT2 2.app/Contents/MacOS/OpenRCT2" <your-park>.park --headless \
//       | grep '^GENERIDE_' > park-probe-output.txt
//   rm ~/Library/Application\ Support/OpenRCT2/plugin/park_probe.js
//
// The game keeps running after the probe prints GENERIDE_DONE (a plugin
// cannot quit it), so stop it with Ctrl-C once you see that line.
//
// Edit REGION below to a rectangle of your park. Coordinates are map tiles,
// the same numbers the game shows in its tile inspector. A 12 by 12 region is
// plenty for the spike.

var REGION = { x0: 60, y0: 60, x1: 71, y1: 71 }; // inclusive

registerPlugin({
    name: 'generide-park-probe',
    version: '1.0',
    authors: ['generide'],
    type: 'local',
    licence: 'MIT',
    targetApiVersion: 34,
    main: function () {
        // Every line is prefixed GENERIDE_ so the parent can grep stdout:
        // plugins have no file I/O, so stdout is the only way out.
        console.log('GENERIDE_MAP|sizeX=' + map.size.x + '|sizeY=' + map.size.y);
        console.log('GENERIDE_REGION|x0=' + REGION.x0 + '|y0=' + REGION.y0 +
                    '|x1=' + REGION.x1 + '|y1=' + REGION.y1);

        for (var y = REGION.y0; y <= REGION.y1; y++) {
            for (var x = REGION.x0; x <= REGION.x1; x++) {
                console.log('GENERIDE_TILE|x=' + x + '|y=' + y + '|' + describeTile(x, y));
            }
        }
        console.log('GENERIDE_DONE');

        // One element as "type[key=value,...]". Keys that do not exist on an
        // element type print as undefined, which is itself a finding: it says
        // that type does not expose that value in this API version.
        function describeElement(element) {
            var fields = ['baseHeight', 'clearanceHeight', 'waterHeight', 'ownership',
                          'slope', 'surfaceStyle', 'object', 'ride', 'isQueue', 'isAdditionQueue'];
            var parts = [];
            for (var i = 0; i < fields.length; i++) {
                var value = element[fields[i]];
                if (value !== undefined) {
                    parts.push(fields[i] + '=' + value);
                }
            }
            return element.type + '[' + parts.join(',') + ']';
        }

        function describeTile(x, y) {
            var tile = map.getTile(x, y);
            if (!tile) {
                return 'no-tile';
            }
            var elements = [];
            for (var i = 0; i < tile.numElements; i++) {
                elements.push(describeElement(tile.getElement(i)));
            }
            return elements.join(' ');
        }
    },
});
