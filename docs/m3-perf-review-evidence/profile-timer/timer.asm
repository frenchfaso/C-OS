* = $080d
entry:
    sei
    cld
    ldx #$ff
    txs
    lda #$35
    sta $01
    lda #$7f
    sta $dc0d
    sta $dd0d
    lda $dc0d
    lda $dd0d
    lda #0
    sta $d011
    sta $d020
    sta $d030
    lda #$8f
    sta $d031
    jsr profile_init
    lda #0
    sta $40
    sta $41
loop:
    jsr profile_wrap_0
    inc $40
    bne loop
    inc $41
    bne loop
    lda #127
    sta $fc30
force_wrap_wait:
    lda $dd05
    bne force_wrap_wait
    lda $dd04
    cmp #16
    bcs force_wrap_wait
    jsr profile_wrap_0
    lda #$a5
    ldx #$33
    ldy #$66
    lda #$a5
    sec
    php
    pla
    sta $310
    lda #$a5
    jsr profile_wrap_0
    sta $301
    stx $302
    sty $303
    php
    pla
    sta $311
    lda #127
    sta $fc30
    lda #$a5
    ldx #$33
    ldy #$66
    lda #$a5
    sec
    php
    pla
    sta $312
    lda #$a5
    jsr profile_wrap_0
    sta $304
    stx $305
    sty $306
    php
    pla
    sta $313
    lda #$55
    sta $300
finished:
    jmp finished
cache_fetch_code:
vm_check_pc:
vm_decode_operands:
vm_preflight:
vm_execute:
cache_unpin:
cache_read_prepared:
cache_write_prepared:
scheduler_tick:
scheduler_native_phase:
cache_service:
vm_video_admit:
vm_dma_admit:
jobs_accept:
    rts
vm_step:
    .for (var i=0;i<512;i++) { nop }
    rts
#importonce
// Generated diagnostics only. Font reservation $fa00..$fc3f is private.
.const PROFILE_NOW = $fc00
.const PROFILE_DELTA = $fc04
.const PROFILE_INDEX = $fc08
.const PROFILE_FLAGS = $fc09
.const PROFILE_CAL_LEFT = $fc0a
.const PROFILE_OVERFLOW = $fc22
.const PROFILE_INTERVAL_WRAPS = $fc24
.const PROFILE_SAMPLE = $fc30
profile_init:
    lda #0
    ldx #0
!:
    sta $fa00,x
    sta $fb00,x
    dex
    bne !-
    ldx #$3f
!:
    sta $fc00,x
    dex
    bpl !-
    lda #$ff
    ldx #0
!:
    .for (var i=0;i<4;i++) { sta $fa08+i,x }
    txa
    clc
    adc #16
    tax
    lda #$ff
    cpx #0
    bne !-
    // Disable CIA2 NMI sources; the interval timer never interrupts.
    lda #$7f
    sta $dd0d
    lda $dd0d
    lda #$10
    sta $dd0e
    lda #$10
    sta $dd0f
    lda #$ff
    sta $dd04
    sta $dd05
    sta $dd06
    sta $dd07
    lda #1
    sta $dd0e
profile_timer_settle:
    lda $dd04
    cmp #$f0
    bcs profile_timer_settle
    lda #0
    sta PROFILE_CAL_LEFT
profile_calibrate:
    jsr profile_wrap_15
    dec PROFILE_CAL_LEFT
    bne profile_calibrate
    rts
// A high/low/high, retrying a torn high-byte boundary. Each measured call
// must be independently bounded below 65536 PHI2, including one raster IRQ.
// A modulo-16-bit interval avoids concatenating an unsettled B cascade step.
profile_read:
profile_read_again:
    lda $dd05
    sta PROFILE_NOW+1
    lda $dd04
    sta PROFILE_NOW
    lda $dd05
    cmp PROFILE_NOW+1
    bne profile_read_again
    lda #0
    sta PROFILE_NOW+2
    sta PROFILE_NOW+3
    rts
profile_begin:
    jsr profile_read
    .for (var i=0;i<4;i++) {
        lda PROFILE_NOW+i
        sta $fb00+i,x
    }
    rts
profile_end:
    stx PROFILE_INDEX
    tsx
    lda $0106,x
    sta PROFILE_FLAGS
    ldx PROFILE_INDEX
    jsr profile_read
    sec
    .for (var i=0;i<2;i++) {
        lda $fb00+i,x
        sbc PROFILE_NOW+i
        sta PROFILE_DELTA+i
    }
    bcs !+
    inc PROFILE_INTERVAL_WRAPS
    bne !+
    inc PROFILE_INTERVAL_WRAPS+1
