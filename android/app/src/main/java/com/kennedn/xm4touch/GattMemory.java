package com.kennedn.xm4touch;

import android.annotation.SuppressLint;
import android.bluetooth.*;
import android.content.Context;
import java.io.ByteArrayOutputStream;
import java.util.UUID;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;

/** All blocking operations run on the install worker, never a Bluetooth callback thread. */
@SuppressLint("MissingPermission")
final class GattMemory implements PatchInstaller.Memory, AutoCloseable {
    private final LinkedBlockingQueue<Integer> operations = new LinkedBlockingQueue<>();
    private final LinkedBlockingQueue<byte[]> notifications = new LinkedBlockingQueue<>();
    private final BluetoothGatt gatt;
    private BluetoothGattCharacteristic tx;
    private volatile boolean disconnected;
    private static UUID uuid(String value) { return UUID.fromString(value); }
    GattMemory(Context context, String address) throws Exception {
        BluetoothManager manager = context.getSystemService(BluetoothManager.class);
        BluetoothAdapter adapter = manager.getAdapter();
        if (adapter == null || !adapter.isEnabled()) throw new IllegalStateException("Enable Bluetooth first");
        gatt = adapter.getRemoteDevice(address).connectGatt(context, false, new BluetoothGattCallback() {
            @Override public void onConnectionStateChange(BluetoothGatt g, int status, int state) {
                if (status == BluetoothGatt.GATT_SUCCESS && state == BluetoothProfile.STATE_CONNECTED) operations.offer(0);
                else if (state == BluetoothProfile.STATE_DISCONNECTED || status != 0) {
                    disconnected = true;
                    operations.offer(-1);
                    notifications.offer(new byte[0]);
                }
            }
            @Override public void onMtuChanged(BluetoothGatt g, int mtu, int status) { operations.offer(status == 0 && mtu >= 23 ? 0 : -1); }
            @Override public void onServicesDiscovered(BluetoothGatt g, int status) { operations.offer(status); }
            @Override public void onDescriptorWrite(BluetoothGatt g, BluetoothGattDescriptor d, int status) { operations.offer(status); }
            @Override public void onCharacteristicWrite(BluetoothGatt g, BluetoothGattCharacteristic c, int status) { operations.offer(status); }
            @Override public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c) { notifications.offer(c.getValue().clone()); }
            @Override public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c, byte[] value) { notifications.offer(value.clone()); }
        }, BluetoothDevice.TRANSPORT_LE);
        try {
            if (gatt == null) throw new IllegalStateException("Could not create GATT connection");
            awaitOperation();
            // Preserve the desktop setup: Sony reply handling uses negotiated MTU state.
            if (!gatt.requestMtu(256)) throw new IllegalStateException("MTU request rejected");
            awaitOperation();
            if (!gatt.discoverServices()) throw new IllegalStateException("Service discovery rejected");
            awaitOperation();
            BluetoothGattService service = gatt.getService(uuid("dc405470-a351-4a59-97d8-2e2e3b207fbb"));
            if (service == null) throw new IllegalStateException("Sony RACE service not found. Check BLE address.");
            tx = service.getCharacteristic(uuid("bfd869fa-a3f2-4c2f-bcff-3eb1ec80cead"));
            BluetoothGattCharacteristic rx = service.getCharacteristic(uuid("2a6b6575-faf6-418c-923f-ccd63a56d955"));
            if (tx == null || rx == null || (tx.getProperties() & BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE) == 0)
                throw new IllegalStateException("RACE characteristics unavailable");
            if (!gatt.setCharacteristicNotification(rx, true)) throw new IllegalStateException("Cannot enable notifications");
            BluetoothGattDescriptor cccd = rx.getDescriptor(uuid("00002902-0000-1000-8000-00805f9b34fb"));
            if (cccd == null) throw new IllegalStateException("Missing notification descriptor");
            cccd.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
            if (!gatt.writeDescriptor(cccd)) throw new IllegalStateException("Notification subscription rejected");
            awaitOperation();
            // Requests are serialized; every write also requires its RACE acknowledgement.
        } catch (Exception e) { close(); throw e; }
    }
    private void awaitOperation() throws Exception {
        Integer status = operations.poll(15, TimeUnit.SECONDS);
        if (status == null || status != 0 || disconnected) throw new IllegalStateException("Bluetooth operation failed or timed out: " + status);
    }
    private byte[] exchange(int command, int address, Integer value) throws Exception {
        if (disconnected) throw new IllegalStateException("Headset disconnected");
        if (!notifications.isEmpty()) throw new IllegalStateException("Unexpected pending RACE data");
        tx.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE);
        tx.setValue(RaceProtocol.request(command, address, value));
        if (!gatt.writeCharacteristic(tx)) throw new IllegalStateException("RACE write rejected");
        awaitOperation();
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(8);
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        while (true) {
            long left = deadline - System.nanoTime();
            byte[] part = left > 0 ? notifications.poll(left, TimeUnit.NANOSECONDS) : null;
            if (part == null || disconnected) throw new IllegalStateException("RACE reply timed out or disconnected");
            bytes.write(part);
            byte[] frame = bytes.toByteArray();
            if (frame.length >= 6) {
                int length = Short.toUnsignedInt(RaceProtocol.buffer(frame).getShort(2)) + 4;
                if (length > 256 || length < 6 || frame.length > length) throw new IllegalStateException("Invalid RACE frame size");
                if (frame.length == length) return RaceProtocol.payload(frame, command);
            }
        }
    }
    @Override public int read(int address) throws Exception {
        return RaceProtocol.readReply(exchange(0x1680, address, null), address);
    }
    @Override public void write(int address, int value) throws Exception {
        byte[] reply = exchange(0x1681, address, value);
        if (reply.length != 1 || reply[0] != 0) throw new IllegalStateException("RACE write not acknowledged");
    }
    @Override public void close() {
        if (gatt != null) { gatt.disconnect(); gatt.close(); }
    }
}
