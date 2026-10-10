#import "hardware.inc"
// 160 pairs, with one shortened pair in each eight-pair group. At 63
// delivered turbo slots per PHI2, 126 CPU cycles span exactly 16 dots.
* = $f000 "320-pixel scanout"
renderer_start:
irq:
    pha
    txa
    pha
    tya
    pha
    lda #1
    sta $d019
    .if (EXTENDED_DIAGNOSTICS != 0) {
    // Sample actual stack depth; render_line's unconditional JSR adds two.
    tsx
    txa
    eor #$ff
    clc
    adc #2
    cmp REPORT+$1c
    bcc !+
    sta REPORT+$1c
!:
    }
    .if (M3_BUILD != 0) {
        // One period tick before synchronization; pixel code remains unchanged.
        inc $fe00
        bne !+
        inc $fe01
        bne !+
        inc $fe02
        bne !+
        inc $fe03
    !:
    }
    bit $d011
    bmi missed
    lda $d012
    cmp #FIRST_LINE
    bcs missed
    ldx #FIRST_LINE-1
top_wait:
    cpx $d012
    bne top_wait
    ldy #0
next_line:
    lda $d012
line_wait:
    cmp $d012
    beq line_wait
    lda #$80
    ldx #$8f
    sta $d031
    stx $d031
    jsr render_line
    iny
    cpy #HEIGHT
    bne next_line
    inc REPORT+$10
    bne restore
    inc REPORT+$11
restore:
    pla
    tay
    pla
    tax
    pla
    rti
missed:
    inc REPORT+$12
    bne restore
    inc REPORT+$13
    jmp restore
nmi:
    pha
    lda #1
    sta nmi_pending
    inc REPORT+$14
    bne nmi_done
    inc REPORT+$15
nmi_done:
    pla
    rti

.align $100
render_line:
patch_start:
    .for (var c=0; c<160; c+=8) {
        .var base = c<144 ? $4000+c*256 : $e000+(c-144)*256
        lda base,y
        sta pixel_stream+(12*c-c/8)+1
    }
patch_end:
    ldx #LINE_DELAY
delay:
    dex
    bne delay
pixel_stream:
    .for (var c=0; c<160; c++) {
        .if ((c & 7)==0) {
            ldx #0
        } else {
            .var base = c<144 ? $4000+c*256 : $e000+(c-144)*256
            ldx base,y
        }
        stx $d020
        lda NYBBLES,x
        sta $d020
    }
pixel_stream_end:
    // Four cycles keep the final high-nibble pixel visible for a full dot.
    nop
    nop
    lda #0
    sta $d020
    .if (MARGIN_ENABLED != 0) {
        jsr MARGIN_ENTRY
    }
    rts
renderer_end:
.assert "renderer fits $f000-$f9ff", renderer_end <= $fa00, true
.assert "20 immediate preparations", patch_end-patch_start, 120
.assert "160 pairs only", pixel_stream_end-pixel_stream, 1900
