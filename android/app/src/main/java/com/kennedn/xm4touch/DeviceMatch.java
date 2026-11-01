package com.kennedn.xm4touch;

import java.util.Locale;

final class DeviceMatch {
    static boolean sonyAudioAddress(String address) {
        return address != null && address.toUpperCase(Locale.ROOT).startsWith("80:99:E7:");
    }
    static boolean xm4Name(String name) {
        return name != null && name.toUpperCase(Locale.ROOT).contains("WH-1000XM4");
    }
}