!:
    lda #0
    sta PROFILE_DELTA+2
    sta PROFILE_DELTA+3
    clc
    .for (var i=0;i<4;i++) {
        lda $fa00+i,x
        adc PROFILE_DELTA+i
        sta $fa00+i,x
    }
    bcc !+
    inc PROFILE_OVERFLOW
!:
    inc $fa04,x
    bne !+
    inc $fa05,x
    bne !+
    inc $fa06,x
    bne !+
    inc $fa07,x
    bne !+
    inc PROFILE_OVERFLOW
!:
    .for (var i=3;i>=0;i--) {
        lda PROFILE_DELTA+i
        cmp $fa08+i,x
        bcc profile_min_update
        bne profile_max_check
    }
profile_min_update:
    .for (var i=0;i<4;i++) {
        lda PROFILE_DELTA+i
        sta $fa08+i,x
    }
profile_max_check:
    .for (var i=3;i>=0;i--) {
        lda PROFILE_DELTA+i
        cmp $fa0c+i,x
        bcc profile_carry
        bne profile_max_update
    }
profile_max_update:
    .for (var i=0;i<4;i++) {
        lda PROFILE_DELTA+i
        sta $fa0c+i,x
    }
profile_carry:
    lda PROFILE_FLAGS
    and #1
    beq profile_end_done
    clc
    .for (var i=0;i<4;i++) {
        lda $fb04+i,x
        adc PROFILE_DELTA+i
        sta $fb04+i,x
    }
    bcc !+
    inc PROFILE_OVERFLOW
!:
    inc $fb08,x
    bne profile_end_done
    inc $fb09,x
    bne profile_end_done
    inc $fb0a,x
    bne profile_end_done
    inc $fb0b,x
    bne profile_end_done
    inc PROFILE_OVERFLOW
profile_end_done:
    rts
profile_nop:
    rts
profile_wrap_0:
    php
    pha
    txa
    pha
    ldx #0
    inc PROFILE_SAMPLE,x
    lda PROFILE_SAMPLE,x
    and #127
    beq profile_sample_0
    pla
    tax
    pla
    plp
    jsr vm_step
    rts
profile_sample_0:
    pla
    tax
    pla
    plp
    php
    pha
    txa
    pha
    tya
    pha
    ldx #0
    jsr profile_begin
    pla
    tay
    pla
    tax
    pla
    plp
    jsr vm_step
    php
    pha
    txa
    pha
    tya
    pha
    ldx #0
    jsr profile_end
    pla
    tay
    pla
    tax
    pla
    plp
    rts

profile_wrap_1:
    php
    pha
    txa
    pha
    ldx #1
    inc PROFILE_SAMPLE,x
    lda PROFILE_SAMPLE,x
    and #127
    beq profile_sample_1
    pla
    tax
    pla
    plp
    jsr cache_fetch_code
    rts
profile_sample_1:
    pla
    tax
    pla
    plp
    php
    pha
    txa
    pha
    tya
    pha
    ldx #16
    jsr profile_begin
    pla
    tay
    pla
    tax
    pla
    plp
    jsr cache_fetch_code
    php
    pha
    txa
    pha
    tya
    pha
    ldx #16
    jsr profile_end
    pla
    tay
    pla
    tax
    pla
    plp
    rts

profile_wrap_2:
    php
    pha
    txa
    pha
    ldx #2
    inc PROFILE_SAMPLE,x
    lda PROFILE_SAMPLE,x
    and #127
    beq profile_sample_2
    pla
    tax
    pla
    plp
    jsr vm_check_pc
    rts
profile_sample_2:
    pla
    tax
    pla
    plp
    php
    pha
    txa
    pha
    tya
    pha
    ldx #32
    jsr profile_begin
    pla
    tay
    pla
    tax
    pla
    plp
    jsr vm_check_pc
    php
    pha
    txa
    pha
    tya
    pha
    ldx #32
    jsr profile_end
    pla
    tay
    pla
    tax
    pla
    plp
    rts

profile_wrap_3:
    php
    pha
    txa
    pha
    ldx #3
    inc PROFILE_SAMPLE,x
    lda PROFILE_SAMPLE,x
    and #127
    beq profile_sample_3
    pla
    tax
    pla
    plp
    jsr vm_decode_operands
    rts
