#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
command -v arduino-cli >/dev/null || { echo "Install arduino-cli first." >&2; exit 1; }
command -v git >/dev/null || { echo "Install git first." >&2; exit 1; }

library=.work/inkplate-library
revision=3c15d3275bb3b5c0d4b0ea8d79d87a8380a94554
index=https://raw.githubusercontent.com/SolderedElectronics/Inkplate-Board-Definitions-for-Arduino-IDE/main/package_Inkplate_Boards_index.json
mkdir -p .work
if [ ! -d "$library" ]; then
  git clone --filter=blob:none --no-checkout https://github.com/SolderedElectronics/Inkplate-Arduino-library.git "$library"
  git -C "$library" sparse-checkout init --cone
  git -C "$library" sparse-checkout set src
  git -C "$library" checkout --detach "$revision"
fi
if [ "$(git -C "$library" rev-parse HEAD)" != "$revision" ]; then
  echo "Expected InkplateLibrary source commit $revision in $library. Inspect the existing checkout." >&2
  exit 1
fi
arduino-cli core update-index --additional-urls "$index"
arduino-cli core install soldered-inkplate-boards:esp32@4.0.0 --additional-urls "$index"
arduino-cli lib install ArduinoJson@7.4.3
arduino-cli compile \
  --library "$library" \
  --build-path .work/firmware-build \
  --build-property upload.maximum_size=2031616 \
  --fqbn soldered-inkplate-boards:esp32:Inkplate4TEMPERA firmware/Enki
