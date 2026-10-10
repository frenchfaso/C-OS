# M3-P performance work

This report records the completed implementation and emulator verification of
the authorized performance step before M4. Application ABI 2
adds the general MULU/MULS instructions specified in revision 7. COS-NUM-1,
COSOBJ1, COSPACK1 and COSREU01 retain their formats. The original M3 delivery
and independent review remain frozen ABI 1 evidence in `docs/m3-evidence` and
`docs/m3-review-evidence`.

The selected 128-byte cache profile completes the original workload in
95 PAL frames, repeated exactly, for 1.436694x original native throughput
(conservative lower bound 1.421695x). The equivalent 32x24 workload reaches
1.465730x. Both retain live UPIC scanout and exact output. The 64-byte profile
remains below 1x, and the 2x stretch goal is unmet. These are qualified emulator
results; physical Ultimate timing remains pending.

## Workload and comparison

The primary workload remains exactly 16x12 pixels, limit 16, signed Q8.8.
Coordinates, escape-before-update order and floor division by 256 are unchanged.
All 192 output bytes must match the independent integer reference, SHA256
`2e62867fb2ecf558567623cd291435f3269a930383edb8602b8ff0c6aab0ca5c`.

The original NMOS 1 MHz native comparison remains 2,682,768 PHI2 ticks, with VIC
display disabled, no REU/turbo, a coherent cascaded CIA2 timer and a 64-tick
collection ceiling. C-OS uses the qualified emulated turbo profile, the full
UPIC 320x200 scanout and disabled horizontal-margin work. GET_FRAME measures
logical image completion before process cleanup, final cache flush or image
presentation. Dirty-cache overlay is checked separately from physical REU.
The displayed image remains the M0 scanout pattern; these are computation
results, not displayed Mandelbrot FPS.

Measured development checkpoints so far:

| Change | Cache | Retired | Frames | PHI2 estimate | Native/C-OS ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| Frozen M3 ABI 1 |128|693,194|8,938|175,685,328|0.015270|
| MULS helper only |128|50,106|1,069|21,012,264|0.127676|
| Register allocation, inline extraction |128|36,358|427|8,393,112|0.319639|
| Same register application |64|36,358|666|13,090,896|0.204934|
| Coherent wrap-safe admission |128|36,358|232|4,560,192|0.588302|
| Cache hot paths plus wrap-safe admission |128|36,358|206|4,049,136|0.662553|
| Same cache/runtime, register application |64|36,358|338|6,643,728|0.403805|
| Validated current-PC loop |128|36,358|172|3,380,832|0.793523|
| Conditional nonaccess unpin (isolated) |128|36,358|156|3,066,336|0.874910|
| Empty native-job metadata scan (isolated) |128|36,358|150|2,948,400|0.909906|
| Separate scheduler/VM admission (isolated) |128|36,358|142|2,791,152|0.961169|
| Combined runtime, cy held in P3 |128|36,357|95|1,867,320|1.436694|
| Same combined runtime/application |64|36,357|257|5,051,592|0.531074|

All rows validate the complete output; the new target runs also validate all
64,000 live scanout pixels, zero missed synchronization, zero active-line DMA
and no NMI/recovery. Each native rerun remains exactly 2,682,768 ticks. Frame
estimates have one PAL period (19,656 ticks) quantization and retain the
conservative original 64-frame timestamp-collection ceiling. No overhead is
subtracted from the main estimates. The combined cache128 candidate exceeds
1x, including its conservative lower
endpoint 1.421695x; both primary repeats give the same frame counts. The
95 current source/control files are frozen; the complete cumulative native
regression passed against the v2 inventory. The
2x stretch goal has not been reached.

Checkpoints bind source/tool snapshots and artifacts under `build/m3-perf`:
`experiments/mul-only-128/result.json`,
`registers/benchmark-{128,64}/result.json`, and
`registers/benchmark-summary.json`. The durable
[checkpoint index](m3-perf-evidence/checkpoints/index.json) links all 13 rows to
their exact receipts, artifact identities and recorded provenance limitations.
The frozen normal results and repeats are
`final-candidate/benchmark-primary-{128,64}/result.json` and
`final-candidate/benchmark-primary-{128,64}-repeat/result.json`. Cache counters are actual target
low16 modulo values: the 128-byte profile has two code misses and three data
misses; the combined 64-byte profile has 3,381 code misses and four data misses.
Neither
needs a dirty-victim writeback in this workload. A shared multiplication helper
reduces 64-byte code fills to 768 but adds 6,612 retirements; its earlier target
comparison improves only from 666 to 631 frames and slows the 128-byte profile.

