#import "hardware.inc"
#import "renderer-addresses.inc"
// Ordinary PRG never spans the I/O hole. Renderer is fetched from the pack.
* = $0801 "BASIC SYS 4608"
    .word basic_end
    .word 10
    .byte $9e
    .if (M3_BUILD != 0) {
        .text "2061"
    } else {
        .text "4608"
    }
    .byte 0
basic_end:
    .word 0

* = M3_BUILD != 0 ? $080d : $1200 "Hardware probe and setup"
resident_start:
entry:
    sei
    cld
    ldx #$ff
    txs
    lda #$35
    sta $01
    lda #$2f
    sta $00
    lda #<boot_nmi
    sta $fffa
    lda #>boot_nmi
    sta $fffb
    lda #$7f
    sta $dc0d
    sta $dd0d
    lda $dc0d
    lda $dd0d
    lda #0
    sta $d01a
    sta $d011
    sta $d015
    sta nmi_pending
    ldx #0
clear_report:
    sta REPORT,x
    inx
    bne clear_report
    lda #$4d
    sta REPORT
    lda #$30
    sta REPORT+1
    lda #$52
    sta REPORT+2
    lda #$31
    sta REPORT+3
    lda $d031
    sta saved_d031
    jsr pal_probe
    bcc pal_ok
    lda #$e1
    jmp failed
pal_ok:
    lda #$80
    sta $d031
    jsr speed_probe
    stx REPORT+7
    sta REPORT+8
    lda #$8f
    sta $d031
    // Probe across 250 successive PAL frames: bounded five-second settling.
    lda #250
    sta repetitions
speed_retry:
    jsr speed_probe
    stx REPORT+9
    sta REPORT+10
    // 16 iterations cost 80 CPU cycles plus loop/raster polling overhead.
    // On the 63-slot PAL target the measured interval is 640..767 iterations.
    // 48-slot and lower profiles fall below this conservative envelope.
    cmp #2
    bne speed_not_ready
    cpx #128
    bcs speed_ok
speed_not_ready:
    dec repetitions
    bne speed_retry
    lda #$e2
    jmp failed
speed_ok:
    jsr alias_probe
    lda REPORT+$0e
    bne reu_failed
    lda REPORT+$0d
    cmp #1
    beq reu_ok
reu_failed:
    lda #$e3
    jmp failed
reu_ok:
    jsr check_pack
    bcc pack_ok
    lda #$e4
    jmp failed
pack_ok:
    jsr timings
    lda REPORT+$0e
    beq !+
    lda #$e3
    jmp failed
!:
    .if (M2_BUILD != 0) {
        jsr m2_boot_load
    }
    jsr fill_pattern
    jsr load_renderer
    ldx #0
nibble_table:
    txa
    lsr
    lsr
    lsr
    lsr
    sta NYBBLES,x
    inx
    bne nibble_table
    lda #<renderer_irq
    sta $fffe
    lda #>renderer_irq
    sta $ffff
    lda #<renderer_nmi
    sta $fffa
    lda #>renderer_nmi
    sta $fffb
    lda #0
    sta $d011
    lda #RASTER_IRQ
    sta $d012
    lda #1
    sta $d019
    sta $d01a
    sta REPORT+4
    cli
    .if (M2_BUILD != 0) {
        jmp m2_kernel_start
    }
idle:
    .if (M3_BUILD == 0) {
    // Runtime exercise: bounded FETCH then STASH of identical saved data.
    // Only the late blanking interval (280-299) is admitted. The measured
    // boot-time 128-byte maximum must be <=512 PHI2 ticks first.
    jsr admit_dma
    bcs idle
    sei
    jsr admit_dma
    bcs idle_cli
    jsr set_benchmark_address
    lda #128
    sta dma_length
    lda #0
    sta dma_length+1
    lda #$91
    sta dma_command
    jsr transfer
    lda #$90
    sta dma_command
    jsr transfer
    inc REPORT+$18
    bne runtime_check
    inc REPORT+$19
runtime_check:
    jsr raster_active
    bcc idle_cli
    inc REPORT+$1a
idle_cli:
    cli
    jmp idle
    }

