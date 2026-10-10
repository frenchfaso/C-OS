#importonce
#import "scheduler.inc"
// Autonomous two-queue arbiter. All routines return with native frames unwound.
scheduler_module_start:
scheduler_start:
scheduler_init:
    jsr cache_reset
    lda #0
    ldx #127
!:
    sta SCHED_BASE,x
    dex
    bpl !-
    sta VM_SLOT
    jsr vm_load_context
    lda #PACK_APP_COUNT
    sta SCHED_APPS
    lda #$ff
    sta SCHED_CURRENT
    lda #1
    sta SCHED_CONTROL
    lda #15
    sta SCHED_DISPATCH_MASK
    ldx #0
scheduler_init_owner:
    stx sched_index
    txa
    jsr scheduler_owner_pointer
    lda #0
    ldy #31
!:
    sta (sched_ptr),y
    dey
    bpl !-
    ldx sched_index
    cpx #PACK_APP_COUNT
    bcs scheduler_init_next
    lda #PROC_RUNNABLE
    ldy #SP_STATE
    sta (sched_ptr),y
    lda #1
    iny
    sta (sched_ptr),y
    txa
    jsr scheduler_enqueue
scheduler_init_next:
    ldx sched_index
    inx
    cpx #4
    bne scheduler_init_owner
    lda #0
    sta $dc0e
    lda #$ff
    sta $dc04
    sta $dc05
    lda #$11
    sta $dc0e
    rts

// The renderer inlines this carry chain before synchronizing its first line.
scheduler_frame_tick:
    inc SCHED_FRAME
    bne !+
    inc SCHED_FRAME+1
    bne !+
    inc SCHED_FRAME+2
    bne !+
    inc SCHED_FRAME+3
!:
    rts

// A slot -> pointer; keep original slot explicitly for correct page selection.
scheduler_owner_pointer:
    pha
    and #1
    lsr
    ror
    ora #96
    sta sched_ptr
    pla
    lsr
    clc
    adc #4
    sta sched_ptr+1
    rts

// A slot -> active architecture, only at consistent opcode/job boundaries.
scheduler_select:
    sta SCHED_TEMP
    cmp VM_SLOT
    beq scheduler_select_pointer
    jsr vm_save_context
    lda SCHED_TEMP
    sta VM_SLOT
    jsr vm_load_context
    lda VM_SLOT
    asl
    tax
    inc SCHED_SWITCHES,x
    bne scheduler_select_pointer
    inc SCHED_SWITCHES+1,x
scheduler_select_pointer:
    lda VM_SLOT
    jmp scheduler_owner_pointer

// A runnable slot -> queue tail; duplicate insertion is inert.
scheduler_enqueue:
    sta SCHED_TEMP+1
    ldx #0
!:
    cpx SCHED_COUNT
    beq scheduler_enqueue_tail
    cmp SCHED_READY,x
    beq scheduler_enqueue_done
    inx
    bne !-
scheduler_enqueue_tail:
    cpx #4
    bcs scheduler_enqueue_done
    sta SCHED_READY,x
    inc SCHED_COUNT
scheduler_enqueue_done:
    rts
scheduler_dequeue:
    ldx SCHED_COUNT
    beq scheduler_dequeue_empty
    lda SCHED_READY
    sta SCHED_TEMP+1
    dec SCHED_COUNT
    ldx #0
!:
    lda SCHED_READY+1,x
    sta SCHED_READY,x
    inx
    cpx #3
    bne !-
    lda SCHED_TEMP+1
    clc
    rts
scheduler_dequeue_empty:
    sec
    rts

// One admitted VM/native phase, or an inert video wait. Owed turn persists.
scheduler_tick:
    lda SCHED_CONTROL
    beq scheduler_tick_done
    jsr scheduler_video_admit
    bcs scheduler_tick_done
    lda SCHED_CANCEL
    beq !+
    sec
    sbc #1
    and #3
    jsr scheduler_select
    jsr scheduler_cancel_current
    lda #0
    sta SCHED_CANCEL
    inc SCHED_CANCELLED
!:
    jsr scheduler_wake_timed
    lda SCHED_DUE
    beq scheduler_tick_vm_first
    jsr scheduler_native_phase
    bcc scheduler_tick_native_done
    jsr scheduler_vm_phase
    rts
scheduler_tick_vm_first:
    jsr scheduler_vm_phase
    bcc scheduler_tick_vm_done
    // A late VM video deferral must not launch a context/service scan.
    // A refused fallback retains its owed native turn unchanged.
    jsr scheduler_video_admit
    bcs scheduler_tick_done
    jsr scheduler_native_phase
    rts
scheduler_tick_vm_done:
    lda #1
    sta SCHED_DUE
    rts
scheduler_tick_native_done:
    lda #0
    sta SCHED_DUE
