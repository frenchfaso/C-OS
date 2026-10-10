#importonce
#import "scheduler.inc"
// Specified bounded CPU jobs, using the centralized coherent scalar layer.
jobs_module_start:
jobs_accept:
    lda VM_SYSCALL_ID
    bne !+
    jmp jobs_exit
!:
    cmp #1
    bne !+
    jmp jobs_info
!:
    cmp #2
    bne !+
    jmp jobs_frame
!:
    cmp #3
    bne !+
    jmp jobs_sleep
!:
    cmp #4
    bne !+
    jmp jobs_event
!:
    cmp #$0a
    bne !+
    jmp jobs_memory
!:
    cmp #$0b
    bne !+
    jmp jobs_memory
!:
    cmp #$0c
    bne !+
    jmp jobs_memory_info
!:
    jmp jobs_unsupported
jobs_exit:
    lda VM_R
    sta VM_TRAP
    lda VM_R+1
    sta VM_TRAP+1
    lda #0
    sta VM_PENDING
    lda #VM_STOPPED
    sta VM_OUTCOME
    jmp scheduler_stop_current
jobs_info:
    lda #<COS_APPLICATION_ABI
    sta VM_R+2
    lda #>COS_APPLICATION_ABI
    sta VM_R+3
    lda #0
    sta VM_R+5
    sta VM_R+7
    sta VM_R+8
    sta VM_R+9
    lda #$40
    sta VM_R+4
    lda #1
    sta VM_R+5
    lda #200
    sta VM_R+6
    jmp jobs_ok
jobs_frame:
    php
    sei
    .for (var i=0;i<4;i++) {
        lda SCHED_FRAME+i
        sta VM_R+2+i
    }
    plp
    jmp jobs_ok
jobs_memory_info:
    .for (var i=0;i<3;i++) {
        lda VM_HEAP_FIRST+i
        sta VM_P+i
        lda VM_HEAP_LAST+i
        sta VM_P+3+i
        lda VM_STACK_FIRST+i
        sta VM_P+6+i
        lda VM_STACK_LAST+i
        sta VM_P+9+i
    }
jobs_ok:
    lda #0
    jmp jobs_return
jobs_sleep:
    lda VM_R
    ora VM_R+1
    bne jobs_sleep_positive
    lda #0
    sta VM_FUEL
    jsr jobs_return
    lda #1
    ldy #SP_REFILL
    sta (sched_ptr),y
    lda VM_SLOT
    jsr scheduler_enqueue
    lda #$ff
    sta SCHED_CURRENT
    rts
jobs_sleep_positive:
    lda #JOB_SLEEP
    ldy #SP_JOB
    sta (sched_ptr),y
    lda #PROC_SLEEPING
    ldy #SP_STATE
    sta (sched_ptr),y
    jmp jobs_wait_time
jobs_event:
    lda VM_SLOT
    asl
    tax
    lda SCHED_WINDOWS,x
    ora SCHED_WINDOWS+1,x
    beq jobs_bad_handle
    lda SCHED_WINDOWS,x
    cmp VM_R+2
    bne jobs_bad_handle
    lda SCHED_WINDOWS+1,x
    cmp VM_R+3
    bne jobs_bad_handle
    jmp jobs_event_wait
jobs_bad_handle:
    lda #5
    jmp jobs_return
jobs_event_wait:
    lda #16
    sta sched_value
    lda #0
    sta sched_value+1
    sta sched_value+2
    lda #1
    sta sched_kind
    .for (var i=0;i<3;i++) {
        lda VM_P+i
        sta sched_address+i
    }
    jsr jobs_validate
    bcc !+
    jmp jobs_return
!:
    lda VM_R
    ora VM_R+1
    bne !+
    lda #4
    jmp jobs_return
!:
    lda #JOB_EVENT
    ldy #SP_JOB
    sta (sched_ptr),y
    lda #PROC_WAIT_EVENT
    ldy #SP_STATE
    sta (sched_ptr),y
jobs_wait_time:
    php
    sei
    ldy #SP_STARTED
    .for (var i=0;i<4;i++) {
        lda SCHED_FRAME+i
        sta (sched_ptr),y
        iny
    }
    plp
    lda VM_R
    ldy #SP_TIMEOUT
    sta (sched_ptr),y
    iny
    lda VM_R+1
    sta (sched_ptr),y
    jmp jobs_bind_generation

