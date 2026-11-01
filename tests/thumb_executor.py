"""Mock executor for the actual Thumb instructions in the 120-byte payload.

External setter calls are mocked; this is not a hardware or full ARM emulator.
"""
import struct
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_OP_REG, CS_OP_IMM, CS_OP_MEM
from capstone.arm import ARM_CC_EQ, ARM_CC_NE

BASE = 0x10060000  # Simulation only; not an installation address.
DISABLED = 0x10074971
ORIGINAL = 0x08263BB5
RETURN = 0x081DCCCB


class Thumb:
    def __init__(self, blob):
        self.argument_count = 2
        self.mem = {BASE + i: byte for i, byte in enumerate(blob)}
        self.mem[DISABLED] = 0
        self.setter_calls = []
        self.forwarded = []
        self.decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
        self.decoder.detail = True

    def read(self, address, size=4):
        return int.from_bytes(bytes(self.mem.get(address + i, 0) for i in range(size)), "little")

    def word(self, address, value):
        for i, byte in enumerate(struct.pack("<I", value & 0xffffffff)):
            self.mem[address + i] = byte

    def invoke(self, event, parent_return):
        self.r = {f"r{i}": 0xA000 + i for i in range(13)}
        self.r.update(r0=event, r1=0x12345678, sp=0x20001000, lr=RETURN, pc=BASE)
        original_args = [self.r[f"r{i}"] for i in range(4)]
        original_r4 = self.r["r4"]
        self.word(self.r["sp"] + 28, parent_return)
        zero = False
        it_conditions = []
        def name(reg):
            return {"ip": "r12", "sb": "r9", "sl": "r10", "fp": "r11"}.get(ins.reg_name(reg), ins.reg_name(reg))
        for _ in range(200):
            pc = self.r["pc"]
            ins = next(self.decoder.disasm(bytes(self.mem.get(pc+i, 0) for i in range(4)), pc, count=1))
            self.r["pc"] += ins.size
            ops = ins.operands
            if ins.mnemonic == "ite":
                it_conditions = [zero, not zero]
                continue
            in_it = bool(it_conditions)
            if in_it and not it_conditions.pop(0):
                continue
            if (ins.cc == ARM_CC_EQ and not zero) or (ins.cc == ARM_CC_NE and zero):
                continue
            def val(op):
                if op.type == CS_OP_REG:
                    return self.r[name(op.reg)]
                if op.type == CS_OP_IMM:
                    return op.imm
                raise AssertionError("Unexpected operand")
            def address(op):
                assert op.type == CS_OP_MEM
                reg = name(op.mem.base)
                origin = ((pc+4) & ~3) if reg == "pc" else self.r[reg]
                return origin + op.mem.disp
            mnemonic = ins.mnemonic.replace(".w", "")
            if mnemonic == "push":
                self.r["sp"] -= 4 * len(ops)
                for i, op in enumerate(ops): self.word(self.r["sp"] + i*4, val(op))
            elif mnemonic == "pop":
                for i, op in enumerate(ops): self.r[name(op.reg)] = self.read(self.r["sp"] + i*4)
                self.r["sp"] += 4 * len(ops)
            elif mnemonic == "adr":
                self.r[name(ops[0].reg)] = ((pc+4) & ~3) + ops[1].imm
            elif mnemonic in ("ldr", "ldrb"):
                self.r[name(ops[0].reg)] = self.read(address(ops[1]), 1 if mnemonic == "ldrb" else 4)
            elif mnemonic == "str": self.word(address(ops[1]), val(ops[0]))
            elif mnemonic == "cmp": zero = val(ops[0]) == val(ops[1])
            elif mnemonic == "subs":
                result = (val(ops[1]) - val(ops[2])) & 0xffffffff
                self.r[name(ops[0].reg)] = result
                zero = result == 0
            elif mnemonic == "bic":
                self.r[name(ops[0].reg)] = val(ops[1]) & ~val(ops[2]) & 0xffffffff
            elif mnemonic == "clz":
                self.r[name(ops[0].reg)] = 32 - val(ops[1]).bit_length()
            elif mnemonic == "lsrs":
                self.r[name(ops[0].reg)] = val(ops[1]) >> val(ops[2])
                zero = self.r[name(ops[0].reg)] == 0
            elif mnemonic in ("movs", "moveq", "movne", "mov"):
                self.r[name(ops[0].reg)] = val(ops[1])
                if mnemonic == "movs" and not in_it: zero = val(ops[1]) == 0
            elif mnemonic in ("adds", "add"):
                reg = name(ops[0].reg)
                self.r[reg] = (self.r[reg] + val(ops[1])) & 0xffffffff
                if mnemonic == "adds": zero = self.r[reg] == 0
            elif mnemonic in ("ite", "it"): pass
            elif mnemonic.startswith("b") and mnemonic not in ("blx", "bx"):
                self.r["pc"] = val(ops[0])
            elif mnemonic in ("cbz", "cbnz"):
                if (val(ops[0]) == 0) == (mnemonic == "cbz"):
                    self.r["pc"] = val(ops[1])
            elif mnemonic == "blx":
                assert val(ops[0]) == 0x0823C6AD
                assert self.r["sp"] % 8 == 0
                self.setter_calls.append(self.r["r0"])
                self.mem[DISABLED] = self.r["r0"]
                # The real callee may clobber all caller-saved arguments.
                self.r.update(r0=0xdead, r1=0xbeef, r2=0xface, r3=0xabcd, lr=(pc+ins.size)|1)
            elif mnemonic == "bx":
                target = val(ops[0])
                if target == ORIGINAL:
                    assert [self.r[f"r{i}"] for i in range(self.argument_count)] == original_args[:self.argument_count]
                    self.forwarded.append(event)
                else:
                    assert target == RETURN
                    assert self.r["r0"] == 0
                assert self.r["r4"] == original_r4
                assert self.r["sp"] == 0x20001000
                return
            else: raise AssertionError(f"Unsupported instruction {ins.mnemonic} {ins.op_str}")
        raise AssertionError("Stub did not return")
