# Independent M3-P review

Verified on October 10, 2026 against specification revision 7 and application
ABI 2. **M3-P passes this independent emulator review.** No new blocking runtime
defect was found. The selected 128-byte cache profile exceeds 1x for both
specified Mandelbrot workloads, including an additional, faster native 1 MHz
control. The 64-byte profile remains below 1x; 2x is not achieved.

## Reproduced performance

All accepted runs use the normal autonomous kernel, live UPIC 320x200 and
disabled margin work. Both 128-byte workloads were repeated twice with
identical frame counts; each 64-byte workload was independently repeated once.
The entire logical image and all 64,000 live scanout pixels pass. Every accepted
benchmark reports zero missed synchronization, active-DMA, NMI and recovery
events. Measurements use target counters, not host wall-clock time.

| Workload | Cache bytes/line | PAL frames | C-OS PHI2 estimate | Frozen native / C-OS | Faster native control / C-OS | Conservative control lower bound |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 16x12 | 128 | 95 | 1,867,320 | 1.436694x | 1.287637x | 1.274191x |
| 16x12 | 64 | 257 | 5,051,592 | 0.531074x | 0.475975x | 0.474117x |
| 32x24 | 128 | 382 | 7,508,592 | 1.465730x | 1.314340x | 1.310900x |
| 32x24 | 64 | 1,040 | 20,442,240 | 0.538374x | 0.482767x | 0.482300x |

The unchanged historical comparator repeats 2,682,768 PHI2 for 16x12 and
11,005,565 PHI2 for 32x24. As an independent robustness check, only its multiply
routine was replaced with the same general combined-product shift/add and
signed high-half correction used by MULS. Coordinates, loops, escape ordering,
precision, output stores, timer and 1 MHz/no-REU configuration remain unchanged.
Both native control repetitions agree: **2,404,431** and
**9,868,842 PHI2**, respectively. This is a separately labelled
additional comparator; the frozen baseline and all historical evidence remain
unchanged. It is not a claim about the fastest possible native Mandelbrot.

The independent review oracle uses exact rational arithmetic and explicitly
quantizes each product downward to Q8.8. It validates all 192 and 768 bytes,
964 and 3,891 completed iterations, and equality between the smaller image and
the even-coordinate samples of the larger one. SHA-256 hashes are
`2e62867fb2ecf558567623cd291435f3269a930383edb8602b8ff0c6aab0ca5c` and
`83c6af3119bdd417f7429627c04198faa2732a05d03f65ce62cff704278cb69a`
for the two output images. Both guest programs occupy 232 bytecode bytes.
They fit the selected owner's two 128-byte code lines; the 64-byte profile
repeatedly refills code. These results do not establish throughput for larger
code working sets, ray tracing, 3D, floating point or multiple compute apps.

Timing ends at logical image completion, before exit cleanup, final dirty-cache
flush and image presentation. The displayed image is the diagnostic scanout
pattern. This is not displayed Mandelbrot FPS. Owner/generation and zero-PIN
checks validate the retained cache contents used to reconstruct logical output.
One-frame uncertainty and the existing 64-frame collection ceiling remain
unsubtracted. Conservative lower bounds subtract at most 64 PHI2 from native
timing and add one PAL frame to the C-OS estimate.

## Source and protection review

- MULU/MULS preserve non-result architecture, capture original operands and
  publish the complete product after preflight. The unsigned routine executes
  sixteen bounded iterations; signed correction is the exact modulo-32-bit
  identity. Its four scratch bytes are dead decode scratch and do not overlap
  the active access flag, next PC, renderer or scheduler state. Fuel and
  retirement remain one per instruction.
- The hot PC entry is reachable only after RUN publishes an already checked
  next PC. Initial imports, selected branch/RET targets, wait/fault/syscall and
  fuel boundaries retain validation. The inlined unsigned u24 comparisons keep
  inclusive upper bounds, alignment and overflow checks.
- Conditional unpin is confined to successful nonaccess instructions. Every
  memory/stack completion and suspension/fault boundary retains cleanup. Only
  data entries acquire PIN. Pointer-table indices and aligned four-byte code
  fetches remain confined to the validated cache layout; ownership, generation,
  dirty-victim rollback and coherence checks remain intact.
- Empty native-job scans read PCB metadata before switching architecture and
  restore the active metadata pointer. Owed native turns, cancellation and
  native-job arbitration remain intact. Separate late VM admission rechecks
  the earlier scheduler gate before a native fallback.
- ABI 2 is consistent across tools, objects, packs, the loader, startup R1 and
  SYS_INFO. Correct-tag ABI 1 rejection is exercised before native loading;
  container formats and COS-NUM-1 remain unchanged.

