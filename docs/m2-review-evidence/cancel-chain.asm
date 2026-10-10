#import "../../native/m2_abi.inc"
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
    lda #$7f
    sta $dc0d
    sta $dd0d
    lda $dc0d
    lda $dd0d
    lda #$8f
    sta $d031
    jsr cache_reset
    // A has a dirty line containing old bytes at $060000. B wants $070000.
    lda #0
    sta VM_SLOT
    sta VM_GENERATION+1
    sta VM_PCB+92
    sta VM_PCB+128+92
    sta CACHE_OWNER+8
    sta CACHE_GEN_HI+8
    lda #1
    sta VM_GENERATION
    sta VM_PCB+91
    sta VM_PCB+128+91
    sta CACHE_GEN_LO+8
    lda #6
    sta CACHE_TAG_HI+8
    lda #(CACHE_VALID|CACHE_DIRTY)
    sta CACHE_FLAGS+8
    lda #$66
    ldx #0
!:
    sta CACHE_DATA,x
    inx
    cpx #cmdLineVars.get("cacheLine").asNumber()
    bne !-
    lda #1
    sta VM_SLOT
    jsr request_b
    lda cache_pending_phase
    sta $0300
    // Kill A before its old dirty line is written back, and advance generation.
    lda #0
    sta VM_SLOT
    jsr cache_invalidate_owner
    lda #2
    sta VM_GENERATION
    sta VM_PCB+91
    lda cache_pending_phase
    sta $0301
    lda CACHE_FLAGS+8
    sta $0302
    // Now cancel requester B too. A's revoked bytes must never become dirty again.
    lda #1
    sta VM_SLOT
    sta VM_GENERATION
    .if (cmdLineVars.get("stale").asNumber()==0) {
        jsr cache_invalidate_owner
    } else {
        inc VM_GENERATION
        jsr cache_service
    }
    lda CACHE_FLAGS+8
    sta $0303
    lda cache_pending_phase
    sta $0304
    // Model later CLOCK pressure: another B miss chooses the same destination.
    lda #0
    sta cache_clock
    jsr request_b
    lda cache_pending_phase
    sta $0305
    jsr cache_service
    lda CACHE_FLAGS+8
    sta $0306
    lda #$55
    sta $0307
halt:
    jmp halt
request_b:
    lda #0
    sta CACHE_ADDR
    sta CACHE_ADDR+1
    lda #7
    sta CACHE_ADDR+2
    lda #1
    sta CACHE_WIDTH
    jsr cache_prepare
    rts
vm_dma_admit:
    clc
    rts
vm_dma_completed:
    rts
#import "../../native/cache.asm"
