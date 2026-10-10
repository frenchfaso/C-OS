#importonce
#import "m2_abi.inc"
// Original NMOS 6510 interpreter. Architectural effects follow complete preflight.
.const V_OP = VM_SCRATCH
.const V_A = VM_SCRATCH+1
.const V_B = VM_SCRATCH+2
.const V_FORM = VM_SCRATCH+3
.const V_WIDTH = VM_SCRATCH+4
.const V_WRITE = VM_SCRATCH+5
.const V_NEXT_HIGH = VM_SCRATCH+6
.const V_TEMP = VM_SCRATCH+7
.const V_COUNT = VM_SCRATCH+8
.const V_ACCESS = VM_SCRATCH+9
.const V_SP_NEXT = VM_SCRATCH+10
.const V_EXTRA = VM_SCRATCH+13
// Multiplication reuses dead decode/preflight scratch after admission.
// The original R0/R1 remain intact until the complete product is published.
.label V_PRODUCT = VM_SCRATCH+1

.macro Copy3(src, dst) {
    lda src
    sta dst
    lda src+1
    sta dst+1
    lda src+2
    sta dst+2
}
.macro JumpEq(value, target) {
    cmp #value
    bne !+
    jmp target
!:
}
.macro JumpCarry(target) {
    bcc !+
    jmp target
!:
}
.macro JumpClear(target) {
    bcs !+
    jmp target
!:
}

vm_start:
vm_run:
    // Imported contexts take a full current-PC check on the first step.
    jsr vm_step
    lda VM_OUTCOME
    bne vm_run_return
vm_run_valid_pc:
    // RUN implies the preceding step published a fully validated next PC.
    // Every boundary returns here; no imported state enters this hot entry.
    jsr vm_step_valid_pc
    lda VM_OUTCOME
    beq vm_run_valid_pc
vm_run_return:
    rts

vm_step:
    ldx #1
    bne vm_step_checks
vm_step_valid_pc:
    ldx #0
vm_step_checks:
    stx V_EXTRA
    lda VM_OUTCOME
    cmp #VM_FAULTED
    beq vm_step_return
    cmp #VM_STOPPED
    beq vm_step_return
    lda VM_PENDING
    beq vm_check_credit
    lda #VM_SYSCALL
    sta VM_OUTCOME
vm_step_return:
    rts
vm_check_credit:
    lda VM_FUEL
    bne vm_check_video
    lda #VM_FUEL_EXHAUSTED
    jmp vm_boundary
vm_check_video:
    jsr vm_video_admit
    bcc vm_attempt
    lda #VM_WAIT_VIDEO
    jmp vm_boundary
vm_attempt:
    lda #0
    sta V_NEXT_HIGH
    sta V_ACCESS
    sta V_WRITE
    sta VM_FAULT
    sta VM_FAULT_HAS_ADDRESS
    Copy3(VM_PC, VM_NEXT)
    lda V_EXTRA
    beq vm_current_pc_valid
    jsr vm_check_pc
    JumpCarry(vm_fault_boundary)
vm_current_pc_valid:
    Copy3(VM_PC, CACHE_ADDR)
    jsr cache_fetch_code
    JumpCarry(vm_memory_wait)
    lda VM_IR
    sta V_OP
    cmp #$3b
    bcc !+
    jmp vm_bad_encoding_boundary
!:
    tax
    lda vm_forms,x
    sta V_FORM
    bne !+
    jmp vm_bad_encoding_boundary
!:
    jsr vm_decode_operands
    JumpCarry(vm_fault_boundary)
    clc
    lda VM_PC
    adc #4
    sta VM_NEXT
    lda VM_PC+1
    adc #0
    sta VM_NEXT+1
    lda VM_PC+2
    adc #0
    sta VM_NEXT+2
    lda #0
    adc #0
    sta V_NEXT_HIGH
    jsr vm_preflight
    JumpCarry(vm_fault_boundary)
    lda V_OP
    cmp #$22
    beq vm_prepare_access
    cmp #$38
    beq vm_prepare_access
    cmp #$36
    bne vm_validate_next
    lda VM_IR+1
    beq vm_prepare_access
vm_validate_next:
    jsr vm_check_pc
    JumpCarry(vm_fault_boundary)
vm_prepare_access:
    lda V_ACCESS
    beq vm_admitted
    Copy3(VM_EA, CACHE_ADDR)
    lda V_WIDTH
    sta CACHE_WIDTH
    lda V_WRITE
    sta CACHE_WRITE
    jsr cache_prepare
    JumpCarry(vm_memory_wait)
    lda V_WRITE
    bne vm_admitted
    jsr cache_read_prepared
    Copy3(CACHE_VALUE, VM_VALUE)
    lda V_OP
    cmp #$22
    bne vm_admitted
    Copy3(VM_VALUE, VM_NEXT)
    lda #0
    sta V_NEXT_HIGH
    jsr vm_check_pc
    JumpCarry(vm_fault_boundary)
vm_admitted:
    dec VM_FUEL
    ldx #0
