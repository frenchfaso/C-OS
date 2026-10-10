#import "m2_abi.inc"
#import "probe.asm"
.const M2_KERNEL_BYTES = cmdLineVars.get("nativeBytes").asNumber()
.const M2_NATIVE_REU = $008000
.const M2_DESCRIPTORS_REU = $00c000
.const M2_INITIALIZATION_REU = $00c200
.label m2_source = $b0
.label m2_destination = $b3
.label m2_remaining = $b6
.label m2_chunk = $b9
.label m2_initial_slot = $ba
.label m2_request = $bb
.label m2_operation = $bc
.const M2_VM_DEFERRALS = M2_MAILBOX+5
.const M2_DMA_DEFERRALS = M2_MAILBOX+7
.const M2_VM_MAXIMUM = M2_MAILBOX+9
.const M2_SERVICE_MAXIMUM = M2_MAILBOX+11

// This stub is part of the PRG. Its DMA destinations exclude the stub.
* = $17a0 "M2 startup loader"
m2_boot_load:
    lda #0
    sta dma_local
    lda #$18
    sta dma_local+1
    lda #<M2_NATIVE_REU
    sta dma_reu
    lda #>M2_NATIVE_REU
    sta dma_reu+1
    lda #0
    sta dma_reu+2
    lda #<M2_KERNEL_BYTES
    sta dma_length
    lda #>M2_KERNEL_BYTES
    sta dma_length+1
    lda #$91
    sta dma_command
    jsr transfer
    jmp m2_kernel_initialize
m2_bootstrap_end:
.assert "M2 loader remains below its DMA destination", m2_bootstrap_end <= $1800, true
.assert "M0 probe leaves room for the M2 loader", resident_end <= $17a0, true

* = MARGIN_ENTRY "Optional margin trampoline"
m2_margin_trampoline:
    jmp margin_irq_hook
m2_bootstrap_end_with_margin:
.assert "M2 loader leaves room for margin trampoline", m2_bootstrap_end <= MARGIN_ENTRY, true

* = $1800 "M2 operational VM, caches and diagnostic harness"
m2_native_start:
m2_kernel_initialize:
    jsr cache_reset
    jsr margin_reset
    lda #0
    ldx #0
m2_clear_state:
    sta VM_STATE,x
    inx
    cpx #VM_STATE_BYTES
    bne m2_clear_state
    ldx #0
m2_clear_mailbox:
    sta M2_MAILBOX,x
    inx
    bne m2_clear_mailbox
    sta VM_SLOT
    lda #1
    sta VM_VIDEO
    lda #0
    sta dma_local
    lda #4
    sta dma_local+1
    lda #<M2_DESCRIPTORS_REU
    sta dma_reu
    lda #>M2_DESCRIPTORS_REU
    sta dma_reu+1
    lda #0
    sta dma_reu+2
    sta dma_length
    lda #2
    sta dma_length+1
    lda #$91
    sta dma_command
    jsr transfer
    lda #<BUFFER
    sta dma_local
    lda #>BUFFER
    sta dma_local+1
    lda #<M2_INITIALIZATION_REU
    sta dma_reu
    lda #>M2_INITIALIZATION_REU
    sta dma_reu+1
    lda #64
    sta dma_length
    lda #0
    sta dma_length+1
    jsr transfer
    lda #0
    sta m2_initial_slot
m2_initialize_next:
    lda m2_initial_slot
    cmp #PACK_APP_COUNT
    beq m2_initialize_done
    asl
    asl
    asl
    asl
    tax
    .for (var i=0; i<3; i++) {
        lda BUFFER+i,x
        sta m2_source+i
        lda BUFFER+3+i,x
        sta m2_destination+i
        lda BUFFER+6+i,x
        sta m2_remaining+i
    }
    jsr m2_restore_data
    lda m2_initial_slot
    asl
    asl
    asl
    asl
    tax
    .for (var i=0; i<3; i++) {
        lda BUFFER+9+i,x
        sta m2_destination+i
        lda BUFFER+12+i,x
        sta m2_remaining+i
    }
    lda #0
    ldx #127
m2_zero_staging:
    sta SAVED,x
    dex
    bpl m2_zero_staging
    jsr m2_clear_bss
    inc m2_initial_slot
    jmp m2_initialize_next
m2_initialize_done:
    jsr vm_load_context
    rts

m2_select_chunk:
    lda m2_remaining
    ora m2_remaining+1
    ora m2_remaining+2
    beq m2_no_chunk
    lda #128
    ldx m2_remaining+1
    bne m2_chunk_ready
    ldx m2_remaining+2
    bne m2_chunk_ready
    cmp m2_remaining
    bcc m2_chunk_ready
    lda m2_remaining
