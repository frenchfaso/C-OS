# C-OS · Commodore OS

**Back to the future.**

What if a C64 had 16 MiB of linear app memory, preemptive multitasking, and a tiny desktop?

C-OS is an OS experiment for the **C64 Ultimate**, targeting its 64 MHz turbo mode and 16 MiB REU. A compact 6510 assembly kernel runs a small register VM; apps use **C-Script**, a simple compiled language. Rust is the recommended choice for the host compiler and tooling.

The plan:

- Linear 24-bit app addresses, with REU transfers handled by the kernel.
- Opcode fuel for preemption, with separate video deadlines.
- A 320×200 UPIC desktop inspired by NeXT: movable square icons, five shell tones, no fixed bars.
- Integers, float24 and float32; simple APIs for graphics, files, SID and Ultimate Audio.

**Current stage: M3 autonomous native kernel implemented and functionally verified.**
The complete NMOS integer VM, coherent REU caches, four-process scheduler and
bounded memory jobs execute with M0's 320×200 scanout on the UE2/TRX64 backend.
The first autonomous Mandelbrot workload validates its complete image against
an independent reference and a native 1 MHz baseline. The Rust VM, assembler,
disassembler and static linker remain the host reference. Physical timing
qualification remains pending.

See [the M3 delivery and complete verification command](docs/m3.md) for paired
native PRG/REU artifacts, autonomous tests, workload measurements and the
cumulative 20 KiB RAM budget. [M2](docs/m2.md) documents the complete ISA and
differential tests. Native execution requires explicit external backend and
firmware inputs; ordinary builds have no emulator dependency.

The subsequent [M3 performance work](docs/m3-perf.md) introduces application
ABI 2 with general integer multiplication and measured interpreter/cache/
scheduler improvements. The original M3 ABI 1 delivery and independent review
remain historical evidence. Current-source verification uses
`scripts/check_m3_perf.py`; its report distinguishes emulator results from
physical Ultimate qualification. The [independent M3-P review](docs/m3-perf-review.md)
reproduces the complete regression and equivalent-image performance results.

Build and verify the host tools with Rust 1.93.0 and Python 3:

```sh
cargo test --locked --workspace
python3 scripts/check_m1.py
cargo clippy --locked --workspace --all-targets -- -D warnings
```

The pipeline assembles, links, disassembles and executes three small programs.
`build/` contains reproducible objects, the shared 16 MiB REU image, maps,
execution results and comparison traces. The first 256 KiB are reserved for the
system; application arenas share the remaining 15.75 MiB.

Build the M0 PRG and diagnostic REU with Java and the pinned Kick Assembler
5.25 installed at `toolchain/KickAss.jar`, or supplied through `KICKASS_JAR`:

```sh
python3 scripts/m0.py
```

See [M0 measurements and hardware procedure](docs/m0.md),
[host tools and exact commands](docs/toolchain.md),
[VM semantics and syscall scope](docs/host-vm.md), and
[historical M0/M1 delivery report](docs/delivery.md).

The C-Script compiler, numeric backends, desktop and device SDK are later
milestones. Unsupported services return explicit errors. The optional UPIC
margin hook is disabled; its ownership contract is tested without activating
work inside the displayed lines.

→ [Start with the specification](specs/SPEC.md) · [C-Script](specs/LANGUAGE.md) · [Ultimate API](specs/ULTIMATE-API.md) · [Numerics](specs/NUMERICS.md)

License: **to be decided**.
