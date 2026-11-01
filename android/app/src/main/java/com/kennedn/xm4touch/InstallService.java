package com.kennedn.xm4touch;

import android.app.*;
import android.content.*;
import android.os.*;
import java.util.concurrent.atomic.AtomicBoolean;

public final class InstallService extends Service {
    private static final AtomicBoolean running = new AtomicBoolean();
    static android.content.SharedPreferences prefs(Context c) { return c.getSharedPreferences("xm4", MODE_PRIVATE); }
    static void status(Context c, String message) {
        prefs(c).edit().putString("status", message).putLong("statusTime", System.currentTimeMillis()).apply();
    }
    static void start(Context c, boolean automatic) {
        if (automatic && !prefs(c).getBoolean("automatic", false)) return;
        try { c.startForegroundService(new Intent(c, InstallService.class)); }
        catch (RuntimeException e) {
            String message = "Open app to install: " + e.getMessage();
            status(c, message); AppNotifications.result(c, "XM4 patch could not start", message);
        }
    }
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (!running.compareAndSet(false, true)) return START_NOT_STICKY;
        final long session = HeadsetStatus.session(this);
        AppNotifications.channels(this);
        try {
            startForeground(1, AppNotifications.notification(this, AppNotifications.PROGRESS,
                "XM4 Touch", HeadsetStatus.CHECKING));
        } catch (RuntimeException e) {
            running.set(false);
            String message = "Cannot start installation: " + e.getMessage();
            status(this, message); AppNotifications.result(this, "XM4 patch could not start", message);
            stopSelf(); return START_NOT_STICKY;
        }
        new Thread(() -> {
            HeadsetStatus.publish(this, session, HeadsetStatus.CHECKING, false);
            try {
                String address = prefs(this).getString("ble", "");
                if (!android.bluetooth.BluetoothAdapter.checkBluetoothAddress(address)) throw new IllegalArgumentException("Set the headset BLE address first");
                byte[] blob;
                try (java.io.InputStream in = getAssets().open("custom-touch-250-min.bin");
                     java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream()) {
                    byte[] chunk = new byte[256]; int count;
                    while ((count = in.read(chunk)) != -1) out.write(chunk, 0, count);
                    blob = out.toByteArray();
                }
                try (GattMemory memory = new GattMemory(this, address)) {
                    PatchInstaller.install(memory, blob);
                    HeadsetStatus.publish(this, session, HeadsetStatus.INSTALLED, true);
                }
            } catch (Exception e) {
                String message = "Failed: " + e.getMessage();
                HeadsetStatus.publish(this, session, message, true);
                android.util.Log.e("Xm4Touch", "Install failed", e);
            }
            finally {
                stopForeground(STOP_FOREGROUND_REMOVE);
                // Stop before reopening the gate; duplicate connection events cannot overlap workers.
                stopSelf(); running.set(false);
            }
        }, "xm4-install").start();
        return START_NOT_STICKY;
    }
    @Override public IBinder onBind(Intent intent) { return null; }
}
