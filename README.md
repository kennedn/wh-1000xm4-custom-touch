# WH-1000XM4 Touch Toggle

RAM patch that makes a long press of CUSTOM toggle touch controls on the Sony WH-1000XM4. Tested on firmware **2.5.0**. Rebooting clears the patch.

## Android App

Install the patch from your phone, with optional automatic installation when the XM4 connects. Requires Android 12+.

### Build

With JDK 17+ and Android SDK 36.1 installed, run from this directory:

```bash
cd android
./gradlew :app:assembleDebug
```

Install `android/app/build/outputs/apk/debug/app-debug.apk` on your phone.

### Usage

* Allow Nearby Devices and notification permissions.
* Assign CUSTOM to Google Assistant in the Sony app.
* Pair the headset in Android settings, then tap **Select XM4**. The list filters paired addresses by `80:99:E7`.
* Tap **Detect LE address** and select the headset, or enter its BLE address manually.
* Tap **Install patch**. Long-press and release CUSTOM to toggle touch controls.
* Enable **Install when XM4 connects** to patch automatically on reconnect.

The app shows **Checking Headset...**, then **Patch installed**. Disconnecting shows **Headset not connected** and clears the result notification.

> Automatic mode restores monitoring after phone reboot and unlock. Force-stop and battery restrictions can prevent background work; reboot/reconnect handling still needs validation.

See [android/README.md](android/README.md) for development notes.

---

## Python Installer

### Prerequisites

* `uv` and Python 3.10+
* USB Bluetooth controller supported by Bumble
* CUSTOM assigned to Google Assistant in the Sony app

### Setup

Clone [RACE Toolkit](https://github.com/auracast-research/race-toolkit) into this directory and install dependencies:

```bash
git clone https://github.com/auracast-research/race-toolkit.git race-toolkit
uv sync
```

### Usage

Power-cycle the headphones, then run:

```bash
uv run python custom_touch_250.py --skip-verify
```

Long-press and release CUSTOM to disable touch. Repeat to enable it. The script exits after installation.

#### Options

| Option | Description |
| --- | --- |
| `--skip-verify` | Skip code readback; write ACKs and callback readback are still checked. |
| `--dynamic` | Select an address from the current heap free list. |
| `--scratch ADDRESS` | Set the upload address. With `--dynamic`, check it fits a free block. |
| `--timings` | Print installation timings. |
| `--controller CONTROLLER` | Bluetooth controller (default: `usb:0`). |
| `--address ADDRESS` | Headset BLE address (default: `C0:2E:A7:E9:FF:00`). |

> The default upload address (`0x10066830`) is unreserved. Dynamic mode checks the free list but does not reserve memory either.

If installation reports a callback mismatch at `0x10003d38`, power-cycle the headphones and retry.

## Building the Payload

The 120-byte payload is included. To rebuild [custom_touch_250_min.S](custom_touch_250_min.S), install GNU Arm tools and run:

```bash
arm-none-eabi-as -mcpu=cortex-m4 -mthumb -o /tmp/custom-touch-min.o custom_touch_250_min.S
arm-none-eabi-ld -Ttext=0 -e hook -o /tmp/custom-touch-min.elf /tmp/custom-touch-min.o
arm-none-eabi-objcopy -O binary -j .text /tmp/custom-touch-min.elf custom-touch-250-min.bin
```

Update `MINIMAL_SIZE` and `MINIMAL_SHA` in the Python installer and `SHA` in
`android/app/src/main/java/com/kennedn/xm4touch/PatchInstaller.java` after changing the payload.

## Tests

```bash
uv run python -m unittest discover -s tests
```

Tests use mocked connections and memory. Capstone is installed by `uv sync` for instruction tests.

## Notes

The installer uploads the payload over RACE and redirects the Google Assistant callback. Only RAM is changed. See [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md) for addresses and reverse-engineering notes.
