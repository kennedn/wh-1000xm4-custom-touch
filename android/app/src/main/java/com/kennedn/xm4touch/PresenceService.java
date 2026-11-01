package com.kennedn.xm4touch;

import android.companion.CompanionDeviceService;

public final class PresenceService extends CompanionDeviceService {
    @Override public void onDeviceAppeared(String address) {
        if (address.equals(InstallService.prefs(this).getString("classic", ""))) {
            Monitoring.checkConnected(this, () -> {});
        }
    }
    @Override public void onDeviceDisappeared(String address) {
        if (address.equals(InstallService.prefs(this).getString("classic", "")))
            Monitoring.checkConnected(this, () -> {}, false);
    }
}
