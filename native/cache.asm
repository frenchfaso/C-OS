#importonce
#import "m2_abi.inc"
// Original C-OS M2 cache and single REU DMA ownership path.
// Code entries 0..7: two private lines per slot. Data entries 8..15: CLOCK.
.const CACHE_LINE_SIZE = cmdLineVars.get("cacheLine").asNumber()
.assert "supported cache lines", CACHE_LINE_SIZE==64 || CACHE_LINE_SIZE==128, true
.const CACHE_LINE_MASK = 256-CACHE_LINE_SIZE
.const CACHE_STAGING = $1000
.label cache_pending_phase = CACHE_WORK
.label cache_pending_index = CACHE_WORK+1
.label cache_pending_tag = CACHE_WORK+2
.label cache_pending_owner = CACHE_WORK+5
.label cache_pending_generation = CACHE_WORK+6
.label cache_pending_old_flags = CACHE_WORK+8
.label cache_code_next = CACHE_WORK+9
.label cache_clock = CACHE_WORK+13
.label cache_prepared_first = CACHE_WORK+14
.label cache_prepared_last = CACHE_WORK+15
.label cache_prepared_offset = CACHE_WORK+16
.label cache_prepared_width = CACHE_WORK+17
.label cache_prepared_address = CACHE_WORK+18
.label cache_native_active = CACHE_WORK+21
.label cache_native_kind = CACHE_WORK+22
.label cache_native_address = CACHE_WORK+23
.label cache_native_width = CACHE_WORK+26
.label cache_native_value = CACHE_WORK+27
.label cache_native_owner = CACHE_WORK+30
.label cache_native_generation = CACHE_WORK+31
.label cache_code_hits = CACHE_WORK+33
.label cache_data_hits = CACHE_WORK+37
.label cache_code_misses = CACHE_WORK+41
.label cache_data_misses = CACHE_WORK+45
.label cache_fetch_bytes = CACHE_WORK+49
.label cache_stash_bytes = CACHE_WORK+53
.label cache_evictions = CACHE_WORK+57
.label cache_deferred = CACHE_WORK+61
.label cache_stale = CACHE_WORK+65
.label cache_native_reads = CACHE_WORK+69
.label cache_native_writes = CACHE_WORK+73
.label cache_dma_calls = CACHE_WORK+77
.label cache_dma_error = CACHE_WORK+33+48*EXTENDED_DIAGNOSTICS // 0=none,1=length,2=REU end,3=local range.
// Normal diagnostics are low16 modulo counters, not lifetime-exact totals.
.label cache_compact_code_misses = CACHE_WORK+34
.label cache_compact_data_misses = CACHE_WORK+36
.label cache_compact_writebacks = CACHE_WORK+38
.label cache_work_end = CACHE_WORK+40+42*EXTENDED_DIAGNOSTICS
.assert "cache work fits", cache_work_end <= $03b0, true
.label cache_tag = CACHE_SCRATCH
.label cache_index = CACHE_SCRATCH+3
.label cache_second = CACHE_SCRATCH+4
.label cache_offset = CACHE_SCRATCH+5
.label cache_count = CACHE_SCRATCH+6
.label cache_temp_ptr = CACHE_SCRATCH+7
.label cache_command = CACHE_SCRATCH+9
.label cache_loop = CACHE_SCRATCH+10
.label cache_end = CACHE_SCRATCH+11
.label cache_byte = CACHE_SCRATCH+14
.label cache_saved_addr = CACHE_SCRATCH+15
.label cache_saved_width = CACHE_SCRATCH+18
.label cache_saved_local = CACHE_SCRATCH+19
cache_code_start:
cache_reset:
    lda #0
    ldx #111
!:
    sta CACHE_TAG_LO,x
    dex
    bpl !-
    ldx #95
!:
    sta CACHE_WORK,x
    dex
    bpl !-
    rts
cache_unpin:
    // Only data entries can acquire a pin through cache_require_data.
    ldx #7
!:
    lda CACHE_FLAGS+8,x
    and #255-CACHE_PIN
    sta CACHE_FLAGS+8,x
    dex
    bpl !-
    rts
cache_set_tag:
    lda CACHE_ADDR
    and #CACHE_LINE_MASK
    sta cache_tag
    lda CACHE_ADDR+1
    sta cache_tag+1
    lda CACHE_ADDR+2
    sta cache_tag+2
    rts
