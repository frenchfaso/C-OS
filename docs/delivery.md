# First delivery: M0 and M1

This is the historical M0/M1 report, retaining its original measurements and
artifact identities. The current native implementation and freshly rebuilt
M0/M1 regression evidence are described in [the M2 delivery](m2.md).

Verified on 2026-10-10. **M1 is implemented and verified on the host. M0 is
functionally verified in emulation; physical timing qualification is pending.**
There is no bootable desktop, native VM, target scheduler, C-Script compiler,
float backend, or device SDK in this delivery.

## Implemented behavior

M0 supplies original NMOS 6502/6510 probes and a real 320×200 UPIC diagnostic.
It checks PAL, executed turbo work and 16 MiB REU capacity; alias and timing
tests preserve and verify modified REU bytes. It measures FETCH/STASH at several
lengths, admits runtime DMA outside the 200 active raster lines, and produces
reproducible PRG/REU artifacts with a checked RAM map.

M1 supplies a shared complete four-byte ISA, validating assembler/disassembler,
COSOBJ1 relocations, a minimal static COSPACK1 linker, and an executable Rust
reference VM. Linear addresses refer to one shared 16 MiB physical REU. The VM
implements checked 24-bit pointer arithmetic, bounded arenas, code protection,
packed descending stacks, selected-PC validation before effects, fuel and
explicit suspension/fault outcomes. Deterministic syscall continuations include
bounded MEM_FILL/MEM_COPY jobs and sleep; deferred services return explicit
ENOTSUP/ENOSYS. ABI 1 and COS-NUM-1 declarations do not imply a numeric backend.

See [VM semantics](host-vm.md) and [toolchain formats and commands](toolchain.md).

## Compile and verify

Run from the repository root. Dependencies are Rust 1.93.0, Python 3, Java, and
the pinned Kick Assembler 5.25 jar described in [m0.md](m0.md).

```sh
cargo test --locked --workspace
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
python3 scripts/check_m1.py

# Set KICKASS_JAR if the pinned jar is not at toolchain/KickAss.jar.
python3 scripts/m0.py
python3 -m unittest discover -s tests/native -v
```

With cached dependencies, add `--offline` to Cargo and to `check_m1.py`.
The M1 script builds release tools, assembles three programs, links demo/empty
packs, disassembles both objects and linked code, runs the programs, saves
boundary traces, and compares repeated builds byte-for-byte.

After that pipeline, execute an individual program with:

```sh
target/release/cosrun build/m1.manifest.json --app Linear --fuel 3
target/release/cosrun build/m1.manifest.json --app Calls --fuel 3
target/release/cosrun build/m1.manifest.json --app Spin --fuel 3 --slices 6
```

Spin intentionally reaches SliceLimit and returns command status 2. To run the
ten-profile emulator suite, provide the external backend/firmware inputs using
the exact command in [m0.md](m0.md). Normal compilation has no emulator dependency.

## Verification results

All **49 Rust tests** passed: 26 independent VM semantics, 8 syscall harness,
15 ISA/toolchain. All **5 native artifact tests** passed. Formatting and Clippy
with warnings denied passed. Tests use independent instruction bytes and
expected effects; assembler/disassembler round-trips are supplementary.

| Program | Deterministic result with fuel 3 |
|---|---|
| Linear | ST16/LD16 across $04FFFF; R2=R3=$ABCD, R4=4; 8 retired opcodes; SP preserved |
| Calls | Two nested calls; R2=42; 14 retired opcodes; SP restored |
| Spin | No explicit yield; 6 slices, 18 retired opcodes, 9 increments; SliceLimit |

The final source tree was also built and tested in an autonomous temporary copy,
using cached Cargo dependencies and the external pinned assembler. All 49 host
and 5 native tests and both build pipelines passed there. Thirteen M0/M1 objects,
images and maps matched the workspace byte-for-byte. No neighboring source is
needed. [Recorded host results](m1-evidence/m1-results.json),
[verification provenance](m1-evidence/verification.json),
[REU map](m1-evidence/m1.map.txt), and three JSONL boundary traces are retained
in `docs/m1-evidence/`; reproduction writes fresh outputs to `build/`.

The UE2/TRX64 backend used by wolf64u passed **10 functional profiles**: accepted
PAL/64 MHz/16 MiB, four smaller REUs, absent REU, 32/48 MHz, NTSC and mismatched
pack. Independent DDR snapshots confirmed preservation for every profile. The
positive capture resolved all 320 stripe pixels and matched all 64,000 source
pixels in both output rows. Its 2,000 ms sample, including startup, recorded
zero missed synchronizations, active-line DMA violations or restoration errors.
This is not a physical timing or steady-state FPS result.

| M0 measured item | Result |
|---|---:|
| Probe code/constant data | 1,411 bytes |
| Renderer including padding | 2,289 bytes |
| Hardware stack | 10 bytes observed; 18-byte conditional static bound |
| FETCH and STASH, 1/16/64/128/256 bytes | 3/18/66/130/258 CIA PHI2 ticks each |
| Driver setup / timer baselines | 1–2 / 0 ticks |

Both transfer paths fit `ticks = 2 + byte_count` on this backend; the intercept
includes command/timer overhead. Runtime tests use 128-byte directions, admitted
only on raster lines 280–299; active scanout is lines 60–259. Physical interference
and worst-case bounds remain unqualified. Backend executable, firmware, profile,
artifact hashes and raw results are in [M0 evidence](m0-evidence/provenance.json).

## Memory budget and remaining hardware checks

The framebuffer consumes 40,960 bytes and visible I/O 4,096 bytes. The remaining
**20,480 bytes** include code, tables, stack, scratch, structures and future caches.
The checked map distinguishes actual code/runtime storage from future reserves.
The resident code reserve has 10,365 bytes beyond the current probe; the renderer
reserve has 271 bytes left. The future 4 KiB numeric target is inside the resident
reserve. These figures do not prove that the finished kernel fits.

REU is shared: 262,144 system bytes and 16,515,072 application bytes (15.75 MiB).
The host pack assigns nonoverlapping application arenas; it has no native boot
images and must not be loaded as a bootable OS. Its tag is `$1C560A45`; the separate
M0 diagnostic's tag is `$E5B09CE4`.

The [physical procedure](m0.md#physical-procedure-still-required) covers profile
and firmware recording, exact PRG/REU loading, independent restoration tests,
320×200 capture and horizontal phase calibration, DMA intercept/slope under
contention, a ten-minute stability run, guard verification, and bounded NMI/menu
disturbance with recovery/stack checks. M0 remains partially qualified until
those checks pass on the physical device.

## Specification and next step

No specifications were changed. The small assembly grammar and JSON field names
fill in host-tool details left unspecified. Initial raster phase/admission
parameters are documented measurements, not new performance guarantees.
No third-party native source was incorporated; the license remains undecided.
SPEC §11 defines the UI colors and layout; illustrative icons add no
application requirements. Project images will use actual implementation captures.

Next, implement M2's minimal NMOS dispatcher and code/data cache path. Compare
architectural snapshots with the host at fuel-three boundaries and injected
cache misses, starting with atomic STORE/PUSH/CALL preflight. Update the actual
resident budget after each addition and integrate DMA only after qualifying the
service-window margins on the target.