failed:
    sta REPORT+4
    lda saved_d031
    sta $d031
    lda #$1b
    sta $d011
    lda #6
    sta $d020
    sta $d021
    // Native screen-code diagnostic remains readable without KERNAL calls.
    ldx #0
failure_text:
    lda failure_message,x
    sta $0400,x
    lda #1
    sta $d800,x
    inx
    cpx #failure_message_end-failure_message
    bne failure_text
    lda REPORT+4
    and #15
    ora #$30
    sta $0427
failure_loop:
    jmp failure_loop
boot_nmi:
    pha
    lda #1
    sta nmi_pending
    pla
    rti
failure_message:
    .byte 3,45,15,19,32,13,48,32,6,1,9,12,5,4,32,45,32
    .byte 19,5,5,32,18,5,16,15,18,20,32,36,48,51,48,48
    .fill 6,32
failure_message_end:

// Count the highest nine-bit raster value until the high bit falls.
pal_probe:
    bit $d011
    bpl pal_probe
    lda #0
    sta REPORT+5
pal_high:
    lda $d012
    cmp REPORT+5
    bcc pal_compare_done
    sta REPORT+5
pal_compare_done:
    bit $d011
    bmi pal_high
    inc REPORT+5
    lda #1
    sta REPORT+6
    lda REPORT+5
    cmp #56
    bne not_pal
    clc
    rts
not_pal:
    sec
    rts