m2_chunk_ready:
    sta m2_chunk
    sta dma_length
    lda #0
    sta dma_length+1
    lda #<SAVED
    sta dma_local
    lda #>SAVED
    sta dma_local+1
    clc
    rts
m2_no_chunk:
    sec
    rts
m2_restore_data:
    jsr m2_select_chunk
    bcs m2_restore_done
    .for (var i=0; i<3; i++) {
        lda m2_source+i
        sta dma_reu+i
    }
    lda #$91
    sta dma_command
    jsr transfer
    jsr m2_stash_chunk
    clc
    lda m2_source
    adc m2_chunk
    sta m2_source
    lda m2_source+1
    adc #0
    sta m2_source+1
    lda m2_source+2
    adc #0
    sta m2_source+2
    jmp m2_restore_data
m2_restore_done:
    rts
m2_clear_bss:
    jsr m2_select_chunk
    bcs m2_restore_done
    jsr m2_stash_chunk
    jmp m2_clear_bss
m2_stash_chunk:
    .for (var i=0; i<3; i++) {
        lda m2_destination+i
        sta dma_reu+i
    }
    lda #$90
    sta dma_command
    jsr transfer
    clc
    lda m2_destination
    adc m2_chunk
    sta m2_destination
    lda m2_destination+1
    adc #0
    sta m2_destination+1
    lda m2_destination+2
    adc #0
    sta m2_destination+2
    sec
    lda m2_remaining
    sbc m2_chunk
    sta m2_remaining
    lda m2_remaining+1
    sbc #0
    sta m2_remaining+1
    lda m2_remaining+2
    sbc #0
    sta m2_remaining+2
    rts

m2_command_harness_start:
// Entered by JMP after bootstrap returns: no live JSR frames to overwrite.
m2_kernel_start:
    sei
    lda #$a5
    ldx #0
m2_stack_fill:
    sta $0100,x
    inx
    bne m2_stack_fill
    cli
m2_kernel_entry:
    lda nmi_pending
    beq m2_poll_command
    jsr m2_recover_nmi
m2_poll_command:
    lda M2_MAILBOX
    cmp M2_MAILBOX+1
    beq m2_kernel_entry
    sta m2_request
    lda M2_MAILBOX+2
    sta m2_operation
    lda #0
    sta M2_MAILBOX+3
    lda m2_operation
    cmp #1
    bne m2_dispatch_2
    jmp m2_load_command
m2_dispatch_2:
    cmp #2
    bne m2_dispatch_3
    jmp m2_step_command
m2_dispatch_3:
    cmp #3
    bne m2_dispatch_4
    jmp m2_run_command
m2_dispatch_4:
    cmp #4
    bne m2_dispatch_5
    jmp m2_service_command
m2_dispatch_5:
    cmp #5
    bne m2_dispatch_6
    jmp m2_complete_command
m2_dispatch_6:
    cmp #6
    bne m2_dispatch_7
    jmp m2_refuel_command
m2_dispatch_7:
    cmp #7
    bne m2_dispatch_8
    jmp m2_switch_command
m2_dispatch_8:
    cmp #8
    bne m2_dispatch_9
    jmp m2_reuse_command
m2_dispatch_9:
    cmp #9
    bne m2_dispatch_10
    jmp m2_native_read_command
m2_dispatch_10:
    cmp #10
    bne m2_dispatch_11
    jmp m2_native_write_command
m2_dispatch_11:
    cmp #11
    bne m2_dispatch_12
    jmp m2_active_command
m2_dispatch_12:
    cmp #12
    bne m2_dispatch_13
    jmp m2_patch_command
m2_dispatch_13:
    cmp #13
    bne m2_dispatch_14
    jmp m2_video_command
m2_dispatch_14:
    cmp #14
    bne m2_dispatch_15
    jmp m2_nmi_command
m2_dispatch_15:
    jmp m2_bad_command
m2_bad_command:
    lda #2
    sta M2_MAILBOX+3
    jmp m2_acknowledge

// Recover only outside raster. The NMI handler preserves interrupted state;
// this path touches no VM/cache continuation or remaining fuel.
m2_recover_nmi:
    lda #0
    sta margin_qualified
    lda #$7f
    sta $dd0d
    lda $dd0d
m2_recovery_wait:
    bit $d011
    bpl m2_recovery_wait
    lda $d012
    cmp #24
    bcc m2_recovery_wait
    cmp #44
    bcs m2_recovery_wait
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
    inc M2_MAILBOX+13
    bne m2_recovery_done
    inc M2_MAILBOX+14
m2_recovery_done:
    rts
