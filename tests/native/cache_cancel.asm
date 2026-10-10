#import "../../native/m2_abi.inc"
// Independent target-level cache cancellation/coherence fixture. The host
// preloads a private 16 MiB REU image filled with $a5; no renderer is enabled.
.const TEST = $0300
.const TEST_LINE = cmdLineVars.get("cacheLine").asNumber()
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
    sta TEST+$1c
    lda #$7f
    sta $dc0d
    sta $dd0d
    lda $dc0d
    lda $dd0d
    lda #$8f
    sta $d031
    jsr cache_reset
    lda #0
    sta VM_SLOT
    sta VM_GENERATION+1
    sta VM_PCB+92
    sta TEST+4
    sta TEST+5
    sta TEST+11
    lda #1
    sta VM_GENERATION
    sta VM_PCB+91
    sta TEST
    sta TEST+7
    lda #6
    sta TEST+6
    // Fill all eight CLOCK lines for A, each dirty with a distinct first byte.
fill_a:
    lda TEST+11
    clc
    adc #$40
    sta TEST+8
    jsr test_store
    lda TEST+4
    clc
    adc #TEST_LINE
    sta TEST+4
    bcc !+
    inc TEST+5
!:
    inc TEST+11
    lda TEST+11
    cmp #8
    bne fill_a
    inc TEST
    // B's ninth data line must reserve an A dirty victim for STASH.
    lda #1
    sta VM_SLOT
    lda #0
    sta TEST+4
    sta TEST+5
    lda #7
    sta TEST+6
    jsr restore_args
    jsr cache_prepare
    bcs !+
    jmp failed
!:
    lda cache_pending_phase
    cmp #1
    beq !+
    jmp failed
!:
    lda cache_pending_owner
    cmp #1
    beq !+
    jmp failed
!:
    // Cancel B before either DMA direction: every A dirty line survives.
    jsr cache_invalidate_owner
    lda #2
    sta VM_GENERATION
    jsr cache_service
    lda cache_pending_phase
    beq !+
    jmp failed
!:
    jsr check_a_dirty
    jsr check_eight_dma
    lda cache_stash_bytes
    ora cache_stash_bytes+1
    ora cache_stash_bytes+2
    ora cache_stash_bytes+3
    beq !+
    jmp failed
!:
    lda cache_dma_calls
    sta TEST+$30
    inc TEST
    // A must still read all its dirty bytes from cache, with no global flush.
    lda #0
    sta VM_SLOT
    sta TEST+4
    sta TEST+5
    sta TEST+11
    lda #1
    sta VM_GENERATION
    lda #6
    sta TEST+6
read_a:
    jsr test_read
    ldx TEST+11
    lda CACHE_VALUE
    sta TEST+$20,x
    txa
    clc
    adc #$40
    cmp CACHE_VALUE
    beq !+
    jmp failed
!:
    lda TEST+4
    clc
    adc #TEST_LINE
    sta TEST+4
    bcc !+
    inc TEST+5
!:
    inc TEST+11
    lda TEST+11
    cmp #8
    bne read_a
    jsr check_eight_dma
    inc TEST
    // An obsolete code refill must be canceled even without an explicit reset.
    lda #1
    sta VM_SLOT
    lda #2
    sta VM_GENERATION
    lda #0
    sta CACHE_ADDR
    sta CACHE_ADDR+1
    lda #7
    sta CACHE_ADDR+2
    jsr cache_fetch_code
    bcs !+
    jmp failed
!:
    lda cache_pending_phase
    cmp #2
    beq !+
    jmp failed
!:
    lda #3
    sta VM_GENERATION
    jsr cache_service
    lda cache_pending_phase
    beq !+
    jmp failed
!:
    lda CACHE_FLAGS+2
    ora CACHE_FLAGS+3
    beq !+
    jmp failed
!:
    lda cache_stale
    cmp #1
    beq !+
    jmp failed
!:
    jsr check_eight_dma
    lda cache_stale
    sta TEST+$31
    inc TEST
    // A native B request overlapping A must keep continuation ownership B.
    lda #0
    sta TEST+4
    sta TEST+5
    lda #6
    sta TEST+6
    jsr restore_args
    jsr cache_native_read
    bcs !+
    jmp failed
!:
    lda cache_pending_phase
    cmp #3
    beq !+
    jmp failed
