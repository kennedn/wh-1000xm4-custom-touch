package com.kennedn.xm4touch;

import android.bluetooth.BluetoothAdapter;
import android.content.*;

public final class RecoveryReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        String action = intent.getAction();
        if (BluetoothAdapter.ACTION_STATE_CHANGED.equals(action)) {
            int state = intent.getIntExtra(BluetoothAdapter.EXTRA_STATE, BluetoothAdapter.ERROR);
            if (state == BluetoothAdapter.STATE_OFF || state == BluetoothAdapter.STATE_TURNING_OFF) {
                HeadsetStatus.disconnected(context); return;
            }
            if (state != BluetoothAdapter.STATE_ON) return;
        } else if (!Intent.ACTION_BOOT_COMPLETED.equals(action) && !Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)) return;
        if (!Monitoring.enabled(context)) return;
        Monitoring.restore(context);
        PendingResult pending = goAsync();
        Monitoring.checkConnected(context.getApplicationContext(), pending::finish);
    }
}
