package com.kennedn.xm4touch;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;

public final class CoreTest {
    static final class Memory implements PatchInstaller.Memory {
        final Map<Integer, Integer> values = new HashMap<>(Map.of(
            0x10068b10, PatchInstaller.TABLE, PatchInstaller.TABLE, PatchInstaller.ORIGINAL,
            0x081dccb4, 0x4b12b57f, 0x0823c6ac, 0x4b0cb537,
            0x100068a4, 0x100668a8, 0x100668a8, 0, 0x100668ac, 0));
        final List<Integer> writes = new ArrayList<>();
        int fail = -1;
        boolean failAttach;
        @Override public int read(int a) { return values.getOrDefault(a, 0); }
        @Override public void write(int a, int v) {
            writes.add(a);
            if (a == fail) throw new IllegalStateException("Injected upload failure");
            values.put(a, v);
            if (failAttach && a == PatchInstaller.TABLE && v != PatchInstaller.ORIGINAL)
                throw new IllegalStateException("Lost attachment ACK");
        }
    }
    interface Checked { void run() throws Exception; }
    static void check(boolean value) { if (!value) throw new AssertionError(); }
    static void fails(Checked action) throws Exception {
        try { action.run(); } catch (IllegalStateException | IllegalArgumentException expected) { return; }
        throw new AssertionError("Expected failure");
    }
    public static void main(String[] args) throws Exception {
        check(DeviceMatch.sonyAudioAddress("80:99:E7:12:34:56"));
        check(DeviceMatch.sonyAudioAddress("80:99:e7:12:34:56"));
        check(!DeviceMatch.sonyAudioAddress("80:99:E8:12:34:56"));
        check(!DeviceMatch.sonyAudioAddress("C0:2E:A7:E9:FF:00"));
        check(!DeviceMatch.sonyAudioAddress(null));
        check(DeviceMatch.xm4Name("LE_WH-1000XM4"));
        check(DeviceMatch.xm4Name("wh-1000xm4"));
        check(!DeviceMatch.xm4Name("WH-1000XM3"));
        check(!DeviceMatch.xm4Name(null));
        byte[] blob = Files.readAllBytes(Path.of(args[0]));
        Memory ok = new Memory();
        check(PatchInstaller.install(ok, blob).startsWith("Patch installed"));
        check(ok.writes.size() == 31 && ok.writes.get(30) == PatchInstaller.TABLE);
        ok.writes.clear();
        ok.values.put(PatchInstaller.SCRATCH + 116, 1);
        check(PatchInstaller.install(ok, blob).equals("Patch already active"));
        check(ok.writes.isEmpty() && ok.read(PatchInstaller.SCRATCH + 116) == 1);
        ok.values.put(PatchInstaller.SCRATCH, 0);
        fails(() -> PatchInstaller.install(ok, blob)); check(ok.writes.isEmpty());
        Memory mismatch = new Memory(); mismatch.values.put(0x081dccb4, 0);
        fails(() -> PatchInstaller.install(mismatch, blob)); check(mismatch.writes.isEmpty());
        Memory unknown = new Memory(); unknown.values.put(PatchInstaller.TABLE, 123);
        fails(() -> PatchInstaller.install(unknown, blob)); check(unknown.writes.isEmpty());
        Memory invalid = new Memory(); byte[] changed = blob.clone(); changed[0] ^= 1;
        fails(() -> PatchInstaller.install(invalid, changed)); check(invalid.writes.isEmpty());
        Memory upload = new Memory(); upload.fail = PatchInstaller.SCRATCH + 8;
        fails(() -> PatchInstaller.install(upload, blob)); check(upload.read(PatchInstaller.TABLE) == PatchInstaller.ORIGINAL);
        Memory attach = new Memory(); attach.failAttach = true;
        fails(() -> PatchInstaller.install(attach, blob)); check(attach.read(PatchInstaller.TABLE) == PatchInstaller.ORIGINAL);
        check(Arrays.equals(RaceProtocol.request(0x1680, 0x10003d38, null),
            new byte[] {5, 0x5a, 8, 0, (byte)0x80, 0x16, 0, 0, 0x38, 0x3d, 0, 0x10}));
        byte[] write = RaceProtocol.request(0x1681, PatchInstaller.SCRATCH, 0x12345678);
        check(write.length == 16 && write[2] == 12 && write[12] == 0x78 && write[15] == 0x12);
        fails(() -> RaceProtocol.request(0x1681, 0x08000000, 0));
        byte[] read = {5, 0x5b, 13, 0, (byte)0x80, 0x16, 0, 0, 0, 0x38, 0x3d, 0, 0x10, 0x78, 0x56, 0x34, 0x12};
        check(RaceProtocol.readReply(RaceProtocol.payload(read, 0x1680), 0x10003d38) == 0x12345678);
        fails(() -> RaceProtocol.readReply(RaceProtocol.payload(read, 0x1680), 0x10003d3c));
        fails(() -> RaceProtocol.payload(read, 0x1681));
        System.out.println("Core checks passed: installation, existing latch, mismatches, rollback, RACE encoding/replies.");
    }
}
