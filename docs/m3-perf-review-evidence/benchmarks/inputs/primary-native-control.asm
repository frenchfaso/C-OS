// Independent native PAL1MHz baseline; same16x12/limit16/signedQ8.8 profile.
// Native16x16 shift/add multiplication keeps full32-bit product and floor>>8.
// No REU accesses, no turbo acceleration, no UPIC presentation.
* = $0801 "BASIC"
    .word basic_end
    .word 10
    .byte $9e
    .text "2061"
    .byte 0
basic_end:
    .word 0
.label cx = $02
.label cy = $04
.label zx = $06
.label zy = $08
.label xx = $0a
.label yy = $0c
.label left = $0e
.label right = $10
.label product = $12
.label multiplicand = $16
.label negative = $1a
.label xpos = $1b
.label ypos = $1c
.label iteration = $1d
.label output_ptr = $1e
.label elapsed = $0304
.const WIDTH = 16
.const HEIGHT = 12
.const LIMIT = 16
* = $080d "Baseline program"
entry:
    sei
    cld
    ldx #$ff
    txs
    lda #$35
    sta $01
    lda #$2f
    sta $00
    lda #$80
    sta $d031
    lda #0
    sta $d030
    sta $d011
    sta $d01a
    sta $d015
    sta $0300
    lda #$7f
    sta $dc0d
    sta $dd0d
    lda $dc0d
    lda $dd0d
    jsr speed_probe
    stx $0301
    sta $0302
    lda #0
    sta $dd0e
    sta $dd0f
    lda #$ff
    sta $dd04
    sta $dd05
    sta $dd06
    sta $dd07
    lda #$50 // B counts A underflows, force load, not yet started.
    sta $dd0f
    lda #$10 // A PHI2 mode, force load, not yet started.
    sta $dd0e
    lda #$41
    sta $dd0f
    lda #<output
    sta output_ptr
    lda #>output
    sta output_ptr+1
    // All timed work, including coordinate/loop initialization, begins here.
    lda #$01
    sta $dd0e
    jsr compute
    // Stop A before reading the cascade. B now has no further clock source.
    lda #0
    sta $dd0e
    sta $dd0f
    // Elapsed from loaded $ffffffff is the bitwise complement of remaining.
    lda $dd04
    eor #$ff
    sta elapsed
    lda $dd05
    eor #$ff
    sta elapsed+1
    lda $dd06
    eor #$ff
    sta elapsed+2
    lda $dd07
    eor #$ff
    sta elapsed+3
    lda #$55
    sta $0300
done:
    jmp done
compute:
    lda #$80
    sta cy
    lda #$fe // -384
    sta cy+1
    lda #0
    sta ypos
next_row:
    lda #0
    sta cx
    sta xpos
    lda #$fe // -512
    sta cx+1
next_pixel:
    lda #0
    sta zx
    sta zx+1
    sta zy
    sta zy+1
    sta iteration
iterate:
    lda zx
    sta left
    sta right
    lda zx+1
    sta left+1
    sta right+1
    jsr multiply
    lda product+1
    sta xx
    lda product+2
    sta xx+1
    lda zy
    sta left
    sta right
    lda zy+1
    sta left+1
    sta right+1
    jsr multiply
    lda product+1
    sta yy
    lda product+2
    sta yy+1
    clc
    lda xx
    adc yy
    lda xx+1
    adc yy+1
    cmp #4
    bcs write_pixel
    lda zx
    sta left
    lda zx+1
    sta left+1
    lda zy
    sta right
    lda zy+1
    sta right+1
    jsr multiply
    asl product+1
    rol product+2
    clc
    lda product+1
    adc cy
    sta zy
    lda product+2
    adc cy+1
    sta zy+1
    sec
    lda xx
    sbc yy
    sta zx
    lda xx+1
    sbc yy+1
    sta zx+1
    clc
    lda zx
    adc cx
    sta zx
    lda zx+1
    adc cx+1
    sta zx+1
    inc iteration
    lda iteration
    cmp #LIMIT
    beq write_pixel
    jmp iterate
write_pixel:
    lda iteration
    ldy #0
    sta (output_ptr),y
    inc output_ptr
    bne !+
    inc output_ptr+1
!:
    clc
    lda cx
    adc #64
    sta cx
    bcc !+
    inc cx+1
!:
    inc xpos
    lda xpos
    cmp #WIDTH
    beq row_done
    jmp next_pixel
row_done:
    clc
    lda cy
    adc #64
    sta cy
    bcc !+
    inc cy+1
!:
    inc ypos
    lda ypos
    cmp #HEIGHT
    beq compute_done
    jmp next_row
compute_done:
    rts
// Both inputs signed16. product is signed32; bytes1/2 give floor>>8.
multiply:
    // Review control: same general combined product algorithm as ABI2 MULS.
    // Original inputs remain intact; caller still reads full product bytes1/2.
    lda right
    sta product
    lda right+1
    sta product+1
    lda #0
    sta product+2
    sta product+3
    ldx #16
review_multiply_bit:
    lda product
    lsr
    bcc review_multiply_shift
    clc
    lda product+2
    adc left
    sta product+2
    lda product+3
    adc left+1
    sta product+3
review_multiply_shift:
    ror product+3
    ror product+2
    ror product+1
    ror product
    dex
    bne review_multiply_bit
    lda left+1
    bpl review_multiply_right_sign
    sec
    lda product+2
    sbc right
    sta product+2
    lda product+3
    sbc right+1
    sta product+3
review_multiply_right_sign:
    lda right+1
    bpl review_multiply_done
    sec
    lda product+2
    sbc left
    sta product+2
    lda product+3
    sbc left+1
    sta product+3
review_multiply_done:
    rts

program_end:
.label speed_high = $22
speed_probe:
    bit $d011
    bmi speed_probe
    lda $d012
    cmp #10
    bne speed_probe
    ldx #0
    stx speed_high
speed_wait:
    lda $d012
    cmp #11
    bne speed_wait
speed_work:
    .for (var i=0;i<16;i++) {
        inx
        bne !+
        inc speed_high
    !:
    }
    lda $d012
    cmp #11
    beq speed_work
    lda speed_high
    rts
baseline_end:
.assert "Baseline code fits classic RAM below$2000", baseline_end<$2000, true
* = $6000 "Computed iteration image"
output:
    .fill WIDTH*HEIGHT,0
