# Third-party notices

The root MIT license covers original Enkiplate code, documentation, the device photograph and material artwork to the extent copyright applies. It does not relicense the following third-party material.

## Dictionary

JMdict Japanese and English data: copyright James William Breen and the Electronic Dictionary Research and Development Group. Used under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). See the [EDRDG license statement](https://www.edrdg.org/edrdg/licence.html) and the copies in `licenses/`.

`enki setup` downloads the English dictionary at runtime. Enkiplate selects common entries, shortens English senses and converts kana readings to ASCII Hepburn. Those derived entries remain CC BY-SA 4.0. The runtime dictionary and learning database are not included in the repository. The curated foundation in `enki_core/content.py` is original teaching material; common spellings were checked against JMdict.

## Weather

Weather data by [Open-Meteo](https://open-meteo.com/), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Daily ranges are rounded and weather codes are mapped to display symbols. The weather provider is credited in the companion UI and README.

## Fonts

Noto Sans JP, Manrope and IBM Plex Mono retain their original authors' copyrights and SIL Open Font License 1.1. Their individual license files are distributed beside the unmodified fonts in `enki/assets/production/`.

## Firmware dependencies

The firmware links, but does not vendor, these libraries:

- [Soldered InkplateLibrary](https://github.com/SolderedElectronics/Inkplate-Arduino-library), LGPL-3.0, including components with their own notices. The exact library source commit is pinned in `scripts/build_firmware.sh`.
- [ArduinoJson](https://github.com/bblanchon/ArduinoJson), MIT, version 7.4.3.
- The Soldered ESP32 board package and its bundled ESP32 SDK components retain their respective upstream licenses.

`FrameCodec.cpp` calls the pinned Inkplate library's bundled miniz decompressor. It does not contain a copied decompressor. Build instructions and full application source are provided so the linked library can be modified and the firmware rebuilt. Anyone distributing compiled firmware must also comply with the linked libraries' license requirements, including the LGPL conditions for combined works. This repository publishes source, not prebuilt firmware images.

## Material artwork

The grayscale stationery plates were created with ChatGPT Image Gen and composed with programmatically rendered text and controls. Prompts are preserved in `enki/assets/objects/*prompts.json`. The MIT grant includes these assets to the extent the author holds rights. There is no claim of exclusive copyright in machine-generated elements.

Python packages are installed from the pinned `uv.lock`; their licenses are supplied by their respective upstream distributions.