## Larger equivalent workload

The additional workload is 32x24, limit 16, step 32, on the same half-open
viewport cx=[-512,512), cy=[-384,384) in signed Q8.8, with the same rounding and
escape order. All 768 output bytes match the independent reference SHA256
`83c6af3119bdd417f7429627c04198faa2732a05d03f65ce62cff704278cb69a`.
The original 192 samples also match its even-x/even-y positions. It has 3,891
completed iterations and 146,476 retired VM instructions. Its separate native
source retains the original multiplication/escape algorithm and changes only
width/height and coordinate steps; native time is 11,005,565 PHI2. The original
primary native source and 2,682,768-tick comparison remain untouched.

| Workload | Cache | Frames | PHI2 estimate | Native/C-OS | Conservative lower | Code/data fills | Writebacks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 16x12, two identical repeats |128|95|1,867,320|1.436694|1.421695|2/3|0|
| 16x12, two identical repeats |64|257|5,051,592|0.531074|0.529003|3,381/4|0|
| 32x24 |128|382|7,508,592|1.465730|1.461894|2/7|0|
| 32x24 |64|1,040|20,442,240|0.538374|0.537853|13,617/14|6|

All six final normal measurements pass full logical output, all 64,000 live
scanout pixels and zero missed-sync/active-DMA/NMI/recovery checks. They start
with empty caches, except that the initial GET_FRAME warms its code line.
Physical output can differ until dirty lines are written back; logical output
is reconstructed from real cache metadata and buffers. Primary output still
has 192 dirty physical differences. Computation finishes before exit cleanup,
final flush and presentation; those costs are not subtracted or presented as
image FPS. One-frame quantization is 1.05% of the primary 95-frame estimate and
0.26% of the larger 382-frame estimate, well below either 128-byte result's
conservative margin above 1x.

The unchanged 64-frame timestamp ceiling is re-established for all four exact
packs in `final-candidate/collection-ceiling.json`: six retirements, at most
10 misses, 14 DMA phases and two fuel rotations give 32 progressing units,
each charged two PAL periods. Every admission domain still contains the
complete 260–299 window. Its 2,046-PHI2 first-unit summary plus the 1-PHI2 outer
bridge costs 2,047 PHI2 for a fresh tick. A refused polling gate can be interrupted
and resume after scanout with old raster samples; charging its entire 23-PHI2
hook and 1-PHI2 branch/return gives 2,071<2,520 PHI2, leaving 449 PHI2 slack.
The compiled-byte residual check is preserved alongside the receipt.
This conditional upper bound includes
timestamp work outside the measured interval and is never subtracted from
the estimate. See the companion Markdown receipt for all assumptions.

The 128-byte code cache is the selected primary profile. The 64-byte variant
still thrashes two small code lines and remains below original native
throughput. Its 13,617 code fills on the larger workload are measured, not an
attribution inferred from retirement percentages. The 2x stretch target is
unmet. Further improvement needs justified bytecode locality/dispatch work
within a 155-byte resident headroom after the numeric reserve; unsized future
OS modules remain an architectural budget decision. No future milestone is
started to hide either limitation.

## General multiply and ABI migration

MULU ($39) and MULS ($3A) require all three operand bytes zero. Both capture old R0/R1,
return the exact low/high 16-bit halves in R0/R1, and preserve R2..R7, every P
and SP. Existing decode/fetch/selected-next-PC checks precede effects. A
completed multiply retires once and consumes one credit; deferred instructions
publish no partial result. It has no native-job or syscall entitlement.

The native routine uses a combined 32-bit accumulator/multiplier, adds old R0
into the high half for each selected multiplier bit, and rotates right exactly
sixteen times. MULS subtracts old R1 from the high half when old R0 is negative,
then old R0 when old R1 is negative. Inputs stay architectural until all four
product bytes are ready. The 106-byte implementation reuses four dead decode
scratch bytes at `$73..$76`; there is no per-context storage increase.

The final-candidate resident size is 7,525 bytes for either cache size. The
planned 4 KiB numeric reserve remains inside the fixed 20 KiB local-RAM budget,
leaving 155 bytes in the resident segment. Private diagnostics have separate
source/maps and their temporary event scratch is excluded from normal builds. Future shell/input/graphics/UCI/SID/audio
code remains unsized; this does not establish that the remaining OS fits.

