#!/bin/sh
# Rebuilds the vendored synthesizer from the spessasynth_lib package on npm.
# The page loads classic scripts, so the library is bundled into one file that
# exposes itself as window.SpessaSynth; its audio worklet processor is already
# self-contained and is copied as it is.
set -eu
cd "$(dirname "$0")/.."
VENDOR=talkingscoresapp/static/js/vendor
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
(cd "$WORK" && npm init -y >/dev/null && npm install --no-audit --no-fund spessasynth_lib esbuild >/dev/null)
"$WORK/node_modules/.bin/esbuild" "$WORK/node_modules/spessasynth_lib/dist/index.js" \
    --bundle --format=iife --global-name=SpessaSynth --minify --outfile="$VENDOR/spessasynth.js"
cp "$WORK/node_modules/spessasynth_lib/dist/spessasynth_processor.min.js" "$VENDOR/"
cp "$WORK/node_modules/spessasynth_lib/LICENSE" "$VENDOR/spessasynth-LICENSE.txt"
node -e 'console.log("spessasynth_lib " + require(process.argv[1]).version)' "$WORK/node_modules/spessasynth_lib/package.json"
