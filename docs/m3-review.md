# Independent M3 review

October 10, 2026. Reviewed against SPEC.md revision 6 and PERFORMANCE.md.
The implementation was uncommitted at repository HEAD `2b93354`. The review
froze and checked all 73 source/control fingerprints and all six external
inputs from the delivered verification record before running it again.

**Disposition: M3 passes this independent functional review. No new blocking
correctness defect was found. Its measured Mandelbrot throughput is far below
the greater-than-1x goal; that goal is explicitly not an M3 acceptance gate.**
This result does not establish that the present VM architecture can reach 1x
or 2x with small changes.

## Mandelbrot correctness and measurement

Both normal packs rebuilt byte-identically, including their manifests, maps,
PRG/REU images and native modules. The independent autonomous benchmark reruns
reproduced the delivered target timings exactly:

| Cache line | C-OS frames | C-OS estimated PHI2 ticks | Native 1 MHz PHI2 ticks | Throughput ratio | C-OS elapsed/native elapsed |
| --- | ---: | ---: | ---: | ---: | ---: |
| 128 bytes | 8,938 | 175,685,328 | 2,682,768 | 0.0152703x | 65.49x |
| 64 bytes | 9,362 | 184,019,472 | 2,682,768 | 0.0145787x | 68.59x |

The 16x12 image uses a limit of 16, the same viewport and escape convention,
and signed Q8.8 arithmetic on both implementations. Every one of the 192 bytes
matches, rather than only a visual resemblance or selected samples. In
addition to auditing the delivered integer reference, this review recomputed
the image with exact rational complex coordinates and explicit quantization
after each product. Its independent output has SHA-256
`2e62867fb2ecf558567623cd291435f3269a930383edb8602b8ff0c6aab0ca5c`.
The case exercises 170 negative nonintegral cross products; incorrectly
truncating toward zero changes two pixels. The checked image therefore tests
this rounding distinction. See the executable
[rational oracle](m3-review-evidence/rational-reference.py) and its
[result](m3-review-evidence/rational-reference.json).

The native baseline runs ordinary NMOS instructions with turbo disabled and
REU disabled. Its executable slow-mode probe reports 16, and its cascaded
CIA2 counter covers the complete computation and a 16-bit timer wrap. Code,
working state, stack and output fit original C64 RAM. The baseline disables
VIC display and does not present the image. It is a disclosed native-compute
baseline, not a claim that both platforms offer equivalent video facilities.

C-OS runs the complete workload in guest bytecode, without host instruction
commands or a workload-specific native service. The normal scheduler and
320x200 UPIC remain active. Both runs retire 693,194 instructions and make
three guest syscalls. Target frame timestamps include scheduling, cache
misses, DMA and time unavailable during scanout; host elapsed time is not the
timer. The published one-frame uncertainty and conservative 64-frame
collection ceiling cannot explain a roughly 65-69-fold slowdown. Collection
overhead is disclosed rather than silently subtracted.

All 192 output bytes remain dirty at completion. This review separately
checked that valid cache entries belong to the live owner/incarnation and lie
inside its arena before accepting the coherent logical image. The current
benchmark does not include final write-back, upload or display of Mandelbrot.
The live scanout check still displays the M0 test pattern; it proves ongoing
video integrity, not a rendered Mandelbrot frame rate. The complete paired
records are [128-byte](m3-review-evidence/benchmark-128.json) and
[64-byte](m3-review-evidence/benchmark-64.json).

This tiny deterministic case is a useful first baseline. It is not sufficient
evidence about larger images, ray tracing, 3D rasterization, float arithmetic
or desktop responsiveness. Keep it as a regression while adding larger cases
when execution time permits.

## Scheduling, lifecycle and memory

Independent execution passed 53 Rust tests, formatting and Clippy, all 20
Python checks against the existing built artifacts, 252 native scheduler
assertions, all six autonomous four-process scenarios, and all 512 physical
cache rollback scenarios. Both cache sizes passed every M3 scenario. The
non-yielding loops, fair fill/copy jobs, sleep and fault isolation, cancellation,
real CIA2 NMI recovery, complete job outputs and guard bytes were checked.
All six scanouts had zero missed synchronization and active-line DMA, and
all 64,000 source pixels matched. The default margin hook remains disabled.