// X entry; carry clear only for a published matching tag/owner/incarnation.
cache_match:
    :cache_sample_stack()
    lda CACHE_FLAGS,x
    and #(CACHE_VALID|CACHE_BUSY)
    cmp #CACHE_VALID
    bne cache_no_match
    lda CACHE_OWNER,x
    cmp VM_SLOT
    bne cache_no_match
    lda CACHE_GEN_LO,x
    cmp VM_GENERATION
    bne cache_no_match
    lda CACHE_GEN_HI,x
    cmp VM_GENERATION+1
    bne cache_no_match
    lda CACHE_TAG_LO,x
    cmp cache_tag
    bne cache_no_match
    lda CACHE_TAG_MID,x
    cmp cache_tag+1
    bne cache_no_match
    lda CACHE_TAG_HI,x
    cmp cache_tag+2
    bne cache_no_match
    clc
    rts
cache_no_match:
    sec
    rts
// X entry -> CACHE_LOCAL. Separate line indices never imply contiguous buffers.
cache_line_pointer:
    :cache_sample_stack()
    lda cache_local_low,x
    sta CACHE_LOCAL
    lda cache_local_high,x
    sta CACHE_LOCAL+1
    rts
cache_local_low:
    .for (var entry=0; entry<16; entry++) {
        .byte <((entry<8 ? CACHE_CODE : CACHE_DATA)+(entry&7)*CACHE_LINE_SIZE)
    }
cache_local_high:
    .for (var entry=0; entry<16; entry++) {
        .byte >((entry<8 ? CACHE_CODE : CACHE_DATA)+(entry&7)*CACHE_LINE_SIZE)
    }
// Counter selected by X, add A (0..255) with 32-bit carry propagation.
cache_add_counter:
    .if (EXTENDED_DIAGNOSTICS==1) {
    clc
    adc CACHE_WORK,x
    sta CACHE_WORK,x
    bcc !+
    inc CACHE_WORK+1,x
    bne !+
    inc CACHE_WORK+2,x
    bne !+
    inc CACHE_WORK+3,x
!:
    rts
    }
cache_fetch_code:
    jsr cache_set_tag
    lda VM_SLOT
    asl
    tax
    stx cache_index
    jsr cache_match
    bcc cache_code_hit
    inx
    jsr cache_match
    bcc cache_code_hit
    :cache_counter(41,1)
    lda cache_pending_phase
    bne cache_code_wait
    ldx VM_SLOT
    lda cache_code_next,x
    eor #1
    sta cache_code_next,x
    clc
    adc cache_index
    tax
    :cache_compact_increment(cache_compact_code_misses)
    jsr cache_request
cache_code_wait:
    sec
    rts
cache_code_hit:
    stx cache_index
    :cache_counter(33,1)
    ldx cache_index
    jsr cache_line_pointer
    lda CACHE_ADDR
    and #CACHE_LINE_SIZE-1
    tay
    // Aligned four-byte VM instructions cannot cross a 64/128-byte line.
    lda (CACHE_LOCAL),y
    sta VM_IR
    iny
    lda (CACHE_LOCAL),y
    sta VM_IR+1
    iny
    lda (CACHE_LOCAL),y
    sta VM_IR+2
    iny
    lda (CACHE_LOCAL),y
    sta VM_IR+3
    clc
    rts
// CACHE_ADDR/CACHE_WIDTH have already passed VM bounds/overflow checks.
cache_prepare:
    jsr cache_unpin
    lda CACHE_ADDR
    sta cache_prepared_address
    and #CACHE_LINE_SIZE-1
    sta cache_prepared_offset
    lda CACHE_ADDR+1
    sta cache_prepared_address+1
    lda CACHE_ADDR+2
    sta cache_prepared_address+2
    lda CACHE_WIDTH
    sta cache_prepared_width
    jsr cache_set_tag
    jsr cache_require_data
    bcc !+
    jmp cache_prepare_wait
!:
    stx cache_prepared_first
    stx cache_prepared_last
    lda cache_prepared_offset
    clc
    adc cache_prepared_width
    cmp #CACHE_LINE_SIZE+1
    bcc cache_prepare_ready
    lda cache_tag
    clc
    adc #CACHE_LINE_SIZE
    sta cache_tag
    lda cache_tag+1
    adc #0
    sta cache_tag+1
    lda cache_tag+2
    adc #0
    sta cache_tag+2
    jsr cache_require_data
    bcc !+
    jmp cache_prepare_wait
