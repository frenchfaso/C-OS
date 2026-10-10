# M2 boot, target diagnostic protocol and video admission

The production bootstrap is `m2.prg`, loaded at $0801 and entered at $1200.
`m2.reu` is its paired 16 MiB image. Both carry the same deterministic build tag.
The existing Rust assembler/static linker writes application code, arena bounds
and initialization seeds; the native builder adds kernel images inside the
already reserved first 256 KiB. It rejects any lower initialization seed ending
beyond $008000 and any native range overlap or local resident overflow.

| REU range | Purpose | Local destination |
| --- | --- | --- |
| $008000 onward | Resident M2 image | $1800–$3FFF, bounded by emitted length |
| $00B000 onward | Unchanged M0 renderer | $F000–$F9FF |
| $00C000–$00C1FF | Four 128-byte initial context records | $0400–$05FF |
| $00C200–$00C23F | Four 16-byte data/BSS initialization records | $1100 staging |

The ordinary PRG ends below $1800. A resident startup stub fetches the kernel
before jumping into it, then restores initialized application data from its
lower seed and clears BSS through 128-byte staging chunks. These startup
transfers precede display activation. Runtime transactions use the centralized
cache driver exclusively, with complete registers, explicit FETCH/STASH,
checked 24-bit inclusive ends, maximum 128 bytes and local ranges confined to
$0800–$11FF. Zero length is a software no-op.

The backend verifier loads a private REU copy whose application BSS and data
destinations contain nonzero sentinels. Before its first fixture, it checks the
resident bytes against `native.bin`, all initial 128-byte PCBs against static
linked bounds/registers, application code against the pack, restored data
against its seed, and every BSS byte against zero. Test patches therefore
cannot conceal an incorrect bootstrap. The published pack stays unchanged.

## Mailbox

This is an internal diagnostic interface, allocated separately in the map; it
is not an application ABI or the M3 scheduler. The CPU keeps raster IRQs enabled
while idle and between commands. The external monitor writes bounded arguments,
then publishes the request sequence last. The kernel completes an operation,
saves its active 96-byte context, publishes an immutable snapshot, and writes
the acknowledgement sequence last. It does not run another VM instruction
until another command arrives.

| Local address | Bytes | Meaning |
| --- | ---: | --- |
| $FE00 | 1 | Request sequence |
| $FE01 | 1 | Acknowledged sequence |
| $FE02 | 1 | Command |
| $FE03 | 1 | Result:0 completed,1 rejected completion,2 invalid command/DMA,3 deferred |
| $FE04 | 1 | Requested context slot 0–3 |
| $FE05–$FE06 | 2 | VM admission deferrals, wrapping counter |
| $FE07–$FE08 | 2 | DMA admission deferrals, wrapping counter |
| $FE09–$FE0A | 2 | Maximum measured single step duration in PHI2 ticks |
| $FE0B–$FE0C | 2 | Maximum measured cache service duration in PHI2 ticks |
| $FE0D–$FE0E | 2 | Completed bounded NMI recoveries |
| $FE20–$FE7F | 96 | Context/command arguments |
| $FE80–$FEA9 | 42 | Syscall completion packet |
| $FEE0–$FF3F | 96 | Published state snapshot |

| Command | Operation |
| ---: | --- |
| 1 | Replace requested slot from 96 argument bytes; revoke old margin ownership and cancel old cache incarnation first |
| 2 | Attempt one opcode; retry a video-only boundary until admitted; expose WAIT_REU to the caller |
| 3 | Run until the interpreter returns a boundary |
| 4 | Service at most one real cache transfer direction; inspect pending phase to distinguish remaining refill work |
| 5 | Complete pending syscall atomically; requested slot must equal active slot, in addition to token/generation/mask validation |
| 6 | Set fuel from argument 0; preserve terminal/pending outcome, otherwise clear ephemeral boundary |
| 7 | Save active slot/load requested slot; retain private code and shared dirty data cache entries |
| 8 | Cancel current owner's continuations/lines and revoke/discard its optional prepared margin record before generation increment |
| 9 | Coherent native scalar read; arguments address 3,width 1,value 3; result bytes returned at argument 4 |
| 10 | Coherent native scalar write using the same argument layout |
| 11 | Forced active-line negative test: suppress one raster IRQ, attempt at PAL65, expect inert WAIT_VIDEO, then rearm IRQ58 |
| 12 | Privileged fixture initialization STASH: address 3,width 1 and bytes in $1000 staging; bounded 1–128 bytes |
| 13 | Diagnostic video mode, argument 0&1; normal acceptance uses enabled video |
| 14 | Real CIA2 timer one-shot NMI injection, followed by bounded recovery with guest state unchanged |