scheduler_tick_done:
    rts

scheduler_vm_phase:
    lda SCHED_CURRENT
    cmp #$ff
    bne scheduler_vm_selected
    jsr scheduler_dequeue
    bcc !+
    jmp scheduler_vm_deferred
!:
    sta SCHED_CURRENT
scheduler_vm_selected:
    jsr scheduler_select
    ldy #SP_REFILL
    lda (sched_ptr),y
    beq !+
    lda #128
    sta VM_FUEL
    lda #0
    sta (sched_ptr),y
!:
    lda #0
    sta VM_OUTCOME
    lda VM_SLOT
    tax
    lda scheduler_owner_bits,x
    and SCHED_DISPATCH_MASK
    beq scheduler_vm_timestamp_done
    lda scheduler_owner_bits,x
    eor #$ff
    and SCHED_DISPATCH_MASK
    sta SCHED_DISPATCH_MASK
    txa
    asl
    asl
    tax
    .for (var i=0;i<4;i++) {
        lda SCHED_FRAME+i
        sta SCHED_FIRST_RUN+i,x
    }
scheduler_vm_timestamp_done:
    // Native CPU jobs arbitrate even when their first phase is tiny.
    jsr scheduler_has_job
    bcs scheduler_vm_single
    jsr vm_run
    jmp scheduler_vm_result
scheduler_vm_single:
    jsr vm_step
scheduler_vm_result:
    lda VM_OUTCOME
    cmp #VM_WAIT_VIDEO
    beq scheduler_vm_deferred
    cmp #VM_RUN
    beq scheduler_vm_retired
    cmp #VM_FUEL_EXHAUSTED
    beq scheduler_vm_rotate
    cmp #VM_YIELD
    beq scheduler_vm_rotate
    cmp #VM_WAIT_REU
    beq scheduler_vm_memory
    cmp #VM_SYSCALL
    beq scheduler_vm_syscall
    cmp #VM_FAULTED
    beq scheduler_vm_fault
    jsr scheduler_cancel_current
    jmp scheduler_vm_retired
scheduler_vm_rotate:
    lda #1
    ldy #SP_REFILL
    sta (sched_ptr),y
    lda VM_SLOT
    jsr scheduler_enqueue
    lda #$ff
    sta SCHED_CURRENT
    jmp scheduler_vm_retired
scheduler_vm_memory:
    lda #PROC_WAIT_REU
    ldy #SP_STATE
    sta (sched_ptr),y
    lda #$ff
    sta SCHED_CURRENT
    jmp scheduler_vm_retired
scheduler_vm_syscall:
    jsr jobs_accept
    lda VM_SLOT
    jsr scheduler_owner_pointer
    ldy #SP_STATE
    lda (sched_ptr),y
    cmp #PROC_RUNNABLE
    beq scheduler_vm_retired
    lda #$ff
    sta SCHED_CURRENT
    jmp scheduler_vm_retired
scheduler_vm_fault:
    jsr scheduler_stop_current
    lda #PROC_FAULTED
    ldy #SP_STATE
    sta (sched_ptr),y
scheduler_vm_retired:
    inc SCHED_VM_PHASES
    bne !+
    inc SCHED_VM_PHASES+1
    bne !+
    inc SCHED_VM_PHASES+2
    bne !+
    inc SCHED_VM_PHASES+3
!:
    jsr vm_save_context
    clc
    rts
scheduler_vm_deferred:
    sec
    rts

scheduler_has_job:
    ldx #0
!:
    stx SCHED_TEMP+2
    txa
    jsr scheduler_owner_pointer
    ldy #SP_STATE
    lda (sched_ptr),y
    cmp #PROC_WAIT_JOB
    beq scheduler_has_job_yes
    ldx SCHED_TEMP+2
    inx
    cpx #4
    bne !-
    lda VM_SLOT
    jsr scheduler_owner_pointer
    clc
    rts
scheduler_has_job_yes:
    lda VM_SLOT
    jsr scheduler_owner_pointer
    sec
    rts

scheduler_native_phase:
    lda cache_pending_phase
    beq scheduler_native_job
    lda cache_pending_owner
    jsr scheduler_select
    jsr scheduler_timer_begin
    jsr cache_service
    bcc !+
    jsr scheduler_account_native
    jmp scheduler_native_deferred
!:
    jsr scheduler_account_native
    lda cache_pending_phase
    bne scheduler_native_completed
    jsr scheduler_wake_reu
    jmp scheduler_native_completed
scheduler_native_job:
    lda cache_native_active
    beq scheduler_native_scan
    lda cache_native_owner
    jsr scheduler_select
    jmp scheduler_native_execute
scheduler_native_scan:
    lda #4
    sta SCHED_TEMP+3