vm_retire:
    inc VM_RETIRED,x
    bne vm_effect
    inx
    cpx #8
    bne vm_retire
vm_effect:
    jsr vm_execute
    lda VM_OUTCOME
    cmp #VM_FAULTED
    beq vm_effect_done
    lda V_OP
    cmp #$36
    bne vm_publish_pc
    lda VM_IR+1
    beq vm_effect_done
vm_publish_pc:
    Copy3(VM_NEXT, VM_PC)
vm_effect_done:
    // Only an admitted memory/stack access can leave prepared data lines pinned.
    lda V_ACCESS
    beq vm_effect_return
    jsr cache_unpin
vm_effect_return:
    rts
vm_bad_encoding_boundary:
    jsr vm_decode_error
    jmp vm_fault_boundary
vm_memory_wait:
    lda #VM_WAIT_REU
vm_boundary:
    sta VM_OUTCOME
    jsr cache_unpin
    rts
vm_fault_boundary:
    lda #VM_FAULTED
    jmp vm_boundary

// Compare two little-endian u24 values in zero page: X/Y are base addresses.
// Carry is lhs >= rhs; zero is equality. A/X/Y are scratch.
vm_compare24:
    inx
    inx
    iny
    iny
    lda $0000,x
    cmp $0000,y
    bne vm_compare_done
    dex
    dey
    lda $0000,x
    cmp $0000,y
    bne vm_compare_done
    dex
    dey
    lda $0000,x
    cmp $0000,y
vm_compare_done:
    rts
vm_address_next:
    Copy3(VM_NEXT, VM_FAULT_ADDRESS)
    lda V_NEXT_HIGH
    sta VM_FAULT_ADDRESS+3
    lda #1
    sta VM_FAULT_HAS_ADDRESS
    rts
vm_address_ea:
    Copy3(VM_EA, VM_FAULT_ADDRESS)
    lda #0
    sta VM_FAULT_ADDRESS+3
    lda #1
    sta VM_FAULT_HAS_ADDRESS
    rts
vm_check_pc:
    lda V_NEXT_HIGH
    beq vm_pc_range
    jsr vm_address_next
    lda V_NEXT_HIGH
    bpl !+
    lda #0
    sta VM_FAULT_HAS_ADDRESS
!:
    lda #FAULT_ADDRESS
    sta VM_FAULT
    sec
    rts
vm_pc_range:
    lda VM_NEXT
    and #3
    bne vm_pc_bad
    lda VM_NEXT+2
    cmp VM_CODE_FIRST+2
    bne vm_pc_lower_result
    lda VM_NEXT+1
    cmp VM_CODE_FIRST+1
    bne vm_pc_lower_result
    lda VM_NEXT
    cmp VM_CODE_FIRST
vm_pc_lower_result:
    bcc vm_pc_bad
    clc
    lda VM_NEXT
    adc #3
    sta VM_LAST
    lda VM_NEXT+1
    adc #0
    sta VM_LAST+1
    lda VM_NEXT+2
    adc #0
    sta VM_LAST+2
    bcs vm_pc_bad
    lda VM_CODE_LAST+2
    cmp VM_LAST+2
    bne vm_pc_upper_result
    lda VM_CODE_LAST+1
    cmp VM_LAST+1
    bne vm_pc_upper_result
    lda VM_CODE_LAST
    cmp VM_LAST
vm_pc_upper_result:
    bcs vm_pc_good
vm_pc_bad:
    jsr vm_address_next
    lda #FAULT_PC
    sta VM_FAULT
    sec
    rts
vm_pc_good:
    clc
    rts
vm_decode_error:
    lda #FAULT_DECODE
    sta VM_FAULT
    lda #0
    sta VM_FAULT_HAS_ADDRESS
    sec
    rts

vm_decode_operands:
    lda VM_IR+1
    and #15
    sta V_A
    lda VM_IR+1
    lsr
    lsr
    lsr
    lsr
    sta V_B
    lda V_FORM
    JumpEq(1, vm_decode_zero)
    JumpEq(3, vm_decode_r_immediate)
    JumpEq(4, vm_decode_shift)
    JumpEq(5, vm_decode_r_single)
    JumpEq(11, vm_decode_make)
    JumpEq(12, vm_decode_absolute)
    JumpEq(15, vm_decode_p_single)
    JumpEq(16, vm_decode_service)
    JumpEq(17, vm_decode_trap)
    // Packed register fields: validate before converting indices to byte offsets.
    lda V_FORM
    cmp #7
    beq vm_decode_low_p
    cmp #8
    beq vm_decode_low_p
    cmp #9
    beq vm_decode_low_p
    cmp #14
    beq vm_decode_low_p
    lda V_A
    cmp #8
    bcs vm_decode_bad_near
    asl
    sta V_A
    jmp vm_decode_high
vm_decode_low_p:
    lda V_A
    cmp #4
    bcs vm_decode_bad_near
    jsr vm_times_three
    sta V_A