| Current normal allocation or bound | Bytes | Accounting |
| --- | ---: | --- |
| Native resident, either profile |7,525|Includes VM, tables, cache, jobs, scheduler and video entry|
| VM instructions / dispatch table |2,619 / 177|Subsets of the resident; 59 dispatch entries|
| General multiply |106|Subset of VM instructions; four reused scratch bytes|
| Planned numeric reserve / remaining resident space |4,096 / 155|Reserve retained inside the fixed local-RAM plan|
| Code and data cache buffers, profile128 / profile64 |2,048 / 1,024|Actual use; fixed reservations remain 2,048 bytes in both profiles|
| Cache metadata / active architecture and bounds |112 / 96|Separate existing runtime state|
| Four PCB metadata records |128|Separate runtime state|
| Scheduler globals / completion and replacement staging |128 / 96|Separate existing reservations|
| VM / cache / scheduler zero-page scratch |30 / 31 / 17|Existing allocations; multiply reuses four VM bytes|
| Hardware stack: normal / IRQ / NMI / combined bound |18 / 8 / 4 / 30|Conditional static depth; no nested IRQ or recursive NMI|

The maps record the local-RAM sections and shared REU reservation individually;
rows describing resident subsets and scratch reuse are not additional space.
Normal diagnostic code and mailbox reservations are zero. Optional margin work
remains disabled; its scratch stays within existing staging space.

Host tools now reject ABI 1/mixed inputs explicitly, including correctly paired
headers. Startup R1, SYS_INFO and generated descriptors use ABI 2. Native
bootstrap rejection additionally tests a frozen original ABI 1 pack against a
current loader rebuilt with its exact old build tag: every checked field
matches except ABI 1 versus ABI 2. Historical images are never rewritten.

Host verification passes 62 tests and clippy. A raster-active native pilot
passes 37 multiply cases covering literal products, deterministic varied
operands, zero/one fuel, cold-fetch retries, video suspension and interleaved
owners. The final cumulative suite passes 654 differential cases per cache
profile, including general multiply semantics and all existing instructions.

## Profiling and qualification

The refreshed frozen M3 target run reproduces 8,938 frames and 693,194 retirements
exactly. The first simultaneous timer-probe design was rejected as primary
because its conservative native tail exceeded the available video guard.
The initial cascaded live timer reader also produced incoherent low/high values
and wrap discontinuities; its precise cause remains unclassified and those
counters are retained as rejected evidence. The repaired profiler measures bounded CIA2A 16-bit intervals
and accumulates 32-bit totals. Its native timer test covers 65,539 calls, an
underflow, all register/flag preservation and 256 empty-call calibration samples.

The qualified original workload samples one in 128 decode/execute calls, with
5,415 samples each. Beyond an empty call, decode averages 1.36–2.36 PHI2 and
execution 1.31–2.31 PHI2. The original admission window is retained, so its
9,488 frames versus 8,938 disclose 550 frames of observed instrumentation
overhead. These systematically selected samples are not exact lifetime totals.

The qualified ABI 2 register/wrap profile samples VM step, code fetch, PC
checking, cache unpin and video admission. Sampled body excess is 4.50–5.50
PHI2 for code fetch, 3.68–4.68 for unpin, and 2.26–3.26 for each PC check
(normally twice per retirement). Successful video admission averages
0.40–1.40 PHI2 beyond an empty call. The sampled VM step includes nested
probes; admission deferrals can include an entire raster interrupt. None of
these inclusive quantities can be summed as disjoint CPU percentages.
That isolated run deliberately narrows admission and completes in 518 versus
232 frames; the 286-frame difference includes both probe cost and unavailable
compute time. Normal benchmark results use the uninstrumented runtime.

A separate single-probe ABI 2 run measures the whole VM step at
24.97–25.97 PHI2 of sampled body excess, with 288 samples and a 44-PHI2
maximum interval. It is the preferred whole-step estimate because it excludes
nested probe wrappers. The narrowed diagnostic window changes elapsed time
from 232 to 247 frames, so it remains profiling evidence only.