!:
    stx cache_prepared_last
cache_prepare_ready:
    clc
    rts
cache_prepare_wait:
    jsr cache_unpin
    sec
    rts
// Return X data entry and pin only a fully published line.
cache_require_data:
    ldx #8
!:
    jsr cache_match
    bcc cache_data_hit
    inx
    cpx #16
    bne !-
    :cache_counter(45,1)
    lda cache_pending_phase
    bne cache_data_wait
    lda #16
    sta cache_loop
cache_clock_scan:
    lda cache_clock
    and #7
    ora #8
    tax
    inc cache_clock
    lda CACHE_FLAGS,x
    and #(CACHE_BUSY|CACHE_PIN)
    bne cache_clock_next
    lda CACHE_FLAGS,x
    and #CACHE_VALID
    beq cache_victim
    lda CACHE_FLAGS,x
    and #CACHE_REF
    beq cache_victim
    lda CACHE_FLAGS,x
    and #255-CACHE_REF
    sta CACHE_FLAGS,x
cache_clock_next:
    dec cache_loop
    bne cache_clock_scan
cache_data_wait:
    sec
    rts
cache_victim:
    :cache_compact_increment(cache_compact_data_misses)
    jsr cache_request
    sec
    rts
cache_data_hit:
    lda CACHE_FLAGS,x
    ora #(CACHE_REF|CACHE_PIN)
    sta CACHE_FLAGS,x
    stx cache_index
    :cache_counter(37,1)
    ldx cache_index
    clc
    rts
// X victim, cache_tag desired line. Keep old dirty ownership through STASH.
cache_request:
    stx cache_pending_index
    lda CACHE_FLAGS,x
    sta cache_pending_old_flags
    and #CACHE_VALID
    beq !+
    stx cache_index
    :cache_counter(57,1)
    ldx cache_index
!:
    lda CACHE_FLAGS,x
    and #(CACHE_VALID|CACHE_DIRTY)
    cmp #(CACHE_VALID|CACHE_DIRTY)
    beq !+
    lda #2
    bne !++
!:
    lda #1
!:
    sta cache_pending_phase
    lda CACHE_FLAGS,x
    ora #CACHE_BUSY
    and #255-CACHE_PIN
    sta CACHE_FLAGS,x
    lda cache_tag
    sta cache_pending_tag
    lda cache_tag+1
    sta cache_pending_tag+1
    lda cache_tag+2
    sta cache_pending_tag+2
    lda VM_SLOT
    sta cache_pending_owner
    lda VM_GENERATION
    sta cache_pending_generation
    lda VM_GENERATION+1
    sta cache_pending_generation+1
    rts
cache_read_prepared:
    lda #0
    sta CACHE_VALUE
    sta CACHE_VALUE+1
    sta CACHE_VALUE+2
    sta cache_count
cache_read_byte:
    jsr cache_prepared_byte_pointer
    ldy #0
    lda (CACHE_LOCAL),y
    ldx cache_count
    sta CACHE_VALUE,x
    inc cache_count
    lda cache_count
    cmp cache_prepared_width
    bne cache_read_byte
    rts
cache_write_prepared:
    lda #0
    sta cache_count
cache_write_byte:
    jsr cache_prepared_byte_pointer
    ldx cache_count
    lda CACHE_VALUE,x
    ldy #0
    sta (CACHE_LOCAL),y
    inc cache_count
    lda cache_count
    cmp cache_prepared_width
    bne cache_write_byte
    ldx cache_prepared_first
    lda CACHE_FLAGS,x
    ora #CACHE_DIRTY
    sta CACHE_FLAGS,x
    ldx cache_prepared_last
    lda CACHE_FLAGS,x
    ora #CACHE_DIRTY
    sta CACHE_FLAGS,x
    rts
cache_prepared_byte_pointer:
    lda cache_prepared_offset
    clc
    adc cache_count
    cmp #CACHE_LINE_SIZE
    bcc cache_prepared_first_byte
    and #CACHE_LINE_SIZE-1
    sta cache_offset
    ldx cache_prepared_last
    jmp cache_prepared_pointer
cache_prepared_first_byte:
    sta cache_offset
    ldx cache_prepared_first
cache_prepared_pointer:
    jsr cache_line_pointer
    lda CACHE_LOCAL
    clc
    adc cache_offset
    sta CACHE_LOCAL
    bcc !+
    inc CACHE_LOCAL+1
