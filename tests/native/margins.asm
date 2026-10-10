#import "../../native/m2_abi.inc"
* = $1800 "Optional phase lifecycle module under test"
#import "../../native/margins.asm"
.const TEST_REPORT = $03e0
.macro MarginAssertA(value, failure) {
    cmp #value
    beq !+
    lda #failure
    jmp test_failed
!:
}
.macro MarginAccept(failure) {
    bcc !+
    lda #failure
    jmp test_failed
!:
}
.macro MarginReject(failure) {
    bcs !+
    lda #failure
    jmp test_failed
!:
}
* = $1200 "Prepared-phase independent native lifecycle test"
test_start:
    sei
    cld
    ldx #$ff
    txs
    lda #$35
    sta $01
    lda #0
    sta $d01a
    lda #$7f
    sta $dc0d
    sta $dd0d
    lda $dc0d
    lda $dd0d
    jsr margin_reset
    lda #2
    sta VM_SLOT
    lda #$34
    sta VM_PID
    lda #$12
    sta VM_PID+1
    lda #$ef
    sta VM_GENERATION
    lda #$be
    sta VM_GENERATION+1
    lda #0
    jsr margin_prepare_begin
    MarginReject(1)
    lda margin_state
    MarginAssertA(MARGIN_IDLE, 2)
    lda #3
    jsr margin_prepare_begin
    MarginAccept(3)
    lda margin_state
    MarginAssertA(MARGIN_DRAFT, 4)
    lda margin_owner
    MarginAssertA(2, 5)
    lda margin_generation+1
    MarginAssertA($be, 6)
    lda margin_pid
    MarginAssertA($34, 7)
    lda #$a5
    sta margin_input_a
    lda #$3c
    sta margin_input_b
    jsr margin_claim_outside
    MarginReject(8)
    lda margin_completions
    MarginAssertA(0, 9)
    inc margin_bound
    jsr margin_publish
    MarginReject(10)
    lda margin_state
    MarginAssertA(MARGIN_DRAFT, 11)
    dec margin_bound
    jsr margin_publish
    MarginAccept(12)
    lda margin_state
    MarginAssertA(MARGIN_READY, 13)
    lda #3
    jsr margin_prepare_begin
    MarginReject(14)
    jsr margin_irq_hook
    MarginReject(15)
    lda margin_state
    MarginAssertA(MARGIN_READY, 16)
    lda margin_completions
    MarginAssertA(0, 17)
    ldx #$5a
    ldy #$a5
    jsr margin_claim_outside
    MarginAccept(18)
    txa
    MarginAssertA($5a, 63)
    tya
    MarginAssertA($a5, 64)
    tsx
    txa
    MarginAssertA($ff, 65)
    php
    pla
    and #4
    MarginAssertA(4, 66)
    lda margin_state
    MarginAssertA(MARGIN_DONE, 19)
    lda MARGIN_PRIVATE
    MarginAssertA($99, 20)
    lda margin_result
    MarginAssertA($99, 21)
    lda margin_entitlement
    MarginAssertA(2, 22)
    lda margin_useful_work
    MarginAssertA(1, 23)
    lda margin_completions
    MarginAssertA(1, 24)
    jsr margin_claim_outside
    MarginReject(25)
    lda margin_completions
    MarginAssertA(1, 26)
    jsr margin_publish
    MarginReject(27)
    jsr margin_consume
    MarginAccept(28)
    MarginAssertA($99, 29)
    lda margin_state
    MarginAssertA(MARGIN_IDLE, 30)
    lda margin_owned
    MarginAssertA(0, 31)
    jsr margin_consume
    MarginReject(32)

    lda #1
    jsr margin_prepare_begin
    MarginAccept(33)
    inc margin_generation
    jsr margin_publish
    MarginReject(34)
    dec margin_generation
    jsr margin_publish
    MarginAccept(35)
    inc margin_live_generation
    jsr margin_claim_outside
    MarginReject(36)
    lda margin_state
    MarginAssertA(MARGIN_CANCELLED, 37)
    lda margin_completions
    MarginAssertA(1, 38)
    lda MARGIN_PRIVATE
    MarginAssertA($99, 39)
    jsr margin_discard_cancelled
    MarginAccept(40)

    lda #1
    jsr margin_prepare_begin
    MarginAccept(41)
    jsr margin_publish
    MarginAccept(42)
    ldx #1
    jsr margin_revoke_owner
    MarginReject(43)
    lda margin_state
    MarginAssertA(MARGIN_READY, 44)
    ldx #2
    jsr margin_revoke_owner
    MarginAccept(45)
    jsr margin_claim_outside
    MarginReject(46)
    lda margin_completions
    MarginAssertA(1, 47)
    jsr margin_discard_cancelled
    MarginAccept(48)

    lda #2
    jsr margin_prepare_begin
    MarginAccept(49)
    jsr margin_publish
    MarginAccept(50)
    lda #MARGIN_RUNNING
    sta margin_state
    ldx #2
    jsr margin_revoke_owner
    MarginReject(51)
    lda margin_state
    MarginAssertA(MARGIN_RUNNING, 52)
    jsr margin_claim_outside
    MarginReject(53)
    lda #MARGIN_READY
    sta margin_state
    jsr margin_claim_outside
    MarginAccept(54)
    inc margin_live_pid
    jsr margin_consume
    MarginReject(55)
    lda margin_state
    MarginAssertA(MARGIN_CANCELLED, 56)
    lda margin_completions
    MarginAssertA(2, 57)
    jsr margin_discard_cancelled
    MarginAccept(58)

    lda #1
    jsr margin_prepare_begin
    MarginAccept(59)
    inc margin_routine
    jsr margin_publish
    MarginReject(60)
    ldx #2
    jsr margin_revoke_owner
    MarginAccept(61)
    jsr margin_discard_cancelled
    MarginAccept(62)
    lda #0
    sta TEST_REPORT+4
    lda #66
    sta TEST_REPORT+5
    jmp test_done
test_failed:
    sta TEST_REPORT+4
    lda #0
    sta TEST_REPORT+5
test_done:
    lda #$4d
    sta TEST_REPORT
    sta TEST_REPORT+1
    lda #$32
    sta TEST_REPORT+2
    lda #1
    sta TEST_REPORT+3
test_stop:
    jmp test_stop
test_code_end:
.assert "test code avoids module", test_code_end <= $1800, true