vm_decode_high:
    lda V_FORM
    cmp #2
    beq vm_decode_high_r
    cmp #9
    beq vm_decode_high_r
    cmp #13
    beq vm_decode_high_r
    lda V_B
    cmp #4
    bcs vm_decode_bad_near
    jsr vm_times_three
    sta V_B
    jmp vm_decode_unused
vm_decode_high_r:
    lda V_B
    cmp #8
    bcs vm_decode_bad_near
    asl
    sta V_B
vm_decode_unused:
    lda V_FORM
    cmp #2
    beq vm_decode_reserved
    cmp #8
    beq vm_decode_reserved
    cmp #9
    beq vm_decode_reserved
    cmp #10
    beq vm_decode_reserved
    clc
    rts
vm_decode_reserved:
    lda VM_IR+2
    ora VM_IR+3
    bne vm_decode_bad_near
    clc
    rts
vm_decode_bad_near:
    jmp vm_decode_error
vm_decode_zero:
    lda VM_IR+1
    ora VM_IR+2
    ora VM_IR+3
    bne vm_decode_bad_near
    clc
    rts
vm_decode_r_immediate:
    lda VM_IR+1
    cmp #8
    bcs vm_decode_bad_near
    asl
    sta V_A
    clc
    rts
vm_decode_r_single:
    jsr vm_decode_r_immediate
    bcs vm_decode_done
    jmp vm_decode_reserved
vm_decode_shift:
    jsr vm_decode_r_immediate
    bcs vm_decode_done
    lda VM_IR+2
    cmp #16
    bcs vm_decode_bad_near
    lda VM_IR+3
    bne vm_decode_bad_near
    clc
vm_decode_done:
    rts
vm_decode_p_single:
    lda VM_IR+1
    cmp #4
    bcs vm_decode_bad_near
    jsr vm_times_three
    sta V_A
    jmp vm_decode_reserved
vm_decode_make:
    lda VM_IR+1
    cmp #4
    bcs vm_decode_bad_near
    jsr vm_times_three
    sta V_A
    lda VM_IR+2
    cmp #8
    bcs vm_decode_bad_near
    asl
    sta V_B
    lda VM_IR+3
    cmp #8
    bcs vm_decode_bad_near
    clc
    rts
vm_decode_service:
    lda VM_IR+1
    sta V_A
    jmp vm_decode_reserved
vm_decode_trap:
    lda VM_IR+1
    bne vm_decode_bad_near
    clc
    rts
vm_decode_absolute:
    lda V_OP
    sec
    sbc #$1c
    cmp #4
    bcs !+
    jsr vm_times_three
    sta V_A
!:
    clc
    rts
vm_times_three:
    sta V_TEMP
    asl
    clc
    adc V_TEMP
    rts

vm_preflight:
    lda V_OP
    cmp #$10
    JumpClear(vm_preflight_done)
    cmp #$16
    bcs vm_preflight_nonmemory
    lda #1
    sta V_ACCESS
    lda V_OP
    cmp #$10
    beq vm_width_one
    cmp #$12
    beq vm_width_one
    cmp #$11
    beq vm_width_two
    cmp #$13
    beq vm_width_two
    lda #3
    bne vm_width_ready
vm_width_one:
    lda #1
    bne vm_width_ready
vm_width_two:
    lda #2
vm_width_ready:
    sta V_WIDTH
    lda V_OP
    cmp #$12
    beq vm_memory_write
    cmp #$13
    beq vm_memory_write
    cmp #$15
    bne vm_memory_address
vm_memory_write:
    lda #1
    sta V_WRITE
vm_memory_address:
    ldx V_B
    clc
    lda VM_P,x
    adc VM_IR+2
    sta VM_EA
    lda VM_P+1,x
    adc VM_IR+3
    sta VM_EA+1
    lda VM_P+2,x
    adc #0
    sta VM_EA+2
    bcc !+
    jsr vm_address_ea
    lda #1
    sta VM_FAULT_ADDRESS+3
    jmp vm_pointer_overflow
!:
    jmp vm_check_access
vm_preflight_nonmemory:
    JumpEq($17, vm_pointer_add)
    JumpEq($18, vm_pointer_sub)
    JumpEq($1b, vm_pointer_make)
    JumpEq($20, vm_absolute_target)
    JumpEq($21, vm_call_preflight)
    cmp #$23
    bcc vm_preflight_stack
    cmp #$2d
    bcs vm_preflight_stack
    jmp vm_branch_preflight
vm_preflight_stack:
    cmp #$30
    bne !+
    jmp vm_stack_preflight
!:
    cmp #$31
    bne !+
    jmp vm_stack_preflight
!:
    cmp #$32
    bne !+
    jmp vm_stack_preflight
!:
    cmp #$33
    bne !+
    jmp vm_stack_preflight
!:
    cmp #$22
    bne !+
    jmp vm_stack_preflight
!:
    cmp #$35
    bne vm_preflight_done
    ldx V_A
    lda VM_P,x
    sta VM_VALUE
    lda VM_P+1,x
    sta VM_VALUE+1
    lda VM_P+2,x
    sta VM_VALUE+2
    jmp vm_validate_sp_value