!:
    rts
// Check the pending request's generation against active state or saved PCB.
cache_pending_live:
    lda cache_pending_owner
    cmp VM_SLOT
    bne cache_pending_saved
    lda VM_GENERATION
    cmp cache_pending_generation
    bne cache_pending_dead
    lda VM_GENERATION+1
    cmp cache_pending_generation+1
    bne cache_pending_dead
    clc
    rts
cache_pending_saved:
    lda cache_pending_owner
    and #1
    lsr
    ror
    sta CACHE_LOCAL
    lda cache_pending_owner
    lsr
    clc
    adc #>VM_PCB
    sta CACHE_LOCAL+1
    ldy #91
    lda (CACHE_LOCAL),y
    cmp cache_pending_generation
    bne cache_pending_dead
    iny
    lda (CACHE_LOCAL),y
    cmp cache_pending_generation+1
    bne cache_pending_dead
    clc
    rts
cache_pending_dead:
    sec
    rts
// The buffer still contains the old victim until FETCH completes. Rollback may
// republish it only while its snapshot and its owning incarnation remain live.
cache_rollback_victim:
    ldx cache_pending_index
    lda cache_pending_old_flags
    and #CACHE_VALID
    beq cache_rollback_dead
    jsr cache_entry_live
    bcs cache_rollback_dead
    lda cache_pending_old_flags
    and #255-CACHE_BUSY-CACHE_PIN
    sta CACHE_FLAGS,x
    rts
cache_rollback_dead:
    lda #0
    sta cache_pending_old_flags
    sta CACHE_FLAGS,x
    rts
cache_service:
    lda cache_pending_phase
    bne !+
    clc
    rts
!:
    jsr cache_pending_live
    bcc cache_service_live
    jsr cache_rollback_victim
    lda #0
    sta cache_pending_phase
    :cache_counter(65,1)
    clc
    rts
cache_service_live:
    ldx cache_pending_index
    lda cache_pending_phase
    cmp #2
    bne !+
    jmp cache_service_fetch_prepare
!:
    // Implicit slot reuse must also revoke an old dirty victim before STASH.
    jsr cache_entry_live
    bcc cache_service_stash
    lda #0
    sta cache_pending_old_flags
    lda cache_pending_phase
    cmp #3
    beq cache_service_dead_flush
    lda #CACHE_BUSY
    sta CACHE_FLAGS,x
    lda #2
    sta cache_pending_phase
    clc
    rts
cache_service_dead_flush:
    lda #0
    sta CACHE_FLAGS,x
    sta cache_pending_phase
    clc
    rts
cache_service_stash:
    jsr cache_line_pointer
    ldx cache_pending_index
    lda CACHE_TAG_LO,x
    sta CACHE_ADDR
    lda CACHE_TAG_MID,x
    sta CACHE_ADDR+1
    lda CACHE_TAG_HI,x
    sta CACHE_ADDR+2
    lda #CACHE_LINE_SIZE
    sta CACHE_WIDTH
    lda #$90
    jsr cache_dma_transfer
    bcc !+
    sec
    rts
!:
    :cache_compact_increment(cache_compact_writebacks)
    ldx cache_pending_index
    lda CACHE_FLAGS,x
    and #255-CACHE_DIRTY
    sta CACHE_FLAGS,x
    lda cache_pending_old_flags
    and #255-CACHE_DIRTY
    sta cache_pending_old_flags
    lda cache_pending_phase
    cmp #3
    beq cache_service_flush_done
    lda #2
    sta cache_pending_phase
    // A separate visit must admit and execute the FETCH phase.
    clc
    rts
cache_service_flush_done:
    lda CACHE_FLAGS,x
    and #255-CACHE_BUSY
    sta CACHE_FLAGS,x
    lda #0
    sta cache_pending_phase
    clc
    rts
cache_service_fetch_prepare:
    jsr cache_line_pointer
cache_service_fetch:
    lda cache_pending_tag
    sta CACHE_ADDR
    lda cache_pending_tag+1
    sta CACHE_ADDR+1
    lda cache_pending_tag+2
    sta CACHE_ADDR+2
    lda #CACHE_LINE_SIZE
    sta CACHE_WIDTH
    lda #$91
    jsr cache_dma_transfer
    bcc !+
    sec
    rts
