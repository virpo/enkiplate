# Verification

Last physical checks: 24 October 2026.

## Checked on a real Inkplate 4TEMPERA

- Firmware 0.2.1, Soldered board core 4.0.0, InkplateLibrary 11.2.1 and ArduinoJson 7.4.3.
- Native 600 × 600 eight-shade screens, touch Reveal and all three grades.
- Wi-Fi card download and review synchronization with USB data disconnected.
- Saved current card, revealed side and pending answers across restart; exactly-once answer synchronization in an isolated hardware test.
- Rolling compressed-card cache, seven ready cards at the latest check, zero pending answers and no reported transport error.
- Wave washi theme received through a settings revision, without reflashing. The current photo shows the installed design with the larger tape.
- Factory settings retained by the separate application/journal partition layout.

## Automated checks

- Scheduling, level changes, import validation and history-preserving schema migrations.
- Calendar recurring events, occurrence overrides, exclusions and timezone handling.
- Frame size, compression, CRC, idempotent review storage and session refill.
- Real-font Japanese wrapping, long text, paper bounds and tape clearance.
- Firmware queue handling and decompression against pinned upstream sources.
- Browser review queue state and flash-region protection.

## Known limits

The host has been used on macOS. CI exercises the service on Linux. No physical Linux or Windows host setup has been tested. Other Inkplate models are unsupported.

Battery life and year-long unattended operation have not been measured. A rolling cache needs a reachable host for fresh cards. Sleep and OTA are not implemented.

Some macOS CH340 connections have stalled after reopening. Disconnecting and reconnecting the adapter recovered transfers. The optional `scripts/reset_usb_macos.c` utility is a manual diagnostic tool; it is not automatic recovery. One missing Wi-Fi heartbeat recovered after a processor restart; its original cause was not isolated.

Browser fixtures and automated tests use sample events and isolated learning databases. They do not prove long-term hardware reliability.