m2_nmi_command:
    jsr m2_video_diagnostic
    bcs m2_nmi_command
    lda #0
    sta $dd0e
    sta $dd05
    lda #128
    sta $dd04
    lda #$81
    sta $dd0d
    lda #$19
    sta $dd0e
m2_nmi_wait:
    lda nmi_pending
    beq m2_nmi_wait
    jsr m2_recover_nmi
    jmp m2_acknowledge

m2_revoke_margin:
    ldx VM_SLOT
    jsr margin_revoke_owner
    bcs m2_margin_revoke_done
    jmp margin_discard_cancelled
m2_margin_revoke_done:
    rts
m2_complete_command:
    lda M2_MAILBOX+4
    cmp VM_SLOT
    bne m2_bad_completion
    jsr vm_complete_syscall
    bcs m2_bad_completion
    jmp m2_acknowledge
m2_bad_completion:
    lda #1
    sta M2_MAILBOX+3
    jmp m2_acknowledge
m2_refuel_command:
    lda M2_ARGUMENTS
    sta VM_FUEL
    lda VM_OUTCOME
    cmp #VM_FAULTED
    beq m2_refuel_done
    cmp #VM_STOPPED
    beq m2_refuel_done
    lda VM_PENDING
    bne m2_refuel_done
    lda #VM_RUN
    sta VM_OUTCOME
m2_refuel_done:
    jmp m2_acknowledge
m2_reuse_command:
    jsr m2_revoke_margin
    jsr cache_invalidate_owner
    inc VM_GENERATION
    bne m2_reuse_ready
    inc VM_GENERATION+1
m2_reuse_ready:
    lda #0
    sta VM_PENDING
    sta VM_OUTCOME
    jmp m2_acknowledge
m2_video_command:
    lda M2_ARGUMENTS
    and #1
    sta VM_VIDEO
    sta $d01a
    lda #1
    sta $d019
    jmp m2_acknowledge

m2_load_command:
    lda M2_MAILBOX+4
    cmp #4
    bcc !+
    jmp m2_bad_command
!:
    pha
    jsr vm_save_context
    pla
    sta VM_SLOT
    jsr vm_load_context
    jsr m2_revoke_margin
    jsr cache_invalidate_owner
    ldx #0
m2_load_bytes:
    lda M2_ARGUMENTS,x
    sta VM_STATE,x
    inx
    cpx #VM_STATE_BYTES
    bne m2_load_bytes
    jmp m2_acknowledge
m2_switch_command:
    lda M2_MAILBOX+4
    cmp #4
    bcc !+
    jmp m2_bad_command
!:
    pha
    jsr vm_save_context
    pla
    sta VM_SLOT
    jsr vm_load_context
    jmp m2_acknowledge
m2_step_command:
    jsr m2_video_diagnostic
    bcs m2_step_command
    jsr start_timer
    jsr vm_step
    jsr end_timer
    lda VM_OUTCOME
    cmp #VM_WAIT_VIDEO
    beq m2_step_command
    ldx #9
    jsr m2_record_maximum
    jmp m2_acknowledge
m2_run_command:
    jsr m2_video_diagnostic
    bcs m2_run_command
    jsr vm_run
    lda VM_OUTCOME
    cmp #VM_WAIT_VIDEO
    beq m2_run_command
    jmp m2_acknowledge
m2_service_command:
    jsr m2_dma_diagnostic
    bcs m2_service_command
    jsr start_timer
    jsr cache_service
    php
    jsr end_timer
    ldx #11
    jsr m2_record_maximum
    plp
    bcs !+
    jmp m2_acknowledge
!:
    lda #3
    sta M2_MAILBOX+3
    jmp m2_acknowledge
m2_native_arguments:
    .for (var i=0; i<3; i++) {
        lda M2_ARGUMENTS+i
        sta CACHE_ADDR+i
        lda M2_ARGUMENTS+4+i
        sta CACHE_VALUE+i
    }
    lda M2_ARGUMENTS+3
    sta CACHE_WIDTH
    rts
m2_native_read_command:
    jsr m2_dma_diagnostic
    bcs m2_native_read_command
    jsr m2_native_arguments
    jsr cache_native_read
    bcs m2_native_wait
    .for (var i=0; i<3; i++) {
        lda CACHE_VALUE+i
        sta M2_ARGUMENTS+4+i
    }
    jmp m2_acknowledge
m2_native_write_command:
    jsr m2_dma_diagnostic
    bcs m2_native_write_command
    jsr m2_native_arguments
    jsr cache_native_write
    bcs m2_native_wait
    jmp m2_acknowledge
m2_native_wait:
    lda cache_dma_error
    beq !+
    lda #2
    sta M2_MAILBOX+3
    jmp m2_acknowledge