!:
    ldx cache_pending_index
    lda cache_pending_tag
    sta CACHE_TAG_LO,x
    lda cache_pending_tag+1
    sta CACHE_TAG_MID,x
    lda cache_pending_tag+2
    sta CACHE_TAG_HI,x
    lda cache_pending_owner
    sta CACHE_OWNER,x
    lda cache_pending_generation
    sta CACHE_GEN_LO,x
    lda cache_pending_generation+1
    sta CACHE_GEN_HI,x
    lda #(CACHE_VALID|CACHE_REF)
    sta CACHE_FLAGS,x
    lda #0
    sta cache_pending_phase
    clc
    rts
// Single runtime REU driver; all fields initialized for every transaction.
// A=$90 STASH or $91 FETCH. CACHE_LOCAL points into cache/staging RAM.
cache_dma_transfer:
    sta cache_command
    :cache_sample_stack()
    lda #0
    sta cache_dma_error
    lda CACHE_WIDTH
    bne !+
    jmp cache_dma_empty
!:
    cmp #129
    bcc !+
    jmp cache_dma_bad_length
!:
    jsr cache_check_reu_end
    bcc !+
    rts
!:
    jsr cache_check_local
    bcc !+
    rts
!:
    jsr vm_dma_admit
    bcc !+
    :cache_counter(61,1)
    sec
    rts
!:
    php
    sei
    // Recheck after masking IRQ; admission is based on the current raster.
    jsr vm_dma_admit
    bcc !+
    plp
    :cache_counter(61,1)
    sec
    rts
!:
    lda CACHE_LOCAL
    sta $df02
    lda CACHE_LOCAL+1
    sta $df03
    lda CACHE_ADDR
    sta $df04
    lda CACHE_ADDR+1
    sta $df05
    lda CACHE_ADDR+2
    sta $df06
    lda CACHE_WIDTH
    sta $df07
    lda #0
    sta $df08
    sta $df09
    sta $df0a
    lda cache_command
    sta $df01
    jsr vm_dma_completed
    plp
    .if (EXTENDED_DIAGNOSTICS==1) {
    lda cache_command
    cmp #$91
    bne cache_dma_stash_count
    ldx #49
    bne cache_dma_bytes
cache_dma_stash_count:
    ldx #53
cache_dma_bytes:
    lda CACHE_WIDTH
    jsr cache_add_counter
    :cache_counter(77,1)
    }
cache_dma_empty:
    clc
    rts
cache_dma_bad_length:
    lda #1
    bne cache_dma_error_return
cache_check_local:
    lda CACHE_LOCAL+1
    cmp #>CACHE_CODE
    bcc cache_dma_bad_local
    cmp #$12
    bcs cache_dma_bad_local
    lda CACHE_WIDTH
    sec
    sbc #1
    clc
    adc CACHE_LOCAL
    lda CACHE_LOCAL+1
    adc #0
    bcs cache_dma_bad_local
    cmp #$12
    bcs cache_dma_bad_local
    clc
    rts
cache_dma_bad_local:
    lda #3
    bne cache_dma_error_return
// Compute inclusive end only after a nonzero validated width.
cache_check_reu_end:
    lda CACHE_WIDTH
    sec
    sbc #1
    clc
    adc CACHE_ADDR
    sta cache_end
    lda CACHE_ADDR+1
    adc #0
    sta cache_end+1
    lda CACHE_ADDR+2
    adc #0
    sta cache_end+2
    bcs !+
    clc
    rts
!:
    lda #2
cache_dma_error_return:
    sta cache_dma_error
    sec
    rts
// Cancel/invalidate every incarnation owned by VM_SLOT before its reuse.
// A miss evicting another owner restores that owner's old dirty entry on cancel.
cache_cancel_owner:
cache_invalidate_owner:
    lda cache_native_active
    beq !+
    lda cache_native_owner
    cmp VM_SLOT
    bne !+
    lda #0
    sta cache_native_active
!:
    lda cache_pending_phase
    beq cache_invalidate_lines
    lda cache_pending_owner
    cmp VM_SLOT
    bne cache_invalidate_victim
    ldx cache_pending_index
    lda CACHE_OWNER,x
    cmp VM_SLOT
    beq cache_invalidate_cancel_clear
    jsr cache_rollback_victim
    jmp cache_invalidate_cancel
cache_invalidate_cancel_clear:
    lda #0
    sta CACHE_FLAGS,x
cache_invalidate_cancel:
    lda #0
    sta cache_pending_phase
    jmp cache_invalidate_lines