profile_sample_3:
    pla
    tax
    pla
    plp
    php
    pha
    txa
    pha
    tya
    pha
    ldx #48
    jsr profile_begin
    pla
    tay
    pla
    tax
    pla
    plp
    jsr vm_decode_operands
    php
    pha
    txa
    pha
    tya
    pha
    ldx #48
    jsr profile_end
    pla
    tay
    pla
    tax
    pla
    plp
    rts

profile_wrap_4:
    php
    pha
    txa
    pha
    ldx #4
    inc PROFILE_SAMPLE,x
    lda PROFILE_SAMPLE,x
    and #127
    beq profile_sample_4
    pla
    tax
    pla
    plp
    jsr vm_preflight
    rts
profile_sample_4:
    pla
    tax
    pla
    plp
    php
    pha
    txa
    pha
    tya
    pha
    ldx #64
    jsr profile_begin
    pla
    tay
    pla
    tax
    pla
    plp
    jsr vm_preflight
    php
    pha
    txa
    pha
    tya
    pha
    ldx #64
    jsr profile_end
    pla
    tay
    pla
    tax
    pla
    plp
    rts

profile_wrap_5:
    php
    pha
    txa
    pha
    ldx #5
    inc PROFILE_SAMPLE,x
    lda PROFILE_SAMPLE,x
    and #127
    beq profile_sample_5
    pla
    tax
    pla
    plp
    jsr vm_execute
    rts
profile_sample_5:
    pla
    tax
    pla
    plp
    php
    pha
    txa
    pha
    tya
    pha
    ldx #80
    jsr profile_begin
    pla
    tay
    pla
    tax
    pla
    plp
    jsr vm_execute
    php
    pha
    txa
    pha
    tya
    pha
    ldx #80
    jsr profile_end
    pla
    tay
    pla
    tax
    pla
    plp
    rts

profile_wrap_6:
    php
    pha
    txa
    pha
    ldx #6
    inc PROFILE_SAMPLE,x
    lda PROFILE_SAMPLE,x
    and #127
    beq profile_sample_6
    pla
    tax
    pla
    plp
    jsr cache_unpin
    rts
profile_sample_6:
    pla
    tax
    pla
    plp
    php
    pha
    txa
    pha
    tya
    pha
    ldx #96
    jsr profile_begin
    pla
    tay
    pla
    tax
    pla
    plp
    jsr cache_unpin
    php
    pha
    txa
    pha
    tya
    pha
    ldx #96
    jsr profile_end
    pla
    tay
    pla
    tax
    pla
    plp
    rts

profile_wrap_7:
    php
    pha
    txa
    pha
    ldx #7
    inc PROFILE_SAMPLE,x
    lda PROFILE_SAMPLE,x
    and #127
    beq profile_sample_7
    pla
    tax
    pla
    plp
    jsr cache_read_prepared
    rts
profile_sample_7:
    pla
    tax
    pla
    plp
    php
    pha
    txa
    pha
    tya
    pha
    ldx #112
    jsr profile_begin
    pla
    tay
    pla
    tax
    pla
    plp
    jsr cache_read_prepared
    php
    pha
    txa
    pha
    tya
    pha
    ldx #112
    jsr profile_end
    pla
    tay
    pla
    tax
    pla
    plp
    rts

profile_wrap_8:
    php
    pha
    txa
    pha
    ldx #8
    inc PROFILE_SAMPLE,x
    lda PROFILE_SAMPLE,x
    and #127
    beq profile_sample_8
    pla
    tax
    pla
    plp
    jsr cache_write_prepared
    rts
profile_sample_8:
    pla
    tax
    pla
    plp
    php
    pha
    txa
    pha
    tya
    pha
    ldx #128
    jsr profile_begin
    pla
    tay
    pla
    tax
    pla
    plp
    jsr cache_write_prepared
    php
    pha
    txa
    pha
    tya
    pha
    ldx #128
    jsr profile_end
    pla
    tay
    pla
    tax
    pla
    plp
    rts

profile_wrap_9:
    php
    pha
    txa
    pha
    ldx #9
    inc PROFILE_SAMPLE,x
    lda PROFILE_SAMPLE,x
    and #127
    beq profile_sample_9
    pla
    tax
    pla
    plp
    jsr scheduler_tick
    rts
