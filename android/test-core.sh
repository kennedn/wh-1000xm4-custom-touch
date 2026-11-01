#!/bin/sh
set -eu
cd "$(dirname "$0")"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
javac -d "$work" app/src/main/java/com/kennedn/xm4touch/DeviceMatch.java app/src/main/java/com/kennedn/xm4touch/PatchInstaller.java app/src/main/java/com/kennedn/xm4touch/RaceProtocol.java app/src/test/java/com/kennedn/xm4touch/CoreTest.java
java -cp "$work" com.kennedn.xm4touch.CoreTest ../custom-touch-250-min.bin
