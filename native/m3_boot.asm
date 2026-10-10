// Original normal M3 bootstrap; all code executes before cache ownership.
#import "m2_abi.inc"
#import "probe.asm"
.const M3_KERNEL_BYTES = cmdLineVars.get("nativeBytes").asNumber()
.const M2_DESCRIPTORS_REU = $00c000
.const M2_INITIALIZATION_REU = $00c200
.label m2_source = $b0
.label m2_destination = $b3
.label m2_remaining = $b6
.label m2_chunk = $b9
.label m2_initial_slot = $ba
m2_boot_load:
    jsr m3_initialize_apps
    lda #0
    sta dma_local
    lda #$12
    sta dma_local+1
    lda #0
    sta dma_reu
    sta dma_reu+2
    lda #$80
    sta dma_reu+1
    lda #<M3_KERNEL_BYTES
    sta dma_length
    lda #>M3_KERNEL_BYTES
    sta dma_length+1
    lda #$91
    sta dma_command
    jsr transfer
    rts
m3_initialize_apps:
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

m3_bootstrap_end:
.assert "normal M3 bootstrap excludes its resident DMA destination", m3_bootstrap_end <= $1200, true
.assert "temporary boot staging excludes the conventional PRG", BUFFER+256 <= $0800, true
.assert "bootstrap initialization preserves process descriptors", SAVED >= $0600, true