vm_preflight_done:
    clc
    rts
vm_pointer_add:
    ldx V_A
    ldy V_B
    clc
    lda VM_P,x
    adc VM_R,y
    sta VM_VALUE
    lda VM_P+1,x
    adc VM_R+1,y
    sta VM_VALUE+1
    lda VM_P+2,x
    adc #0
    sta VM_VALUE+2
    bcc vm_preflight_done
    Copy3(VM_VALUE, VM_FAULT_ADDRESS)
    lda #1
    sta VM_FAULT_ADDRESS+3
    sta VM_FAULT_HAS_ADDRESS
    jmp vm_pointer_overflow
vm_pointer_sub:
    ldx V_A
    ldy V_B
    sec
    lda VM_P,x
    sbc VM_R,y
    sta VM_VALUE
    lda VM_P+1,x
    sbc VM_R+1,y
    sta VM_VALUE+1
    lda VM_P+2,x
    sbc #0
    sta VM_VALUE+2
    bcs vm_preflight_done
    lda #0
    sta VM_FAULT_HAS_ADDRESS
vm_pointer_overflow:
    lda #FAULT_ADDRESS
    sta VM_FAULT
    sec
    rts
vm_pointer_make:
    lda VM_IR+3
    asl
    tax
    lda VM_R+1,x
    beq !+
    lda #0
    sta VM_FAULT_HAS_ADDRESS
    jmp vm_pointer_overflow
!:
    lda VM_R,x
    sta VM_VALUE+2
    ldx V_B
    lda VM_R,x
    sta VM_VALUE
    lda VM_R+1,x
    sta VM_VALUE+1
    clc
    rts
vm_call_preflight:
    jsr vm_check_pc
    JumpCarry(vm_preflight_return)
    jsr vm_absolute_target
    jmp vm_stack_preflight
vm_absolute_target:
    Copy3(VM_IR+1, VM_NEXT)
    lda #0
    sta V_NEXT_HIGH
    clc
vm_preflight_return:
    rts

vm_branch_preflight:
    lda V_OP
    cmp #$29
    bcs vm_compare_p_branch
    ldx V_A
    ldy V_B
    cmp #$27
    bcc vm_compare_r_unsigned
    lda VM_R+1,y
    eor #$80
    sta V_TEMP
    lda VM_R+1,x
    eor #$80
    cmp V_TEMP
    bne vm_branch_condition
    lda VM_R,x
    cmp VM_R,y
    jmp vm_branch_condition
vm_compare_r_unsigned:
    lda VM_R+1,x
    cmp VM_R+1,y
    bne vm_branch_condition
    lda VM_R,x
    cmp VM_R,y
    jmp vm_branch_condition
vm_compare_p_branch:
    ldx V_A
    ldy V_B
    lda VM_P+2,x
    cmp VM_P+2,y
    bne vm_branch_condition
    lda VM_P+1,x
    cmp VM_P+1,y
    bne vm_branch_condition
    lda VM_P,x
    cmp VM_P,y
vm_branch_condition:
    // Save the comparison before opcode comparisons change flags.
    php
    pla
    sta V_TEMP
    lda V_OP
    cmp #$23
    beq vm_branch_equal
    cmp #$29
    beq vm_branch_equal
    cmp #$24
    beq vm_branch_different
    cmp #$2a
    beq vm_branch_different
    cmp #$25
    beq vm_branch_less
    cmp #$27
    beq vm_branch_less
    cmp #$2b
    beq vm_branch_less
    lda V_TEMP
    and #1
    beq vm_branch_not_taken
    bne vm_branch_taken
vm_branch_equal:
    lda V_TEMP
    and #2
    beq vm_branch_not_taken
    bne vm_branch_taken
vm_branch_different:
    lda V_TEMP
    and #2
    bne vm_branch_not_taken
    beq vm_branch_taken
vm_branch_less:
    lda V_TEMP
    and #1
    bne vm_branch_not_taken
vm_branch_taken:
    lda VM_IR+2
    sta VM_VALUE
    lda VM_IR+3
    sta VM_VALUE+1
    lda #0
    bit VM_IR+3
    bpl !+
    lda #$ff
!:
    sta VM_VALUE+2
    sta V_EXTRA
    asl VM_VALUE
    rol VM_VALUE+1
    rol VM_VALUE+2
    asl VM_VALUE
    rol VM_VALUE+1
    rol VM_VALUE+2
    clc
    lda VM_NEXT
    adc VM_VALUE
    sta VM_NEXT
    lda VM_NEXT+1
    adc VM_VALUE+1
    sta VM_NEXT+1
    lda VM_NEXT+2
    adc VM_VALUE+2
    sta VM_NEXT+2
    lda V_NEXT_HIGH
    adc V_EXTRA
    sta V_NEXT_HIGH
vm_branch_not_taken:
    clc
    rts

vm_stack_minimum:
    sec
    lda VM_STACK_FIRST
    sbc #1
    sta VM_VALUE
    lda VM_STACK_FIRST+1
    sbc #0
    sta VM_VALUE+1
    lda VM_STACK_FIRST+2
    sbc #0
    sta VM_VALUE+2
    rts
vm_validate_sp_value:
    // Candidate in VM_VALUE; permit the full-stack first-1 sentinel.
    Copy3(VM_VALUE, VM_EA)
    jsr vm_stack_minimum
    ldx #VM_EA
    ldy #VM_VALUE
    jsr vm_compare24
    bcc vm_sp_bad
    ldx #VM_EA
    ldy #VM_STACK_LAST
    jsr vm_compare24
    bcc vm_sp_good
    beq vm_sp_good
vm_sp_bad:
    jsr vm_address_ea
    lda #FAULT_SP
    sta VM_FAULT
    sec
    rts
vm_sp_good:
    clc
    rts
vm_stack_preflight:
    Copy3(VM_SP, VM_VALUE)
    jsr vm_validate_sp_value
    JumpCarry(vm_preflight_return)
    lda #1
    sta V_ACCESS
    lda V_OP
    cmp #$30
    beq vm_stack_two
    cmp #$31
    beq vm_stack_two
    lda #3
    bne vm_stack_width_ready
vm_stack_two:
    lda #2
vm_stack_width_ready:
    sta V_WIDTH
    lda V_OP
    cmp #$31
    beq vm_stack_pop
    cmp #$33
    beq vm_stack_pop
    cmp #$22
    beq vm_stack_pop
    lda #1
    sta V_WRITE
    sec
    lda VM_SP
    sbc V_WIDTH
    sta V_SP_NEXT
    lda VM_SP+1
    sbc #0
    sta V_SP_NEXT+1
    lda VM_SP+2
    sbc #0
    sta V_SP_NEXT+2
    jsr vm_stack_minimum
    ldx #V_SP_NEXT
    ldy #VM_VALUE
    jsr vm_compare24
    bcs vm_stack_push_address
    lda #FAULT_STACK_OVERFLOW
    jmp vm_stack_fault
vm_stack_push_address:
    clc
    lda V_SP_NEXT
    adc #1
    sta VM_EA
    lda V_SP_NEXT+1
    adc #0
    sta VM_EA+1
    lda V_SP_NEXT+2
    adc #0
    sta VM_EA+2
    jmp vm_check_access
vm_stack_pop:
    clc
    lda VM_SP
    adc V_WIDTH
    sta V_SP_NEXT
    lda VM_SP+1
    adc #0
    sta V_SP_NEXT+1
    lda VM_SP+2
    adc #0
    sta V_SP_NEXT+2
    bcs vm_stack_underflow
    ldx #V_SP_NEXT
    ldy #VM_STACK_LAST
    jsr vm_compare24
    bcc vm_stack_pop_address
    beq vm_stack_pop_address
vm_stack_underflow:
    lda #FAULT_STACK_UNDERFLOW
vm_stack_fault:
    sta VM_FAULT
    Copy3(VM_SP, VM_FAULT_ADDRESS)
    lda #0
    sta VM_FAULT_ADDRESS+3
    lda #1
    sta VM_FAULT_HAS_ADDRESS
    sec
    rts
vm_stack_pop_address:
    clc
    lda VM_SP
    adc #1
    sta VM_EA
    lda VM_SP+1
    adc #0
    sta VM_EA+1
    lda VM_SP+2
    adc #0
    sta VM_EA+2
    jmp vm_check_access

vm_check_access:
    jsr vm_address_ea
    clc
    lda V_WIDTH
    adc #$ff
    sta V_TEMP
    clc
    lda VM_EA
    adc V_TEMP
    sta VM_LAST
    lda VM_EA+1
    adc #0
    sta VM_LAST+1
    lda VM_EA+2
    adc #0
    sta VM_LAST+2
    bcc !+
    jmp vm_pointer_overflow
!:
    ldx #VM_EA
    ldy #VM_ARENA_FIRST
    jsr vm_compare24
    bcc vm_access_outside
    ldx #VM_LAST
    ldy #VM_ARENA_LAST
    jsr vm_compare24
    bcc vm_access_protection
    beq vm_access_protection
vm_access_outside:
    lda #FAULT_ARENA
    sta VM_FAULT
    sec
    rts
vm_access_protection:
    lda V_WRITE
    beq vm_access_good
    ldx #VM_EA
    ldy #VM_CODE_LAST
    jsr vm_compare24
    bcc vm_access_possible_overlap
    beq vm_access_possible_overlap
    bcs vm_access_good
vm_access_possible_overlap:
    ldx #VM_LAST
    ldy #VM_CODE_FIRST
    jsr vm_compare24
    bcc vm_access_good
    lda #FAULT_READ_ONLY
    sta VM_FAULT
    sec
    rts
vm_access_good:
    // A successful access preflight is not itself a recorded fault.
    lda #0
    sta VM_FAULT_HAS_ADDRESS
    clc
    rts

