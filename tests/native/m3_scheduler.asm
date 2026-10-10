#import "m2_abi.inc"
#import "scheduler.inc"
.const REPORT=$0300
.const PACK_APP_COUNT=4
.const TEST_REPORT=$03e0
.macro expect(value) {
    cmp #value
    beq !+
    sta TEST_REPORT+6
    lda #value
    sta TEST_REPORT+7
    inc TEST_REPORT+4
    jmp test_done
!:
    inc TEST_REPORT+5
}
*=$1200 "Independent native M3 contract checks"
test_start:
    sei
    cld
    ldx #$ff
    txs
    lda #$35
    sta $01
    lda #0
    sta VM_VIDEO
    sta VM_SLOT
    ldx #95
!:
    sta VM_STATE,x
    dex
    bpl !-
    lda #4
    sta VM_ARENA_FIRST+2
    sta VM_ARENA_LAST+2
    sta VM_CODE_FIRST+2
    sta VM_CODE_LAST+2
    sta VM_HEAP_FIRST+2
    sta VM_HEAP_LAST+2
    sta VM_STACK_FIRST+2
    sta VM_STACK_LAST+2
    sta VM_PC+2
    sta VM_SP+2
    lda #$ff
    sta VM_ARENA_LAST
    sta VM_ARENA_LAST+1
    sta VM_CODE_LAST
    sta VM_HEAP_LAST
    sta VM_STACK_LAST
    sta VM_STACK_LAST+1
    sta VM_SP
    sta VM_SP+1
    lda #1
    sta VM_HEAP_FIRST+1
    sta VM_GENERATION
    lda #$fb
    sta VM_HEAP_LAST+1
    lda #$fc
    sta VM_STACK_FIRST+1
    lda #83
    sta VM_FUEL
    jsr vm_save_context
    inc VM_SLOT
    jsr vm_save_context
    inc VM_SLOT
    jsr vm_save_context
    inc VM_SLOT
    jsr vm_save_context
    jsr scheduler_init
    lda #0
    sta SCHED_CONTROL
    sta TEST_REPORT+4
    sta TEST_REPORT+5
    lda #'M'
    sta TEST_REPORT
    lda #'S'
    sta TEST_REPORT+1
    lda #'3'
    sta TEST_REPORT+2
    lda #1
    sta TEST_REPORT+3
    lda #0
    jsr scheduler_select
    // Seed physical bytes0..31 and guard bytes32..95 independently.
    ldx #95
    lda #$5a
!:
    sta $1000,x
    dex
    bpl !-
    ldx #31
!:
    txa
    sta $1000,x
    dex
    bpl !-
    lda #0
    sta CACHE_ADDR
    lda #1
    sta CACHE_ADDR+1
    lda #4
    sta CACHE_ADDR+2
    lda #96
    sta CACHE_WIDTH
    lda #0
    sta CACHE_LOCAL
    lda #$10
    sta CACHE_LOCAL+1
    lda #$90
    jsr cache_dma_transfer
    // Full-range invalid requests must neither enqueue nor transfer a byte.
    jsr test_fill_args
    lda #1
    sta VM_R+3
    jsr jobs_accept
    lda VM_R
    :expect(1)
    jsr test_fill_args
    lda #1
    sta VM_R+7
    jsr jobs_accept
    lda VM_R
    :expect(2)
    jsr test_fill_args
    lda #0
    sta VM_P+1
    jsr jobs_accept
    lda VM_R
    :expect(9)
    jsr test_fill_args
    lda #$ff
    sta VM_P
    sta VM_P+1
    jsr jobs_accept
    lda VM_R
    :expect(2)
    jsr test_fill_args
    lda #0
    sta VM_R+4
    lda #$ff
    sta VM_P
    sta VM_P+1
    sta VM_P+2
    jsr jobs_accept
    lda VM_R
    :expect(0)
    lda VM_PENDING
    :expect(0)
    // Fill17 bytes, preserving both guards and remaining opcode credit.
    jsr test_fill_args
    jsr jobs_accept
    jsr test_drive
    lda VM_FUEL
    :expect(83)
    lda VM_R
    :expect(0)
    // A consumed completion stays inert on replay.
    lda #23
    jsr jobs_complete
    bcs !+
    inc TEST_REPORT+4
    jmp test_done
!:
    inc TEST_REPORT+5
    lda SCHED_COMPLETIONS
    :expect(1)
    lda VM_R
    :expect(0)
    jsr test_fetch
    lda $1140
    :expect($a5)
    lda $1150
    :expect($a5)
    lda $113f
    :expect($5a)
    lda $1151
    :expect($5a)
    // Backward then forward overlap has independent complete byte expectations.
    jsr test_copy_args
    jsr jobs_accept
    jsr test_drive
    jsr test_fetch
    ldx #31