cache_invalidate_victim:
    ldx cache_pending_index
    lda CACHE_OWNER,x
    cmp VM_SLOT
    bne cache_invalidate_lines
    // Revocation applies to the rollback snapshot as well as published flags,
    // including a clean victim whose STASH already completed (phase2).
    lda #0
    sta cache_pending_old_flags
    lda cache_pending_phase
    cmp #1
    beq !+
    cmp #3
    bne cache_invalidate_lines
    // A native request from another owner no longer needs the killed line.
    lda #0
    sta cache_pending_phase
    jmp cache_invalidate_lines
!:
    // Discard killed owner's dirty bytes, while keeping the other owner's refill.
    lda #2
    sta cache_pending_phase
cache_invalidate_lines:
    ldx #15
cache_invalidate_scan:
    lda CACHE_OWNER,x
    cmp VM_SLOT
    bne cache_invalidate_next
    cpx cache_pending_index
    bne cache_invalidate_clear
    lda cache_pending_phase
    cmp #2
    bne cache_invalidate_clear
    // Another owner still has a scheduled refill into this destination.
    lda #CACHE_BUSY
    sta CACHE_FLAGS,x
    jmp cache_invalidate_next
cache_invalidate_clear:
    lda #0
    sta CACHE_FLAGS,x
cache_invalidate_next:
    dex
    bpl cache_invalidate_scan
    rts
// Full scalar native hooks perform real DMA after overlap-only write-back.
cache_native_read:
    lda #0
    jmp cache_native_begin
cache_native_write:
    lda #1
cache_native_begin:
    sta cache_byte
    lda cache_native_active
    bne cache_native_continue
    lda #0
    sta cache_dma_error
    lda CACHE_WIDTH
    cmp #1
    bcs !+
    jmp cache_dma_bad_length
!:
    cmp #4
    bcc !+
    jmp cache_dma_bad_length
!:
    jsr cache_check_reu_end
    bcc !+
    rts
!:
    lda #1
    sta cache_native_active
    lda cache_byte
    sta cache_native_kind
    lda CACHE_WIDTH
    sta cache_native_width
    lda VM_SLOT
    sta cache_native_owner
    lda VM_GENERATION
    sta cache_native_generation
    lda VM_GENERATION+1
    sta cache_native_generation+1
    ldx #2
!:
    lda CACHE_ADDR,x
    sta cache_native_address,x
    lda CACHE_VALUE,x
    sta cache_native_value,x
    dex
    bpl !-
cache_native_continue:
    lda cache_native_owner
    cmp VM_SLOT
    bne cache_native_wait
    lda cache_native_generation
    cmp VM_GENERATION
    bne cache_native_stale
    lda cache_native_generation+1
    cmp VM_GENERATION+1
    bne cache_native_stale
    lda cache_pending_phase
    bne cache_native_wait
    jsr cache_native_find_dirty
    bcc cache_native_transfer
    // One overlapping dirty line is serviced at a time, retaining its tag.
    stx cache_pending_index
    lda CACHE_FLAGS,x
    sta cache_pending_old_flags
    ora #CACHE_BUSY
    and #255-CACHE_PIN
    sta CACHE_FLAGS,x
    lda cache_native_owner
    sta cache_pending_owner
    lda cache_native_generation
    sta cache_pending_generation
    lda cache_native_generation+1
    sta cache_pending_generation+1
    lda #3
    sta cache_pending_phase
cache_native_wait:
    sec
    rts
cache_native_stale:
    lda #0
    sta cache_native_active
    :cache_counter(65,1)
    sec
    rts
cache_native_transfer:
    ldx #2
!:
    lda cache_native_address,x
    sta CACHE_ADDR,x
    dex
    bpl !-
    lda cache_native_width
    sta CACHE_WIDTH
    lda #<CACHE_STAGING
    sta CACHE_LOCAL
    lda #>CACHE_STAGING
    sta CACHE_LOCAL+1
    lda cache_native_kind
    beq cache_native_fetch
    ldx #2
!:
    lda cache_native_value,x
    sta CACHE_STAGING,x
    dex
    bpl !-
    lda #$90
    bne cache_native_dma
cache_native_fetch:
    lda #$91
cache_native_dma:
    jsr cache_dma_transfer
    bcs cache_native_wait
    lda cache_native_kind
    bne cache_native_write_done
    lda #0
    sta CACHE_VALUE
    sta CACHE_VALUE+1
    sta CACHE_VALUE+2
    ldx #0
