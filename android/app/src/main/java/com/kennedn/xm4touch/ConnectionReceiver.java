package com.kennedn.xm4touch;

import android.bluetooth.BluetoothDevice;
import android.content.*;
import android.os.Build;

public final class ConnectionReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        String action = intent.getAction();
        if (!BluetoothDevice.ACTION_ACL_CONNECTED.equals(action) && !BluetoothDevice.ACTION_ACL_DISCONNECTED.equals(action)) return;
        BluetoothDevice device = intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE);
        String selected = InstallService.prefs(context).getString("classic", "");
        if (device == null || !device.getAddress().equals(selected)) return;
        // Closing our short-lived GATT connection is not an audio-headset disconnect.
        if (Build.VERSION.SDK_INT >= 33 && intent.getIntExtra(BluetoothDevice.EXTRA_TRANSPORT,
                BluetoothDevice.TRANSPORT_BREDR) == BluetoothDevice.TRANSPORT_LE) return;
        if (BluetoothDevice.ACTION_ACL_CONNECTED.equals(action)) {
            HeadsetStatus.connected(context);
            InstallService.start(context, true);
        } else {
            HeadsetStatus.disconnected(context);
        }
    }
}