jobs_memory:
    lda VM_SYSCALL_ID
    cmp #$0a
    bne !+
    lda VM_R+3
    beq !+
    lda #1
    jmp jobs_return
!:
    lda VM_R+7
    bne jobs_range_error
    lda VM_R+4
    sta sched_value
    lda VM_R+5
    sta sched_value+1
    lda VM_R+6
    sta sched_value+2
    ora sched_value
    ora sched_value+1
    bne !+
    jmp jobs_ok
!:
    lda #1
    sta sched_kind
    .for (var i=0;i<3;i++) {
        lda VM_P+i
        sta sched_address+i
    }
    jsr jobs_validate
    bcc !+
    jmp jobs_return
!:
    lda VM_SYSCALL_ID
    cmp #$0b
    bne jobs_memory_ready
    lda #0
    sta sched_kind
    .for (var i=0;i<3;i++) {
        lda VM_P+3+i
        sta sched_address+i
    }
    jsr jobs_validate
    bcc jobs_memory_ready
    jmp jobs_return
jobs_range_error:
    lda #2
    jmp jobs_return
jobs_memory_ready:
    ldy #SP_DST
    .for (var i=0;i<3;i++) {
        lda VM_P+i
        sta (sched_ptr),y
        iny
    }
    .for (var i=0;i<3;i++) {
        lda VM_P+3+i
        sta (sched_ptr),y
        iny
    }
    .for (var i=0;i<3;i++) {
        lda sched_value+i
        sta (sched_ptr),y
        iny
    }
    lda #0
    ldy #SP_PHASE
    sta (sched_ptr),y
    lda #JOB_FILL
    ldy #SP_JOB
    sta (sched_ptr),y
    lda VM_SYSCALL_ID
    cmp #$0a
    beq jobs_fill_ready
    lda #JOB_COPY
    sta (sched_ptr),y
    // Backward memmove iff src < dst <= inclusive source end.
    ldx #2
!:
    lda VM_P,x
    cmp VM_P+3,x
    bne jobs_overlap_order
    dex
    bpl !-
    jmp jobs_job_ready
jobs_overlap_order:
    bcc jobs_job_ready
    ldx #2
!:
    lda VM_P,x
    cmp sched_bytes,x
    bne jobs_overlap_end
    dex
    bpl !-
    bmi jobs_backward
jobs_overlap_end:
    bcs jobs_job_ready
jobs_backward:
    lda #JOB_COPY_BACKWARD
    ldy #SP_JOB
    sta (sched_ptr),y
    // Source end was validated above. Compute destination end identically.
    ldy #SP_SRC
    .for (var i=0;i<3;i++) {
        lda sched_bytes+i
        sta (sched_ptr),y
        iny
    }
    .for (var i=0;i<3;i++) {
        lda VM_P+i
        sta sched_address+i
    }
    jsr jobs_end
    ldy #SP_DST
    .for (var i=0;i<3;i++) {
        lda sched_bytes+i
        sta (sched_ptr),y
        iny
    }
    jmp jobs_job_ready
jobs_fill_ready:
    ldy #SP_VALUE
    lda VM_R+2
    sta (sched_ptr),y
    iny
    sta (sched_ptr),y
    iny
    sta (sched_ptr),y
jobs_job_ready:
    lda #PROC_WAIT_JOB
    ldy #SP_STATE
    sta (sched_ptr),y
jobs_bind_generation:
    ldy #SP_GENERATION
    lda VM_GENERATION
    sta (sched_ptr),y
    iny
    lda VM_GENERATION+1
    sta (sched_ptr),y
    rts

// Validate the complete nonempty range before any chunk. kind1 means write.
jobs_validate:
    jsr jobs_end
    bcs jobs_validate_bad
    ldx #2
!:
    lda sched_address,x
    cmp VM_ARENA_FIRST,x
    bne jobs_validate_first
    dex
    bpl !-
    bmi jobs_validate_last
jobs_validate_first:
    bcc jobs_validate_bad
jobs_validate_last:
    ldx #2
!:
    lda sched_bytes,x
    cmp VM_ARENA_LAST,x
    bne jobs_validate_end
    dex
    bpl !-
    bmi jobs_validate_code
jobs_validate_end:
    bcs jobs_validate_bad
jobs_validate_code:
    lda sched_kind
    beq jobs_validate_ok
    ldx #2
!:
    lda sched_address,x
    cmp VM_CODE_LAST,x
    bne jobs_validate_code_start
    dex
    bpl !-
    bmi jobs_validate_code_end
