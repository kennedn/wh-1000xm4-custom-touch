package com.kennedn.xm4touch;

import android.content.Context;

/** Serializes disconnects and install results so an old worker cannot publish stale success. */
final class HeadsetStatus {
    static final String CHECKING = "Checking Headset...", INSTALLED = "Patch installed", DISCONNECTED = "Headset not connected";
    static synchronized long session(Context c) { return InstallService.prefs(c).getLong("connectionSession", 0); }
    static synchronized void connected(Context c) {
        if (InstallService.prefs(c).getBoolean("disconnected", true)) {
            InstallService.prefs(c).edit().putBoolean("disconnected", false).apply();
            InstallService.status(c, "Headset connected");
        }
    }
    static synchronized void disconnected(Context c) {
        InstallService.prefs(c).edit().putBoolean("disconnected", true).putLong("connectionSession", session(c) + 1).apply();
        InstallService.status(c, DISCONNECTED);
        c.getSystemService(android.app.NotificationManager.class).cancel(2);
    }
    static synchronized void publish(Context c, long session, String message, boolean notify) {
        if (session(c) != session || InstallService.prefs(c).getBoolean("disconnected", false)) return;
        InstallService.status(c, message);
        if (notify) AppNotifications.result(c, "XM4 Touch", message);
    }
}