The completion packet contains token 8, generation 2, status 2, R-mask 1, P-mask 1,
R-values 16 and P-values 12, all little endian. R0's mask bit and high P-mask bits
are rejected. Stale, duplicate or wrong-owner completions leave state unchanged.
Command 11 deliberately removes one frame and is separated from ordinary
continuous-rendering stability; it checks admission rejection before any
instruction fetch or fuel/architectural effect.

## Differential memory and continuations

`m2_ue2.py` boots once per cache variant and adaptively executes the fixture
commands. At every attempt/service boundary it records the 96-byte architecture,
112-byte metadata, code/data buffers, cache continuation/counters and physical
REU watch bytes through the backend's read-only firmware-memory monitor. It
checks architecture before servicing a miss and checks it again after each
separate STASH/FETCH. It overlays only valid dirty cached data to compare logical
memory; it also retains the distinct physical samples. No diagnostic flush is
inserted to make the oracle comparison pass.

Boundary checks reject leaked pins, multiple busy destinations, a mismatch
between pending phase and busy ownership, unaligned valid tags, invalid owners,
dirty immutable code lines or a service visit executing multiple transfers.
Between independent fixtures, old owner incarnations are cancelled before
physical patches. Within a fixture, ordinary context switches never flush all
caches. Coherent native writes flush overlapping dirty data before partial
physical updates and invalidate overlapping data/code cache lines afterward.

## Timing and admission

The renderer bytes, pixel cadence and IRQ58 entry remain those of M0. Normal
VM attempts and runtime DMA are admitted only at real PAL raster 280–299.
The latest start leaves at least 70 complete 63-PHI2 lines (4410 ticks) before
the next IRQ58. The renderer owns all 200 active lines 60–259. Each opcode checks
admission; the DMA driver checks again immediately before its transaction under
saved IRQ state. A completion callback checks the actual post-transfer raster
and updates the retained M0 violation counter independently of admission.

CIA1 timer A is started from a settled counter. Both start and end snapshots
read high-low-high and retry if high changes: CIA timer low reads do not latch
high. Measurements include their surrounding call/setup overhead and are
reported as actual target PHI2 observations. These are measurements of the
supplied backend, not physical Ultimate guarantees. The measured boot FETCH and
STASH bounds remain separate from timed interpreter and cache-service paths.

The accepted turbo probe envelope is 640–767 loop increments across one PAL
line; lower speed profiles are rejected. A conservative qualified-profile rate
of 48 normal-RAM CPU cycles per PHI2 gives ample room for the finite assembled
opcode/cache paths, with separate I/O and DMA bounds. Static bounds and measured
high-water observations must be read alongside the backend/artifact identifiers
in the milestone report. Video waits/cache misses preserve remaining fuel.

Primitive admission hooks remain finite and defer immediately while an NMI
recovery is pending. Diagnostic outer command loops perform recovery, so the
second admission check never waits while IRQs are masked. NMI handlers preserve
interrupted registers and request recovery. At a
consistent outside-raster boundary, recovery disables optional margin
qualification, acknowledges/disables CIA2 interrupt sources and rearms the
normal IRQ58 renderer from the late blanking window. It changes no guest
architecture, credit or cache continuation. Command 14 injects an actual CIA2
one-shot edge and the runner compares state, metadata, buffers and logical
memory before/after, then checks a complete normal capture. This controlled
outside-display injection does not qualify firmware-menu disturbances.