vm_execute:
    lda #VM_RUN
    sta VM_OUTCOME
    lda V_OP
    asl
    tax
    lda vm_handlers,x
    sta V_SP_NEXT
    lda vm_handlers+1,x
    sta V_SP_NEXT+1
    ldx V_A
    ldy V_B
    jmp (V_SP_NEXT)
vm_e_nop:
    rts
vm_e_mov:
    lda VM_R,y
    sta VM_R,x
    lda VM_R+1,y
    sta VM_R+1,x
    rts
vm_e_ldi:
    lda VM_IR+2
    sta VM_R,x
    lda VM_IR+3
    sta VM_R+1,x
    rts
vm_e_add:
    clc
    lda VM_R,x
    adc VM_R,y
    sta VM_R,x
    lda VM_R+1,x
    adc VM_R+1,y
    sta VM_R+1,x
    rts
vm_e_sub:
    sec
    lda VM_R,x
    sbc VM_R,y
    sta VM_R,x
    lda VM_R+1,x
    sbc VM_R+1,y
    sta VM_R+1,x
    rts
vm_e_and:
    lda VM_R,x
    and VM_R,y
    sta VM_R,x
    lda VM_R+1,x
    and VM_R+1,y
    sta VM_R+1,x
    rts
vm_e_or:
    lda VM_R,x
    ora VM_R,y
    sta VM_R,x
    lda VM_R+1,x
    ora VM_R+1,y
    sta VM_R+1,x
    rts
vm_e_xor:
    lda VM_R,x
    eor VM_R,y
    sta VM_R,x
    lda VM_R+1,x
    eor VM_R+1,y
    sta VM_R+1,x
    rts
vm_e_shl:
    lda VM_IR+2
    sta V_COUNT
    beq vm_e_shift_done
vm_e_shl_loop:
    asl VM_R,x
    rol VM_R+1,x
    dec V_COUNT
    bne vm_e_shl_loop
vm_e_shift_done:
    rts
vm_e_shr:
    lda VM_IR+2
    sta V_COUNT
    beq vm_e_shift_done
vm_e_shr_loop:
    lsr VM_R+1,x
    ror VM_R,x
    dec V_COUNT
    bne vm_e_shr_loop
    rts
vm_e_sar:
    lda VM_IR+2
    sta V_COUNT
    beq vm_e_shift_done
vm_e_sar_loop:
    lda VM_R+1,x
    cmp #$80
    ror VM_R+1,x
    ror VM_R,x
    dec V_COUNT
    bne vm_e_sar_loop
    rts
vm_e_addi:
    clc
    lda VM_R,x
    adc VM_IR+2
    sta VM_R,x
    lda VM_R+1,x
    adc VM_IR+3
    sta VM_R+1,x
    rts
vm_e_trunc:
    lda #0
    sta VM_R+1,x
    rts
vm_e_sext:
    lda VM_R,x
    and #$80
    beq vm_e_trunc
    lda #$ff
    sta VM_R+1,x
    rts
vm_e_not:
    lda VM_R,x
    eor #$ff
    sta VM_R,x
    lda VM_R+1,x
    eor #$ff
    sta VM_R+1,x
    rts
vm_e_mulu:
    jsr vm_multiply_unsigned
    jmp vm_multiply_publish
vm_e_muls:
    jsr vm_multiply_unsigned
    // Signed product differs from the unsigned product only in its high half:
    // subtract old R1 if old R0 is negative, and old R0 if old R1 is negative.
    lda VM_R+1
    bpl vm_multiply_right_sign
    sec
    lda V_PRODUCT+2
    sbc VM_R+2
    sta V_PRODUCT+2
    lda V_PRODUCT+3
    sbc VM_R+3
    sta V_PRODUCT+3
vm_multiply_right_sign:
    lda VM_R+3
    bpl vm_multiply_publish
    sec
    lda V_PRODUCT+2
    sbc VM_R
    sta V_PRODUCT+2
    lda V_PRODUCT+3
    sbc VM_R+1
    sta V_PRODUCT+3
vm_multiply_publish:
    .for (var i=0; i<4; i++) {
        lda V_PRODUCT+i
        sta VM_R+i
    }
    rts
// Exact 16x16 -> 32-bit shift/add. The multiplier starts in the low half;
// each rotation shifts one consumed multiplier bit out of the product.
// Exactly sixteen iterations, including zero operands. A/X/flags are scratch.
vm_multiply_unsigned:
    lda VM_R+2
    sta V_PRODUCT
    lda VM_R+3
    sta V_PRODUCT+1
    lda #0
    sta V_PRODUCT+2
    sta V_PRODUCT+3
    ldx #16
vm_multiply_bit:
    lda V_PRODUCT
    lsr
    bcc vm_multiply_shift
    clc
    lda V_PRODUCT+2
    adc VM_R
    sta V_PRODUCT+2
    lda V_PRODUCT+3
    adc VM_R+1
    sta V_PRODUCT+3
vm_multiply_shift:
    ror V_PRODUCT+3
    ror V_PRODUCT+2
    ror V_PRODUCT+1
    ror V_PRODUCT
    dex
    bne vm_multiply_bit
    rts
