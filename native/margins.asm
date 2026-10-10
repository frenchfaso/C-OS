#importonce
#import "m2_abi.inc"
// Optional CPU-local phase preparation. No timing profile is qualified in M2.
// This private record is never a userspace ABI or a second scheduler.
.const MARGIN_RECORD = $1080
.const MARGIN_RECORD_BYTES = 32
.const MARGIN_PRIVATE = $10a0
.const MARGIN_PRIVATE_BYTES = 16
.const MARGIN_IDLE = 0
.const MARGIN_DRAFT = 1
.const MARGIN_READY = 2
.const MARGIN_RUNNING = 3
.const MARGIN_DONE = 4
.const MARGIN_CANCELLED = 5
.const MARGIN_ROUTINE_XOR = 1
.const MARGIN_MAX_CYCLES = 512
.const MARGIN_CLOBBER_A_FLAGS = $09
.label margin_state = MARGIN_RECORD
.label margin_routine = MARGIN_RECORD+1
.label margin_owner = MARGIN_RECORD+2
.label margin_generation = MARGIN_RECORD+3
.label margin_bound = MARGIN_RECORD+5
.label margin_clobbers = MARGIN_RECORD+7
.label margin_owned = MARGIN_RECORD+8
.label margin_input_a = MARGIN_RECORD+9
.label margin_input_b = MARGIN_RECORD+10
.label margin_result = MARGIN_RECORD+11
.label margin_continuation = MARGIN_RECORD+12
.label margin_entitlement = MARGIN_RECORD+13
.label margin_useful_work = MARGIN_RECORD+14
.label margin_completions = MARGIN_RECORD+15
.label margin_live_owner = MARGIN_RECORD+16
.label margin_live_generation = MARGIN_RECORD+17
.label margin_pid = MARGIN_RECORD+19
.label margin_live_pid = MARGIN_RECORD+21
.label margin_buffer = MARGIN_RECORD+23
.label margin_qualified = MARGIN_RECORD+25
.label margin_actual_cost = MARGIN_RECORD+26

margin_module_start:
// Outside-raster initialization only; A/X/flags are scratch.
margin_reset:
    lda #0
    ldx #MARGIN_RECORD_BYTES+MARGIN_PRIVATE_BYTES-1
!:
    sta MARGIN_RECORD,x
    dex
    bpl !-
    rts

// Outside-raster handoff: A is the existing native service entitlement.
// The ordinary path cedes the private buffer until consume/discard.
margin_prepare_begin:
    cmp #0
    beq margin_reject
    ldx margin_state
    bne margin_reject
    sta margin_entitlement
    lda VM_SLOT
    sta margin_owner
    sta margin_live_owner
    lda VM_GENERATION
    sta margin_generation
    sta margin_live_generation
    lda VM_GENERATION+1
    sta margin_generation+1
    sta margin_live_generation+1
    lda VM_PID
    sta margin_pid
    sta margin_live_pid
    lda VM_PID+1
    sta margin_pid+1
    sta margin_live_pid+1
    lda #MARGIN_ROUTINE_XOR
    sta margin_routine
    sta margin_owned
    sta margin_continuation
    lda #<MARGIN_MAX_CYCLES
    sta margin_bound
    lda #>MARGIN_MAX_CYCLES
    sta margin_bound+1
    lda #MARGIN_CLOBBER_A_FLAGS
    sta margin_clobbers
    lda #<MARGIN_PRIVATE
    sta margin_buffer
    lda #>MARGIN_PRIVATE
    sta margin_buffer+1
    lda #0
    sta margin_useful_work
    sta margin_actual_cost
    sta margin_actual_cost+1
    sta margin_qualified
    lda #MARGIN_DRAFT
    sta margin_state
    clc
    rts
margin_reject:
    sec
    rts

