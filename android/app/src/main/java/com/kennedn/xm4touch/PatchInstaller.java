package com.kennedn.xm4touch;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.security.MessageDigest;

/** Firmware-specific installer. Transport-independent so preflight and writes can be tested. */
final class PatchInstaller {
    static final int SCRATCH = 0x10066830, TABLE = 0x10003d38, ORIGINAL = 0x08263bb5;
    static final String SHA = "ec7550567bc9cb36bc44e6b956a6fe21e0ceb6fc6106f0cd9a2fa75e8ed7b64a";
    private static String hex(byte[] bytes) {
        StringBuilder result = new StringBuilder();
        for (byte b : bytes) result.append(String.format("%02x", b & 255));
        return result.toString();
    }
    interface Memory {
        int read(int address) throws Exception;
        void write(int address, int value) throws Exception;
    }
    private static void expect(Memory memory, int address, int expected) throws Exception {
        if (memory.read(address) != expected)
            throw new IllegalStateException(String.format("Firmware/state mismatch at %08x. No installation; reboot headset if previously patched.", address));
    }
    static String install(Memory memory, byte[] blob) throws Exception {
        if (blob.length != 120 || !hex(MessageDigest.getInstance("SHA-256").digest(blob)).equals(SHA))
            throw new IllegalArgumentException("Payload checksum mismatch");
        expect(memory, 0x10068b10, TABLE);
        expect(memory, 0x081dccb4, 0x4b12b57f);
        expect(memory, 0x0823c6ac, 0x4b0cb537);
        expect(memory, 0x100068a4, 0x100668a8);
        expect(memory, 0x100668a8, 0);
        expect(memory, 0x100668ac, 0);
        int callback = memory.read(TABLE);
        ByteBuffer words = ByteBuffer.wrap(blob).order(ByteOrder.LITTLE_ENDIAN);
        if (callback == (SCRATCH | 1)) {
            // The final word is mutable latch state. Never reset it during a held press.
            for (int i = 0; i < blob.length - 4; i += 4) expect(memory, SCRATCH + i, words.getInt(i));
            int latch = memory.read(SCRATCH + blob.length - 4);
            if (latch != 0 && latch != 1) throw new IllegalStateException("Existing patch has invalid latch; reboot headset");
            return "Patch already active";
        }
        if (callback != ORIGINAL) throw new IllegalStateException("Unknown callback; reboot headset before installing");
        try {
            for (int i = 0; i < blob.length; i += 4) {
                memory.write(SCRATCH + i, words.getInt(i));
                expect(memory, SCRATCH + i, words.getInt(i));
            }
            // Publish only after all payload words have been acknowledged and verified.
            expect(memory, TABLE, ORIGINAL);
            memory.write(TABLE, SCRATCH | 1);
            expect(memory, TABLE, SCRATCH | 1);
        } catch (Exception failure) {
            try { memory.write(TABLE, ORIGINAL); expect(memory, TABLE, ORIGINAL); }
            catch (Exception detach) {
                failure.addSuppressed(detach);
                throw new IllegalStateException("Installation failed; callback restoration unconfirmed. Reboot headset.", failure);
            }
            throw failure;
        }
        return "Patch installed. CUSTOM long-press toggles touch.";
    }
}
