# Reverse engineering notes

The target is a WH-1000XM4 running firmware 2.5.0. The directory was originally
named for the XM3, but the addresses below are for the XM4.

## Button handling

The CUSTOM button already has a route through the Google Assistant handler.
Rather than replace the button dispatcher, the patch replaces a callback used
by that handler.

The callback receives an event in `r0` and an optional data pointer in `r1`.
The wrapper saves its caller's return address at `SP + 28`. Checking that
address along with the event lets the patch distinguish the button action
from intermediate Assistant calls.

Two action paths are handled:

| Saved return address | Event |
| --- | --- |
| `0x08257957` | `4` |
| `0x0825796f` | `0x43` |

The observed trigger is a long press. Recognised Assistant prelude/release
calls are consumed; other callers are forwarded to the original callback.
Some Assistant setup still runs before the callback is reached.

## Touch controls

| Address | Purpose |
| --- | --- |
| `0x10068b10` | Pointer to the callback table |
| `0x10003d38` | Callback slot we replace |
| `0x08263bb5` | Original callback, including the Thumb bit |
| `0x10074971` | Touch-disabled byte |
| `0x0823c6ad` | Touch setter, including the Thumb bit |
| `0x10066830` | Default patch location |

The patch reads the disabled byte, inverts it and calls the existing setter.
That also runs Sony's touch-status notification code.

A four-byte latch allows one toggle per press/release cycle. Events `8` and
`0x80` on the recognised release paths clear it. Without the latch, holding
CUSTOM caused repeated toggles and an unpredictable final state.

The first version was 196 bytes and included counters and an observe mode.
Removing those, while keeping the latch, brought it down to 120 bytes. The
current code is in [custom_touch_250_min.S](custom_touch_250_min.S).

## Loading the patch

RACE commands `0x1680` and `0x1681`, module 0, read and write a four-byte word.
Changed-value writes and restoration were tested before attempting execution.

The installer uploads the code first and changes the callback slot last. At
the default location it writes `0x10066831` to the slot: the low bit marks a
Thumb function pointer. Python can then disconnect.

An early observe-mode patch counted button events from SRAM. Calling the
setter from the patch subsequently confirmed that touch could be turned off
and back on. Reboot restores the stock callback and clears the patch.

Only the 2.5.0 address map has been tested. The earlier firmware experiments
didn't establish a reliable version boundary for RACE access.

## RAM placement

Matching saved captures shared a free range from `0x1001b418` to `0x100668a7`.
They weren't tagged with boot identifiers. The last 120 bytes of that range,
starting at `0x10066830`, were used successfully and are now the default.

This is still heap memory. Neither fixed nor dynamic placement reserves it.
`--dynamic` walks the current free list and rechecks the chosen block before
uploading. Heap metadata is read serially: pipelined walks sometimes returned
invalid headers, and the cause wasn't pinned down.

MPU control read as `7`, with cached regions matching the firmware setup.
The button tests confirmed that this SRAM location actually executes code.

## Installation time

| Configuration | Shell runtime |
| --- | ---: |
| Dynamic placement, code readback enabled | 4.556 s |
| Fixed placement, code readback skipped | 2.416 s |

The runs used different checks and verification settings. Most of the
improvement came from skipping GATT discovery and sending four requests at a
time. Removing the destination backup and optionally skipping code readback
also reduced the number of requests.

Packing 16 read requests into one GATT write took about the same time as the
four-request window. Requesting a 7.5 ms interval briefly worked, then returned
to 30 ms. Neither experiment is in the current installer.

## Custom firmware

The RAM patch works, but hasn't been made persistent. A firmware version would
need a permanent location for the function and latch, plus a change to callback
registration or startup code.

The update container can be decrypted. Rebuilding a modified image, satisfying
its integrity checks and getting the updater to accept it are still open work.
No modified firmware has been flashed.

The original notes, captures and diagnostic tools are in the local ignored
`archive/` directory. They aren't included in a fresh clone.