!:
    // Inspect stable PCB metadata before loading an architecture.
    lda SCHED_JOB_CURSOR
    jsr scheduler_owner_pointer
    ldy #SP_STATE
    lda (sched_ptr),y
    cmp #PROC_WAIT_JOB
    bne scheduler_native_scan_next
    lda SCHED_JOB_CURSOR
    jsr scheduler_select
    jmp scheduler_native_execute
scheduler_native_scan_next:
    inc SCHED_JOB_CURSOR
    lda SCHED_JOB_CURSOR
    and #3
    sta SCHED_JOB_CURSOR
    dec SCHED_TEMP+3
    bne !-
    // An empty scan keeps the architecture and restores its metadata pointer.
    lda VM_SLOT
    jsr scheduler_owner_pointer
scheduler_native_deferred:
    sec
    rts
scheduler_native_execute:
    jsr scheduler_timer_begin
    jsr jobs_step
    bcc !+
    jsr scheduler_account_native
    jmp scheduler_native_deferred
!:
    jsr scheduler_account_native
    lda VM_SLOT
    clc
    adc #1
    and #3
    sta SCHED_JOB_CURSOR
scheduler_native_completed:
    inc SCHED_NATIVE_PHASES
    bne !+
    inc SCHED_NATIVE_PHASES+1
    bne !+
    inc SCHED_NATIVE_PHASES+2
    bne !+
    inc SCHED_NATIVE_PHASES+3
!:
    jsr vm_save_context
    clc
    rts

// A state/current continuation is cancelled before freeing its incarnation.
scheduler_cancel_current:
    ldx VM_SLOT
    jsr margin_revoke_owner
    bcs !+
    jsr margin_discard_cancelled
!:
    jsr cache_invalidate_owner
    // Revoking the requester/victim can release the single driver directly.
    // Other owners waiting behind it must not depend on a future service call.
    lda cache_pending_phase
    bne !+
    jsr scheduler_wake_reu
!:
    lda #0
    sta VM_PENDING
    lda VM_OUTCOME
    cmp #VM_FAULTED
    beq !+
    lda #VM_STOPPED
    sta VM_OUTCOME
!:
scheduler_stop_current:
    lda #0
    sta VM_PENDING
    lda VM_SLOT
    asl
    tax
    lda #0
    sta SCHED_WINDOWS,x
    sta SCHED_WINDOWS+1,x
    ldy #SP_JOB
    sta (sched_ptr),y
    ldy #SP_STATE
    sta (sched_ptr),y
    lda VM_SLOT
    cmp SCHED_CURRENT
    bne !+
    lda #$ff
    sta SCHED_CURRENT
!:
    lda VM_SLOT
    sta SCHED_TEMP+4
    ldx #0
scheduler_remove_scan:
    cpx SCHED_COUNT
    beq scheduler_cancel_done
    lda SCHED_READY,x
    cmp SCHED_TEMP+4
    beq scheduler_remove_found
    inx
    bne scheduler_remove_scan
scheduler_remove_found:
    dec SCHED_COUNT
scheduler_remove_shift:
    cpx SCHED_COUNT
    beq scheduler_cancel_done
    lda SCHED_READY+1,x
    sta SCHED_READY,x
    inx
    bne scheduler_remove_shift
scheduler_cancel_done:
    rts

// Trusted replacement is split around bounded owned-arena seed initialization.
// Revoke/increment first; the stopped slot accepts no new VM or native request.
scheduler_revoke_for_replace:
    jsr scheduler_cancel_current
    inc VM_GENERATION
    bne !+
    inc VM_GENERATION+1
!:
    jmp vm_save_context
// Caller supplies a validated fresh96-byte context at FE80 after initializing
// its owned arena. The packet's incarnation is ignored in favor of the new one.
scheduler_install_replacement:
    lda VM_GENERATION
    sta SCHED_TEMP+8
    lda VM_GENERATION+1
    sta SCHED_TEMP+9
    ldx #0
!:
    lda M2_COMPLETION,x
    sta VM_STATE,x
    inx
    cpx #VM_STATE_BYTES
    bne !-
    lda SCHED_TEMP+8
    sta VM_GENERATION
    lda SCHED_TEMP+9
    sta VM_GENERATION+1
    lda #0
    sta VM_PENDING
    sta VM_OUTCOME
    ldy #31
!:
    sta (sched_ptr),y
    dey
    bpl !-
    lda #PROC_RUNNABLE
    ldy #SP_STATE
    sta (sched_ptr),y
    lda #1
    iny
    sta (sched_ptr),y
    jsr vm_save_context
    lda VM_SLOT
    jmp scheduler_enqueue

scheduler_wake_reu:
    ldx #0