At the first kernel entry, after every startup JSR has returned, the kernel
fills its hardware stack page with $A5 under SEI. The final monitor sample
records the deepest changed byte as a touched-depth lower bound alongside
inline samples and the conditional static bound. Coincidental $A5 pushes can
make the sentinel result underestimate depth; it is never a global proof.
The normal static maximum is 14 bytes; adding IRQ 8 plus one NMI 4 gives 26 under
the documented no-recursive-NMI/default-disabled-margin conditions.

## Optional margin hook

The normal build has `marginEnabled=0`; it emits zero extra instructions after
the final pixel. M0 and default M2 renderer PRGs are byte identical. An explicit
`m2.py --margin-hook` inserts a call after the final high pixel and border reset
through the $17E0 trampoline. The hook remains idle because no activation
profile is qualified. Prepared-record lifecycle code is resident; its 32-byte
record at $1080 and 16-byte private scratch at $10A0 fit the existing 512-byte
staging reservation and are separate from live VM/cache/raster scratch.
Activation requires the full timing and stability evidence in the margin
supplement; the lifecycle self-test supplies no timing qualification.

## Reproduction and hardware procedure

Use the pinned Kick Assembler/Java setup documented by M0 and the existing
locked Rust toolchain. `scripts/check_m2.py` runs the current host pipeline,
independent vectors, both native builds/repeat hash checks, M0 regression,
cache cancellation, margin lifecycle and adaptive target comparisons. The
Ultimate backend paths are explicit command-line inputs. A normal clone build
has no sibling-project dependency; no GPL backend source is copied into C-OS.
The runner uses a private flash/settings copy, private USB directory and ignored
output working directory. Failed/interrupted runs have no successful result
file, and diagnostic control uses a private loopback endpoint.

Physical qualification requires the following additional checks. The supplied
`m2_ue2.py` transport controls the emulator; physical replay needs a monitor or
memory-dump transport for the documented mailbox protocol.

1. Repeat [M0's physical profile, preservation and capture procedure](m0.md#physical-procedure-still-required).
   Retain firmware/FPGA revisions, settings, both matched M2 PRG/REU pairs,
   maps and fixture SHA-256. Use PAL, 16 MiB REU and the tested nominal 64 MHz
   turbo mode, with `marginEnabled=0`. Load the complete REU before `SYS 4608`.
2. Drive mailbox requests with the sequence published last and acknowledgment
   checked before the next command. Verify bootstrap data, BSS and all PCBs
   before fixture patches. Capture all 320 columns, 200 lines, one-pixel edges
   and sixteen palette indices.
3. Replay cold/warm, split-line, $xxFFFF, final-REU-byte, dirty CLOCK and native
   coherence fixtures for both line sizes. Include STORE/PUSH/CALL and
   LOAD/POP/RET. At each WAIT, STASH and FETCH boundary retain architecture,
   metadata, cache buffers and separate logical/physical REU observations.
4. Alternate at least two contexts with fuel 1, 3 and 128. Include a low-fuel
   loop without YIELD, faulted-context reload, slot reuse and stale or
   wrong-owner syscall completions. Check unchanged credit across waits and
   exactly one retirement/effect for resumed instructions.
5. Measure opcode attempts, cache service, raw FETCH/STASH and setup/timer
   baselines separately under relevant memory, I/O and device contention.
   Retain worst cases and the hardware stack high-water. Establish device
   memory/I/O/DMA stall bounds and show that the resulting conservative guard
   fits before IRQ58 using logic/video capture; a post-DMA raster sample alone
   cannot exclude unobserved stalls.
6. Run arithmetic plus a repeated miss/dirty workload spanning more than 64 KiB
   for at least ten minutes, with zero normal missed synchronizations and
   active-line DMA violations. Separately inject bounded CIA2 NMI and firmware
   menu disturbances. Compare guest state, cache continuation, fuel and stack,
   and verify restored scanout after recovery.
7. Archive raw observations, configuration and artifact identities. Requalify
   admission after profile or timing changes. Margin activation requires its
   separate SPEC §17.7 gate; the idle optional hook and lifecycle assertions
   do not qualify raster work.

These physical measurements remain pending; emulation results cannot replace
them.