Normal admission uses coherent D011/D012/D011 classification and rejects
mismatched high-bit samples without retry. All domains admit PAL 260–311.
Scheduler/native/DMA entry additionally admits 0–20, with a 2,331-PHI2 guard;
per-opcode VM admission admits 0–50, with a 441-PHI2 guard. The final complete
scheduler summary is 2,046 PHI2; the separately proved remaining VM/return
suffix is 371 PHI2. The latter includes the following refused VM entry, result
handling and either tick return or a refused native fallback. A successful
native fallback requires a fresh scheduler admission. This excludes the
already completed prefix only after its independent control-flow proof.
There is no enlarged native-job/DMA window or hidden job entitlement.

The current-PC fast path is entered only after the preceding instruction
returned RUN and published a fully checked next PC. All selected branch/RET
addresses retain validation. Every scheduler/import/native-job entry and every
wait/fault/syscall/fuel boundary goes through the full VM entry. The flag uses
dead private preflight scratch; it is not a decoded-code cache. Conditional
unpin skips the scan only when V_ACCESS=0: a nonaccess instruction cannot pin a
data line, all access completions keep cleanup, and all boundary cleanup stays
unconditional. Native jobs never set data PIN. Empty native-job scanning checks
stable PCB metadata before loading architecture and restores the active pointer
when there is no job.

Native gate fixtures exercise stable PAL lines and both torn high-bit
directions; the validated-PC fixture compares full-step and vm_run paths across
74 cases per cache profile. Conditional unpin has separate 304-case regressions
per cache profile. See [m3-perf-cache.md](m3-perf-cache.md) and the pin-lifetime
record in build/m3-perf/unpin-skip for detailed byte/memory invariants.
Optional horizontal-margin execution remains disabled.

A larger64 development benchmark was rejected because its old DMA completion
counter reported one active-line event. Its original trace has no per-transfer
raster witness, so that event remains unclassified. An independent assembled
routine reproduction proves that the old raster_active high/low pair could
report a false active311->0 wrap and miss an active255->256 transition. Two
private event-capture repeats observed no event and do not identify the original
one. The normal predicate now confirms D011 after D012, resolving each known
transition without retry: 255->256 is active on both sides, 311->0 inactive.
All 824 stable/torn classifier vectors pass on each cache profile, preserving
X/Y and the hardware stack. All six fresh normal workloads and the complete
regressions passed this stronger completion check; the rejected measurement
is retained.

Autonomous fairness sampling also required a diagnostic correction. Separate
monitor reads ran while job counters advanced; a trace proved non-simultaneous
samples. The test now pauses at a scheduler boundary and reads both PCBs in one
block before resuming, retaining the original <=4 phase-count threshold. The
failed old reading remains evidence, not an accepted scheduler defect.

See [m3-perf-profile.md](m3-perf-profile.md) for measurement semantics and
isolated-source workflow. Emulator qualification does not establish physical
Ultimate timing; hardware qualification remains pending. M4 has not begun.

## Reproduction and verification

Run from the repository root with Rust1.93.0, Python3, Java25, KickAssembler5.25
and the explicitly supplied UE2 backend/firmware inputs. Network access is not
needed with the existing Rust dependency cache. The native verification uses
the protected exported emulator executable, not a Cargo build of its project.
The original correctly paired ABI1 delivery is an explicit input for its
migration-rejection test; its build directory must retain map, manifest,
PRG and REU bytes. Physical Ultimate qualification is a separate procedure.

```sh
python3 scripts/check_m3_perf.py \
  --emulator /Users/frenchfaso/Documents/Code/C64/UE2-C64U-Emulator/target/release/ue2emu \
  --config /Users/frenchfaso/Documents/Code/C64/runtime/c64u.toml \
  --flash /Users/frenchfaso/Documents/Code/C64/runtime/flash.bin \
  --settings /Users/frenchfaso/Documents/Code/C64/runtime/ultimate.cfg \
  --kickass /Users/frenchfaso/Documents/Code/C64/toolchain/kickassembler/KickAss.jar \
  --java /Library/Java/JavaVirtualMachines/temurin-25.jdk/Contents/Home/bin/java \
  --cpu-core /Users/frenchfaso/Documents/Code/C64/UE2-C64U-Emulator/vendor/trx64-core/src \
  --old-build /Users/frenchfaso/Documents/Code/C64/C-OS/build/m3/128 \
  --out build/m3-perf/recheck-current \
  --offline
```

Choose a fresh output directory: the runner refuses to replace previous
snapshots/evidence. `--prepare-only` creates an immutable source inventory
without starting an emulator. Full verification creates current ABI2 host
objects, independently links and repeats both native profiles, checks map and
normal reserve limits, and runs all applicable suites in that private tree.
The first final attempt stopped only at two stale ABI1-era VM-size assertions;
its failed snapshot/log is retained. The corrected v2 inventory differs in
exactly `tests/native/test_m2_artifacts.py`, whose expected table now has59
entries/177bytes and instructions2619bytes. No native source changed between
those freezes.