!:
    lda cache_pending_owner
    cmp #1
    beq !+
    jmp failed
!:
    jsr cache_invalidate_owner
    lda #4
    sta VM_GENERATION
    jsr cache_service
    lda cache_pending_phase
    ora cache_native_active
    beq !+
    jmp failed
!:
    jsr check_a_dirty
    jsr check_eight_dma
    inc TEST
    // Retrying the new B incarnation coherently writes back only A's overlap.
native_read_retry:
    jsr restore_args
    jsr cache_native_read
    bcc !+
    jsr cache_service
    jmp native_read_retry
!:
    lda CACHE_VALUE
    cmp #$40
    beq !+
    jmp failed
!:
    lda cache_dma_calls
    cmp #10
    beq !+
    jmp failed
!:
    lda CACHE_FLAGS+8
    and #(CACHE_VALID|CACHE_DIRTY|CACHE_BUSY)
    cmp #CACHE_VALID
    beq !+
    jmp failed
!:
    ldx #9
!:
    lda CACHE_FLAGS,x
    and #(CACHE_VALID|CACHE_DIRTY|CACHE_BUSY)
    cmp #(CACHE_VALID|CACHE_DIRTY)
    beq !+
    jmp failed
!:
    inx
    cpx #16
    bne !--
    inc TEST
    // Trusted code writes invalidate both private owners of a physical line.
    lda #0
    sta VM_SLOT
    lda #1
    sta VM_GENERATION
    jsr test_code
    lda #1
    sta VM_SLOT
    lda #4
    sta VM_GENERATION
    jsr test_code
    lda #1
    sta CACHE_ADDR
    sta CACHE_WIDTH
    lda #0
    sta CACHE_ADDR+1
    lda #7
    sta CACHE_ADDR+2
    lda #$66
    sta CACHE_VALUE
    jsr cache_native_write
    bcc !+
    jmp failed
!:
    lda CACHE_FLAGS
    ora CACHE_FLAGS+1
    ora CACHE_FLAGS+2
    ora CACHE_FLAGS+3
    beq !+
    jmp failed
!:
    lda #0
    sta VM_SLOT
    lda #1
    sta VM_GENERATION
    jsr test_code
    lda VM_IR+1
    cmp #$66
    beq !+
    jmp failed
!:
    lda cache_dma_calls
    cmp #14
    beq !+
    jmp failed
!:
    lda #$55
    sta TEST
halt:
    jmp halt
failed:
    lda TEST
    ora #$80
    sta TEST
    jmp halt
check_eight_dma:
    lda cache_dma_calls
    cmp #8
    beq !+
    jmp failed
!:
    lda cache_dma_calls+1
    ora cache_dma_calls+2
    ora cache_dma_calls+3
    beq !+
    jmp failed
!:
    rts
check_a_dirty:
    ldx #8
!:
    lda CACHE_FLAGS,x
    and #(CACHE_VALID|CACHE_DIRTY|CACHE_BUSY|CACHE_PIN)
    cmp #(CACHE_VALID|CACHE_DIRTY)
    beq !+
    jmp failed
!:
    lda CACHE_OWNER,x
    beq !+
    jmp failed
!:
    lda CACHE_GEN_LO,x
    cmp #1
    beq !+
    jmp failed
!:
    inx
    cpx #16
    bne !---
    rts
restore_args:
    ldx #2
!:
    lda TEST+4,x
    sta CACHE_ADDR,x
    dex
    bpl !-
    lda TEST+7
    sta CACHE_WIDTH
    lda TEST+8
    sta CACHE_VALUE
    rts
test_store:
    jsr restore_args
    jsr cache_prepare
    bcc !+
    jsr cache_service
    jmp test_store
!:
    jsr cache_write_prepared
    jsr cache_unpin
    rts
test_read:
    jsr restore_args
    jsr cache_prepare
    bcc !+
    jsr cache_service
    jmp test_read
!:
    jsr cache_read_prepared
    jsr cache_unpin
    rts
test_code:
    lda #0
    sta CACHE_ADDR
    sta CACHE_ADDR+1
    lda #7
    sta CACHE_ADDR+2
    jsr cache_fetch_code
    bcc !+
    jsr cache_service
    jmp test_code
!:
    rts
vm_dma_admit:
    clc
    rts
vm_dma_completed:
    rts
#import "../../native/cache.asm"
