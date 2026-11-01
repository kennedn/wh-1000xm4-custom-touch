/* XM4 2.5.0 hook with latch.
 * Callback ABI: r0=event, r1=custom data; r2/r3 are caller-saved scratch.
 */
.syntax unified
.cpu cortex-m4
.thumb
.section .text
.global hook
.thumb_func
hook:
    ldr r2, [sp, #28]
    ldr r3, press_return
    subs r2, r2, r3
    beq press_four
    cmp r2, #0x18
    beq press_43
    cmp r2, #0x30
    beq consume
    ldr r2, [sp, #28]
    ldr r3, prelude_return
    subs r2, r2, r3
    bic r2, r2, #0x20     /* exact prelude offsets: 0, 0x0e, 0x20, 0x2e */
    cbz r2, consume
    cmp r2, #0x0e
    beq consume
forward:
    ldr r3, original
    bx r3
press_four:
    cmp r0, #4
    bne forward
    b toggle
press_43:
    cmp r0, #0x43
    bne forward
toggle:
    adr r3, latch
    ldr r2, [r3]
    cbnz r2, success
    movs r2, #1
    str r2, [r3]
    ldr r3, touch_disabled
    ldrb r0, [r3]
    clz r0, r0
    lsrs r0, r0, #5        /* !disabled: CLZ(0)=32; CLZ(byte!=0)<32 */
    push {r4, lr}         /* preserve return and 8-byte stack alignment */
    ldr r3, touch_setter
    blx r3
    pop {r4, lr}
    b success
consume:
    cmp r0, #8
    beq release
    cmp r0, #0x80
    bne success
release:
    adr r3, latch
    movs r2, #0
    str r2, [r3]
success:
    movs r0, #0
    bx lr
.balign 4
press_return:   .word 0x08257957
prelude_return: .word 0x0825608f
original:      .word 0x08263bb5
touch_disabled:.word 0x10074971
touch_setter:  .word 0x0823c6ad
latch:         .word 0
