// Autonomous normal kernel; the bootstrap's code and scratch are no longer live.
#import "m2_abi.inc"
#import "hardware.inc"
.const M3_ADMISSION_LOW = EXTENDED_DIAGNOSTICS == 0 && MARGIN_ENABLED == 0 ? 4 : 24
.const M3_ADMISSION_EARLY_END = 19
* = $1200 "M3 resident runtime"
m3_native_start:
m3_kernel_entry:
    sei
    cld
    // One-time stack watermark before any live native call frames exist.
    ldx #$ff
    txs
    lda #$a5
    ldx #0
m3_stack_fill:
    sta $0100,x
    inx
    bne m3_stack_fill
    jsr margin_reset
    jsr profile_init
    lda #0
    ldx #VM_STATE_BYTES-1
!:
    sta VM_STATE,x
    dex
    bpl !-
    sta VM_SLOT
    lda #1
    sta VM_VIDEO
    jsr scheduler_init
    cli
m3_kernel_loop:
    lda nmi_pending
    beq !+
    jsr m3_recover_nmi
!:
    jsr scheduler_tick
    jmp m3_kernel_loop

m3_video_runtime_start:
// Finite admission hooks preserve VM/cache scratch and hold no call frame
// across a deadline. Recovery waits occur only in the outer kernel loop.
vm_video_admit:
    lda nmi_pending
    bne m3_video_deferred
    lda VM_VIDEO
    beq m3_admission_safe
    jsr m3_raster_admit
    bcs m3_video_deferred
m3_admission_safe:
    clc
    rts
m3_video_deferred:
    inc REPORT+$16
    bne !+
    inc REPORT+$17
!:
    sec
    rts
vm_dma_admit:
    lda nmi_pending
    bne m3_dma_deferred
    lda VM_VIDEO
    beq m3_admission_safe
    lda REPORT+$37
    cmp #2
    bcs m3_dma_deferred
    lda REPORT+$4b
    cmp #2
    bcs m3_dma_deferred
    jsr m3_raster_admit
    bcs m3_dma_deferred
    clc
    rts
m3_dma_deferred:
    inc REPORT+$18
    bne !+
    inc REPORT+$19
!:
    sec
    rts
// Coherent high-low-high classification, with a torn read deferred instead of
// retried. Both high-bit samples must agree; no active line can become a false
// early-frame admission at 255->256 or a false post-scanout admission at wrap.
// Normal profile: 260..311 and 0..20; diagnostics retain 280..299 only.
// The complete last admitted scheduler tail must fit before raster IRQ58.
// A/flags are scratch; X/Y and interpreter/cache scratch are preserved.
m3_raster_admit:
    bit $d011
    bmi m3_raster_post
    lda $d012
    cmp #M3_ADMISSION_EARLY_END
    bcs m3_raster_reject
    bit $d011
    bmi m3_raster_reject
    clc
    rts
m3_raster_post:
    lda $d012
    cmp #M3_ADMISSION_LOW
    bcc m3_raster_reject
    cmp #(EXTENDED_DIAGNOSTICS == 0 && MARGIN_ENABLED == 0 ? 56 : 44)
    bcs m3_raster_reject
    bit $d011
    bpl m3_raster_reject
    clc
    rts
m3_raster_reject:
    sec
    rts
vm_dma_completed:
    // Compact actual-transfer serial for per-owner native byte accounting.
    inc REPORT+$1d
    lda VM_VIDEO
    beq !+
    jsr raster_active
    bcc !+
    inc REPORT+$1a
    bne !+
    inc REPORT+$1b
!:
    rts
raster_active:
    bit $d011
    bmi !+
    lda $d012
    cmp #FIRST_LINE
    bcc m3_not_active
    sec
    rts
!:
    lda $d012
    cmp #4
    bcc m3_is_active
m3_not_active:
    clc
    rts
m3_is_active:
    sec
    rts
m3_recover_nmi:
    lda #0
    sta margin_qualified
    lda #$7f
    sta $dd0d
    lda $dd0d
m3_recovery_wait:
    bit $d011
    bpl m3_recovery_wait
    lda $d012
    cmp #24
    bcc m3_recovery_wait
    cmp #44
    bcs m3_recovery_wait
    php
    sei
    lda #RASTER_IRQ
    sta $d012
    lda #1
    sta $d019
    lda VM_VIDEO
    sta $d01a
    lda #0
    sta nmi_pending
    plp
    inc REPORT+$1e
    bne !+
    inc REPORT+$1f
!:
    rts
m3_video_runtime_end:

#import "vm.asm"
#import "cache.asm"
#import "m3-margins.inc"
#import "scheduler.asm"
#import "jobs.asm"
#import "profile.asm"
m3_native_end:
.assert "normal M3 runtime fits its assigned resident area", m3_native_end <= $4000, true
