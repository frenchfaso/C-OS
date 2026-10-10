//! ABI 2 multiplication is checked with literal bytes and a shift/add oracle.
use cos_tools::vm::{Bounds, FaultCause, Memory, Outcome, Range, Vm};

const BASE: u32 = 0x40000;

fn setup(opcode: u8, fallthrough: bool) -> (Vm, Memory) {
    let bounds = Bounds {
        arena: Range {
            first: BASE,
            last: 0x5ffff,
        },
        code: Range {
            first: BASE,
            last: BASE + if fallthrough { 7 } else { 3 },
        },
        heap: Range {
            first: BASE + 0x100,
            last: 0x5ff7f,
        },
        stack: Range {
            first: 0x5ff80,
            last: 0x5ffff,
        },
    };
    let mut vm = Vm::new(7, bounds, BASE, None).unwrap();
    vm.state.r = [0xffff, 0x8000, 0x1234, 0x5678, 0xabcd, 0xfedc, 7, 0xbeef];
    vm.state.p = [0, 0xffffff, 0x123456, 0x5fffd];
    vm.state.sp = 0x5fffc;
    let mut memory = Memory::new();
    memory
        .write(BASE, &[opcode, 0, 0, 0, 0x20, 0, 0, 4])
        .unwrap();
    memory.write(0x5fff0, &[0xa5; 16]).unwrap();
    (vm, memory)
}

fn unsigned_product(left: u16, right: u16) -> u32 {
    let mut result = 0_u32;
    for bit in 0..16 {
        if right & (1 << bit) != 0 {
            result += u32::from(left) << bit;
        }
    }
    result
}

fn exact_product(left: u16, right: u16, signed: bool) -> u32 {
    if !signed {
        return unsigned_product(left, right);
    }
    let negative = (left ^ right) & 0x8000 != 0;
    let magnitude = |n: u16| if n & 0x8000 != 0 { n.wrapping_neg() } else { n };
    let product = unsigned_product(magnitude(left), magnitude(right));
    if negative {
        product.wrapping_neg()
    } else {
        product
    }
}

fn commit(vm: &mut Vm, memory: &mut Memory, left: u16, right: u16, expected: u32) {
    vm.state.pc = BASE;
    vm.state.r[0] = left;
    vm.state.r[1] = right;
    vm.refuel(1);
    let before = vm.state.clone();
    assert!(vm.step_one(memory).is_none());
    assert_eq!(vm.state.r[0], expected as u16, "{left:04x} * {right:04x}");
    assert_eq!(
        vm.state.r[1],
        (expected >> 16) as u16,
        "{left:04x} * {right:04x}"
    );
    assert_eq!(vm.state.r[2..], before.r[2..]);
    assert_eq!(vm.state.p, before.p);
    assert_eq!(vm.state.sp, before.sp);
    assert_eq!(vm.state.pc, BASE + 4);
    assert_eq!(vm.state.fuel, 0);
    assert_eq!(vm.state.retired, before.retired + 1);
    let after = vm.state.clone();
    assert_eq!(vm.step_one(memory), Some(Outcome::FuelExhausted));
    assert_eq!(vm.state, after);
    assert_eq!(memory.read(0x5fff0, 16).unwrap(), &[0xa5; 16]);
}

#[test]
fn multiplication_extrema_carries_signs_and_equal_operands() {
    for (opcode, cases) in [
        (
            0x39,
            vec![
                (0, 0xffff, 0),
                (1, 0xffff, 0x0000ffff),
                (0xffff, 0xffff, 0xfffe0001),
                (0x8000, 0x8000, 0x40000000),
                (0x8000, 0xffff, 0x7fff8000),
                (0x0101, 0x0101, 0x00010201),
                (0x7fff, 0xffff, 0x7ffe8001),
                (0xffff, 0xfffe, 0xfffd0002),
            ],
        ),
        (
            0x3a,
            vec![
                (0, 0x8000, 0),
                (1, 0xffff, 0xffffffff),
                (0xffff, 0xffff, 1),
                (0x8000, 0x8000, 0x40000000),
                (0x8000, 0xffff, 0x00008000),
                (0x8000, 1, 0xffff8000),
                (0x7fff, 0x7fff, 0x3fff0001),
                (0x8000, 0x7fff, 0xc0008000),
                (0x1234, 0xfffe, 0xffffdb98),
                (0xfffe, 0x1234, 0xffffdb98),
            ],
        ),
    ] {
        let (mut vm, mut memory) = setup(opcode, true);
        for (left, right, product) in cases {
            assert_eq!(exact_product(left, right, opcode == 0x3a), product);
            commit(&mut vm, &mut memory, left, right, product);
        }
    }
}

#[test]
fn multiplication_varied_inputs_match_an_independent_shift_add_oracle() {
    for opcode in [0x39, 0x3a] {
        let (mut vm, mut memory) = setup(opcode, true);
        let mut sequence = 0x6532a1b7_u32;
        for _ in 0..4096 {
            sequence = sequence.wrapping_mul(1664525).wrapping_add(1013904223);
            let left = (sequence >> 8) as u16;
            sequence = sequence.wrapping_mul(1664525).wrapping_add(1013904223);
            let right = (sequence >> 8) as u16;
            commit(
                &mut vm,
                &mut memory,
                left,
                right,
                exact_product(left, right, opcode == 0x3a),
            );
        }
    }
}

#[test]
fn multiply_zero_fuel_and_fetch_retries_preserve_the_complete_state() {
    for opcode in [0x39, 0x3a] {
        let (mut vm, mut memory) = setup(opcode, true);
        vm.refuel(0);
        memory.hold_line(BASE);
        let before = vm.state.clone();
        assert_eq!(vm.step_one(&mut memory), Some(Outcome::FuelExhausted));
        assert_eq!(vm.state, before);
        vm.refuel(1);
        let before = vm.state.clone();
        for _ in 0..3 {
            assert_eq!(
                vm.step_one(&mut memory),
                Some(Outcome::WaitMemory { line: BASE })
            );
            assert_eq!(vm.state, before);
        }
        memory.release_line(BASE);
        commit(
            &mut vm,
            &mut memory,
            0xffff,
            0x8000,
            exact_product(0xffff, 0x8000, opcode == 0x3a),
        );
    }
}

#[test]
fn multiply_invalid_next_pc_or_reserved_fields_fault_before_results() {
    for opcode in [0x39, 0x3a] {
        let (mut vm, mut memory) = setup(opcode, false);
        vm.refuel(1);
        let before = vm.state.clone();
        let Some(Outcome::Fault(fault)) = vm.step_one(&mut memory) else {
            panic!("expected fault")
        };
        assert_eq!(fault.cause, FaultCause::InvalidPc);
        assert_eq!(fault.address, Some(BASE + 4));
        assert_eq!(vm.state, before);
        for field in 1..4 {
            for nonzero in [1, 0x80, 0xff] {
                let (mut vm, mut memory) = setup(opcode, true);
                let mut word = [opcode, 0, 0, 0];
                word[field] = nonzero;
                memory.write(BASE, &word).unwrap();
                vm.refuel(1);
                let before = vm.state.clone();
                let Some(Outcome::Fault(fault)) = vm.step_one(&mut memory) else {
                    panic!("expected fault")
                };
                assert!(matches!(fault.cause, FaultCause::Decode(_)));
                assert_eq!(vm.state, before);
            }
        }
    }
}

#[test]
fn interleaved_multiply_owners_and_run_have_independent_results() {
    let (mut unsigned, mut memory) = setup(0x39, true);
    let (mut signed, mut signed_memory) = setup(0x3a, true);
    for i in 0..32_u16 {
        commit(
            &mut unsigned,
            &mut memory,
            0xffff - i,
            i,
            exact_product(0xffff - i, i, false),
        );
        commit(
            &mut signed,
            &mut signed_memory,
            0x8000 + i,
            0xffff - i,
            exact_product(0x8000 + i, 0xffff - i, true),
        );
    }
    for (vm, memory, signedness) in [
        (&mut unsigned, &mut memory, false),
        (&mut signed, &mut signed_memory, true),
    ] {
        vm.state.pc = BASE;
        vm.state.r[0] = 0xffff;
        vm.state.r[1] = 0xffff;
        vm.refuel(1);
        assert_eq!(vm.run(memory), Outcome::FuelExhausted);
        let result = u32::from(vm.state.r[0]) | (u32::from(vm.state.r[1]) << 16);
        assert_eq!(result, exact_product(0xffff, 0xffff, signedness));
    }
}
