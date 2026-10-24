# 🪨 Enkiplate firmware

For Soldered **Inkplate 4TEMPERA**: ESP32, 4 MB flash, PSRAM and a 600 × 600 touchscreen. The firmware keeps a rolling cache of flashcards and persistent answers, receiving rendered frames over Wi-Fi or USB.

## Build

Install [Arduino CLI](https://arduino.github.io/arduino-cli/latest/installation/) and Git. From the repository root:

```sh
bash scripts/build_firmware.sh
uv run python scripts/flash_device.py --verify-only
```

The script installs Soldered board core **4.0.0** and **ArduinoJson 7.4.3**, and checks out **InkplateLibrary 11.2.1**, commit `3c15d3275bb3b5c0d4b0ea8d79d87a8380a94554`. The core uses Arduino-ESP32 3.3.11. Its official package index is [maintained by Soldered](https://raw.githubusercontent.com/SolderedElectronics/Inkplate-Board-Definitions-for-Arduino-IDE/main/package_Inkplate_Boards_index.json).

Outputs go into ignored `.work/firmware-build/`. This compiles only; it does not flash or reset a device.

## Flash safely

Charge the Inkplate and power it on. A visible USB adapter does not mean the processor is on. In the companion app, choose **Disconnect USB** before flashing. List available ports:

```sh
uv run python -m serial.tools.list_ports
```

Use the port belonging to your Inkplate:

```sh
uv run python scripts/flash_device.py --port YOUR_SERIAL_PORT
```

The helper verifies image sizes and partition boundaries, confirms that the service released USB, and saves a complete original-flash backup under private `data/hardware/` before writing anything. A full backup can take several minutes at the default 115200 baud. `--baud 230400` or `--baud 460800` opts into faster transfers. `--esptool /path/to/esptool` selects the ESP32 core's esptool if it is not found automatically.

For a companion on another port, pass `--service-url http://127.0.0.1:PORT`. Connection refused is accepted when the service is stopped; other USB-release failures stop flashing.

Flashing replaces the previous application. **Do not erase all flash, change VCOM or upload the generated merged image.** The helper uploads separate segments and retains factory settings. Its backups may contain credentials; keep `data/` private.

## Partitions and persistence

| Region | Start | Size |
| --- | --- | --- |
| Factory/default NVS | `0x9000` | 20 KB |
| Application | `0x10000` | 1,984 KB |
| Enkiplate answer journal | `0x200000` | 128 KB |
| Cached frame filesystem | `0x220000` | 1,920 KB |

`Enki/partitions.csv` preserves the board's EEPROM-backed settings. The first installation initializes only the new journal. Updates retain it. State uses alternating NVS blobs with generation counters and CRC32. The current card, revealed side and pending reviews survive restarts. This is a single-application layout; there is no OTA partition.

## Transport

Frames are 600 × 600, eight shades and 180,000 raw bytes: two pixels per byte, each three-bit value shifted left in its nibble to match Inkplate's buffer. Wi-Fi downloads zlib-compressed frames and verifies raw length and CRC32 before committing. The pinned library's miniz decoder state is allocated on the heap, outside the default 8 KB Arduino loop stack.

The device caches up to 16 complete cards and starts refilling at six remaining. Metadata rendering runs in a separate network task. One frame downloads per loop so touch can run between transfers. Grades during prefetch are removed from the incoming queue before commit. Pending answers sync before new selection and are removed only after acknowledgement. A grade and card advance share one persisted state update.

USB uses newline-delimited JSON at 115200 baud. `frame` is followed by `ready`, 180,000 bytes and `stored`. `prepare`, `batch`, `abort`, `status`, `ack` and `config` coordinate staging, review recovery and Wi-Fi setup. `tap` is a USB-only debugging command. Status omits credentials and the device key. The host uses protocol acknowledgements instead of `Serial.flush()` because some macOS CH340 connections block while draining their transmit queue.

## Wi-Fi setup

Run `uv run enki serve --host 0.0.0.0`, open http://localhost:8787, choose **Inkplate → Connect USB**, and enter your Wi-Fi credentials. The app sends the device key and local server address over USB. Keep the host awake and reachable. HTTP is intended only for a trusted local network.

The device checks `/api/time` every 15 seconds. A changed study revision replaces cached screens when the level or design changes. An exhausted cache refills immediately; failures retry after 15 seconds. A genuinely empty study session polls every 60 seconds. The states distinguish **Nothing due**, **Getting cards...**, and **Offline. Reconnecting...**.

Authenticated heartbeat headers report firmware version, ready cards, pending answers, prefetch state, current frame, filesystem use, uptime and a sanitized transport error. The companion shows those values in device status.

## macOS CH340 recovery

Some CH340 adapters have stopped transmitting after reopening. First disconnect USB in the app, then unplug and reconnect the cable. If necessary, the optional helper can re-enumerate a single matching adapter. It refuses multiple matches and does not flash firmware.

```sh
mkdir -p .work
clang -Wno-deprecated-declarations scripts/reset_usb_macos.c -framework IOKit -framework CoreFoundation -o .work/reset_inkplate_usb
.work/reset_inkplate_usb
.work/reset_inkplate_usb --reset
```

The first command to the compiled helper lists adapters. Only `--reset` performs recovery. Ensure no other process owns the serial port.

The display stays awake for desk use. Battery life has not been measured. See [hardware verification and known limits](../docs/VERIFICATION.md).