jobs_validate_code_start:
    bcs jobs_validate_ok
jobs_validate_code_end:
    ldx #2
!:
    lda sched_bytes,x
    cmp VM_CODE_FIRST,x
    bne jobs_validate_code_finish
    dex
    bpl !-
    bmi jobs_validate_readonly
jobs_validate_code_finish:
    bcc jobs_validate_ok
jobs_validate_readonly:
    lda #9
    sec
    rts
jobs_validate_bad:
    lda #2
    sec
    rts
jobs_validate_ok:
    lda #0
    clc
    rts
jobs_end:
    // Inclusive end = address + (length-1), retaining overflow after byte3.
    sec
    lda sched_value
    sbc #1
    sta sched_bytes
    lda sched_value+1
    sbc #0
    sta sched_bytes+1
    lda sched_value+2
    sbc #0
    sta sched_bytes+2
    clc
    .for (var i=0;i<3;i++) {
        lda sched_address+i
        adc sched_bytes+i
        sta sched_bytes+i
    }
    rts

// At most one coherent scalar transfer. A split copy keeps its local value.
jobs_step:
    ldy #SP_GENERATION
    lda (sched_ptr),y
    cmp VM_GENERATION
    beq !+
    jmp jobs_stale
!:
    iny
    lda (sched_ptr),y
    cmp VM_GENERATION+1
    beq !+
    jmp jobs_stale
!:
    lda VM_PENDING
    bne !+
    jmp jobs_stale
!:
    ldy #SP_LEFT+2
    lda (sched_ptr),y
    dey
    ora (sched_ptr),y
    bne jobs_three
    dey
    lda (sched_ptr),y
    cmp #3
    bcs jobs_three
    bcc jobs_width
jobs_three:
    lda #3
jobs_width:
    sta sched_width
    sta CACHE_WIDTH
    ldy #SP_JOB
    lda (sched_ptr),y
    sta sched_kind
    cmp #JOB_FILL
    beq jobs_write_phase
    ldy #SP_PHASE
    lda (sched_ptr),y
    bne jobs_write_phase
    ldy #SP_SRC
    jsr jobs_scalar_address
    jsr cache_native_read
    bcc !+
    jmp jobs_deferred
!:
    ldy #SP_VALUE
    .for (var i=0;i<3;i++) {
        lda CACHE_VALUE+i
        sta (sched_ptr),y
        iny
    }
    lda #1
    ldy #SP_PHASE
    sta (sched_ptr),y
    jmp jobs_chunk_done
jobs_write_phase:
    ldy #SP_DST
    jsr jobs_scalar_address
    ldy #SP_VALUE
    .for (var i=0;i<3;i++) {
        lda (sched_ptr),y
        sta CACHE_VALUE+i
        iny
    }
    jsr cache_native_write
    bcc !+
    jmp jobs_deferred
!:
    lda #0
    ldy #SP_PHASE
    sta (sched_ptr),y
    clc
    ldy #SP_NATIVE_BYTES
    lda (sched_ptr),y
    adc sched_width
    sta (sched_ptr),y
    .for (var i=1;i<4;i++) {
        iny
        lda (sched_ptr),y
        adc #0
        sta (sched_ptr),y
    }
    sec
    ldy #SP_LEFT
    lda (sched_ptr),y
    sbc sched_width
    sta (sched_ptr),y
    sta sched_value
    .for (var i=1;i<3;i++) {
        iny
        lda (sched_ptr),y
        sbc #0
        sta (sched_ptr),y
        sta sched_value+i
    }
    lda sched_value
    ora sched_value+1
    ora sched_value+2
    beq jobs_finished
    ldy #SP_DST
    jsr jobs_advance
    ldy #SP_SRC
    jsr jobs_advance
jobs_chunk_done:
    ldy #SP_NATIVE_CHUNKS
    lda (sched_ptr),y
    clc
    adc #1
    sta (sched_ptr),y
    .for (var i=1;i<4;i++) {
        iny
        lda (sched_ptr),y
        adc #0
        sta (sched_ptr),y
    }
    clc
    rts
jobs_finished:
    jsr jobs_chunk_done
    lda #0
    jsr jobs_complete
    clc
    rts
jobs_stale:
    lda #0
    ldy #SP_JOB
    sta (sched_ptr),y
    sec
    rts
jobs_deferred:
    sec
    rts
