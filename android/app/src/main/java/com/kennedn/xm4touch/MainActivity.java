package com.kennedn.xm4touch;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.le.*;
import android.companion.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.os.*;
import android.widget.*;
import java.util.Locale;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.UUID;

@SuppressLint("MissingPermission")
public final class MainActivity extends Activity {
    private TextView status, selected;
    private EditText ble;
    private Switch automatic;
    private Button detect;
    private BluetoothLeScanner scanner;
    private ScanCallback scanCallback;
    private final LinkedHashMap<String, String> leDevices = new LinkedHashMap<>();
    private boolean resumed, detectOnResume;
    private final Runnable scanTimeout = () -> finishLeScan(true);
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable refresh = new Runnable() {
        @Override public void run() {
            status.setText(InstallService.prefs(MainActivity.this).getString("status", "Ready"));
            handler.postDelayed(this, 1000);
        }
    };
    private CompanionDeviceManager companions() { return getSystemService(CompanionDeviceManager.class); }
    private boolean permissions() {
        if (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED &&
                checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) == PackageManager.PERMISSION_GRANTED) return true;
        if (Build.VERSION.SDK_INT >= 33) InstallService.prefs(this).edit().putBoolean("notificationRequested", true).apply();
        requestPermissions(Build.VERSION.SDK_INT >= 33 ? new String[] {
            Manifest.permission.BLUETOOTH_CONNECT, Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.POST_NOTIFICATIONS
        } : new String[] { Manifest.permission.BLUETOOTH_CONNECT, Manifest.permission.BLUETOOTH_SCAN }, 1);
        return false;
    }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout layout = new LinearLayout(this); layout.setOrientation(LinearLayout.VERTICAL);
        int pad = (int)(24 * getResources().getDisplayMetrics().density); layout.setPadding(pad, pad, pad, pad);
        ScrollView scroll = new ScrollView(this); scroll.addView(layout); setContentView(scroll);
        TextView title = new TextView(this); title.setText("XM4 Touch"); title.setTextSize(28); layout.addView(title);
        TextView instructions = new TextView(this);
        instructions.setText("WH-1000XM4 • firmware 2.5.0\n\nAssign CUSTOM to Google Assistant in the Sony app. Pair the headphones with Android, then select them below.\n\nThe patch lasts until headset reboot. It uses unreserved RAM, like the desktop PoC.\n"); layout.addView(instructions);
        selected = new TextView(this); layout.addView(selected); showSelected();
        Button select = new Button(this); select.setText("Select XM4"); layout.addView(select);
        select.setOnClickListener(v -> selectPairedHeadset());
        TextView addressLabel = new TextView(this); addressLabel.setText("Headset BLE address (may differ from its audio address)"); layout.addView(addressLabel);
        ble = new EditText(this); ble.setSingleLine(true); ble.setHint("AA:BB:CC:DD:EE:FF");
        ble.setText(InstallService.prefs(this).getString("ble", "")); layout.addView(ble);
        TextView addressHelp = new TextView(this); addressHelp.setText("Detect the LE address below, or enter it manually.\n"); layout.addView(addressHelp);
        detect = new Button(this); detect.setText("Detect LE address"); layout.addView(detect);
        detect.setOnClickListener(v -> startLeScan());
        Button install = new Button(this); install.setText("Install patch"); layout.addView(install);
        install.setOnClickListener(v -> { if (permissions() && saveAddress()) InstallService.start(this, false); });
        automatic = new Switch(this); automatic.setText("Install when XM4 connects"); layout.addView(automatic);
        automatic.setChecked(InstallService.prefs(this).getBoolean("automatic", false));
        automatic.setOnCheckedChangeListener((button, enabled) -> {
            String classic = InstallService.prefs(this).getString("classic", "");
            if (enabled && (!permissions() || !saveAddress() || !companions().getAssociations().contains(classic))) {
                report("Select the XM4 and set its BLE address before enabling automatic installation.");
                button.setChecked(false);
                if (!classic.isEmpty() && permissions() && saveAddress()) associateHeadset(classic);
                return;
            }
            try {
                if (enabled) companions().startObservingDevicePresence(classic);
                else if (companions().getAssociations().contains(classic)) companions().stopObservingDevicePresence(classic);
                InstallService.prefs(this).edit().putBoolean("automatic", enabled).apply();
                if (enabled) Monitoring.checkConnected(getApplicationContext(), () -> {});
            } catch (Exception e) { report(e.getMessage()); if (enabled) button.setChecked(false); }
        });
        Button forget = new Button(this); forget.setText("Forget headset"); layout.addView(forget);
        forget.setOnClickListener(v -> {
            automatic.setChecked(false);
            try { for (String address : companions().getAssociations()) companions().disassociate(address); }
            catch (Exception e) { report(e.getMessage()); }
            finishLeScan(false);
            HeadsetStatus.disconnected(this);
            detectOnResume = false;
            ble.setText("");
            InstallService.prefs(this).edit().remove("classic").remove("ble").putBoolean("automatic", false).apply(); showSelected();
        });
        Button notifications = new Button(this); notifications.setText("Notification settings"); layout.addView(notifications);
        notifications.setOnClickListener(v -> startActivity(new Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS)
            .putExtra(android.provider.Settings.EXTRA_APP_PACKAGE, getPackageName())));
        TextView monitoringHelp = new TextView(this);
        monitoringHelp.setText("Automatic mode resumes after phone reboot and unlock. Allow notifications to see patch results. Force-stop or restricted battery settings can prevent automatic work.");
        layout.addView(monitoringHelp);
        status = new TextView(this); status.setPadding(0, pad, 0, 0); layout.addView(status);
        if (permissions() && Build.VERSION.SDK_INT >= 33 &&
                checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED &&
                !InstallService.prefs(this).getBoolean("notificationRequested", false)) {
            InstallService.prefs(this).edit().putBoolean("notificationRequested", true).apply();
            requestPermissions(new String[] {Manifest.permission.POST_NOTIFICATIONS}, 3);
        }
        AppNotifications.channels(this);
        Monitoring.restore(this);
    }
    private void startLeScan() {
        detectOnResume = false;
        if (!permissions() || scanCallback != null) return;
        BluetoothAdapter adapter = getSystemService(BluetoothManager.class).getAdapter();
        if (adapter == null || !adapter.isEnabled()) { report("Enable Bluetooth first"); return; }
        scanner = adapter.getBluetoothLeScanner();
        if (scanner == null) { report("Bluetooth LE scanner unavailable"); return; }
        leDevices.clear();
        scanCallback = new ScanCallback() {
            @Override public void onScanResult(int type, ScanResult result) { found(result); }
            @Override public void onBatchScanResults(List<ScanResult> results) { for (ScanResult result : results) found(result); }
            private void found(ScanResult result) {
                handler.post(() -> {
                    if (scanCallback != this) return;
                    ScanRecord record = result.getScanRecord();
                    String name = record == null ? null : record.getDeviceName();
                    if (name == null) name = result.getDevice().getName();
                    boolean race = record != null && record.getServiceUuids() != null && record.getServiceUuids().contains(
                        new ParcelUuid(UUID.fromString("dc405470-a351-4a59-97d8-2e2e3b207fbb")));
                    if (DeviceMatch.xm4Name(name) || race) {
                        String address = result.getDevice().getAddress();
                        leDevices.put(address, (name == null ? "Sony RACE device" : name) + "\n" + address);
                        report("Found " + leDevices.size() + " LE candidate(s). Finishing scan…");
                    }
                });
            }
            @Override public void onScanFailed(int error) {
                handler.post(() -> {
                    if (scanCallback != this) return;
                    finishLeScan(false); report("LE discovery failed (" + error + "). Retry or enter the address manually.");
                });
            }
        };
        detect.setEnabled(false); detect.setText("Scanning for 15 seconds…");
        report("Looking for LE_WH-1000XM4. Keep the headphones powered on and nearby.");
        try {
            // LE addresses need not share the Classic Sony prefix. Match advertisements instead.
            scanner.startScan(null, new ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(), scanCallback);
            handler.postDelayed(scanTimeout, 15000);
        } catch (RuntimeException e) { finishLeScan(false); report("Cannot scan: " + e.getMessage()); }
    }
    private void finishLeScan(boolean choose) {
        handler.removeCallbacks(scanTimeout);
        if (scanCallback != null && scanner != null) {
            try { scanner.stopScan(scanCallback); } catch (RuntimeException ignored) { }
        }
        scanCallback = null; scanner = null;
        if (detect != null) { detect.setEnabled(true); detect.setText("Detect LE address"); }
        if (!choose || !resumed) return;
        if (leDevices.isEmpty()) {
            report("No XM4 LE advertisements found. Keep the headset on, retry, or enter the known BLE address manually.");
            return;
        }
        ArrayList<String> addresses = new ArrayList<>(leDevices.keySet());
        new AlertDialog.Builder(this).setTitle("Select your XM4 LE device")
            .setItems(leDevices.values().toArray(new String[0]), (dialog, which) -> {
                ble.setText(addresses.get(which));
                saveAddress();
                report("LE address saved. Ready to install.");
            }).setNegativeButton("Cancel", null).show();
    }
    private void selectPairedHeadset() {
        if (!permissions()) return;
        BluetoothAdapter adapter = getSystemService(BluetoothManager.class).getAdapter();
        if (adapter == null || !adapter.isEnabled()) { report("Enable Bluetooth first"); return; }
        ArrayList<BluetoothDevice> devices = new ArrayList<>(adapter.getBondedDevices());
        devices.removeIf(device -> !DeviceMatch.sonyAudioAddress(device.getAddress()));
        devices.sort(Comparator.comparing(d -> d.getName() == null ? d.getAddress() : d.getName()));
        if (devices.isEmpty()) {
            new AlertDialog.Builder(this).setTitle("No matching Sony devices")
                .setMessage("Pair your XM4 in Android Bluetooth settings. Only paired addresses starting with 80:99:E7 are shown.")
                .setPositiveButton("Bluetooth settings", (dialog, which) -> startActivity(new Intent(android.provider.Settings.ACTION_BLUETOOTH_SETTINGS)))
                .setNegativeButton("Cancel", null).show();
            return;
        }
        String[] labels = new String[devices.size()];
        for (int i = 0; i < devices.size(); i++) {
            BluetoothDevice device = devices.get(i);
            labels[i] = (device.getName() == null ? "Unnamed device" : device.getName()) + "\n" + device.getAddress();
        }
        new AlertDialog.Builder(this).setTitle("Select your paired XM4").setItems(labels, (dialog, which) -> {
            String address = devices.get(which).getAddress();
            selectAddress(address);
            associateHeadset(address);
        }).setNegativeButton("Cancel", null).show();
    }
    private void selectAddress(String address) {
        if (!address.equals(InstallService.prefs(this).getString("classic", ""))) {
            automatic.setChecked(false);
            HeadsetStatus.disconnected(this);
            ble.setText("");
            InstallService.prefs(this).edit().remove("ble").apply();
        }
        if (ble.getText().toString().isBlank()) detectOnResume = true;
        InstallService.prefs(this).edit().putString("classic", address).apply();
        showSelected();
        report("Headset selected. Detect its LE address, then try Install patch.");
        if (resumed && detectOnResume) handler.post(() -> { if (resumed && detectOnResume) startLeScan(); });
    }
    private void associateHeadset(String address) {
        if (companions().getAssociations().contains(address)) return;
        // A targeted single-device request can match an already bonded headset;
        // broad discovery depends on discoverability and the advertised name.
        AssociationRequest request = new AssociationRequest.Builder()
            .addDeviceFilter(new BluetoothDeviceFilter.Builder().setAddress(address).build())
            .setSingleDevice(true).build();
        try {
            companions().associate(request, new CompanionDeviceManager.Callback() {
                private void launch(IntentSender chooser) {
                    try { startIntentSenderForResult(chooser, 2, null, 0, 0, 0); }
                    catch (IntentSender.SendIntentException e) { report(e.getMessage()); }
                }
                @Override public void onDeviceFound(IntentSender chooser) { launch(chooser); }
                @Override public void onAssociationPending(IntentSender chooser) { launch(chooser); }
                @Override public void onAssociationCreated(AssociationInfo info) {
                    selectAddress(address);
                }
                @Override public void onFailure(CharSequence error) {
                    report("Automatic setup failed: " + error + ". Manual installation is still available.");
                }
            }, handler);
        } catch (RuntimeException e) { report("Automatic setup failed: " + e.getMessage()); }
    }
    private void report(String message) { InstallService.status(this, message); }
    private void showSelected() { selected.setText("Selected headset: " + InstallService.prefs(this).getString("classic", "none")); }
    private boolean saveAddress() {
        String address = ble.getText().toString().trim().toUpperCase(Locale.ROOT);
        if (!android.bluetooth.BluetoothAdapter.checkBluetoothAddress(address)) { report("Enter a valid BLE address"); return false; }
        InstallService.prefs(this).edit().putString("ble", address).apply(); return true;
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == 2 && result == RESULT_OK && data != null) {
            BluetoothDevice device = data.getParcelableExtra(CompanionDeviceManager.EXTRA_DEVICE);
            if (device != null) selectAddress(device.getAddress());
        }
    }
    @Override protected void onResume() {
        super.onResume(); resumed = true; handler.post(refresh);
        Monitoring.checkConnected(getApplicationContext(), () -> {}, false);
        if (detectOnResume) handler.post(() -> { if (resumed && detectOnResume) startLeScan(); });
    }
    @Override protected void onPause() {
        resumed = false; handler.removeCallbacks(refresh);
        if (scanCallback != null) detectOnResume = true;
        finishLeScan(false); super.onPause();
    }
}