!:
    lda CACHE_STAGING,x
    sta CACHE_VALUE,x
    inx
    cpx cache_native_width
    bne !-
    :cache_counter(69,1)
    jmp cache_native_complete
cache_native_write_done:
    // Flush was done before DMA, so invalidation cannot lose adjacent dirty bytes.
    ldx #0
!:
    jsr cache_native_overlap
    bcc !+
    lda #0
    sta CACHE_FLAGS,x
!:
    inx
    cpx #16
    bne !--
    :cache_counter(73,1)
cache_native_complete:
    lda #0
    sta cache_native_active
    clc
    rts
cache_native_find_dirty:
    ldx #8
!:
    jsr cache_native_overlap
    bcc !+
    lda CACHE_FLAGS,x
    and #(CACHE_VALID|CACHE_DIRTY|CACHE_BUSY)
    cmp #(CACHE_VALID|CACHE_DIRTY)
    beq cache_native_found
!:
    inx
    cpx #16
    bne !--
    clc
    rts
cache_native_found:
    sec
    rts
// Carry set when valid data entry X intersects the saved native scalar range.
cache_native_overlap:
    lda CACHE_FLAGS,x
    and #CACHE_VALID
    beq cache_native_no_overlap
    jsr cache_entry_live
    bcs cache_native_no_overlap
    // Scalar width <=3: only first and last aligned tags can intersect.
    lda cache_native_address
    and #CACHE_LINE_MASK
    cmp CACHE_TAG_LO,x
    bne cache_native_last_tag
    lda cache_native_address+1
    cmp CACHE_TAG_MID,x
    bne cache_native_last_tag
    lda cache_native_address+2
    cmp CACHE_TAG_HI,x
    beq cache_native_yes_overlap
cache_native_last_tag:
    lda cache_native_width
    sec
    sbc #1
    clc
    adc cache_native_address
    sta cache_end
    lda cache_native_address+1
    adc #0
    sta cache_end+1
    lda cache_native_address+2
    adc #0
    sta cache_end+2
    lda cache_end
    and #CACHE_LINE_MASK
    cmp CACHE_TAG_LO,x
    bne cache_native_no_overlap
    lda cache_end+1
    cmp CACHE_TAG_MID,x
    bne cache_native_no_overlap
    lda cache_end+2
    cmp CACHE_TAG_HI,x
    bne cache_native_no_overlap
cache_native_yes_overlap:
    sec
    rts
cache_native_no_overlap:
    clc
    rts
// Native coherence follows physical overlap across all live owners.
// X is preserved; publication generation is checked against active or saved PCB.
cache_entry_live:
    :cache_sample_stack()
    lda CACHE_OWNER,x
    cmp #4
    bcs cache_entry_dead
    cmp VM_SLOT
    bne cache_entry_saved
    lda CACHE_GEN_LO,x
    cmp VM_GENERATION
    bne cache_entry_dead
    lda CACHE_GEN_HI,x
    cmp VM_GENERATION+1
    bne cache_entry_dead
    clc
    rts
cache_entry_saved:
    and #1
    lsr
    ror
    sta CACHE_LOCAL
    lda CACHE_OWNER,x
    lsr
    clc
    adc #>VM_PCB
    sta CACHE_LOCAL+1
    ldy #91
    lda (CACHE_LOCAL),y
    cmp CACHE_GEN_LO,x
    bne cache_entry_dead
    iny
    lda (CACHE_LOCAL),y
    cmp CACHE_GEN_HI,x
    bne cache_entry_dead
    clc
    rts
cache_entry_dead:
    sec
    rts
cache_code_end:
// Preserve API registers, and measure current hardware stack use without
// introducing extra stack pushes or another JSR into the measured path.
.macro cache_sample_stack() {
    .if (EXTENDED_DIAGNOSTICS==1) {
    sta cache_saved_width
    stx cache_saved_local
    tsx
    txa
    eor #$ff
    cmp $031c
    bcc !+
    sta $031c
!:
    ldx cache_saved_local
    lda cache_saved_width
    }
}
.macro cache_counter(offset,value) {
    .if (EXTENDED_DIAGNOSTICS==1) {
        lda #value
        ldx #offset
        jsr cache_add_counter
    }
}
.macro cache_compact_increment(address) {
    .if (EXTENDED_DIAGNOSTICS==0) {
        inc address
        bne !+
        inc address+1
!:
    }
}