test_backward_expected:
    txa
    sec
    sbc #1
    cmp $1100,x
    beq !+
    inc TEST_REPORT+4
    jmp test_done
!:
    inc TEST_REPORT+5
    dex
    bne test_backward_expected
    jsr test_copy_args
    lda #0
    sta VM_P
    lda #1
    sta VM_P+3
    jsr jobs_accept
    jsr test_drive
    jsr test_fetch
    ldx #30
test_forward_expected:
    txa
    cmp $1100,x
    beq !+
    inc TEST_REPORT+4
    jmp test_done
!:
    inc TEST_REPORT+5
    dex
    bpl test_forward_expected
    lda VM_FUEL
    :expect(83)
    lda SCHED_COMPLETIONS
    :expect(3)
    // Positive sleep wakes through unsigned frame wrap and requests one quantum.
    lda #$ff
    sta SCHED_FRAME+1
    sta SCHED_FRAME+2
    sta SCHED_FRAME+3
    lda #$fe
    sta SCHED_FRAME
    lda #1
    sta VM_PENDING
    lda #3
    sta VM_SYSCALL_ID
    lda #2
    sta VM_R
    lda #0
    sta VM_R+1
    jsr jobs_accept
    jsr scheduler_frame_tick
    jsr scheduler_wake_timed
    ldy #SP_STATE
    lda (sched_ptr),y
    :expect(PROC_SLEEPING)
    jsr scheduler_frame_tick
    jsr scheduler_wake_timed
    lda SCHED_FRAME
    :expect(0)
    lda VM_R
    :expect(0)
    ldy #SP_REFILL
    lda (sched_ptr),y
    :expect(1)
    // Immediate poll is an explicit trusted-harness handle, never a free quantum.
    lda #1
    sta SCHED_WINDOWS
    sta VM_R+2
    sta VM_PENDING
    lda #0
    sta VM_R+3
    sta VM_R
    sta VM_R+1
    lda #7
    sta VM_FUEL
    lda #4
    sta VM_SYSCALL_ID
    lda #$ff
    sta VM_P
    sta VM_P+1
    sta VM_P+2
    jsr jobs_accept
    lda VM_R
    :expect(2)
    lda VM_FUEL
    :expect(7)
    lda #$40
    sta VM_P
    lda #1
    sta VM_P+1
    sta VM_PENDING
    lda #4
    sta VM_P+2
    lda #0
    sta VM_R
    jsr jobs_accept
    lda VM_R
    :expect(4)
    lda VM_FUEL
    :expect(7)
    lda VM_PENDING
    :expect(0)
    lda #1
    sta VM_PENDING
    lda #2
    sta VM_R
    jsr jobs_accept
    ldy #SP_STATE
    lda (sched_ptr),y
    :expect(PROC_WAIT_EVENT)
    lda VM_FUEL
    :expect(7)
    jsr scheduler_frame_tick
    jsr scheduler_frame_tick
    jsr scheduler_wake_timed
    lda VM_R
    :expect(4)
    ldy #SP_REFILL
    lda (sched_ptr),y
    :expect(1)
    // Old completion cannot mutate a replacement or grant credit.
    jsr test_fill_args
    jsr jobs_accept
    inc VM_GENERATION
    lda #23
    jsr jobs_complete
    bcs !+
    inc TEST_REPORT+4
    jmp test_done
!:
    inc TEST_REPORT+5
    lda VM_FUEL
    :expect(83)
    lda VM_PENDING
    :expect(1)
    jsr scheduler_revoke_for_replace
    lda VM_GENERATION
    :expect(3)
    ldy #SP_JOB
    lda (sched_ptr),y
    :expect(0)
    lda cache_native_active
    :expect(0)
    // Build a fresh trusted context, bounded arena seed precedes publication.
    ldx #95
!:
    lda VM_STATE,x
    sta M2_COMPLETION,x
    dex
    bpl !-
    lda #0
    sta M2_COMPLETION+69
    sta M2_COMPLETION+90
    // Seed replacement-owned bytes after revoke, before making it runnable.
    lda #$6b
    sta $1000
    lda #0
    sta CACHE_ADDR
    sta CACHE_LOCAL
    lda #1
    sta CACHE_ADDR+1
    sta CACHE_WIDTH
    lda #4
    sta CACHE_ADDR+2
    lda #$10
    sta CACHE_LOCAL+1
    lda #$90
    jsr cache_dma_transfer
    jsr scheduler_install_replacement
    lda VM_GENERATION
    :expect(3)
    ldy #SP_STATE
    lda (sched_ptr),y
    :expect(PROC_RUNNABLE)
    lda VM_PENDING
    :expect(0)
    jsr test_fetch
    lda $1100
    :expect($6b)
    // Simulate a fresh pending request and an old generation completion packet.
    jsr test_fill_args
    jsr jobs_accept
    ldy #SP_GENERATION
    lda #1
    sta (sched_ptr),y
    lda #23
    jsr jobs_complete
    bcs !+
    inc TEST_REPORT+4
    jmp test_done
!:
    inc TEST_REPORT+5
    lda VM_PENDING
    :expect(1)
    lda VM_FUEL
    :expect(83)
    lda VM_R
    :expect(4)
    lda VM_GENERATION
    :expect(3)
    // One driver wakes multiple WAIT_REU owners at queue tail, preserving credit.
    lda #0
    sta SCHED_COUNT
    sta VM_PCB+96
    sta VM_PCB+128+96
    sta VM_PCB+256+96
    sta VM_PCB+384+96
    sta VM_PCB+97
    sta VM_PCB+128+97
    lda #PROC_WAIT_REU
    sta VM_PCB+96
    sta VM_PCB+128+96
    lda #7
    sta VM_PCB+34
    lda #9
    sta VM_PCB+128+34
    jsr scheduler_wake_reu
    lda SCHED_COUNT
    :expect(2)
    lda SCHED_READY
    :expect(0)
    lda SCHED_READY+1
    :expect(1)
    lda VM_PCB+96
    :expect(PROC_RUNNABLE)
    lda VM_PCB+128+96
    :expect(PROC_RUNNABLE)
    lda VM_PCB+97
    :expect(0)
    lda VM_PCB+128+97
    :expect(0)
    lda VM_PCB+34
    :expect(7)
    lda VM_PCB+128+34
    :expect(9)
    // Cancelling the live single driver must release unrelated waiters too.
    lda #0
    sta SCHED_COUNT
    sta CACHE_ADDR
    sta CACHE_ADDR+1
    lda #4
    sta CACHE_ADDR+2
    lda #PROC_WAIT_REU
    sta VM_PCB+96
    sta VM_PCB+128+96
    jsr cache_fetch_code
    lda cache_pending_phase
    :expect(2)
    jsr scheduler_cancel_current
    lda cache_pending_phase
    :expect(0)
    lda SCHED_COUNT
    :expect(1)
    lda SCHED_READY
    :expect(1)
    lda VM_PCB+96
    :expect(PROC_STOPPED)
    lda VM_PCB+128+96
    :expect(PROC_RUNNABLE)
    lda VM_PCB+128+34
    :expect(9)
    lda VM_PCB+128+97
    :expect(0)
    lda VM_PENDING
    :expect(0)
    tsx
    txa
    :expect($ff)
test_done:
    jmp test_done
test_fill_args:
    lda #1
    sta VM_PENDING
    lda #$0a
    sta VM_SYSCALL_ID
    lda #$a5
    sta VM_R+2
    lda #17
    sta VM_R+4
    lda #$40
    sta VM_P
    lda #1
    sta VM_P+1
    lda #4
    sta VM_P+2
    lda #0
    sta VM_R+3
    sta VM_R+5
    sta VM_R+6
    sta VM_R+7
    lda #83
    sta VM_FUEL
    rts
test_copy_args:
    jsr test_fill_args
    lda #$0b
    sta VM_SYSCALL_ID
    lda #31
    sta VM_R+4
    lda #1
    sta VM_P
    sta VM_P+4
    lda #0
    sta VM_P+3
    lda #4
    sta VM_P+5
    rts
test_drive:
    jsr jobs_step
    lda cache_pending_phase
    beq !+
    jsr cache_service
!:
    lda VM_PENDING
    bne test_drive
    rts
test_fetch:
    lda #0
    sta CACHE_ADDR
    sta CACHE_LOCAL
    lda #1
    sta CACHE_ADDR+1
    lda #4
    sta CACHE_ADDR+2
    lda #$11
    sta CACHE_LOCAL+1
    lda #96
    sta CACHE_WIDTH
    lda #$91
    jsr cache_dma_transfer
    rts
.assert "native contract harness does not overlap resident modules", * <= $1b00, true
*=$1b00 "Real interpreter, caches, scheduler and jobs"
scheduler_video_admit:
vm_video_admit:
vm_dma_admit:
    clc
    rts
vm_dma_completed:
    inc REPORT+$1d
    rts
margin_revoke_owner:
    sec
    rts
margin_discard_cancelled:
    rts
#import "vm.asm"
#import "cache.asm"
#import "scheduler.asm"
#import "jobs.asm"
.assert "native contract modules fit resident memory", * <= $4000, true
