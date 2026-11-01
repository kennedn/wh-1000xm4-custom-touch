package com.kennedn.xm4touch;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.os.Build;

final class AppNotifications {
    static final String PROGRESS = "installation", RESULTS = "results";
    static void channels(Context context) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(PROGRESS, "Patch installation", NotificationManager.IMPORTANCE_LOW));
        manager.createNotificationChannel(new NotificationChannel(RESULTS, "Patch results", NotificationManager.IMPORTANCE_DEFAULT));
    }
    static Notification notification(Context context, String channel, String title, String message) {
        PendingIntent open = PendingIntent.getActivity(context, 0, new Intent(context, MainActivity.class),
            PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Builder(context, channel).setContentTitle(title).setContentText(message)
            .setStyle(new Notification.BigTextStyle().bigText(message))
            .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth).setContentIntent(open).setAutoCancel(true).build();
    }
    static void result(Context context, String title, String message) {
        channels(context);
        if (Build.VERSION.SDK_INT >= 33 && context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return;
        try {
            context.getSystemService(NotificationManager.class).notify(2, notification(context, RESULTS, title, message));
        } catch (SecurityException e) { android.util.Log.w("Xm4Touch", "Notifications are not permitted", e); }
    }
}
