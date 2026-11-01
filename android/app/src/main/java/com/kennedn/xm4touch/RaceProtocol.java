package com.kennedn.xm4touch;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Arrays;

final class RaceProtocol {
    static ByteBuffer buffer(byte[] bytes) { return ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN); }
    static byte[] request(int command, int address, Integer value) {
        if ((address & 3) != 0) throw new IllegalArgumentException("Unaligned address");
        if (value != null && (address < 0x10000000 || address > 0x1007fffc))
            throw new IllegalArgumentException("Write outside SRAM");
        ByteBuffer packet = ByteBuffer.allocate(value == null ? 12 : 16).order(ByteOrder.LITTLE_ENDIAN);
        packet.put((byte)5).put((byte)0x5a).putShort((short)(packet.capacity() - 4)).putShort((short)command);
        packet.putShort((short)0).putInt(address);
        if (value != null) packet.putInt(value);
        return packet.array();
    }
    static byte[] payload(byte[] frame, int command) {
        ByteBuffer b = buffer(frame);
        if (frame.length < 6 || b.get(0) != 5 || b.get(1) != 0x5b ||
                Short.toUnsignedInt(b.getShort(4)) != command || Short.toUnsignedInt(b.getShort(2)) + 4 != frame.length)
            throw new IllegalStateException("Unexpected RACE response");
        return Arrays.copyOfRange(frame, 6, frame.length);
    }
    static int readReply(byte[] reply, int address) {
        if (reply.length != 11 || reply[0] != 0 || buffer(reply).getShort(1) != 0 || buffer(reply).getInt(3) != address)
            throw new IllegalStateException("Invalid RACE read reply");
        return buffer(reply).getInt(7);
    }
}