profile_sample_9:
    pla
    tax
    pla
    plp
    php
    pha
    txa
    pha
    tya
    pha
    ldx #144
    jsr profile_begin
    pla
    tay
    pla
    tax
    pla
    plp
    jsr scheduler_tick
    php
    pha
    txa
    pha
    tya
    pha
    ldx #144
    jsr profile_end
    pla
    tay
    pla
    tax
    pla
    plp
    rts

profile_wrap_10:
    php
    pha
    txa
    pha
    ldx #10
    inc PROFILE_SAMPLE,x
    lda PROFILE_SAMPLE,x
    and #127
    beq profile_sample_10
    pla
    tax
    pla
    plp
    jsr scheduler_native_phase
    rts
profile_sample_10:
    pla
    tax
    pla
    plp
    php
    pha
    txa
    pha
    tya
    pha
    ldx #160
    jsr profile_begin
    pla
    tay
    pla
    tax
    pla
    plp
    jsr scheduler_native_phase
    php
    pha
    txa
    pha
    tya
    pha
    ldx #160
    jsr profile_end
    pla
    tay
    pla
    tax
    pla
    plp
    rts

profile_wrap_11:
    php
    pha
    txa
    pha
    ldx #11
    inc PROFILE_SAMPLE,x
    lda PROFILE_SAMPLE,x
    and #127
    beq profile_sample_11
    pla
    tax
    pla
    plp
    jsr cache_service
    rts
profile_sample_11:
    pla
    tax
    pla
    plp
    php
    pha
    txa
    pha
    tya
    pha
    ldx #176
    jsr profile_begin
    pla
    tay
    pla
    tax
    pla
    plp
    jsr cache_service
    php
    pha
    txa
    pha
    tya
    pha
    ldx #176
    jsr profile_end
    pla
    tay
    pla
    tax
    pla
    plp
    rts

profile_wrap_12:
    php
    pha
    txa
    pha
    ldx #12
    inc PROFILE_SAMPLE,x
    lda PROFILE_SAMPLE,x
    and #127
    beq profile_sample_12
    pla
    tax
    pla
    plp
    jsr vm_video_admit
    rts
profile_sample_12:
    pla
    tax
    pla
    plp
    php
    pha
    txa
    pha
    tya
    pha
    ldx #192
    jsr profile_begin
    pla
    tay
    pla
    tax
    pla
    plp
    jsr vm_video_admit
    php
    pha
    txa
    pha
    tya
    pha
    ldx #192
    jsr profile_end
    pla
    tay
    pla
    tax
    pla
    plp
    rts

profile_wrap_13:
    php
    pha
    txa
    pha
    ldx #13
    inc PROFILE_SAMPLE,x
    lda PROFILE_SAMPLE,x
    and #127
    beq profile_sample_13
    pla
    tax
    pla
    plp
    jsr vm_dma_admit
    rts
profile_sample_13:
    pla
    tax
    pla
    plp
    php
    pha
    txa
    pha
    tya
    pha
    ldx #208
    jsr profile_begin
    pla
    tay
    pla
    tax
    pla
    plp
    jsr vm_dma_admit
    php
    pha
    txa
    pha
    tya
    pha
    ldx #208
    jsr profile_end
    pla
    tay
    pla
    tax
    pla
    plp
    rts

profile_wrap_14:
    php
    pha
    txa
    pha
    ldx #14
    inc PROFILE_SAMPLE,x
    lda PROFILE_SAMPLE,x
    and #127
    beq profile_sample_14
    pla
    tax
    pla
    plp
    jsr jobs_accept
    rts
profile_sample_14:
    pla
    tax
    pla
    plp
    php
    pha
    txa
    pha
    tya
    pha
    ldx #224
    jsr profile_begin
    pla
    tay
    pla
    tax
    pla
    plp
    jsr jobs_accept
    php
    pha
    txa
    pha
    tya
    pha
    ldx #224
    jsr profile_end
    pla
    tay
    pla
    tax
    pla
    plp
    rts

profile_wrap_15:
    php
    pha
    txa
    pha
    tya
    pha
    ldx #240
    jsr profile_begin
    pla
    tay
    pla
    tax
    pla
    plp
    jsr profile_nop
    php
    pha
    txa
    pha
    tya
    pha
    ldx #240
    jsr profile_end
    pla
    tay
    pla
    tax
    pla
    plp
    rts