// All record fields and local inputs precede the final atomic READY store.
margin_publish:
    lda margin_state
    cmp #MARGIN_DRAFT
    bne margin_reject
    jsr margin_record_valid
    bcs margin_reject
    lda #MARGIN_READY
    sta margin_state
    clc
    rts

// Reads only the private ownership snapshot. Slot reuse revokes it outside IRQ.
margin_same_owner:
    lda margin_owner
    cmp margin_live_owner
    bne margin_reject
    lda margin_generation
    cmp margin_live_generation
    bne margin_reject
    lda margin_generation+1
    cmp margin_live_generation+1
    bne margin_reject
    lda margin_pid
    cmp margin_live_pid
    bne margin_reject
    lda margin_pid+1
    cmp margin_live_pid+1
    bne margin_reject
    clc
    rts
margin_record_valid:
    jsr margin_same_owner
    bcs margin_reject
    lda margin_owned
    cmp #1
    bne margin_reject
    lda margin_entitlement
    beq margin_reject
    lda margin_routine
    cmp #MARGIN_ROUTINE_XOR
    bne margin_reject
    lda margin_clobbers
    cmp #MARGIN_CLOBBER_A_FLAGS
    bne margin_reject
    lda margin_bound
    cmp #<MARGIN_MAX_CYCLES
    bne margin_reject
    lda margin_bound+1
    cmp #>MARGIN_MAX_CYCLES
    bne margin_reject
    lda margin_buffer
    cmp #<MARGIN_PRIVATE
    bne margin_reject
    lda margin_buffer+1
    cmp #>MARGIN_PRIVATE
    bne margin_reject
    clc
    rts

// Explicit ordinary-path test service. Never called by the default renderer.
// Claim before the body; duplicate, partial or stale records perform no work.
margin_claim_outside:
    php
    sei
    lda margin_state
    cmp #MARGIN_READY
    bne margin_claim_locked_reject
    jsr margin_record_valid
    bcs margin_claim_locked_stale
    lda #MARGIN_RUNNING
    sta margin_state
    plp
    jsr margin_private_body
    sta margin_result
    dec margin_entitlement
    inc margin_useful_work
    inc margin_completions
    lda #MARGIN_DONE
    sta margin_state
    clc
    rts
margin_claim_locked_stale:
    lda #MARGIN_CANCELLED
    sta margin_state
    lda #0
    sta margin_owned
margin_claim_locked_reject:
    plp
    sec
    rts
margin_claim_stale:
    lda #MARGIN_CANCELLED
    sta margin_state
    lda #0
    sta margin_owned
margin_claim_reject:
    sec
    rts
margin_private_body:
    lda margin_input_a
    eor margin_input_b
    sta MARGIN_PRIVATE
    rts

// Outside-raster consumption returns A=result and releases private ownership.
// The ordinary arbiter charges its measured cost and rotates the existing job.
margin_consume:
    lda margin_state
    cmp #MARGIN_DONE
    bne margin_claim_reject
    jsr margin_same_owner
    bcs margin_claim_stale
    lda #0
    sta margin_owned
    sta margin_state
    lda margin_result
    clc
    rts

// Called outside raster before cancelling/reusing owner X. IRQ sees no partial
// ownership transition; a RUNNING phase cannot be cancelled from its own body.
margin_revoke_owner:
    txa
    cmp margin_owner
    bne margin_claim_reject
    lda margin_state
    cmp #MARGIN_RUNNING
    beq margin_claim_reject
    php
    sei
    lda #MARGIN_CANCELLED
    sta margin_state
    lda #0
    sta margin_owned
    plp
    clc
    rts
margin_discard_cancelled:
    lda margin_state
    cmp #MARGIN_CANCELLED
    bne margin_claim_reject
    lda #0
    sta margin_state
    sta margin_owned
    clc
    rts

// Prepared call site after the final pixel. No qualified profile, admission
// clock or timing gate is supplied in M2, so even an explicit call stays idle.
margin_irq_hook:
    sec
    rts
margin_module_end:
