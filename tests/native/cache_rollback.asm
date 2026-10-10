#import "../../native/m2_abi.inc"
// 128 autonomous scenarios: request kind, write-back timing, cancellation order,
// victim revocation/reuse, and explicit/active-stale/saved-stale requester exit.
.const TEST_LINE = cmdLineVars.get("cacheLine").asNumber()
.assert "requested diagnostics profile", EXTENDED_DIAGNOSTICS==cmdLineVars.get("extendedDiagnostics").asNumber(), true
.const TEST = $0200
.const TEST_CASE = TEST
.const TEST_DMA = TEST+1
.const TEST_STASH = TEST+2
.const TEST_FETCH = TEST+4
.const TEST_NATIVE_VALUE = TEST+6
.const TEST_RETRY = TEST+7
.const TEST_DONE = TEST+$ff
.const TEST_ROW = $b0
.const TEST_ROWS = $3000
*=$1200
entry:
    sei
    cld
    ldx #$ff
    txs
    lda #$35
    sta $01
    lda #$2f
    sta $00
    lda #0
    sta $d01a
    sta $031c
    sta TEST_CASE
    sta TEST_DONE
    lda #$7f
    sta $dc0d
    sta $dd0d
    lda $dc0d
    lda $dd0d
    lda #$8f
    sta $d031
test_case:
    jsr cache_reset
    lda #0
    sta TEST_DMA
    sta TEST_STASH
    sta TEST_STASH+1
    sta TEST_FETCH
    sta TEST_FETCH+1
    lda #$cc
    sta TEST_NATIVE_VALUE
    lda TEST_CASE
    asl
    asl
    asl
    asl
    asl
    sta TEST_ROW
    lda TEST_CASE
    lsr
    lsr
    lsr
    clc
    adc #>TEST_ROWS
    sta TEST_ROW+1
    ldy #31
    lda #$cc
!:
    sta (TEST_ROW),y
    dey
    bpl !-
    lda TEST_CASE
    ldy #0
    sta (TEST_ROW),y
    lda #$34
    sta VM_PCB+91
    sta CACHE_GEN_LO+8
    lda #$12
    sta VM_PCB+92
    sta CACHE_GEN_HI+8
    lda #$78
    sta VM_PCB+128+91
    lda #$56
    sta VM_PCB+128+92
    lda #0
    sta CACHE_TAG_LO+8
    sta CACHE_OWNER+8
    lda TEST_CASE
    sta CACHE_TAG_MID+8
    lda #6
    sta CACHE_TAG_HI+8
    lda #(CACHE_VALID|CACHE_DIRTY)
    sta CACHE_FLAGS+8
    lda #$66
    ldx #0
!:
    sta CACHE_DATA,x
    inx
    cpx #TEST_LINE
    bne !-
    jsr activate_b
    lda TEST_CASE
    and #64
    bne request_native
    jsr arguments_b
    jsr cache_prepare
    jmp requested
request_native:
    jsr arguments_a
    jsr cache_native_read
requested:
    bcs !+
    jmp failed
!:
    ldy #1
    lda cache_pending_phase
    sta (TEST_ROW),y
    lda TEST_CASE
    and #32
    beq before_writeback
    jsr cache_service
    bcc !+
    jmp failed
!:
before_writeback:
    ldy #2
    lda cache_pending_phase
    sta (TEST_ROW),y
    lda TEST_CASE
    and #16
    bne requester_first
    jsr revoke_victim
    jsr cancel_requester
    jmp actions_done
requester_first:
    jsr cancel_requester
    jsr revoke_victim
actions_done:
    ldy #3
    lda cache_pending_phase
    sta (TEST_ROW),y
    iny
    lda CACHE_FLAGS+8
    sta (TEST_ROW),y
    iny
    lda cache_pending_old_flags
    sta (TEST_ROW),y
    iny
    lda TEST_DMA
    sta (TEST_ROW),y
    iny
    lda TEST_STASH
    sta (TEST_ROW),y
    iny
    lda TEST_STASH+1
    sta (TEST_ROW),y
    ldy #26
    lda cache_pending_owner
    sta (TEST_ROW),y
    iny
    lda CACHE_OWNER+8
    sta (TEST_ROW),y
    iny
    lda CACHE_GEN_LO+8
    sta (TEST_ROW),y
    iny
    lda CACHE_GEN_HI+8
    sta (TEST_ROW),y
    // A stale native continuation is explicitly observed and retired before
    // any new incarnation attaches. It must not execute the old scalar read.
    lda TEST_CASE
    and #3
    cmp #3
    beq finish_original
    lda TEST_CASE
    and #64
    beq original_done
    lda cache_native_active
    beq original_done
    jsr activate_b
    jsr arguments_a
    jsr cache_native_read
    jmp original_done
finish_original:
    lda #16
    sta TEST_RETRY
original_retry:
    jsr activate_b
    lda TEST_CASE
    and #64
    beq original_cache_retry
    jsr arguments_a
    jsr cache_native_read
    bcs original_service
    lda CACHE_VALUE
    sta TEST_NATIVE_VALUE
    jmp original_done
original_cache_retry:
    jsr arguments_b
    jsr cache_prepare
    bcs original_service
    jsr cache_unpin
    jmp original_done
original_service:
    jsr cache_service
    dec TEST_RETRY
    bne original_retry
    jmp failed
original_done:
    ldy #9
    lda CACHE_FLAGS+8
    sta (TEST_ROW),y
    iny
    lda cache_native_active
    asl
    asl
    asl
    asl
    ora cache_pending_phase
    sta (TEST_ROW),y
    // Real CLOCK pressure after cancellation must never STASH revoked bytes.
    lda #0
    sta cache_clock
    lda #16
    sta TEST_RETRY
pressure_retry:
    jsr activate_b
    jsr arguments_b
    jsr cache_prepare
    bcc pressure_done
    jsr cache_service
    dec TEST_RETRY
    bne pressure_retry
    jmp failed
pressure_done:
    jsr cache_read_prepared
    lda CACHE_VALUE
    ldy #24
    sta (TEST_ROW),y
    jsr cache_unpin
    ldy #11
    lda CACHE_FLAGS+8
    sta (TEST_ROW),y
    iny
    lda TEST_DMA
    sta (TEST_ROW),y
    iny
    lda TEST_STASH
    sta (TEST_ROW),y
    iny
    lda TEST_STASH+1
    sta (TEST_ROW),y
    ldy #16
    lda TEST_FETCH
    sta (TEST_ROW),y
    iny
    lda TEST_FETCH+1
    sta (TEST_ROW),y
    iny
    lda CACHE_OWNER+8
    sta (TEST_ROW),y
    iny
    lda CACHE_GEN_LO+8
    sta (TEST_ROW),y
    iny
    lda CACHE_GEN_HI+8
    sta (TEST_ROW),y
    iny
    lda CACHE_TAG_LO+8
    sta (TEST_ROW),y
    iny
    lda CACHE_TAG_MID+8
    sta (TEST_ROW),y
    iny
    lda CACHE_TAG_HI+8
    sta (TEST_ROW),y
    ldy #25
    lda TEST_NATIVE_VALUE
    sta (TEST_ROW),y
    ldy #30
    lda cache_dma_error
    sta (TEST_ROW),y
    iny
    lda #$55
    sta (TEST_ROW),y
    inc TEST_CASE
    lda TEST_CASE
    cmp #128
    beq complete
    jmp test_case
complete:
    lda #$55
    sta TEST_DONE
halt:
    jmp halt
failed:
    lda #$80
    ldy #31
    sta (TEST_ROW),y
    lda TEST_CASE
    ora #$80
    sta TEST_DONE
    jmp halt
activate_a:
    lda #0
    sta VM_SLOT
    lda VM_PCB+91
    sta VM_GENERATION
    lda VM_PCB+92
    sta VM_GENERATION+1
    rts
activate_b:
    lda #1
    sta VM_SLOT
    lda VM_PCB+128+91
    sta VM_GENERATION
    lda VM_PCB+128+92
    sta VM_GENERATION+1
    rts
arguments_a:
    lda #6
    bne arguments
arguments_b:
    lda #7
arguments:
    sta CACHE_ADDR+2
    lda #0
    sta CACHE_ADDR
    lda TEST_CASE
    sta CACHE_ADDR+1
    lda #1
    sta CACHE_WIDTH
    rts
revoke_victim:
    lda TEST_CASE
    and #12
    beq victim_done
    jsr activate_a
    lda TEST_CASE
    and #12
    cmp #12
    beq victim_stale
    jsr cache_invalidate_owner
    lda TEST_CASE
    and #12
    cmp #4
    beq victim_done
    inc VM_PCB+91
    inc VM_GENERATION
    jmp reuse_arena
victim_stale:
    inc VM_PCB+92
    inc VM_GENERATION+1
reuse_arena:
    // Trusted diagnostic patch after incarnation revocation. Reusing this
    // physical arena must not be undone by an obsolete dirty buffer later.
    jsr arguments_a
    lda #TEST_LINE
    sta CACHE_WIDTH
    lda #0
    sta CACHE_LOCAL
    lda #$10
    sta CACHE_LOCAL+1
    ldx #0
    lda #$77
!:
    sta $1000,x
    inx
    cpx #TEST_LINE
    bne !-
    lda #$90
    jsr cache_dma_transfer
    bcc victim_done
    jmp failed
victim_done:
    rts
cancel_requester:
    lda TEST_CASE
    and #3
    cmp #3
    beq requester_done
    jsr activate_b
    lda TEST_CASE
    and #3
    beq requester_explicit
    cmp #1
    bne requester_saved_stale
    inc VM_PCB+128+91
    inc VM_GENERATION
    jmp requester_stale
requester_saved_stale:
    inc VM_PCB+128+92
    // Requester B is saved; victim A is active for the rollback liveness check.
    jsr activate_a
requester_stale:
    jsr cache_service
requester_done:
    rts
requester_explicit:
    jsr cache_invalidate_owner
    rts
vm_dma_admit:
    clc
    rts
vm_dma_completed:
    // Independent physical-transaction observations, also present in normal
    // builds where the cache's extended counters are compiled away.
    inc TEST_DMA
    // A still contains the command just written to DF01.
    cmp #$90
    bne observed_fetch
    lda CACHE_WIDTH
    clc
    adc TEST_STASH
    sta TEST_STASH
    bcc observed_done
    inc TEST_STASH+1
observed_done:
    rts
observed_fetch:
    lda CACHE_WIDTH
    clc
    adc TEST_FETCH
    sta TEST_FETCH
    bcc observed_done
    inc TEST_FETCH+1
    rts
#import "../../native/cache.asm"
.assert "fixture code must not overlap result rows", * <= TEST_ROWS, true