!:
    stx SCHED_TEMP+5
    txa
    jsr scheduler_owner_pointer
    ldy #SP_STATE
    lda (sched_ptr),y
    cmp #PROC_WAIT_REU
    bne scheduler_wake_reu_next
    lda #PROC_RUNNABLE
    sta (sched_ptr),y
    lda SCHED_TEMP+5
    jsr scheduler_enqueue
scheduler_wake_reu_next:
    ldx SCHED_TEMP+5
    inx
    cpx #4
    bne !-
    lda VM_SLOT
    jmp scheduler_owner_pointer

scheduler_wake_timed:
    ldx #0
scheduler_wake_timed_scan:
    stx SCHED_TEMP+5
    txa
    jsr scheduler_owner_pointer
    ldy #SP_STATE
    lda (sched_ptr),y
    cmp #PROC_SLEEPING
    beq scheduler_wake_test
    cmp #PROC_WAIT_EVENT
    bne scheduler_wake_timed_next
    ldy #SP_TIMEOUT
    lda (sched_ptr),y
    iny
    and (sched_ptr),y
    cmp #$ff
    beq scheduler_wake_timed_next
scheduler_wake_test:
    sec
    ldy #SP_STARTED
    .for (var i=0;i<4;i++) {
        lda SCHED_FRAME+i
        sbc (sched_ptr),y
        sta sched_value+i
        iny
    }
    lda sched_value+2
    ora sched_value+3
    bne scheduler_wake_expired
    ldy #SP_TIMEOUT+1
    lda sched_value+1
    cmp (sched_ptr),y
    bcc scheduler_wake_timed_next
    bne scheduler_wake_expired
    dey
    lda sched_value
    cmp (sched_ptr),y
    bcc scheduler_wake_timed_next
scheduler_wake_expired:
    lda SCHED_TEMP+5
    jsr scheduler_select
    ldy #SP_STATE
    lda (sched_ptr),y
    cmp #PROC_WAIT_EVENT
    lda #0
    bcc !+
    lda #4
!:
    jsr jobs_complete
    bcs scheduler_wake_timed_next
    lda #1
    ldy #SP_REFILL
    sta (sched_ptr),y
scheduler_wake_timed_next:
    ldx SCHED_TEMP+5
    inx
    cpx #4
    bne scheduler_wake_timed_scan
    lda VM_SLOT
    jmp scheduler_owner_pointer

scheduler_timer_begin:
    lda REPORT+$1d
    sta SCHED_TEMP+6
    jsr scheduler_timer_read
    lda sched_value
    sta SCHED_TIMER_START
    lda sched_value+1
    sta SCHED_TIMER_START+1
    rts
scheduler_timer_read:
    lda $dc05
    sta sched_value+1
    lda $dc04
    sta sched_value
    lda $dc05
    cmp sched_value+1
    bne scheduler_timer_read
    rts
scheduler_account_native:
    jsr scheduler_timer_read
    sec
    lda SCHED_TIMER_START
    sbc sched_value
    sta SCHED_TIMER_END
    lda SCHED_TIMER_START+1
    sbc sched_value+1
    sta SCHED_TIMER_END+1
    cmp SCHED_NATIVE_MAX+1
    bcc !+
    bne scheduler_native_new_max
    lda SCHED_TIMER_END
    cmp SCHED_NATIVE_MAX
    bcc !+
scheduler_native_new_max:
    lda SCHED_TIMER_END
    sta SCHED_NATIVE_MAX
    lda SCHED_TIMER_END+1
    sta SCHED_NATIVE_MAX+1
!:
    lda VM_SLOT
    asl
    asl
    tax
    clc
    lda SCHED_NATIVE_TICKS,x
    adc SCHED_TIMER_END
    sta SCHED_NATIVE_TICKS,x
    lda SCHED_NATIVE_TICKS+1,x
    adc SCHED_TIMER_END+1
    sta SCHED_NATIVE_TICKS+1,x
    lda SCHED_NATIVE_TICKS+2,x
    adc #0
    sta SCHED_NATIVE_TICKS+2,x
    lda SCHED_NATIVE_TICKS+3,x
    adc #0
    sta SCHED_NATIVE_TICKS+3,x
    lda REPORT+$1d
    cmp SCHED_TEMP+6
    beq !+
    clc
    lda SCHED_DMA_BYTES,x
    adc CACHE_WIDTH
    sta SCHED_DMA_BYTES,x
    lda SCHED_DMA_BYTES+1,x
    adc #0
    sta SCHED_DMA_BYTES+1,x
    lda SCHED_DMA_BYTES+2,x
    adc #0
    sta SCHED_DMA_BYTES+2,x
    lda SCHED_DMA_BYTES+3,x
    adc #0
    sta SCHED_DMA_BYTES+3,x
!:
    rts
scheduler_end:
scheduler_owner_bits:
    .byte 1,2,4,8
scheduler_module_end:
