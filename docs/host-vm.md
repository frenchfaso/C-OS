# Host reference VM, M1

The reference implements every opcode in SPEC §8, with one shared 16,777,216-byte
physical REU. Application addresses are physical offsets; no per-process base is
added to a pointer. The first 262,144 bytes belong to the system. A VM context
contains eight u16 R registers, four u24 P values, PC, descending SP, an eight-bit
fuel counter and a retired-opcode count. Bounds are inclusive; $FFFFFF is a valid
last byte. Integers wrap at 16 bits, while address calculations use wider checked
intermediates. There are no persistent arithmetic flags.

`src/isa.rs` defines opcodes, operand forms, encoding and strict decoding together.
`src/vm.rs` handles effects and bounds. `src/harness.rs` provides a deterministic
kernel boundary. These are one small Rust crate; serde and serde_json are used
only for host objects, manifests and diagnostic snapshots.

## Execution boundaries

`Vm::run(&mut Memory)` returns one of these explicit outcomes:

| Outcome | Architectural state |
|---|---|
| FuelExhausted | No opcode is fetched without credit; PC identifies the next instruction |
| Yield | Instruction completed, PC advanced once, remaining turn surrendered |
| WaitMemory | PC, registers, stack, memory, fuel and retirement unchanged |
| Syscall | Invocation retired once; returning PC already published; continuation owns a token |
| Fault | Terminal process fault with PID, original PC, cause and affected address when available |
| Stopped | PROC_EXIT completed with its u16 exit code |

Preflight validates decoding, the selected next PC, address arithmetic, full
access ranges and availability before any instruction effects. An untaken
branch validates fallthrough only; a taken branch validates its destination.
CALL additionally checks its future return PC before pushing three little-endian
bytes. RET reads and validates the saved PC before changing SP. JMP, RET, TRAP
and PROC_EXIT do not require fallthrough. A returning syscall cannot accept a
job without a valid resumption PC.

Validation failures do not retire an instruction or consume fuel. TRAP is a
valid explicit instruction: it consumes one unit before recording its terminal
fault. A fault terminates only that context; memory and other contexts remain
usable. Target resource cleanup belongs to later kernel milestones.

No stack bytes are stored on the host or hardware call stack as guest frames.
SP points at the next free byte of the descending REU stack. Its empty value is
stack_last, and its full value is stack_first-1. Push/pop widths are exactly two
or three bytes, including unaligned values. SETSP accepts both endpoints.

`Memory::hold_line/release_line` withholds 128-byte blocks to test resumption.
Every required line must be available before effects; multi-line writes cannot
partially retire. This hook models availability only. It implements neither
M2's code/data caches nor DMA timing or write-back replacement.

## Deterministic syscall harness

Implemented services are PROC_EXIT, SYS_INFO, GET_FRAME, SLEEP, MEM_INFO,
MEM_FILL and MEM_COPY. FILL and memmove process at most 128 bytes per `tick`;
the whole declared range is checked before the first chunk. Copy direction
preserves overlapping data. Empty requests never dereference their pointers.
These host jobs demonstrate the continuation boundary; they do not constitute
target native services or M3 scheduling.

Each pending request captures its original arguments, VM owner and completion
token. A private host identity also distinguishes fresh VM incarnations with
the same PID; it does not enter architectural snapshots or affect execution.
Running a waiting VM returns the same request without another invocation.
Completion validates the token and all scalar outputs before publishing any
result. Repeated or stale completions fail. Registers without declared outputs
are preserved. CPU jobs retain remaining fuel. Positive sleep wakes with the
configured full quantum (default 128); SLEEP(0) and YIELD surrender the turn.
Sleep uses unsigned differences of the model frame counter, including wrap.

Known deferred SDK services return ENOTSUP, with declared scalar outputs zero
and buffers unchanged. Unassigned/reserved IDs return ENOSYS. Graphics, input,
numeric operations, files, storage, RTC, SID and audio are explicitly deferred;
there are no successful placeholder implementations. SYS_INFO describes the
specified target geometry, not an already implemented desktop.

`cosrun` loads and validates a COSPACK1 linked manifest and its header/build tag,
restores initialized data from its seed, clears BSS and applies the SPEC §15.2
entry convention. `--fuel` selects 1..255 instructions per quantum. `--slices`
limits returned VM boundaries, including syscall boundaries. Reaching the limit
returns command status 2 and `SliceLimit`, without fabricating a VM fault.
Faults return status 2; malformed input returns 1. A completed application returns
command status 0 and reports its own exit code separately.

With `--trace FILE`, JSONL captures context and execution outcomes at boundaries,
plus native chunk completions. These are comparison fixtures for M2. Model
frames advance once per harness service tick; they are deterministic test inputs,
not real-time performance measurements or a PAL scheduler.

## Verification

```sh
cargo test --locked --workspace
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
python3 scripts/check_m1.py
```

Add `--offline` to Cargo and the Python script when dependencies are cached.
`tests/semantics.rs` uses hand-written instruction bytes and independently
specified expected values. It covers every defined opcode, all reserved opcodes,
bad registers/fields/counts, signed and unsigned comparisons, shifts, wrapping,
linear accesses across $xxFFFF, the final REU byte, code protection, CALL/RET and
stack limits, selected-PC checks before effects, suspension and fuel-three loops.
`tests/harness.rs` checks continuations, errors, full-range validation, bounded
jobs, overlap and monotonic waits. `tests/toolchain.rs` validates relocation and
formats independently of the VM. Round-trip disassembly is supplementary.

No specification change was needed. Assembly source syntax and host JSON field
names fill in the deliberately unspecified tooling details; see
[toolchain.md](toolchain.md). Float semantics and C-Script compilation remain
their stated M4 milestones.

The next M2 step is a minimal NMOS dispatcher for these same opcodes, with
register/context snapshots compared to the host after each fuel-three slice
and each injected cache miss. Keep STORE/PUSH/CALL preflight atomic, update the
resident map with actual assembled sizes, and integrate REU transfers only in
the M0-qualified service windows before broadening the implementation.