// Measure executed CPU work during one complete line, not $d031 readback.
// The loop runs away from video IRQs, with VIC display disabled.
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
    .for (var i=0; i<16; i++) {
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

// Save every byte before any writes; duplicates from aliased banks therefore
// have the same saved value. Restore all 256 banks and verify every read.
alias_probe:
    jsr single_byte_address
    lda #0
    sta bank
save_banks:
    lda #$91
    sta dma_command
    jsr bank_transfer
    ldx bank
    lda BUFFER
    sta SAVED,x
    inc bank
    bne save_banks
tag_banks:
    lda bank
    sta BUFFER
    lda #$90
    sta dma_command
    jsr bank_transfer
    inc bank
    bne tag_banks
    lda #$91
    sta dma_command
    jsr bank_transfer
    lda BUFFER
    eor #$ff
    clc
    adc #1
    sta REPORT+$0c
    bne capacity_small
    inc REPORT+$0d
capacity_small:
verify_tags:
    lda #$91
    sta dma_command
    jsr bank_transfer
    lda bank
    cmp BUFFER
    beq tag_ok
    lda #1
    sta REPORT+$0f
tag_ok:
    inc bank
    bne verify_tags
restore_banks:
    ldx bank
    lda SAVED,x
    sta BUFFER
    lda #$90
    sta dma_command
    jsr bank_transfer
    inc bank
    bne restore_banks
verify_restore:
    lda #$91
    sta dma_command
    jsr bank_transfer
    ldx bank
    lda SAVED,x
    cmp BUFFER
    beq restore_ok
    lda #1
    sta REPORT+$0e
restore_ok:
    inc bank
    bne verify_restore
    lda REPORT+$0f
    beq alias_done
    lda #0
    sta REPORT+$0d
alias_done:
    rts
bank_transfer:
    lda bank
    sta dma_reu+2
    jmp transfer
single_byte_address:
    lda #<BUFFER
    sta dma_local
    lda #>BUFFER
    sta dma_local+1
    lda #$40
    sta dma_reu
    lda #0
    sta dma_reu+1
    sta dma_reu+2
    sta dma_length+1
    lda #1
    sta dma_length
    rts

check_pack:
    lda #0
    sta dma_reu
    sta dma_reu+1
    sta dma_reu+2
    lda #16
    sta dma_length
    lda #$91
    sta dma_command
    jsr transfer
    ldx #0
header_check:
    lda BUFFER,x
    cmp expected_header,x
    bne bad_pack
    inx
    cpx #16
    bne header_check
    clc
    rts
bad_pack:
    sec
    rts
expected_header:
    .text "COSREU01"
    .dword BUILD_TAG
    .word COS_APPLICATION_ABI
    .byte PACK_APP_COUNT,0

// Return raw16-bit CIA1 timer A elapsed PHI2 ticks. Both reads are live;
// retry high-low-high on rollover rather than assuming a hardware latch.
start_timer:
    lda #0
    sta $dc0e
    lda #$ff
    sta $dc04
    sta $dc05
    lda #$11
    sta $dc0e
    // FORCE LOAD takes effect on a PHI2 edge. Wait beyond that edge before
    // taking a start sample; at turbo the first read can precede the reload.
timer_settled:
    lda $dc04
    cmp #$f0
    bcs timer_settled
timer_start_sample:
    lda $dc05
    sta before_timer+1
    lda $dc04
    sta before_timer
    lda $dc05
    cmp before_timer+1
    bne timer_start_sample
    rts
end_timer:
    lda $dc05
    sta scratch_ptr+1
    lda $dc04
    sta scratch_ptr
    lda $dc05
    cmp scratch_ptr+1
    bne end_timer
    sec
    lda before_timer
    sbc scratch_ptr
    sta scratch_ptr
    lda before_timer+1
    sbc scratch_ptr+1
    sta scratch_ptr+1
    rts
set_benchmark_address:
    lda #<BUFFER
    sta dma_local
    lda #>BUFFER
    sta dma_local+1
    lda #0
    sta dma_reu
    sta dma_reu+2
    lda #$40
    sta dma_reu+1
    rts
timings:
    jsr set_benchmark_address
    lda #0
    sta dma_length
    sta dma_length+1
    lda #$91
    sta dma_command
    // Execute a software zero-length FETCH. Passing this to hardware would
    // mean 65536 bytes and overwrite the probe: boot survival tests the no-op.
    jsr transfer
    lda #1
    sta dma_length+1
    jsr transfer
    ldx #0
save_benchmark:
    lda BUFFER,x
    sta SAVED,x
    inx
    bne save_benchmark
    lda #0
    sta timer_index
timer_record:
    ldx timer_index
    lda test_lengths,x
    sta dma_length
    lda test_length_high,x
    sta dma_length+1
    lda test_commands,x
    sta dma_command
    lda #16
    sta repetitions
    txa
    asl
    asl
    tax
    lda #$ff
    sta REPORT+$20,x
    sta REPORT+$21,x
    lda #0
    sta REPORT+$22,x
    sta REPORT+$23,x
timer_repeat:
    jsr start_timer
    lda dma_command
    beq timer_baseline
    cmp #$ff
    beq timer_complete
    jsr transfer
    jmp timer_complete
timer_baseline:
    // Same driver setup, no command register store: initial setup component.
    jsr transfer_setup
timer_complete:
    jsr end_timer
    lda timer_index
    asl
    asl
    tax
    lda scratch_ptr+1
    cmp REPORT+$21,x
    bcc new_min
    bne check_max
    lda scratch_ptr
    cmp REPORT+$20,x
    bcs check_max
new_min:
    lda scratch_ptr
    sta REPORT+$20,x
    lda scratch_ptr+1
    sta REPORT+$21,x
check_max:
    lda scratch_ptr+1
    cmp REPORT+$23,x
    bcc timer_again
    bne new_max
    lda scratch_ptr
    cmp REPORT+$22,x
    bcc timer_again
new_max:
    lda scratch_ptr
    sta REPORT+$22,x
    lda scratch_ptr+1
    sta REPORT+$23,x
timer_again:
    dec repetitions
    bne timer_repeat
    inc timer_index
    lda timer_index
    cmp #12
    beq !+
    jmp timer_record
!:
    // Restore all 256 affected bytes, then check data, not only registers.
    ldx #0
restore_benchmark:
    lda SAVED,x
    sta BUFFER,x
    inx
    bne restore_benchmark
    lda #0
    sta dma_length
    lda #1
    sta dma_length+1
    lda #$90
    sta dma_command
    jsr transfer
    lda #$91
    sta dma_command
    jsr transfer
    ldx #0
check_benchmark:
    lda BUFFER,x
    cmp SAVED,x
    beq benchmark_equal
    lda #1
    sta REPORT+$0e
benchmark_equal:
    inx
    bne check_benchmark
    rts
test_lengths:
    .byte 1,1,1,16,64,128,0,1,16,64,128,0
test_length_high:
    .byte 0,0,0,0,0,0,1,0,0,0,0,1
test_commands:
    .byte 0,$ff,$91,$91,$91,$91,$91,$90,$90,$90,$90,$90

transfer:
    lda dma_length
    ora dma_length+1
    beq transfer_done
    jsr transfer_setup
    lda dma_command
    sta REU+1
transfer_done:
    rts
transfer_setup:
    .if (EXTENDED_DIAGNOSTICS != 0) {
    tsx
    txa
    eor #$ff
    cmp REPORT+$1c
    bcc !+
    sta REPORT+$1c
!:
    }
    lda dma_local
    sta REU+2
    lda dma_local+1
    sta REU+3
    lda dma_reu
    sta REU+4
    lda dma_reu+1
    sta REU+5
    lda dma_reu+2
    sta REU+6
    lda dma_length
    sta REU+7
    lda dma_length+1
    sta REU+8
    lda #0
    sta REU+9
    sta REU+10
    rts

// True geometry is generated into the specified 160 split pages.
// Borders: white top/bottom, left red/right cyan. Body: 16 bars;
// rows 80-119 alternate low=white/high=black to reveal nibble order.
fill_pattern:
    lda #0
    sta scratch_ptr
    lda #$40
    sta scratch_ptr+1
    ldx #0
fill_column:
    ldy #0
fill_row:
    lda #0
    cpy #200
    bcs pixel_ready
    txa
    // 160 pairs / 16 colors = ten pairs per bar; division by repeated
    // subtraction is initialization only, bounded by 15 iterations.
    sta row
    lda #0
bar_div:
    pha
    lda row
    cmp #10
    bcc bar_div_done
    sec
    sbc #10
    sta row
    pla
    clc
    adc #1
    jmp bar_div
bar_div_done:
    pla
    sta row
    asl
    asl
    asl
    asl
    ora row
    cpy #80
    bcc borders
    cpy #120
    bcs borders
    lda #$01
borders:
    cpx #0
    bne right_border
    and #$f0
    ora #2
right_border:
    cpx #159
    bne vertical_borders
    and #$0f
    ora #$30
vertical_borders:
    cpy #0
    beq white_edge
    cpy #199
    bne pixel_ready
white_edge:
    lda #$11
pixel_ready:
    sta (scratch_ptr),y
    iny
    bne fill_row
    inc scratch_ptr+1
    lda scratch_ptr+1
    cmp #$d0
    bne column_next
    lda #$e0
    sta scratch_ptr+1
column_next:
    inx
    cpx #160
    bne fill_column
    rts

load_renderer:
    lda #0
    sta dma_local
    lda #$f0
    sta dma_local+1
    lda #0
    sta dma_reu
    sta dma_reu+2
    .if (M2_BUILD != 0) {
        lda #$b0
    } else {
        lda #$10
    }
    sta dma_reu+1
    lda #<RENDER_BYTES
    sta dma_length
    lda #>RENDER_BYTES
    sta dma_length+1
    lda #$91
    sta dma_command
    jsr transfer
    rts

raster_active:
    .if (M3_BUILD == 0) {
    bit $d011
    bmi active_high
    lda $d012
    cmp #60
    bcc raster_not_active
    sec
    rts
active_high:
    lda $d012
    cmp #4
    bcc raster_is_active
raster_not_active:
    clc
    rts
raster_is_active:
    sec
    rts
    }
admit_dma:
    .if (M3_BUILD == 0) {
    // Two 128-byte transfers need separate observed bounds. Fixed late
    // blanking admission gives >=70 complete lines before the next guard.
    // Record 5 max high byte must be <=1 (<=511 ticks).
    lda REPORT+$37
    cmp #2
    bcs deferred
    lda REPORT+$4b
    cmp #2
    bcs deferred
    bit $d011
    bpl deferred
    lda $d012
    cmp #24
    bcc deferred
    cmp #44
    bcs deferred
    clc
    rts
deferred:
    inc REPORT+$16
    bne deferred_done
    inc REPORT+$17
deferred_done:
    sec
    rts
    }
resident_end:
.assert "resident probe fits its original budget", resident_end <= $4000, true