The six normal measurements' exact executed commands are retained in
`build/m3-perf/final-candidate/normal-timing/commands.json`. Their inputs are
`final-candidate/{primary,larger}.json`, the canonical primary/larger assembly,
and their host profiles. Build either fresh object with `target/release/cosasm`,
then `scripts/m3.py --manifest ... --cache-line 128` (or64) and
`scripts/m2_bounds.py --build ... --cpu-core ... --out .../bounds.json`.
`scripts/m3_benchmark.py` takes the same four backend inputs, Java/KickAss,
`--build`, fresh `--out`, `--application`, `--host-profile`, and
`--workload primary` or `--workload larger`. The larger workload selects its
separately specified native32x24 baseline; no edit to the primary source is
required.

Source freeze v2:95 files, inventory SHA256
`6cc2533e45c5c99d0c566d1d541d59b13c2ea33c293709fc1704b4987c7184f7`.
Checker SHA256 `eb8c82462525641ecd46603d06fbc92c277806d3393a4c8cd296ff4392d263a1`;
runner SHA256 `9c8800b869f68cf140057bce28e54d88ac3a3afbea1d375d0868775b77949159`.
All supplied firmware/tool inputs are hashed in each receipt; disposable private
firmware/USB/FAT copies are reclaimed only after successful helper completion,
regular-file/owner/nlink/hash checks and `lsof` shows no open descriptor.
Compiled artifacts, reports, source, images and cleanup journals are preserved.

The final staged run completed at 2026-10-10T18:12:59Z with all 50 executed
commands returning zero. No M0/M2 result from the old delivery substitutes for
a current-source run. The complete receipt is
[`regression/result.json`](m3-perf-evidence/regression/result.json), SHA256
`97d3f1f30114ca3e082a969e286fc69e50fc5936d26383f179ea77ab9281cd8b`.

| Final verification | Result |
| --- | --- |
| Host formatting, Rust tests, Clippy |62 tests; no warnings; ABI2 release tools|
| Python artifact/bounds/runner/profiler checks |58 tests|
| M1 and repeated M2/M3 linking |All current host outputs; both cache sizes byte-identical on repeat|
| M0 profile matrix |10 profiles with expected success/rejection codes|
| Native VM differential |654 cases per profile; 1,308 total|
| Physical dirty-victim rollback |512 scenarios across normal/extended and both cache sizes|
| Cache cancellation and optional margin fixture |Both cache profiles pass; normal margin execution remains disabled|
| Coherent admission / completion classification |3,296 / 1,648 stable and torn-read vectors|
| Validated-current-PC equivalence |148 paired cases; 296 VM executions|
| Native M3 scheduler contracts |252 assertions|
| Autonomous four-process stress |Six packs, including fairness, sleep, cancellation and real CIA2 NMI recovery|
| Correct-tag ABI1 native rejection |Only checked ABI differs; loader rejects with $E4 before native loading|
| Normal workloads |Six full-output/live-scanout captures; zero missed-sync/active-DMA/NMI/recovery|

Current and staged sources, external inputs, tool binaries and all result-file
hashes were revalidated after the suite. The normal native images are identical
to the fully tested M3 images: cache128 SHA256
`50cae5a9d3d495d056c064cbee9fdae9780c611660dbb942a39c96ecbf075171`,
cache64 SHA256
`6e24d4672a168f983060343ab1a2a8f28d660dca26ef1a57b7e6a288f316f0ea`.
Different manifest object paths produce separate wrapper/pack build tags;
every benchmark binds its actual wrapper, REU image, map and bounds.

The original ABI1 delivery's 43 evidence files and 16 canonical artifacts,
plus the independent ABI1 review's 26 recorded evidence files, still match
their frozen inventories. English reports, provenance, full outputs, images,
conditional bounds and current regression logs are collected in
[`m3-perf-evidence`](m3-perf-evidence/README.md). Its
[`verification.json`](m3-perf-evidence/verification.json) binds the final source
freeze, current regression and six normal measurements. Full 16 MiB REU packs
remain at the recorded build paths, with hashes in the receipts. Implementation
resources are released for the coordinator's independent review. M4 has not
started; no index edits, commits or pushes were performed.
