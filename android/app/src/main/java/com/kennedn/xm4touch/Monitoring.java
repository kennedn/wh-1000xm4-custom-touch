package com.kennedn.xm4touch;

import android.Manifest;
import android.annotation.SuppressLint;
import android.bluetooth.*;
import android.companion.CompanionDeviceManager;
import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Handler;
import android.os.Looper;
import java.util.concurrent.atomic.AtomicBoolean;

final class Monitoring {
    static boolean enabled(Context c) {
        return InstallService.prefs(c).getBoolean("automatic", false) &&
            c.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED;
    }
    static void restore(Context c) {
        if (!enabled(c)) return;
        String address = InstallService.prefs(c).getString("classic", "");
        CompanionDeviceManager manager = c.getSystemService(CompanionDeviceManager.class);
        try {
            if (!manager.getAssociations().contains(address)) {
                InstallService.status(c, "Select XM4 again to restore automatic management."); return;
            }
            manager.startObservingDevicePresence(address);
            InstallService.prefs(c).edit().putLong("monitoringRestored", System.currentTimeMillis()).apply();
        } catch (RuntimeException e) { InstallService.status(c, "Cannot restore monitoring: " + e.getMessage()); }
    }
    /** Catch a connection that happened during boot, before the receiver could observe it. */
    @SuppressLint("MissingPermission")
    static void checkConnected(Context c, Runnable complete) { checkConnected(c, complete, true); }
    @SuppressLint("MissingPermission")
    static void checkConnected(Context c, Runnable complete, boolean install) {
        if ((install && !enabled(c)) || c.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED ||
                InstallService.prefs(c).getString("classic", "").isEmpty()) { complete.run(); return; }
        BluetoothAdapter adapter = c.getSystemService(BluetoothManager.class).getAdapter();
        if (adapter == null || !adapter.isEnabled()) { HeadsetStatus.disconnected(c); complete.run(); return; }
        final long observedSession = HeadsetStatus.session(c);
        Handler handler = new Handler(Looper.getMainLooper());
        AtomicBoolean finished = new AtomicBoolean();
        Runnable done = () -> { if (finished.compareAndSet(false, true)) complete.run(); };
        Runnable timeout = () -> done.run();
        handler.postDelayed(timeout, 8000);
        try {
            boolean accepted = adapter.getProfileProxy(c, new BluetoothProfile.ServiceListener() {
                @Override public void onServiceConnected(int profile, BluetoothProfile proxy) {
                    try {
                        if (finished.get() || HeadsetStatus.session(c) != observedSession) return;
                        String selected = InstallService.prefs(c).getString("classic", "");
                        boolean connected = false;
                        for (BluetoothDevice device : proxy.getConnectedDevices()) {
                            if (selected.equals(device.getAddress())) { connected = true; break; }
                        }
                        if (connected) {
                            HeadsetStatus.connected(c);
                            if (install) InstallService.start(c, true);
                        } else HeadsetStatus.snapshotDisconnected(c, observedSession);
                    } catch (RuntimeException e) { InstallService.status(c, "Cannot check headset connection: " + e.getMessage()); }
                    finally { adapter.closeProfileProxy(profile, proxy); handler.removeCallbacks(timeout); done.run(); }
                }
                @Override public void onServiceDisconnected(int profile) { handler.removeCallbacks(timeout); done.run(); }
            }, BluetoothProfile.A2DP);
            if (!accepted) { handler.removeCallbacks(timeout); done.run(); }
        } catch (RuntimeException e) { handler.removeCallbacks(timeout); done.run(); }
    }
}