vm_e_ld8:
    lda VM_VALUE
    sta VM_R,x
    lda #0
    sta VM_R+1,x
    rts
vm_e_ld16:
    lda VM_VALUE
    sta VM_R,x
    lda VM_VALUE+1
    sta VM_R+1,x
    rts
vm_e_ldp:
    lda VM_VALUE
    sta VM_P,x
    lda VM_VALUE+1
    sta VM_P+1,x
    lda VM_VALUE+2
    sta VM_P+2,x
    rts
vm_e_store_r:
    lda VM_R,x
    sta CACHE_VALUE
    lda VM_R+1,x
    sta CACHE_VALUE+1
    jmp cache_write_prepared
vm_e_store_p:
    lda VM_P,x
    sta CACHE_VALUE
    lda VM_P+1,x
    sta CACHE_VALUE+1
    lda VM_P+2,x
    sta CACHE_VALUE+2
    jmp cache_write_prepared
vm_e_pmov:
    lda VM_P,y
    sta VM_P,x
    lda VM_P+1,y
    sta VM_P+1,x
    lda VM_P+2,y
    sta VM_P+2,x
    rts
vm_e_pointer:
    jmp vm_e_ldp
vm_e_pgetlo:
    lda VM_P,y
    sta VM_R,x
    lda VM_P+1,y
    sta VM_R+1,x
    rts
vm_e_pgethi:
    lda VM_P+2,y
    sta VM_R,x
    lda #0
    sta VM_R+1,x
    rts
vm_e_pli:
    lda VM_IR+1
    sta VM_P,x
    lda VM_IR+2
    sta VM_P+1,x
    lda VM_IR+3
    sta VM_P+2,x
    rts
vm_e_call:
    clc
    lda VM_PC
    adc #4
    sta CACHE_VALUE
    lda VM_PC+1
    adc #0
    sta CACHE_VALUE+1
    lda VM_PC+2
    adc #0
    sta CACHE_VALUE+2
    jsr cache_write_prepared
    jmp vm_e_stack_publish
vm_e_push_r:
    jsr vm_e_store_r
    jmp vm_e_stack_publish
vm_e_push_p:
    jsr vm_e_store_p
    jmp vm_e_stack_publish
vm_e_pop_r:
    jsr vm_e_ld16
    jmp vm_e_stack_publish
vm_e_pop_p:
    jsr vm_e_ldp
vm_e_stack_publish:
    // Recompute the admitted stack result: dispatch used V_SP_NEXT as a jump pointer.
    lda V_OP
    cmp #$31
    beq vm_e_sp_add
    cmp #$33
    beq vm_e_sp_add
    cmp #$22
    beq vm_e_sp_add
    sec
    lda VM_SP
    sbc V_WIDTH
    sta VM_SP
    lda VM_SP+1
    sbc #0
    sta VM_SP+1
    lda VM_SP+2
    sbc #0
    sta VM_SP+2
    rts
vm_e_sp_add:
    clc
    lda VM_SP
    adc V_WIDTH
    sta VM_SP
    lda VM_SP+1
    adc #0
    sta VM_SP+1
    lda VM_SP+2
    adc #0
    sta VM_SP+2
    rts
vm_e_getsp:
    lda VM_SP
    sta VM_P,x
    lda VM_SP+1
    sta VM_P+1,x
    lda VM_SP+2
    sta VM_P+2,x
    rts
vm_e_setsp:
    lda VM_P,x
    sta VM_SP
    lda VM_P+1,x
    sta VM_SP+1
    lda VM_P+2,x
    sta VM_SP+2
    rts
vm_e_syscall:
    Copy3(VM_PC, VM_CALL_PC)
    lda VM_IR+1
    sta VM_SYSCALL_ID
    lda #1
    sta VM_PENDING
    ldx #0
vm_e_token_increment:
    inc VM_TOKEN,x
    bne vm_e_syscall_done
    inx
    cpx #8
    bne vm_e_token_increment
vm_e_syscall_done:
    lda #VM_SYSCALL
    sta VM_OUTCOME
    rts
vm_e_yield:
    lda #0
    sta VM_FUEL
    lda #VM_YIELD
    sta VM_OUTCOME
    rts
vm_e_trap:
    lda VM_IR+2
    sta VM_TRAP
    lda VM_IR+3
    sta VM_TRAP+1
    lda #FAULT_TRAP
    sta VM_FAULT
    lda #0
    sta VM_FAULT_HAS_ADDRESS
    lda #VM_FAULTED
    sta VM_OUTCOME
    rts

vm_save_context:
    jsr vm_context_pointer
    ldx #0
    ldy #0
vm_save_loop:
    lda VM_STATE,x
    sta (V_SP_NEXT),y
    inx
    iny
    cpx #VM_STATE_BYTES
    bne vm_save_loop
    rts
vm_load_context:
    jsr vm_context_pointer
    ldx #0
    ldy #0
vm_load_loop:
    lda (V_SP_NEXT),y
    sta VM_STATE,x
    inx
    iny
    cpx #VM_STATE_BYTES
    bne vm_load_loop
    rts
vm_context_pointer:
    lda VM_SLOT
    and #1
    lsr
    ror
    sta V_SP_NEXT
    lda VM_SLOT
    lsr
    clc
    adc #>VM_PCB
    sta V_SP_NEXT+1
    rts

// Atomic diagnostic completion; bytecode cannot access this mailbox.
vm_complete_syscall:
    lda VM_PENDING
    bne !+
    jmp vm_completion_rejected
!:
    ldx #0
vm_completion_token:
    lda VM_TOKEN,x
    cmp M2_COMPLETION,x
    beq !+
    jmp vm_completion_rejected
!:
    inx
    cpx #8
    bne vm_completion_token
    lda VM_GENERATION
    cmp M2_COMPLETION+8
    beq !+
    jmp vm_completion_rejected
!:
    lda VM_GENERATION+1
    cmp M2_COMPLETION+9
    beq !+
    jmp vm_completion_rejected
!:
    lda M2_COMPLETION+12
    and #1
    beq !+
    jmp vm_completion_rejected
!:
    lda M2_COMPLETION+13
    and #$f0
    beq !+
    jmp vm_completion_rejected
!:
    lda VM_SYSCALL_ID
    bne vm_completion_returning
    lda M2_COMPLETION+12
    ora M2_COMPLETION+13
    beq !+
    jmp vm_completion_rejected
!:
    lda VM_R
    sta VM_TRAP
    lda VM_R+1
    sta VM_TRAP+1
    lda #0
    sta VM_PENDING
    lda #VM_STOPPED
    sta VM_OUTCOME
    jsr cache_unpin
    clc
    rts
vm_completion_returning:
    lda M2_COMPLETION+10
    sta VM_R
    lda M2_COMPLETION+11
    sta VM_R+1
    lda M2_COMPLETION+12
    sta V_TEMP
    ldx #0
vm_completion_registers:
    lsr V_TEMP
    bcc vm_completion_r_skip
    lda M2_COMPLETION+14,x
    sta VM_R,x
    lda M2_COMPLETION+15,x
    sta VM_R+1,x
vm_completion_r_skip:
    inx
    inx
    cpx #16
    bne vm_completion_registers
    lda M2_COMPLETION+13
    sta V_TEMP
    ldx #0
vm_completion_pointers:
    lsr V_TEMP
    bcc vm_completion_p_skip
    lda M2_COMPLETION+30,x
    sta VM_P,x
    lda M2_COMPLETION+31,x
    sta VM_P+1,x
    lda M2_COMPLETION+32,x
    sta VM_P+2,x
vm_completion_p_skip:
    inx
    inx
    inx
    cpx #12
    bne vm_completion_pointers
    lda #0
    sta VM_PENDING
    sta VM_OUTCOME
    jsr cache_unpin
    clc
    rts
vm_completion_rejected:
    sec
    rts

// Operand forms: 0 invalid, 1 zero, 2 rr, 3 r/u16, 4 shift, 5 r,
// 6 rp/u16, 7 pp/u16, 8 pp, 9 pr, 10 rp, 11 make, 12 u24,
// 13 branch-r, 14 branch-p, 15 p, 16 syscall, 17 trap.
vm_tables_start:
vm_forms:
    .byte 1,2,3,2,2,2,2,2,4,4,4,3,5,5,5,0
    .byte 6,6,6,6,7,7,8,9,9,10,10,11,12,12,12,12
    .byte 12,12,1,13,13,13,13,13,13,14,14,14,14,0,0,0
    .byte 5,5,15,15,15,15,16,1,17,1,1
vm_handlers:
    .word vm_e_nop,vm_e_mov,vm_e_ldi,vm_e_add,vm_e_sub,vm_e_and,vm_e_or,vm_e_xor
    .word vm_e_shl,vm_e_shr,vm_e_sar,vm_e_addi,vm_e_trunc,vm_e_sext,vm_e_not,vm_e_nop
    .word vm_e_ld8,vm_e_ld16,vm_e_store_r,vm_e_store_r,vm_e_ldp,vm_e_store_p,vm_e_pmov,vm_e_pointer
    .word vm_e_pointer,vm_e_pgetlo,vm_e_pgethi,vm_e_pointer,vm_e_pli,vm_e_pli,vm_e_pli,vm_e_pli
    .word vm_e_nop,vm_e_call,vm_e_stack_publish,vm_e_nop,vm_e_nop,vm_e_nop,vm_e_nop,vm_e_nop
    .word vm_e_nop,vm_e_nop,vm_e_nop,vm_e_nop,vm_e_nop,vm_e_nop,vm_e_nop,vm_e_nop
    .word vm_e_push_r,vm_e_pop_r,vm_e_push_p,vm_e_pop_p,vm_e_getsp,vm_e_setsp,vm_e_syscall,vm_e_yield,vm_e_trap,vm_e_mulu,vm_e_muls
vm_tables_end:
vm_end:
