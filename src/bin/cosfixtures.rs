//! Native differential inputs and host snapshots; the target executes real bytecode.
use cos_tools::isa::Opcode;
use cos_tools::vm::{Bounds, FaultCause, Memory, Outcome, Range, ReturnValues, Syscall, Vm};
use serde::Serialize;
use std::{env, fs, path::PathBuf};

const BASE: u32 = 0x040000;
const LAST: u32 = 0x05ffff;

#[derive(Clone, Serialize)]
struct Bytes {
    address: u32,
    data: Vec<u8>,
}
#[derive(Serialize)]
struct Context {
    slot: u8,
    initial: Vec<u8>,
}
#[derive(Serialize)]
struct Action {
    command: u8,
    slot: u8,
    arguments: Vec<u8>,
    completion: Vec<u8>,
    expected_state: Vec<u8>,
    watches: Vec<Bytes>,
    expected_result: Option<u8>,
    native_data: Option<Vec<u8>>,
}
#[derive(Serialize)]
struct Case {
    name: String,
    group: String,
    patches: Vec<Bytes>,
    contexts: Vec<Context>,
    actions: Vec<Action>,
    quantum: u8,
    initial_watches: Vec<Bytes>,
}
#[derive(Default, Clone)]
struct CallState {
    token: u64,
    id: u8,
    pc: u32,
    pending: bool,
    exit: Option<u16>,
}

fn put(bytes: &mut [u8], offset: usize, value: u64, width: usize) {
    bytes[offset..offset + width].copy_from_slice(&value.to_le_bytes()[..width]);
}
fn state(vm: &Vm, outcome: Option<&Outcome>, call: &CallState, generation: u16) -> Vec<u8> {
    let mut bytes = vec![0; 96];
    for (i, r) in vm.state.r.iter().enumerate() {
        put(&mut bytes, i * 2, u64::from(*r), 2);
    }
    for (i, p) in vm.state.p.iter().enumerate() {
        put(&mut bytes, 16 + i * 3, u64::from(*p), 3);
    }
    put(&mut bytes, 28, u64::from(vm.state.pc), 3);
    put(&mut bytes, 31, u64::from(vm.state.sp), 3);
    bytes[34] = vm.state.fuel;
    put(&mut bytes, 35, vm.state.retired, 8);
    put(&mut bytes, 43, u64::from(vm.pid), 2);
    for (i, range) in [
        vm.bounds.arena,
        vm.bounds.code,
        vm.bounds.heap,
        vm.bounds.stack,
    ]
    .iter()
    .enumerate()
    {
        put(&mut bytes, 45 + i * 6, u64::from(range.first), 3);
        put(&mut bytes, 48 + i * 6, u64::from(range.last), 3);
    }
    bytes[69] = match outcome {
        None => 0,
        Some(Outcome::FuelExhausted) => 1,
        Some(Outcome::WaitMemory { .. }) => 2,
        Some(Outcome::Yield) => 3,
        Some(Outcome::Syscall(_)) => 4,
        Some(Outcome::Fault(_)) => 5,
        Some(Outcome::Stopped { .. }) => 6,
    };
    if let Some(Outcome::Fault(fault)) = outcome {
        bytes[70] = match fault.cause {
            FaultCause::Decode(_) => 1,
            FaultCause::InvalidPc => 2,
            FaultCause::AddressOverflow => 3,
            FaultCause::OutOfArena => 4,
            FaultCause::ReadOnly => 5,
            FaultCause::StackOverflow => 6,
            FaultCause::StackUnderflow => 7,
            FaultCause::InvalidSp => 8,
            FaultCause::Trap(_) => 9,
        };
        if let Some(address) = fault.address {
            put(&mut bytes, 71, u64::from(address), 4);
            bytes[75] = 1;
        }
        if let FaultCause::Trap(value) = fault.cause {
            put(&mut bytes, 76, u64::from(value), 2);
        }
    }
    if let Some(code) = call.exit {
        put(&mut bytes, 76, u64::from(code), 2);
    }
    bytes[78] = call.id;
    put(&mut bytes, 79, call.token, 8);
    put(&mut bytes, 87, u64::from(call.pc), 3);
    bytes[90] = u8::from(call.pending);
    put(&mut bytes, 91, u64::from(generation), 2);
    bytes
}

fn memory_bytes(memory: &Memory, ranges: &[(u32, u32)]) -> Vec<Bytes> {
    ranges
        .iter()
        .map(|&(address, length)| Bytes {
            address,
            data: memory.read(address, length).unwrap().to_vec(),
        })
        .collect()
}
fn action(
    command: u8,
    vm: &Vm,
    outcome: Option<&Outcome>,
    call: &CallState,
    generation: u16,
    memory: &Memory,
    watches: &[(u32, u32)],
) -> Action {
    Action {
        command,
        slot: 0,
        arguments: vec![],
        completion: vec![],
        expected_state: state(vm, outcome, call, generation),
        watches: memory_bytes(memory, watches),
        expected_result: None,
        native_data: None,
    }
}
fn setup(words: &[[u8; 4]], base: u32, last: u32) -> (Vm, Memory, Vec<Bytes>, Vec<(u32, u32)>) {
    let bounds = Bounds {
        arena: Range { first: base, last },
        code: Range {
            first: base,
            last: base + words.len() as u32 * 4 - 1,
        },
        heap: Range {
            first: (base + 0x100).max((base + words.len() as u32 * 4 + 127) & !127),
            last: last - 0x80,
        },
        stack: Range {
            first: last - 0x7f,
            last,
        },
    };
    let mut vm = Vm::new(0x1234, bounds, base, None).unwrap();
    vm.state.r = [0xaaaa, 0x8001, 0xff00, 0xbeef, 0x1234, 0xf0f0, 3, 0xab];
    vm.state.p = [base + 0xffff, base + 0xfff8, base + 0x17f, last];
    let mut memory = Memory::new();
    let code = Bytes {
        address: base,
        data: words.iter().flatten().copied().collect(),
    };
    memory.write(base, &code.data).unwrap();
    (vm, memory, vec![code], vec![(base, words.len() as u32 * 4)])
}
fn seed(
    memory: &mut Memory,
    patches: &mut Vec<Bytes>,
    watches: &mut Vec<(u32, u32)>,
    address: u32,
    data: &[u8],
) {
    memory.write(address, data).unwrap();
    patches.push(Bytes {
        address,
        data: data.to_vec(),
    });
    watches.push((address, data.len() as u32));
}
fn completion(call: &Syscall, generation: u16, values: &ReturnValues) -> Vec<u8> {
    let mut bytes = vec![0; 42];
    put(&mut bytes, 0, call.token, 8);
    put(&mut bytes, 8, u64::from(generation), 2);
    put(&mut bytes, 10, u64::from(values.status), 2);
    for i in 0..8 {
        if let Some(value) = values.r[i] {
            bytes[12] |= 1 << i;
            put(&mut bytes, 14 + i * 2, u64::from(value), 2);
        }
    }
    for i in 0..4 {
        if let Some(value) = values.p[i] {
            bytes[13] |= 1 << i;
            put(&mut bytes, 30 + i * 3, u64::from(value), 3);
        }
    }
    bytes
}
// Fixture construction keeps initial state, physical patches and independent
// watch ranges explicit at each call site.
#[allow(clippy::too_many_arguments)]
fn build_case(
    name: String,
    group: &str,
    mut vm: Vm,
    mut memory: Memory,
    patches: Vec<Bytes>,
    watches: Vec<(u32, u32)>,
    attempts: usize,
    quantum: u8,
    generation: u16,
) -> Case {
    vm.refuel(quantum);
    let mut call = CallState::default();
    let initial = state(&vm, None, &call, generation);
    let initial_watches = memory_bytes(&memory, &watches);
    let mut actions = vec![];
    for _ in 0..attempts {
        let outcome = vm.step_one(&mut memory);
        if let Some(Outcome::Syscall(request)) = &outcome {
            call.token = request.token;
            call.id = request.id;
            call.pc = request.pc;
            call.pending = true;
        }
        actions.push(action(
            2,
            &vm,
            outcome.as_ref(),
            &call,
            generation,
            &memory,
            &watches,
        ));
        match &outcome {
            Some(Outcome::FuelExhausted | Outcome::Yield) => {
                vm.refuel(quantum);
                let mut refill = action(6, &vm, None, &call, generation, &memory, &watches);
                refill.arguments = vec![quantum];
                actions.push(refill);
            }
            Some(Outcome::Syscall(request)) => {
                // Native repeated invocation and stale completion must be inert.
                actions.push(action(
                    2,
                    &vm,
                    outcome.as_ref(),
                    &call,
                    generation,
                    &memory,
                    &watches,
                ));
                let mut values = ReturnValues::status(if request.id == 0xff { 6 } else { 11 });
                if request.id == 1 {
                    values.status = 0;
                    values.r[1] = Some(cos_tools::ABI);
                    values.r[2] = Some(320);
                    values.r[3] = Some(200);
                    values.r[4] = Some(0);
                }
                let mut stale = action(
                    5,
                    &vm,
                    outcome.as_ref(),
                    &call,
                    generation,
                    &memory,
                    &watches,
                );
                stale.completion = completion(request, generation, &values);
                stale.completion[8] ^= 1;
                stale.expected_result = Some(1);
                actions.push(stale);
                let packet = completion(request, generation, &values);
                call.pending = false;
                let done = if request.id == 0 {
                    let code = request.r[0];
                    vm.exit_syscall(request.token, code).unwrap();
                    call.exit = Some(code);
                    Some(Outcome::Stopped { code })
                } else {
                    vm.complete_syscall(request.token, values).unwrap();
                    None
                };
                let mut finish =
                    action(5, &vm, done.as_ref(), &call, generation, &memory, &watches);
                finish.completion = packet;
                finish.expected_result = Some(0);
                actions.push(finish);
                if done.is_some() {
                    actions.push(action(
                        2,
                        &vm,
                        done.as_ref(),
                        &call,
                        generation,
                        &memory,
                        &watches,
                    ));
                    break;
                }
            }
            Some(Outcome::Fault(_) | Outcome::Stopped { .. }) => {
                actions.push(action(
                    2,
                    &vm,
                    outcome.as_ref(),
                    &call,
                    generation,
                    &memory,
                    &watches,
                ));
                break;
            }
            _ => (),
        }
    }
    Case {
        name,
        group: group.into(),
        patches,
        contexts: vec![Context { slot: 0, initial }],
        actions,
        quantum,
        initial_watches,
    }
}
fn cases() -> Vec<Case> {
    let mut result = vec![];
    let mut generation = 0u16;
    let mut add = |name: String,
                   group: &str,
                   vm: Vm,
                   memory: Memory,
                   patches: Vec<Bytes>,
                   watches: Vec<(u32, u32)>,
                   attempts,
                   quantum| {
        generation += 1;
        result.push(build_case(
            name, group, vm, memory, patches, watches, attempts, quantum, generation,
        ));
    };
    // Literal encodings, independent of the shared encoder and assembler.
    let valid = [
        [0x00, 0, 0, 0],
        [0x01, 0x32, 0, 0],
        [0x02, 2, 0x34, 0x12],
        [0x03, 0x32, 0, 0],
        [0x04, 0x32, 0, 0],
        [0x05, 0x32, 0, 0],
        [0x06, 0x32, 0, 0],
        [0x07, 0x32, 0, 0],
        [0x08, 2, 3, 0],
        [0x09, 2, 3, 0],
        [0x0a, 2, 3, 0],
        [0x0b, 2, 0x34, 0x12],
        [0x0c, 2, 0, 0],
        [0x0d, 2, 0, 0],
        [0x0e, 2, 0, 0],
        [0x10, 2, 0, 0],
        [0x11, 2, 0, 0],
        [0x12, 2, 0, 0],
        [0x13, 2, 0, 0],
        [0x14, 1, 0, 0],
        [0x15, 1, 0, 0],
        [0x16, 0x10, 0, 0],
        [0x17, 0x60, 0, 0],
        [0x18, 0x60, 0, 0],
        [0x19, 2, 0, 0],
        [0x1a, 2, 0, 0],
        [0x1b, 2, 6, 7],
        [0x1c, 0x12, 0x34, 0x56],
        [0x1d, 0x12, 0x34, 0x56],
        [0x1e, 0x12, 0x34, 0x56],
        [0x1f, 0x12, 0x34, 0x56],
        [0x20, 4, 0, 4],
        [0x21, 4, 0, 4],
        [0x22, 0, 0, 0],
        [0x23, 0x32, 0, 0],
        [0x24, 0x32, 0, 0],
        [0x25, 0x32, 0, 0],
        [0x26, 0x32, 0, 0],
        [0x27, 0x32, 0, 0],
        [0x28, 0x32, 0, 0],
        [0x29, 0x10, 0, 0],
        [0x2a, 0x10, 0, 0],
        [0x2b, 0x10, 0, 0],
        [0x2c, 0x10, 0, 0],
        [0x30, 3, 0, 0],
        [0x31, 3, 0, 0],
        [0x32, 0, 0, 0],
        [0x33, 0, 0, 0],
        [0x34, 0, 0, 0],
        [0x35, 3, 0, 0],
        [0x36, 1, 0, 0],
        [0x37, 0, 0, 0],
        [0x38, 0, 7, 0x10],
        [0x39, 0, 0, 0],
        [0x3a, 0, 0, 0],
    ];
    assert_eq!(valid.len(), Opcode::ALL.len());
    for word in valid {
        let (mut vm, mut memory, mut patches, mut watches) =
            setup(&[word, [0x36, 0, 0, 0]], BASE, LAST);
        seed(
            &mut memory,
            &mut patches,
            &mut watches,
            BASE + 0xfff8,
            &[
                0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0xef, 0xbe, 0xa5, 0x44, 0x55,
            ],
        );
        seed(
            &mut memory,
            &mut patches,
            &mut watches,
            LAST - 7,
            &[0xa5, 0x5a, 0, 4, 0, 4, 0, 4],
        );
        if matches!(word[0], 0x31 | 0x33 | 0x22) {
            vm.state.sp = LAST - 3;
            seed(
                &mut memory,
                &mut patches,
                &mut watches,
                LAST - 2,
                &[4, 0, 4],
            );
        }
        add(
            format!("opcode-{:02x}", word[0]),
            "isa",
            vm,
            memory,
            patches,
            watches,
            1,
            3,
        );
    }
    let mut invalid = vec![];
    for op in 0..=255u8 {
        if Opcode::from_byte(op).is_err() {
            invalid.push([op, 0, 0, 0]);
        }
    }
    for op in [0x00, 0x22, 0x37, 0x39, 0x3a] {
        invalid.extend([[op, 1, 0, 0], [op, 0, 1, 0], [op, 0, 0, 1]]);
    }
    for op in [
        0x01, 0x03, 0x04, 0x05, 0x06, 0x07, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,
    ] {
        invalid.extend([[op, 0x08, 0, 0], [op, 0x80, 0, 0], [op, 0xff, 0, 0]]);
        if op < 0x23 {
            invalid.extend([[op, 0, 1, 0], [op, 0, 0, 1]]);
        }
    }
    for op in [0x02, 0x0b, 0x0c, 0x0d, 0x0e, 0x30, 0x31] {
        invalid.extend([[op, 8, 0, 0], [op, 0x10, 0, 0], [op, 0xff, 0, 0]]);
        if !matches!(op, 0x02 | 0x0b) {
            invalid.extend([[op, 0, 1, 0], [op, 0, 0, 1]]);
        }
    }
    for op in [0x08, 0x09, 0x0a] {
        invalid.extend([[op, 8, 0, 0], [op, 0, 16, 0], [op, 0, 0, 1]]);
    }
    for op in [0x10, 0x11, 0x12, 0x13, 0x19, 0x1a] {
        invalid.extend([[op, 8, 0, 0], [op, 0x40, 0, 0]]);
    }
    for op in [0x19, 0x1a, 0x16, 0x17, 0x18] {
        invalid.extend([[op, 0, 1, 0], [op, 0, 0, 1]]);
    }
    for op in [0x14, 0x15, 0x16, 0x29, 0x2a, 0x2b, 0x2c] {
        invalid.extend([[op, 4, 0, 0], [op, 0x40, 0, 0]]);
    }
    for op in [0x17, 0x18] {
        invalid.extend([[op, 4, 0, 0], [op, 0x80, 0, 0]]);
    }
    invalid.extend([
        [0x1b, 4, 0, 0],
        [0x1b, 0x10, 0, 0],
        [0x1b, 0, 8, 0],
        [0x1b, 0, 0, 8],
    ]);
    for op in [0x32, 0x33, 0x34, 0x35] {
        invalid.extend([
            [op, 4, 0, 0],
            [op, 0x10, 0, 0],
            [op, 0, 1, 0],
            [op, 0, 0, 1],
        ]);
    }
    invalid.extend([[0x36, 0, 1, 0], [0x36, 0, 0, 1], [0x38, 1, 0, 0]]);
    for (i, word) in invalid.into_iter().enumerate() {
        let (vm, memory, patches, watches) = setup(&[word], BASE, LAST);
        add(
            format!("invalid-{i:03}-{word:02x?}"),
            "decode",
            vm,
            memory,
            patches,
            watches,
            1,
            128,
        );
    }
    // Fixed-width arithmetic vectors are also checked against independent literals.
    for (i, (word, left, right, expected)) in [
        ([0x03, 0x10, 0, 0], 0xffff, 1, 0),
        ([0x04, 0x10, 0, 0], 0, 1, 0xffff),
        ([0x05, 0x10, 0, 0], 0xf0f0, 0x0ff0, 0x00f0),
        ([0x06, 0x10, 0, 0], 0xf0f0, 0x0ff0, 0xfff0),
        ([0x07, 0x10, 0, 0], 0xf0f0, 0x0ff0, 0xff00),
        ([0x08, 0, 1, 0], 0x8001, 0, 2),
        ([0x09, 0, 1, 0], 0x8001, 0, 0x4000),
        ([0x0a, 0, 1, 0], 0x8001, 0, 0xc000),
        ([0x0b, 0, 5, 0], 0xfffe, 0, 3),
        ([0x0c, 0, 0, 0], 0xab80, 0, 0x80),
        ([0x0d, 0, 0, 0], 0xab80, 0, 0xff80),
        ([0x0e, 0, 0, 0], 0xa5f0, 0, 0x5a0f),
    ]
    .into_iter()
    .enumerate()
    {
        let (mut vm, memory, patches, watches) = setup(&[word, [0x36, 0, 0, 0]], BASE, LAST);
        vm.state.r[0] = left;
        vm.state.r[1] = right;
        let case = build_case(
            format!("integer-{i:02}"),
            "integer",
            vm,
            memory,
            patches,
            watches,
            1,
            1,
            generation + 1,
        );
        assert_eq!(
            u16::from_le_bytes(case.actions[0].expected_state[..2].try_into().unwrap()),
            expected
        );
        generation += 1;
        result.push(case);
    }
    // Remaining ranges exercise actual data misses, atomic accesses and 24-bit limits.
    let mut add_more = |name: String,
                        group: &str,
                        vm: Vm,
                        memory: Memory,
                        patches: Vec<Bytes>,
                        watches: Vec<(u32, u32)>,
                        attempts,
                        quantum| {
        generation += 1;
        result.push(build_case(
            name, group, vm, memory, patches, watches, attempts, quantum, generation,
        ));
    };
    for word in [
        [0x01, 0, 0, 0],
        [0x03, 0, 0, 0],
        [0x04, 0, 0, 0],
        [0x07, 0, 0, 0],
        [0x08, 0, 0, 0],
        [0x09, 0, 0, 0],
        [0x0a, 0, 0, 0],
        [0x16, 0, 0, 0],
    ] {
        let (vm, memory, patches, watches) = setup(&[word, [0x36, 0, 0, 0]], BASE, LAST);
        add_more(
            format!("self-or-zero-{:02x}", word[0]),
            "operand-aliasing",
            vm,
            memory,
            patches,
            watches,
            1,
            3,
        );
    }
    let (mut vm, memory, patches, watches) = setup(&[[0x1b, 0, 1, 2], [0x36, 0, 0, 0]], BASE, LAST);
    vm.state.r[2] = 256;
    add_more(
        "pmake-high-overflow".into(),
        "address-faults",
        vm,
        memory,
        patches,
        watches,
        1,
        3,
    );
    for pointer in [LAST, LAST - 128, LAST + 1] {
        let (mut vm, memory, patches, watches) =
            setup(&[[0x35, 0, 0, 0], [0x36, 0, 0, 0]], BASE, LAST);
        vm.state.p[0] = pointer;
        add_more(
            format!("setsp-{pointer:06x}"),
            "stack-faults",
            vm,
            memory,
            patches,
            watches,
            1,
            3,
        );
    }
    let (mut vm, memory, patches, watches) =
        setup(&[[0x10, 0x01, 1, 0], [0x36, 0, 0, 0]], BASE, LAST);
    vm.state.p[0] = 0xffffff;
    add_more(
        "memory-offset-overflow".into(),
        "address-faults",
        vm,
        memory,
        patches,
        watches,
        1,
        3,
    );
    for op in [0x10, 0x11, 0x12, 0x13, 0x14, 0x15] {
        for address in [0x040101, 0x04013f, 0x04017f, 0x04ffff] {
            let (mut vm, mut memory, mut patches, mut watches) =
                setup(&[[op, 0x01, 0, 0], [0x36, 0, 0, 0]], BASE, LAST);
            vm.state.p[0] = address;
            vm.state.p[1] = 0xabcdef;
            vm.state.r[1] = 0xbeef;
            seed(
                &mut memory,
                &mut patches,
                &mut watches,
                address - 1,
                &[0xa5, 0xef, 0xbe, 0x56, 0xcc],
            );
            add_more(
                format!("access-{op:02x}-{address:06x}"),
                "linear-memory",
                vm,
                memory,
                patches,
                watches,
                1,
                3,
            );
        }
    }
    for (op, pointer, amount) in [
        (0x17, 0xffffff, 1),
        (0x17, 0xffff00, 0x100),
        (0x18, 0, 1),
        (0x18, 0x100, 0x101),
    ] {
        let (mut vm, memory, patches, watches) =
            setup(&[[op, 0x10, 0, 0], [0x36, 0, 0, 0]], BASE, LAST);
        vm.state.p[0] = pointer;
        vm.state.r[1] = amount;
        add_more(
            format!("pointer-{op:02x}-{pointer:06x}"),
            "address-faults",
            vm,
            memory,
            patches,
            watches,
            1,
            3,
        );
    }
    for address in [0x000000, 0x03ffff, 0x040000, 0x05ffff, 0x060000, 0xffffff] {
        for op in [0x10, 0x11, 0x12, 0x13] {
            let (mut vm, mut memory, mut patches, mut watches) =
                setup(&[[op, 0x01, 0, 0], [0x36, 0, 0, 0]], BASE, LAST);
            vm.state.p[0] = address;
            if address >= 0x40000 {
                seed(&mut memory, &mut patches, &mut watches, address, &[0xa5]);
                if address == BASE {
                    // Keep the executable word intact for code-write protection.
                    patches.pop();
                    watches.pop();
                    memory.write(BASE, &[op, 1, 0, 0]).unwrap();
                }
            }
            add_more(
                format!("bounds-{op:02x}-{address:06x}"),
                "arena-code-protection",
                vm,
                memory,
                patches,
                watches,
                1,
                3,
            );
        }
    }
    for op in [0x10, 0x11, 0x12, 0x13, 0x14, 0x15] {
        let (mut vm, mut memory, mut patches, mut watches) =
            setup(&[[op, 0x01, 0, 0], [0x36, 0, 0, 0]], 0xfffc00, 0xffffff);
        vm.state.p[0] = 0xffffff;
        vm.state.p[1] = 0xabcdef;
        seed(&mut memory, &mut patches, &mut watches, 0xffffff, &[0x5a]);
        add_more(
            format!("final-reu-{op:02x}"),
            "last-reu-byte",
            vm,
            memory,
            patches,
            watches,
            1,
            1,
        );
    }
    for op in [0x30, 0x32, 0x21, 0x31, 0x33, 0x22] {
        let push = matches!(op, 0x30 | 0x32 | 0x21);
        let word = if op == 0x21 {
            [op, 4, 0, 4]
        } else {
            [op, 0, 0, 0]
        };
        for invalid_sp in [false, true] {
            let (mut vm, memory, patches, watches) = setup(&[word, [0x36, 0, 0, 0]], BASE, LAST);
            vm.state.sp = if invalid_sp {
                vm.bounds.stack.first - 2
            } else if push {
                vm.bounds.stack.first - 1
            } else {
                LAST
            };
            add_more(
                format!("stack-{op:02x}-{invalid_sp}"),
                "stack-faults",
                vm,
                memory,
                patches,
                watches,
                1,
                3,
            );
        }
    }
    for target in [0, BASE - 4, BASE + 1, BASE + 8, 0xffffff] {
        let (mut vm, memory, patches, watches) =
            setup(&[[0, 0, 0, 0], [0x36, 0, 0, 0]], BASE, LAST);
        vm.state.pc = target;
        add_more(
            format!("pc-{target:06x}"),
            "pc-faults",
            vm,
            memory,
            patches,
            watches,
            1,
            3,
        );
    }
    for op in [0x02, 0x13, 0x30, 0x21, 0x36, 0x39, 0x3a] {
        let word = match op {
            0x02 => [op, 2, 42, 0],
            0x13 => [op, 0x01, 0, 0],
            0x21 => [op, 0, 0, 4],
            0x36 => [op, 1, 0, 0],
            0x39 | 0x3a => [op, 0, 0, 0],
            _ => [op, 2, 0, 0],
        };
        let (mut vm, mut memory, mut patches, mut watches) = setup(&[word], BASE, LAST);
        vm.state.p[0] = BASE + 0x17f;
        seed(
            &mut memory,
            &mut patches,
            &mut watches,
            BASE + 0x17e,
            &[0xa5, 0x5a, 0xcc, 0x33],
        );
        seed(&mut memory, &mut patches, &mut watches, LAST - 7, &[0; 8]);
        add_more(
            format!("invalid-fallthrough-{op:02x}"),
            "preflight",
            vm,
            memory,
            patches,
            watches,
            1,
            3,
        );
    }
    for target in [BASE, BASE + 1, BASE + 8, 0xffffff] {
        let (mut vm, mut memory, mut patches, mut watches) =
            setup(&[[0x22, 0, 0, 0], [0x36, 0, 0, 0]], BASE, LAST);
        vm.state.sp = LAST - 3;
        seed(
            &mut memory,
            &mut patches,
            &mut watches,
            LAST - 2,
            &target.to_le_bytes()[..3],
        );
        add_more(
            format!("return-{target:06x}"),
            "return-preflight",
            vm,
            memory,
            patches,
            watches,
            1,
            3,
        );
    }
    for op in 0x23..=0x2c {
        for (i, (left, right)) in [
            (0x8000u32, 0x7fff),
            (0xffff, 0xffff),
            (0x7fff, 0x8000),
            (0, 0xffff),
            (0x8001, 0x8000),
            (0x0001, 0x0000),
        ]
        .into_iter()
        .enumerate()
        {
            let (mut vm, memory, patches, watches) = setup(
                &[
                    [op, 0x10, 1, 0],
                    [0, 0, 0, 0],
                    [0x02, 2, 42, 0],
                    [0x36, 0, 0, 0],
                ],
                BASE,
                LAST,
            );
            vm.state.r[0] = left as u16;
            vm.state.r[1] = right as u16;
            vm.state.p[0] = left;
            vm.state.p[1] = right;
            add_more(
                format!("branch-{op:02x}-{i}"),
                "branch-comparisons",
                vm,
                memory,
                patches,
                watches,
                2,
                3,
            );
        }
    }
    for (word, base, last) in [
        ([0x23, 0, 0xfe, 0xff], BASE, LAST),
        ([0x23, 0, 0xff, 0x7f], BASE, LAST),
        ([0x23, 0, 0xff, 0x7f], 0xfffc00, 0xffffff),
    ] {
        let (vm, memory, patches, watches) = setup(&[word, [0x36, 0, 0, 0]], base, last);
        add_more(
            format!("branch-overflow-{base:06x}-{:02x}", word[2]),
            "branch-overflow",
            vm,
            memory,
            patches,
            watches,
            1,
            3,
        );
    }
    let nested = [
        [0x21, 12, 0, 4],
        [0x36, 0, 0, 0],
        [0x38, 0, 0, 0],
        [0x30, 3, 0, 0],
        [0x32, 0, 0, 0],
        [0x21, 32, 0, 4],
        [0x33, 0, 0, 0],
        [0x31, 3, 0, 0],
        [0x22, 0, 0, 0],
    ];
    let (vm, mut memory, mut patches, mut watches) = setup(&nested, BASE, LAST);
    seed(&mut memory, &mut patches, &mut watches, LAST - 31, &[0; 32]);
    // Inner function returns at +32; outer then restores pointer/integer and returns.
    add_more(
        "nested-stack".into(),
        "nested-calls",
        vm,
        memory,
        patches,
        watches,
        25,
        3,
    );
    for quantum in [1, 3, 128] {
        let (vm, memory, patches, watches) = setup(&[[0x0b, 2, 1, 0], [0x20, 0, 0, 4]], BASE, LAST);
        add_more(
            format!("non-yield-loop-{quantum}"),
            "fuel",
            vm,
            memory,
            patches,
            watches,
            20,
            quantum,
        );
    }
    // More than eight distinct dirty lines must use real CLOCK write-back.
    for stride in [64u16, 128, 256] {
        let mut words = vec![];
        for i in 0..12 {
            words.push([0x13, 0x01, (i * stride) as u8, ((i * stride) >> 8) as u8]);
        }
        for i in 0..12 {
            words.push([0x11, 0x02, (i * stride) as u8, ((i * stride) >> 8) as u8]);
        }
        words.push([0x36, 0, 0, 0]);
        let (mut vm, mut memory, mut patches, mut watches) = setup(&words, BASE, LAST);
        vm.state.p[0] = BASE + 0x100;
        vm.state.r[1] = 0xbeef;
        for i in 0..12 {
            seed(
                &mut memory,
                &mut patches,
                &mut watches,
                BASE + 0x100 + u32::from(i * stride),
                &[0xa5, 0x5a],
            );
        }
        add_more(
            format!("clock-conflicts-{stride}"),
            "dirty-eviction",
            vm,
            memory,
            patches,
            watches,
            35,
            3,
        );
    }
    // A real code working set exceeding two lines exercises alternating replacement.
    let mut words = vec![[0; 4]; 100];
    words[0] = [0x20, 0x80, 0, 4];
    words[32] = [0x20, 0, 1, 4];
    words[64] = [0x20, 0, 0, 4];
    let (mut vm, memory, patches, watches) = setup(&words, BASE, LAST);
    vm.bounds.heap.first = BASE + 0x200;
    add_more(
        "code-three-line-loop".into(),
        "code-cache",
        vm,
        memory,
        patches,
        watches,
        20,
        3,
    );
    // Coherent native operations are trusted test services, not implemented SDK calls.
    generation += 1;
    let (mut vm, mut memory, mut patches, mut watches) = setup(
        &[[0x13, 0x01, 0, 0], [0x11, 0x02, 0, 0], [0x36, 0, 0, 0]],
        BASE,
        LAST,
    );
    vm.state.p[0] = BASE + 0x17f;
    vm.state.r[1] = 0xabcd;
    vm.refuel(3);
    seed(
        &mut memory,
        &mut patches,
        &mut watches,
        BASE + 0x17e,
        &[0xa5, 0x11, 0x22, 0xcc],
    );
    let call = CallState::default();
    let initial = state(&vm, None, &call, generation);
    let initial_watches = memory_bytes(&memory, &watches);
    let mut actions = vec![];
    assert!(vm.step_one(&mut memory).is_none());
    actions.push(action(2, &vm, None, &call, generation, &memory, &watches));
    let mut read = action(9, &vm, None, &call, generation, &memory, &watches);
    read.arguments = vec![0x7f, 1, 4, 2, 0, 0, 0];
    read.native_data = Some(vec![0xcd, 0xab]);
    actions.push(read);
    memory.write(BASE + 0x180, &[0x99]).unwrap();
    let mut write = action(10, &vm, None, &call, generation, &memory, &watches);
    write.arguments = vec![0x80, 1, 4, 1, 0x99, 0, 0];
    actions.push(write);
    assert!(vm.step_one(&mut memory).is_none());
    assert_eq!(vm.state.r[2], 0x99cd);
    actions.push(action(2, &vm, None, &call, generation, &memory, &watches));
    let mut deadline = action(11, &vm, None, &call, generation, &memory, &watches);
    deadline.expected_state[69] = 7;
    actions.push(deadline);
    result.push(Case {
        name: "native-coherence-split".into(),
        group: "native-coherence".into(),
        patches,
        contexts: vec![Context { slot: 0, initial }],
        actions,
        quantum: 3,
        initial_watches,
    });

    // Saved contexts retain state and cache ownership without per-switch flushes.
    generation += 1;
    let (mut a, mut memory, mut patches, mut watches) = setup(
        &[[0x13, 0x01, 0, 0], [0x11, 0x02, 0, 0], [0x13, 0x31, 0, 0]],
        BASE,
        LAST,
    );
    let (mut b, bmem, bpatch, bwatch) = setup(
        &[
            [0x13, 0x01, 0, 0],
            [0x11, 0x02, 0, 0],
            [0x0b, 2, 1, 0],
            [0x20, 8, 0, 6],
        ],
        0x060000,
        0x07ffff,
    );
    for patch in &bpatch {
        memory
            .write(
                patch.address,
                bmem.read(patch.address, patch.data.len() as u32).unwrap(),
            )
            .unwrap();
    }
    patches.extend(bpatch);
    watches.extend(bwatch);
    a.state.p[0] = BASE + 0x100;
    a.state.r[1] = 0xa1a2;
    a.state.p[3] = 0x060100;
    b.pid = 0x5678;
    b.state.p[0] = 0x060100;
    b.state.r[1] = 0xb1b2;
    a.refuel(3);
    b.refuel(3);
    seed(
        &mut memory,
        &mut patches,
        &mut watches,
        BASE + 0x100,
        &[0x11, 0x22],
    );
    seed(
        &mut memory,
        &mut patches,
        &mut watches,
        0x060100,
        &[0x33, 0x44],
    );
    let call = CallState::default();
    let contexts = vec![
        Context {
            slot: 0,
            initial: state(&a, None, &call, generation),
        },
        Context {
            slot: 1,
            initial: state(&b, None, &call, generation),
        },
    ];
    let initial_watches = memory_bytes(&memory, &watches);
    let mut actions = vec![];
    let mut saved_outcomes = [None, None];
    for (slot, do_step) in [
        (0, true),
        (1, true),
        (0, true),
        (1, true),
        (0, true),
        (1, true),
        (0, true),
    ] {
        let vm = if slot == 0 { &mut a } else { &mut b };
        let mut switch = action(
            7,
            vm,
            saved_outcomes[slot as usize].as_ref(),
            &call,
            generation,
            &memory,
            &watches,
        );
        switch.slot = slot;
        actions.push(switch);
        if do_step {
            let outcome = vm.step_one(&mut memory);
            let mut step = action(
                2,
                vm,
                outcome.as_ref(),
                &call,
                generation,
                &memory,
                &watches,
            );
            step.slot = slot;
            actions.push(step);
            saved_outcomes[slot as usize] = outcome;
        }
    }
    assert_eq!(a.state.r[2], 0xa1a2);
    assert_eq!(b.state.r[2], 0xb1b3);
    assert_eq!(a.state.retired, 2); // Third opcode faults before touching the other arena.
    result.push(Case {
        name: "two-context-isolation".into(),
        group: "context-isolation".into(),
        patches,
        contexts,
        actions,
        quantum: 3,
        initial_watches,
    });
    result.push(pending_context_case(generation + 1));
    result.push(run_boundary_case(generation + 2));
    result.extend(multiplication_cases(2000));
    result
}

// A shift/add oracle is independent of the reference VM's native integer multiply.
fn product_oracle(left: u16, right: u16, signed: bool) -> u32 {
    let magnitude = |n: u16| {
        if signed && n & 0x8000 != 0 {
            n.wrapping_neg()
        } else {
            n
        }
    };
    let a = u32::from(magnitude(left));
    let b = magnitude(right);
    let mut value = 0_u32;
    for bit in 0..16 {
        if b & (1 << bit) != 0 {
            value += a << bit;
        }
    }
    if signed && (left ^ right) & 0x8000 != 0 {
        value.wrapping_neg()
    } else {
        value
    }
}

fn multiplication_cases(mut generation: u16) -> Vec<Case> {
    let mut result = vec![];
    for opcode in [0x39, 0x3a] {
        for (left, right) in [
            (0, 0),
            (0, 0xffff),
            (1, 1),
            (1, 0xffff),
            (0xffff, 0xffff),
            (0x8000, 0x8000),
            (0x8000, 0xffff),
            (0xffff, 0x8000),
            (0x8000, 1),
            (0x7fff, 0x7fff),
            (0x8000, 0x7fff),
            (0x1234, 0xfffe),
            (0xfffe, 0x1234),
            (0xffff, 0xfffe),
            (0x0101, 0x0101),
            (0xaaaa, 0x5555),
        ] {
            generation += 1;
            let (mut vm, memory, patches, watches) =
                setup(&[[opcode, 0, 0, 0], [0x36, 0, 0, 0]], BASE, LAST);
            vm.state.r[0] = left;
            vm.state.r[1] = right;
            let expected = product_oracle(left, right, opcode == 0x3a);
            let case = build_case(
                format!("multiply-{opcode:02x}-{left:04x}-{right:04x}"),
                "integer-multiply",
                vm,
                memory,
                patches,
                watches,
                1,
                1,
                generation,
            );
            assert_eq!(
                &case.actions[0].expected_state[..4],
                &expected.to_le_bytes()
            );
            result.push(case);
        }
        // Cross both code-cache line sizes while checking every individual result.
        // Loads are literal encodings; every multiply snapshot also preserves R2–R7/P/SP.
        let mut sequence = 0x6532a1b7_u32;
        let mut words = vec![];
        let mut products = vec![];
        for _ in 0..32 {
            sequence = sequence.wrapping_mul(1664525).wrapping_add(1013904223);
            let left = (sequence >> 8) as u16;
            sequence = sequence.wrapping_mul(1664525).wrapping_add(1013904223);
            let right = (sequence >> 8) as u16;
            words.extend([
                [0x02, 0, left as u8, (left >> 8) as u8],
                [0x02, 1, right as u8, (right >> 8) as u8],
                [opcode, 0, 0, 0],
            ]);
            products.push(product_oracle(left, right, opcode == 0x3a));
        }
        words.push([0x36, 0, 0, 0]);
        let (vm, memory, patches, watches) = setup(&words, BASE, LAST);
        generation += 1;
        let case = build_case(
            format!("multiply-varied-{opcode:02x}"),
            "integer-multiply",
            vm,
            memory,
            patches,
            watches,
            96,
            128,
            generation,
        );
        for (n, product) in products.iter().enumerate() {
            assert_eq!(
                &case.actions[n * 3 + 2].expected_state[..4],
                &product.to_le_bytes()
            );
        }
        result.push(case);

        // Zero fuel wins even on a cold fetch; one refill then commits once.
        generation += 1;
        let (mut vm, mut memory, patches, watches) =
            setup(&[[opcode, 0, 0, 0], [0x36, 0, 0, 0]], BASE, LAST);
        vm.refuel(0);
        let call = CallState::default();
        let initial = state(&vm, None, &call, generation);
        let initial_watches = memory_bytes(&memory, &watches);
        let outcome = vm.step_one(&mut memory);
        assert_eq!(outcome, Some(Outcome::FuelExhausted));
        let mut actions = vec![action(
            2,
            &vm,
            outcome.as_ref(),
            &call,
            generation,
            &memory,
            &watches,
        )];
        vm.refuel(1);
        let mut refill = action(6, &vm, None, &call, generation, &memory, &watches);
        refill.arguments = vec![1];
        actions.push(refill);
        // Native command11 forces an active-line attempt before code is fetched.
        let mut video = action(11, &vm, None, &call, generation, &memory, &watches);
        video.expected_state[69] = 7;
        actions.push(video);
        assert!(vm.step_one(&mut memory).is_none());
        actions.push(action(2, &vm, None, &call, generation, &memory, &watches));
        let outcome = vm.step_one(&mut memory);
        assert_eq!(outcome, Some(Outcome::FuelExhausted));
        actions.push(action(
            2,
            &vm,
            outcome.as_ref(),
            &call,
            generation,
            &memory,
            &watches,
        ));
        result.push(Case {
            name: format!("multiply-zero-fuel-video-retry-{opcode:02x}"),
            group: "multiply-boundaries".into(),
            patches,
            contexts: vec![Context { slot: 0, initial }],
            actions,
            quantum: 1,
            initial_watches,
        });
    }

    generation += 1;
    let (mut a, mut memory, mut patches, mut watches) = setup(
        &[[0x39, 0, 0, 0], [0x3a, 0, 0, 0], [0x36, 0, 0, 0]],
        BASE,
        LAST,
    );
    let (mut b, _, bpatches, bwatches) = setup(
        &[[0x3a, 0, 0, 0], [0x39, 0, 0, 0], [0x36, 0, 0, 0]],
        0x60000,
        0x7ffff,
    );
    for patch in &bpatches {
        memory.write(patch.address, &patch.data).unwrap();
    }
    patches.extend(bpatches);
    watches.extend(bwatches);
    a.state.r[0] = 0xffff;
    a.state.r[1] = 0xffff;
    a.refuel(2);
    b.pid = 0x5678;
    b.state.r[0] = 0x8000;
    b.state.r[1] = 0x8000;
    b.refuel(2);
    let call = CallState::default();
    let contexts = vec![
        Context {
            slot: 0,
            initial: state(&a, None, &call, generation),
        },
        Context {
            slot: 1,
            initial: state(&b, None, &call, generation),
        },
    ];
    let initial_watches = memory_bytes(&memory, &watches);
    let mut actions = vec![];
    let mut outcomes = [None, None];
    for slot in [0, 1, 0, 1, 0, 1] {
        let vm = if slot == 0 { &mut a } else { &mut b };
        let mut switch = action(
            7,
            vm,
            outcomes[slot as usize].as_ref(),
            &call,
            generation,
            &memory,
            &watches,
        );
        switch.slot = slot;
        actions.push(switch);
        let outcome = vm.step_one(&mut memory);
        let mut step = action(
            2,
            vm,
            outcome.as_ref(),
            &call,
            generation,
            &memory,
            &watches,
        );
        step.slot = slot;
        actions.push(step);
        outcomes[slot as usize] = outcome;
    }
    assert_eq!(&a.state.r[..2], &[0xfffe, 0xffff]);
    assert_eq!(&b.state.r[..2], &[0, 0]);
    assert_eq!((a.state.retired, b.state.retired), (2, 2));
    result.push(Case {
        name: "multiply-interleaved-owners".into(),
        group: "multiply-boundaries".into(),
        patches,
        contexts,
        actions,
        quantum: 2,
        initial_watches,
    });
    result
}

fn run_boundary_case(generation: u16) -> Case {
    // The first attempt genuinely fills code; subsequent multi-opcode run calls
    // stay within that line so the independently expected slice is unambiguous.
    let (mut vm, mut memory, patches, watches) =
        setup(&[[0x0b, 2, 1, 0], [0x20, 0, 0, 4]], BASE, LAST);
    vm.state.r[2] = 0;
    vm.refuel(3);
    let call = CallState::default();
    let initial = state(&vm, None, &call, generation);
    let initial_watches = memory_bytes(&memory, &watches);
    let outcome = vm.step_one(&mut memory);
    let mut actions = vec![action(
        2,
        &vm,
        outcome.as_ref(),
        &call,
        generation,
        &memory,
        &watches,
    )];
    for _ in 0..3 {
        let outcome = vm.run(&mut memory);
        assert_eq!(outcome, Outcome::FuelExhausted);
        actions.push(action(
            3,
            &vm,
            Some(&outcome),
            &call,
            generation,
            &memory,
            &watches,
        ));
        vm.refuel(3);
        let mut refill = action(6, &vm, None, &call, generation, &memory, &watches);
        refill.arguments = vec![3];
        actions.push(refill);
    }
    assert_eq!(vm.state.retired, 9);
    assert_eq!(vm.state.r[2], 5);
    Case {
        name: "native-run-fuel-slices".into(),
        group: "run-boundaries".into(),
        patches,
        contexts: vec![Context { slot: 0, initial }],
        actions,
        quantum: 3,
        initial_watches,
    }
}

fn pending_context_case(generation: u16) -> Case {
    let (mut a, mut memory, mut patches, mut watches) =
        setup(&[[0x36, 1, 0, 0], [0x37, 0, 0, 0]], BASE, LAST);
    let (mut b, _, bpatch, bwatch) =
        setup(&[[0x36, 0xff, 0, 0], [0x37, 0, 0, 0]], 0x060000, 0x07ffff);
    for patch in &bpatch {
        memory.write(patch.address, &patch.data).unwrap();
    }
    patches.extend(bpatch);
    watches.extend(bwatch);
    b.pid = 0x5678;
    a.refuel(3);
    b.refuel(3);
    let mut acall = CallState::default();
    let mut bcall = CallState::default();
    let contexts = vec![
        Context {
            slot: 0,
            initial: state(&a, None, &acall, generation),
        },
        Context {
            slot: 1,
            initial: state(&b, None, &bcall, generation),
        },
    ];
    let initial_watches = memory_bytes(&memory, &watches);
    let mut actions = vec![];
    let mut requests = vec![];
    for slot in [0, 1] {
        let (vm, call) = if slot == 0 {
            (&mut a, &mut acall)
        } else {
            (&mut b, &mut bcall)
        };
        let mut switch = action(7, vm, None, call, generation, &memory, &watches);
        switch.slot = slot;
        actions.push(switch);
        let outcome = vm.step_one(&mut memory).unwrap();
        let Outcome::Syscall(request) = &outcome else {
            panic!("expected pending call");
        };
        call.id = request.id;
        call.token = request.token;
        call.pc = request.pc;
        call.pending = true;
        requests.push(request.clone());
        let mut step = action(2, vm, Some(&outcome), call, generation, &memory, &watches);
        step.slot = slot;
        actions.push(step);
    }
    assert_eq!(requests[0].token, requests[1].token);
    let a_values = ReturnValues::status(0);
    let b_values = ReturnValues::status(6);
    // Same token and generation are insufficient: command target identifies owner.
    let b_pending = Outcome::Syscall(requests[1].clone());
    let mut wrong_owner = action(
        5,
        &b,
        Some(&b_pending),
        &bcall,
        generation,
        &memory,
        &watches,
    );
    wrong_owner.slot = 0;
    wrong_owner.completion = completion(&requests[0], generation, &a_values);
    wrong_owner.expected_result = Some(1);
    actions.push(wrong_owner);
    b.complete_syscall(requests[1].token, b_values.clone())
        .unwrap();
    bcall.pending = false;
    let mut complete_b = action(5, &b, None, &bcall, generation, &memory, &watches);
    complete_b.slot = 1;
    complete_b.completion = completion(&requests[1], generation, &b_values);
    complete_b.expected_result = Some(0);
    actions.push(complete_b);
    let a_pending = Outcome::Syscall(requests[0].clone());
    actions.push(action(
        7,
        &a,
        Some(&a_pending),
        &acall,
        generation,
        &memory,
        &watches,
    ));
    let repeated = a.step_one(&mut memory).unwrap();
    actions.push(action(
        2,
        &a,
        Some(&repeated),
        &acall,
        generation,
        &memory,
        &watches,
    ));
    a.complete_syscall(requests[0].token, a_values.clone())
        .unwrap();
    acall.pending = false;
    let mut complete_a = action(5, &a, None, &acall, generation, &memory, &watches);
    complete_a.completion = completion(&requests[0], generation, &a_values);
    complete_a.expected_result = Some(0);
    actions.push(complete_a);
    Case {
        name: "pending-context-owner-collision".into(),
        group: "context-syscall-isolation".into(),
        patches,
        contexts,
        actions,
        quantum: 3,
        initial_watches,
    }
}

fn manifest_cases(
    path: &std::path::Path,
    generation: u16,
) -> Result<Vec<Case>, Box<dyn std::error::Error>> {
    let manifest: cos_tools::pack::LinkedManifest = serde_json::from_slice(&fs::read(path)?)?;
    manifest.validate()?;
    let image = fs::read(
        path.parent()
            .unwrap_or(std::path::Path::new("."))
            .join(&manifest.reu_image),
    )?;
    manifest.validate_image(&image)?;
    let mut result = vec![];
    for (index, app) in manifest.apps.iter().enumerate() {
        for quantum in [1, 3, 128] {
            let vm = Vm::new(
                app.id,
                Bounds {
                    arena: app.arena,
                    code: app.code,
                    heap: app.heap,
                    stack: app.stack,
                },
                app.entry,
                (app.data.length != 0).then_some(app.data.start),
            )?;
            let mut memory = Memory::new();
            let mut patches = vec![];
            let mut watches = vec![];
            seed(
                &mut memory,
                &mut patches,
                &mut watches,
                app.code.first,
                &image[app.code.first as usize..=app.code.last as usize],
            );
            if app.data.length != 0 {
                seed(
                    &mut memory,
                    &mut patches,
                    &mut watches,
                    app.data.start,
                    &image[app.data_seed.start as usize
                        ..(app.data_seed.start + app.data_seed.length) as usize],
                );
            }
            seed(
                &mut memory,
                &mut patches,
                &mut watches,
                app.stack.last - 31,
                &[0; 32],
            );
            // Linear deliberately uses BSS around the 64 KiB boundary.
            if app.name == "Linear" {
                seed(&mut memory, &mut patches, &mut watches, 0x04fffe, &[0; 4]);
            }
            result.push(build_case(
                format!("assembly-{}-{quantum}", app.name),
                "assembled-programs",
                vm,
                memory,
                patches,
                watches,
                if app.name == "Spin" { 24 } else { 80 },
                quantum,
                generation + index as u16 * 3 + u16::from(quantum),
            ));
        }
    }
    Ok(result)
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().skip(1).collect();
    let out = PathBuf::from(
        args.first()
            .map(String::as_str)
            .unwrap_or("build/m2-fixtures.json"),
    );
    if let Some(parent) = out.parent() {
        fs::create_dir_all(parent)?;
    }
    let mut cases = cases();
    if args.len() > 1 {
        if args.len() != 3 || args[1] != "--manifest" {
            return Err("usage: cosfixtures OUTPUT [--manifest LINKED_MANIFEST]".into());
        }
        cases.extend(manifest_cases(std::path::Path::new(&args[2]), 1000)?);
    }
    let document = serde_json::json!({"format":"COSM2FIXTURES1","abi":cos_tools::ABI,
        "state_bytes":96,"qualification":"Host semantic oracle for native execution","cases":cases});
    fs::write(&out, serde_json::to_vec_pretty(&document)?)?;
    println!(
        "Generated {} native differential cases: {}",
        document["cases"].as_array().unwrap().len(),
        out.display()
    );
    Ok(())
}