Fresh normal builds match the delivered native bytes for both profiles and
the same bytes exercised by the complete regression. The conditional scheduler
bound is **2,046 < 2,331 PHI2**; the late VM/return suffix is **371 < 441 PHI2**.
The source/control-flow audit covers both return paths, the following refused
VM entry and native fallback refusal. Bounds retain CPU48/I/O7/DMA511 and the
documented interrupt/workload assumptions. These are conditional emulator
bounds, not a physical-device timing qualification.

## Independently repeated verification

The complete cumulative runner finishes all 50 commands successfully in an
isolated source tree with a private Cargo target. Its 39 result files and all
command logs are hash-checked. No previous test receipt substitutes for a fresh
run in this review.

| Check | Result |
| --- | --- |
| Rust tests, formatting and Clippy | 62 tests; checks pass |
| Python artifact/bound/harness checks | 58 tests pass |
| M0 profile matrix, M1 and deterministic builds | All 10 profiles; repeated M2/M3 builds agree |
| Native instruction differential | 654 cases per cache profile, 1,308 total |
| Physical cache rollback | 512 scenarios pass |
| Cache cancellation and disabled-margin handoff fixture | Both profiles pass |
| Raster admission/completion vectors | 3,296 / 1,648 pass |
| Full-entry versus hot-PC comparison | 148 paired cases, 296 executions pass |
| Scheduler and autonomous multiprocess tests | 252 assertions and six packs pass, including NMI recovery |
| Correctly tagged old ABI pack | Rejected with E4 before native loading |
| Profiler timer qualification | 65,539 calls, actual 16-bit wrap and register/flag preservation pass |

The six accepted profiler groups were independently decoded from their raw
counter bytes. Calibration, sample counts, interval ranges and reported
inclusive totals agree. Their systematically sampled, sometimes nested/IRQ-
inclusive costs are not summed into lifetime CPU percentages. Historical
profiling experiments were audited rather than all re-executed; the timer
qualification and final uninstrumented workloads were re-executed.

The first larger-128 review attempt timed out in the host control socket while
waiting for target progress and produced no benchmark result. Its logs are
retained and excluded. Remaining measurements ran after the regression suite,
with fresh destinations and a documented host socket deadline of 300 rather
than 60 seconds. The wrapper changes no target command, target wait, binary,
clock, pause, algorithm or timing boundary. Accepted repetition counts exclude
the interrupted attempt.

The developer's historical larger64 completion-counter event remains
unclassified. This review does not retrospectively explain it. The final
coherent completion classifier, stable/torn-read fixtures and current live
runs pass; the old rejected observation remains separate evidence.

## Budget and next milestone

Normal resident code is **7,525 bytes** in both configurations. The planned
**4,096-byte numeric reserve** is preserved, leaving **155 bytes** in that
resident segment. The reserve is an estimate, not an assembled float library;
UI, input and device modules remain unsized. The result therefore closes the
specified M3-P review, not the future OS memory budget or physical qualification.
M4a can build on this ABI; subsequent native services/numerics must update the
actual map and resolve their space requirements before expansion.

## Evidence and reproduction

[Verification receipt](m3-perf-review-evidence/verification.json),
[benchmark mapping and independent oracle](m3-perf-review-evidence/benchmarks/summary.json),
[complete regression receipt](m3-perf-review-evidence/regression/result.json),
[raw-profiler audit](m3-perf-review-evidence/profile-counter-audit.json), and
[file inventory](m3-perf-review-evidence/inventory.json) bind this review.
The inventory includes exact commands, source/control and external-input hashes,
maps, bounds, outputs, full scanout captures, native control source and rejected
transport logs. Firmware, emulator binaries and full 16 MiB REU input copies
are not redistributed in the evidence directory.

The original private review is `/private/tmp/cos-m3-perf-review-20261010-l_cj5l_l`. Reproduction drivers retain its
`review-evidence/` relative layout; copy them there within a fresh source
snapshot, and use the supplied command records and explicit backend/tool paths.
The full suite entry point remains `scripts/check_m3_perf.py --offline`; use
a fresh output and a private Cargo target. Source identity is the frozen
95-file inventory, not the repository commit alone: implementation remains an
uncommitted working-tree delivery. This publication changes review files only.

All 95 original source/control fingerprints, 14 external inputs, 460 developer
evidence files and three reports were verified. The original ABI 1 delivery's
43 evidence files and 16 build artifacts, plus 26 previous independent-review
evidence files, remain unchanged. No runtime fix or normative spec change was
needed. The periodic monitor remains disabled.