The reviewed cancellation fixes passed again: neither revoked dirty victims
nor unrelated WAIT_REU owners were left in the formerly failing state.
Source inspection covered scheduler queue/fuel rules, job validation and
overlap direction, completion/replacement lifetime, bootstrap reuse, native
stack use, and admission/timer paths. The static bounds regenerated as
3,736/3,742 PHI2 against a 4,410-tick guard. These remain conditional bounds
for the last admitted opcode and its scheduler tail, not whole-quantum or
physical-hardware guarantees.

The review did not rerun every M0/M1/M2 differential scenario again. Their
delivered receipts and unchanged source/artifact provenance are distinct from
the freshly executed M3/rollback checks above. Physical Ultimate timing and
interference qualification remain open.

After reserving the planned 4 KiB numeric core, only 409/403 bytes remain in
the current resident-code region. Shell, input, graphics and device modules
are still unsized. Before further native features, produce an integrated
budget for those modules; the present map proves the current build fits,
not that the complete future OS fits.

## Performance follow-up

The existing host profile attributes 659,138 of 693,194 retired instructions
(95.09%) to the multiplication routine. This is an instruction fraction, not
a measured fraction of elapsed target time. It does not justify an Amdahl-law
speedup estimate or a promise that a native multiply alone reaches 1x.

The next performance investigation should measure the relevant target costs:
interpreter decode/validation, arithmetic, cache/REU service, context switching
and raster admission. Keep profiling instrumentation separate and quantify
its overhead against the normal complete-image run. Avoid inferring total
throughput from nominal 64 MHz or a faster host emulator.

Start with equivalent bytecode and interpreter hot-path improvements that
preserve ABI 1. A general bounded 16x16 multiply with a full 32-bit product is
a reasonable subsequent shared-ABI proposal; specify signedness, result
registers, clobbers, fuel, timing and host/target equivalence together before
adopting it. Do not move the whole Mandelbrot computation into a syscall.
Any wider raster admission needs refreshed deadline evidence. The current
admission range is only lines 260-299, but a range of admission lines is not
itself a measurement of CPU duty cycle or available speedup.

Performance improvements must be judged by this unchanged complete-output
comparison first. Preserve the failing baseline and report each subsequent
gain honestly; achieving functional M3 must not be described as achieving
the user's throughput target.

### Measured bytecode-only experiment

A private variant replaces the multiplication loop's `MOV R0,R6; SHL R0,15`
low-bit test with `LDI R0,1; AND R0,R6`. The branch only distinguishes zero
from nonzero, so the test has the same meaning. Both use two instructions and
the same code space; the native runtime binary is byte-identical.

With 128-byte cache lines, the entire image still matches and the retired count
remains 693,194. Elapsed time falls from 8,938 to 8,816 frames: **1.01384x
relative throughput, approximately a 1.4% gain**. Against the unchanged native
baseline the result is still only **0.0154816x**. This is a useful measured
example of an inexpensive improvement, not a solution to the main gap. The
experiment is retained as a [patch](m3-review-evidence/bit-mask.patch) and
[complete benchmark record](m3-review-evidence/bit-mask-benchmark-128.json);
it was not applied to the delivered application.

## Reproduction and evidence

The review used the commands documented by `scripts/m3.py`,
`scripts/m2_bounds.py`, `scripts/m3_ue2.py`,
`tests/native/check_cache_rollback.py` and `scripts/m3_benchmark.py`, with the
same explicitly fingerprinted emulator, firmware, configuration, assembler
and Java as the delivery. Rebuilt sources, binaries and execution records
were isolated from the developer's working tree. The only repository additions
from this review are this document and `m3-review-evidence/`.

The evidence directory retains complete benchmark, scheduler, autonomous and
rollback records, regenerated maps/bounds, output bytes and host test logs.
The [review receipt](m3-review-evidence/verification.json) binds the original
source fingerprints, external inputs and saved evidence to this review.
Run `python3 docs/m3-review-evidence/rational-reference.py` to compare all four
saved images with the independent rational oracle. Large private firmware
and REU input copies from completed runs were removed after recording their
hashes; original firmware and developer artifacts were preserved.