!:
    lda #3
    sta M2_MAILBOX+3
    jmp m2_acknowledge
m2_active_command:
    // Negative admission injection: the ordinary IRQ owns the entire active
    // interval, so temporarily suppress this frame's raster handler. The VM
    // must reject before fetching, and scanout resumes at IRQ58 next frame.
    lda #0
    sta $d01a
m2_active_wait:
    bit $d011
    bmi m2_active_wait
    lda $d012
    cmp #65
    bne m2_active_wait
    jsr vm_step
    lda #RASTER_IRQ
    sta $d012
    lda #1
    sta $d019
    sta $d01a
    jmp m2_acknowledge
m2_patch_command:
    jsr m2_dma_diagnostic
    bcs m2_patch_command
    jsr m2_native_arguments
    lda CACHE_WIDTH
    beq m2_bad_patch
    cmp #129
    bcs m2_bad_patch
    // Privileged fixture initialization only, never an application service.
    // The runner cancels each fixture owner before patching its physical arena.
    lda #<SAVED
    sta CACHE_LOCAL
    lda #>SAVED
    sta CACHE_LOCAL+1
    lda #$90
    jsr cache_dma_transfer
    bcs !+
    jmp m2_acknowledge
!:
    jmp m2_native_wait
m2_bad_patch:
    lda #2
    sta M2_MAILBOX+3
m2_acknowledge:
    jsr vm_save_context
    ldx #0
m2_snapshot_bytes:
    lda VM_STATE,x
    sta M2_SNAPSHOT,x
    inx
    cpx #VM_STATE_BYTES
    bne m2_snapshot_bytes
    lda m2_request
    sta M2_MAILBOX+1
    jmp m2_kernel_entry

m2_record_maximum:
    lda scratch_ptr+1
    cmp M2_MAILBOX+1,x
    bcc m2_maximum_done
    bne m2_new_maximum
    lda scratch_ptr
    cmp M2_MAILBOX,x
    bcc m2_maximum_done
m2_new_maximum:
    lda scratch_ptr
    sta M2_MAILBOX,x
    lda scratch_ptr+1
    sta M2_MAILBOX+1,x
m2_maximum_done:
    rts
m2_command_harness_end:

// Both hooks preserve interpreter/cache scratch. The fixed late-PAL window
// leaves >=70 complete lines before the next IRQ58 even at the latest start.
m2_video_diagnostic:
    lda nmi_pending
    beq m2_video_diagnostic_ready
    jsr m2_recover_nmi
m2_video_diagnostic_ready:
    jmp vm_video_admit
m2_dma_diagnostic:
    lda nmi_pending
    beq m2_dma_diagnostic_ready
    jsr m2_recover_nmi
m2_dma_diagnostic_ready:
    jmp vm_dma_admit
vm_video_admit:
    lda nmi_pending
    bne m2_video_deferred
    lda VM_VIDEO
    beq m2_admission_safe
    bit $d011
    bpl m2_video_deferred
    lda $d012
    cmp #24
    bcc m2_video_deferred
    cmp #44
    bcs m2_video_deferred
m2_admission_safe:
    clc
    rts
m2_video_deferred:
    inc M2_VM_DEFERRALS
    bne !+
    inc M2_VM_DEFERRALS+1
!:
    sec
    rts
vm_dma_admit:
    lda nmi_pending
    bne m2_dma_deferred
    lda VM_VIDEO
    beq m2_admission_safe
    // Retain both independently measured128-byte bounds, including setup.
    lda REPORT+$37
    cmp #2
    bcs m2_dma_deferred
    lda REPORT+$4b
    cmp #2
    bcs m2_dma_deferred
    bit $d011
    bpl m2_dma_deferred
    lda $d012
    cmp #24
    bcc m2_dma_deferred
    cmp #44
    bcs m2_dma_deferred
    clc
    rts
m2_dma_deferred:
    inc M2_DMA_DEFERRALS
    bne !+
    inc M2_DMA_DEFERRALS+1
!:
    sec
    rts
// Called immediately after every runtime DMA command, before IRQ restoration.
// The actual completion raster is checked independently of admission.
vm_dma_completed:
    lda VM_VIDEO
    beq m2_dma_completed_done
    jsr raster_active
    bcc m2_dma_completed_done
    inc REPORT+$1a
    bne m2_dma_completed_done
    inc REPORT+$1b
m2_dma_completed_done:
    rts
m2_diagnostic_end:

#import "vm.asm"
#import "cache.asm"
#import "margins.asm"
m2_native_end:
.assert "M2 resident native image fits local RAM", m2_native_end <= $4000, true
