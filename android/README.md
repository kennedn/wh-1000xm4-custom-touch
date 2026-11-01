# XM4 Touch for Android

Android BLE installer for the WH-1000XM4 **2.5.0** RAM patch. Requires Android 12+. See the [main README](../README.md#android-app) for setup and usage.

## Build

With JDK 17+ and Android SDK 36.1 installed:

```bash
./gradlew :app:assembleDebug
```

APK: `app/build/outputs/apk/debug/app-debug.apk`.

The build copies `../custom-touch-250-min.bin` into the app. Update the checksum in both installers if the payload changes.

## Behaviour

* Scans for LE devices for 15 seconds, matching XM4 names or the Sony RACE service. LE addresses may differ from the audio address.
* Checks firmware and existing patch state before writing. Every write is acknowledged and read back; the callback is attached last.
* Shows patch results in a notification and follows the phone’s light/dark theme.
* Restores companion monitoring after reboot and unlock, app updates and Bluetooth being re-enabled. Checks for an existing A2DP connection during recovery.

> Uses the same fixed, unreserved RAM address as the Python PoC. Reboot the headset if an unknown callback or damaged patch is reported.

Manual installation has been tested on the headset. LE discovery and automatic reconnect/reboot handling still need phone testing. Force-stopping the app prevents automatic work until it is opened again.

## Tests

```bash
./test-core.sh
```

Tests cover the installer, RACE packets and device matching without a phone.