jobs_scalar_address:
    .for (var i=0;i<3;i++) {
        lda (sched_ptr),y
        sta CACHE_ADDR+i
        iny
    }
    lda sched_kind
    cmp #JOB_COPY_BACKWARD
    bne !+
    lda sched_width
    sec
    sbc #1
    sta sched_extra
    sec
    lda CACHE_ADDR
    sbc sched_extra
    sta CACHE_ADDR
    lda CACHE_ADDR+1
    sbc #0
    sta CACHE_ADDR+1
    lda CACHE_ADDR+2
    sbc #0
    sta CACHE_ADDR+2
!:
    rts
jobs_advance:
    lda sched_kind
    cmp #JOB_COPY_BACKWARD
    beq jobs_retreat
    clc
    lda (sched_ptr),y
    adc sched_width
    sta (sched_ptr),y
    .for (var i=1;i<3;i++) {
        iny
        lda (sched_ptr),y
        adc #0
        sta (sched_ptr),y
    }
    rts
jobs_retreat:
    sec
    lda (sched_ptr),y
    sbc sched_width
    sta (sched_ptr),y
    .for (var i=1;i<3;i++) {
        iny
        lda (sched_ptr),y
        sbc #0
        sta (sched_ptr),y
    }
    rts

// Job completion is accepted once, for the active matching incarnation only.
jobs_complete:
    pha
    lda VM_PENDING
    beq jobs_complete_stale
    ldy #SP_GENERATION
    lda (sched_ptr),y
    cmp VM_GENERATION
    bne jobs_complete_stale
    iny
    lda (sched_ptr),y
    cmp VM_GENERATION+1
    bne jobs_complete_stale
    ldy #SP_JOB
    lda (sched_ptr),y
    beq jobs_complete_stale
    lda #0
    sta (sched_ptr),y
    pla
    jsr jobs_return
    lda #PROC_RUNNABLE
    ldy #SP_STATE
    sta (sched_ptr),y
    lda VM_SLOT
    tax
    lda scheduler_owner_bits,x
    ora SCHED_DISPATCH_MASK
    sta SCHED_DISPATCH_MASK
    txa
    asl
    tax
    inc SCHED_COMPLETIONS,x
    bne !+
    inc SCHED_COMPLETIONS+1,x
!:
    lda VM_SLOT
    asl
    asl
    tax
    .for (var i=0;i<4;i++) {
        lda SCHED_FRAME+i
        sta SCHED_WOKE+i,x
    }
    lda VM_SLOT
    jmp scheduler_enqueue
jobs_complete_stale:
    pla
    sec
    rts
jobs_return:
    sta VM_R
    lda #0
    sta VM_R+1
    sta VM_PENDING
    sta VM_OUTCOME
    rts

jobs_unsupported:
    lda #6
    sta sched_extra
    lda VM_SYSCALL_ID
    cmp #$0e
    bcc jobs_known
    cmp #$20
    bcc jobs_error_outputs
    cmp #$2e
    bcc jobs_known
    cmp #$30
    beq jobs_known
    cmp #$40
    bcc jobs_error_outputs
    cmp #$44
    bcc jobs_known
    cmp #$50
    bcc jobs_error_outputs
    cmp #$57
    bcc jobs_known
    cmp #$60
    bcc jobs_error_outputs
    cmp #$62
    bcc jobs_known
    cmp #$70
    bcc jobs_error_outputs
    cmp #$74
    bcs jobs_error_outputs
jobs_known:
    lda #11
    sta sched_extra
jobs_error_outputs:
    ldx #0
!:
    lda jobs_output_ids,x
    cmp VM_SYSCALL_ID
    beq jobs_clear_outputs
    inx
    cpx #16
    bne !-
    jmp jobs_error_return
jobs_clear_outputs:
    lda jobs_output_masks,x
    sta sched_phase
    ldx #0
!:
    lsr sched_phase
    bcc !+
    lda #0
    sta VM_R,x
    sta VM_R+1,x
!:
    inx
    inx
    cpx #16
    bne !--
jobs_error_return:
    lda sched_extra
    jmp jobs_return
jobs_output_ids:
    .byte $05,$20,$28,$29,$40,$50,$56,$22,$23,$25,$26,$61,$0d,$30,$72,$ff
jobs_output_masks:
    .byte $02,$02,$02,$02,$02,$02,$02,$06,$06,$06,$06,$06,$1e,$0c,$0e,$00
jobs_module_end:
