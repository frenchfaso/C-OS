use cos_tools::harness::{Harness, ServiceState};
use cos_tools::vm::{Bounds, Memory, Outcome, Range, Vm};

fn setup(id: u8) -> (Vm, Memory, Harness) {
    let bounds = Bounds {
        arena: Range {
            first: 0x40000,
            last: 0x5ffff,
        },
        code: Range {
            first: 0x40000,
            last: 0x40007,
        },
        heap: Range {
            first: 0x40100,
            last: 0x5feff,
        },
        stack: Range {
            first: 0x5ff00,
            last: 0x5ffff,
        },
    };
    let vm = Vm::new(7, bounds, 0x40000, None).unwrap();
    let mut memory = Memory::new();
    memory
        .write(0x40000, &[0x36, id, 0, 0, 0x36, 0, 0, 0])
        .unwrap();
    (vm, memory, Harness::new())
}

#[test]
fn invocation_and_completion_are_exactly_once() {
    let (mut vm, mut memory, mut kernel) = setup(1);
    vm.state.r[7] = 0xbeef;
    vm.refuel(3);
    let Outcome::Syscall(call) = vm.run(&mut memory) else {
        panic!()
    };
    assert_eq!(vm.state.pc, 0x40004);
    assert_eq!((vm.state.fuel, vm.state.retired), (2, 1));
    assert_eq!(vm.run(&mut memory), Outcome::Syscall(call.clone()));
    assert_eq!(
        kernel.accept(&mut vm, &mut memory, &call).unwrap(),
        ServiceState::Complete
    );
    assert_eq!(vm.state.r[0..5], [0, 2, 320, 200, 0]);
    assert_eq!(vm.state.r[7], 0xbeef);
    assert!(kernel.accept(&mut vm, &mut memory, &call).is_err());
    assert_eq!(kernel.calls, 1);
    let Outcome::Syscall(exit) = vm.run(&mut memory) else {
        panic!()
    };
    kernel.accept(&mut vm, &mut memory, &exit).unwrap();
    assert_eq!(vm.run(&mut memory), Outcome::Stopped { code: 0 });
    assert_eq!(vm.state.retired, 2);
}

#[test]
fn equal_tokens_from_other_processes_or_incarnations_cannot_reassign_a_job() {
    let (mut owner, mut memory, mut kernel) = setup(0x0a);
    owner.state.p[0] = 0x50100;
    owner.state.r[1] = 0x42;
    owner.state.r[2] = 256;
    let Outcome::Syscall(original) = owner.run(&mut memory) else {
        panic!()
    };
    kernel.accept(&mut owner, &mut memory, &original).unwrap();
    // An identical fresh VM can have the same PID, local token and arguments.
    let (mut fresh, _, _) = setup(0x0a);
    fresh.state.p[0] = 0x50100;
    fresh.state.r[1] = 0x42;
    fresh.state.r[2] = 256;
    let Outcome::Syscall(other) = fresh.run(&mut memory) else {
        panic!()
    };
    assert_eq!(original, other);
    assert!(kernel.accept(&mut fresh, &mut memory, &other).is_err());
    assert!(kernel.tick(&mut fresh, &mut memory).is_err());
    assert_eq!(memory.read(0x50100, 256).unwrap(), &[0; 256]);
    // A different process with a matching local token is rejected too.
    fresh.pid = 8;
    assert!(kernel.tick(&mut fresh, &mut memory).is_err());
    assert_eq!(
        kernel.tick(&mut owner, &mut memory).unwrap(),
        ServiceState::Pending
    );
    assert_eq!(
        kernel.tick(&mut owner, &mut memory).unwrap(),
        ServiceState::Complete
    );
    assert!(fresh.pending_syscall().is_some());
    assert!(owner.pending_syscall().is_none());
    assert_eq!(memory.read(0x50100, 256).unwrap(), &[0x42; 256]);
    assert_eq!(kernel.calls, 1);
}

#[test]
fn unavailable_services_report_explicit_errors_without_memory_effects() {
    for (id, status) in [(0x20, 11), (0x30, 11), (0x60, 11), (0x80, 6), (0xff, 6)] {
        let (mut vm, mut memory, mut kernel) = setup(id);
        vm.state.r[1] = 0x1234;
        vm.state.r[2] = 0x4567;
        vm.state.r[3] = 0x89ab;
        vm.state.p[0] = 0x50100;
        memory.write(0x50100, &[0x55; 16]).unwrap();
        let Outcome::Syscall(call) = vm.run(&mut memory) else {
            panic!()
        };
        kernel.accept(&mut vm, &mut memory, &call).unwrap();
        assert_eq!(vm.state.r[0], status);
        if id == 0x20 {
            assert_eq!(vm.state.r[1], 0);
        }
        if id == 0x30 {
            assert_eq!(&vm.state.r[2..4], &[0, 0]);
        }
        assert_eq!(memory.read(0x50100, 16).unwrap(), &[0x55; 16]);
        assert_eq!(vm.state.p[0], 0x50100);
    }
}

#[test]
fn full_range_is_validated_before_progressive_job_effects() {
    for (destination, source, length, expected) in [
        (0x40006, 0x50000, 3, 9),        // intersects code
        (0x5fff0, 0x50000, 32, 2),       // past arena
        (0x50000, 0x3ffff, 2, 2),        // kernel reserve source
        (0x50000, 0x50000, u32::MAX, 2), // length must not narrow to u24
    ] {
        let (mut vm, mut memory, mut kernel) = setup(0x0b);
        vm.state.p[0] = destination;
        vm.state.p[1] = source;
        vm.state.r[2] = length as u16;
        vm.state.r[3] = (length >> 16) as u16;
        memory.write(0x50000, &[0x55; 32]).unwrap();
        let Outcome::Syscall(call) = vm.run(&mut memory) else {
            panic!()
        };
        assert_eq!(
            kernel.accept(&mut vm, &mut memory, &call).unwrap(),
            ServiceState::Complete
        );
        assert_eq!(vm.state.r[0], expected);
        assert_eq!(memory.read(0x50000, 32).unwrap(), &[0x55; 32]);
        assert_eq!(kernel.chunks, 0);
    }
}

#[test]
fn empty_copy_does_not_dereference_both_pointers() {
    let (mut vm, mut memory, mut kernel) = setup(0x0b);
    vm.state.p[0] = 0;
    vm.state.p[1] = 0xffffff;
    vm.state.r[2] = 0;
    vm.state.r[3] = 0;
    let Outcome::Syscall(call) = vm.run(&mut memory) else {
        panic!()
    };
    assert_eq!(
        kernel.accept(&mut vm, &mut memory, &call).unwrap(),
        ServiceState::Complete
    );
    assert_eq!(vm.state.r[0], 0);
    assert_eq!(kernel.chunks, 0);
}

#[test]
fn bounded_fill_preserves_fuel_and_waiting_line_has_no_effect() {
    let (mut vm, mut memory, mut kernel) = setup(0x0a);
    vm.state.p[0] = 0x4fffe;
    vm.state.r[1] = 0xa5;
    vm.state.r[2] = 257;
    vm.state.r[3] = 0;
    vm.refuel(3);
    let Outcome::Syscall(call) = vm.run(&mut memory) else {
        panic!()
    };
    kernel.accept(&mut vm, &mut memory, &call).unwrap();
    kernel.accept(&mut vm, &mut memory, &call).unwrap();
    assert_eq!(kernel.calls, 1);
    memory.hold_line(0x50000);
    assert_eq!(
        kernel.tick(&mut vm, &mut memory).unwrap(),
        ServiceState::WaitMemory { line: 0x50000 }
    );
    assert_eq!(memory.read(0x4fffe, 257).unwrap(), &[0; 257]);
    memory.release_line(0x50000);
    for expected in [
        ServiceState::Pending,
        ServiceState::Pending,
        ServiceState::Complete,
    ] {
        assert_eq!(kernel.tick(&mut vm, &mut memory).unwrap(), expected);
        assert_eq!((vm.state.fuel, vm.state.retired), (2, 1));
    }
    assert_eq!(kernel.chunks, 3);
    assert_eq!(memory.read(0x4fffe, 257).unwrap(), &[0xa5; 257]);
    assert!(kernel.tick(&mut vm, &mut memory).is_err());
}

#[test]
fn memmove_matches_snapshot_for_both_overlap_directions_and_identity() {
    for (destination, source) in [(0x50101, 0x50100), (0x50100, 0x50101), (0x50100, 0x50100)] {
        let (mut vm, mut memory, mut kernel) = setup(0x0b);
        let input: Vec<u8> = (0..=255).chain(0..=255).collect();
        memory.write(0x50100, &input).unwrap();
        let expected = memory.read(source, 300).unwrap().to_vec();
        vm.state.p[0] = destination;
        vm.state.p[1] = source;
        vm.state.r[2] = 300;
        let Outcome::Syscall(call) = vm.run(&mut memory) else {
            panic!()
        };
        kernel.accept(&mut vm, &mut memory, &call).unwrap();
        while kernel.tick(&mut vm, &mut memory).unwrap() != ServiceState::Complete {}
        assert_eq!(memory.read(destination, 300).unwrap(), expected);
        assert_eq!(kernel.chunks, 3);
    }
}

#[test]
fn sleep_uses_wrapping_monotonic_frames_and_only_real_wait_refills() {
    let (mut vm, mut memory, mut kernel) = setup(3);
    kernel.frame = u32::MAX - 1;
    vm.state.r[0] = 3;
    vm.refuel(3);
    let Outcome::Syscall(call) = vm.run(&mut memory) else {
        panic!()
    };
    kernel.accept(&mut vm, &mut memory, &call).unwrap();
    kernel.frame = 0;
    assert_eq!(
        kernel.tick(&mut vm, &mut memory).unwrap(),
        ServiceState::Pending
    );
    assert_eq!(vm.state.fuel, 2);
    kernel.frame = 1;
    assert_eq!(
        kernel.tick(&mut vm, &mut memory).unwrap(),
        ServiceState::Complete
    );
    assert_eq!(vm.state.fuel, 128);
    let (mut vm, mut memory, mut kernel) = setup(3);
    vm.state.r[0] = 0;
    vm.refuel(3);
    let Outcome::Syscall(call) = vm.run(&mut memory) else {
        panic!()
    };
    kernel.accept(&mut vm, &mut memory, &call).unwrap();
    assert_eq!(vm.state.fuel, 0);
}
