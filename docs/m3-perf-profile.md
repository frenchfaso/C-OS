# Isolated M3 target-cost profile

`scripts/m3_profile.py` measures complete autonomous target execution in an
isolated frozen source tree. It leaves working native sources and original
`docs/m3-evidence/` and `docs/m3-review-evidence/` unchanged. Every result binds
its source snapshot, ABI-matched host linker, executed artifacts, emulator and
private input hashes, independent image reference, retired count and live PAL
scanout check. These are functional-emulator PHI2 observations; physical
Ultimate timing remains unqualified.

## Accepted measurements

The ABI1 M3 baseline is the independently reviewed 16×12 Mandelbrot, limit 16,
signed Q8.8, all 192 logical bytes before cleanup. Its repeated autonomous run
again took **8,938 PAL frames** and retired **693,194 opcodes**. The profile
reuses that completed run only after exact artifact, map, input, full-output,
retirement and scanout checks. The baseline artifact tag is `$9184C26E`.

The first accepted profile, `build/m3-perf/profile-A/result.json`, samples every
128th call to operand decode and execution. Both have 5,415 samples. Empty
probe calibration takes 256 samples, with a 2–3 PHI2 interval. The instrumented
complete workload takes **9,488 frames**, an observed **550-frame / 6.15%**
increase. Its admission window remains 260–299; generated final admitted
opcode plus scheduler tail is 4,141 PHI2, below the 4,410 PHI2 guard. Thus the
paired elapsed difference for this group includes instrumentation and its
scheduling/cache effects, with no deliberate deadline contraction.

| ABI1 helper | Samples | Inclusive PHI2 total | Mean body excess versus empty probe | Largest interval |
| --- | ---: | ---: | ---: | ---: |
| Operand decode | 5,415 | 23,624 | 1.36–2.36 | 6 |
| Execute | 5,415 | 23,324 | 1.31–2.31 | 12 |

The second original-baseline group, `build/m3-perf/profile-checks/result.json`,
measures the protection/cache paths. Its complete output also passes. The
diagnostic window is deliberately contracted to 260–280: final admitted tail
5,559 PHI2 is below the 5,607 guard. It takes **20,787 frames**, versus 8,938;
this large difference combines window contraction with instrumentation and
must not be used as a production performance result.

| ABI1 protection/cache helper | Samples | Inclusive PHI2 total | Mean body excess | Largest interval |
| --- | ---: | ---: | ---: | ---: |
| PC bounds check | 10,940 | 55,749 | 2.10–3.10 | 6 |
| Preflight | 5,415 | 19,874 | 0.67–1.67 | 18 |
| Code fetch | 5,499 | 40,615 | 4.39–5.39 | 9 |
| Cache unpin | 5,920 | 39,487 | 3.67–4.67 | 7 |

The remaining original group, `build/m3-perf/profile-services/result.json`,
measures scheduler/native/cache service and admission. Its complete output
passes in **10,375 frames**; diagnostic window 260–295 has a 4,609-PHI2 tail
below its 4,662 guard. The 1,437-frame elapsed increase again includes the
earlier diagnostic deadline.

| ABI1 service helper | Samples | Inclusive PHI2 total | Mean body excess | Largest interval |
| --- | ---: | ---: | ---: | ---: |
| Native scheduler phase | 201 | 36,995 | 181.05–182.05 | 243 |
| Cache service | 85 | 11,804 | 135.87–136.87 | 142 |
| DMA admission | 169 | 571 | 0.38–1.38 | 4 |
| Successful video admission | 5,733 | 17,786 | 0.10–1.10 | — |

Native phase is inclusive of a nested sampled cache service; cache service is
inclusive of sampled DMA admission and any REU transfer. These describe
scheduler/cache work in this benchmark, which launches no memory or numeric
job. They do not measure all possible native-job workloads. Inspection of the
frozen scheduler shows that an empty job scan still selects each of four
owners before checking its PCB state, causing repeated 96-byte context saves
and loads. This is a concrete candidate for avoiding wasted work.

The 123,522 scheduler-tick samples total 2,146,855 PHI2, with a largest interval
of 12,729. The 129,092 video-admission samples include 123,359 carry-set samples
totalling 1,399,337 PHI2, with a largest interval of 12,720. These inclusive
totals contain raster IRQ time; their averages do not isolate rejection CPU
cost. The exact call populations in this instrumented run are 15,810,859
scheduler ticks, 16,523,842 video admissions, 25,774 native phases, 10,892 cache
services and 21,686 DMA admissions. They are reconstructed from continuous
sampling counters; their timing totals are still sampled, not lifetime totals.

Primitive execution and operand decode have small absolute target costs. This
measurement does **not** equate the old 95.09% multiplication opcode fraction
with 95.09% of elapsed time.

The ABI2 residual profile, `build/m3-perf/profile-wrap/result.json`, measures
the frozen ABI2 register-based workload and coherent wrap-safe admission from
`build/m3-perf/wrap-window/source`. Its uninstrumented complete run takes
**232 frames**, retiring **36,358 opcodes**. The 1/128-sampled profile still
produces the identical 192-byte image and live 64,000-pixel scanout, with zero
missed synchronization, active-line DMA, NMI or recovery diagnostics. It takes
**518 frames**. The observed **286-frame** increase combines the probes with a
deliberately earlier diagnostic deadline: its window is 260–300, versus the
baseline's 260–311 and 0–20. The generated tail is 4,318 PHI2, below its 4,347
PHI2 guard. This paired difference is not pure probe CPU cost.

| ABI2 residual helper | Samples | Inclusive PHI2 total | Mean body excess versus empty probe | Largest interval |
| --- | ---: | ---: | ---: | ---: |
| Whole VM step | 290 | 9,379 | 29.34–30.34 | 52 |
| Code fetch | 284 | 2,129 | 4.50–5.50 | 8 |
| PC bounds check | 568 | 2,988 | 2.26–3.26 | 6 |
| Cache unpin | 299 | 1,998 | 3.68–4.68 | 7 |
| Successful video admission | 278 | 946 | 0.40–1.40 | — |

PC bounds checks occur twice on the ordinary path. Whole VM-step samples
include any nested sampled probes, so their interval is not an estimate with
those nested costs removed. The separate sampled totals must not be summed
as disjoint lifetime percentages. Sampling is systematic, not random; no
unqualified extrapolation to total lifetime ticks is made.

Video admission has 7,946 samples in total, of which 7,668 return carry set.
Their inclusive intervals include raster IRQ time; the largest is **12,720
PHI2**. Its inclusive rejection total (156,659 PHI2) must not be presented as
the CPU cost of rejection checks. The 278 carry-clear samples isolate the
successful admission path. Code fetch, cache unpin and repeated PC checks
therefore merit optimization before assuming successful raster admission
itself dominates residual CPU cost. This does not remove the large wall-time
restriction imposed by scanout.

A separate single-helper probe removes nesting from the whole-step estimate:
`build/m3-perf/profile-wrap-step/result.json` has **288 VM-step samples**, 8,054
inclusive PHI2, mean body excess **24.97–25.97 PHI2**, and maximum 44. Its
complete workload passes in **247 frames**; the diagnostic early-frame cutoff
is 18 rather than 20, and tail 2,432 is below guard 2,457. This is the preferred
residual whole-step measurement. It still includes step-internal work and any
interrupt time, but has no nested probes.

`build/m3-perf/profile-wrap-arithmetic/result.json` separately measures 284
preflight and execution calls each. Preflight totals 903 PHI2, mean body excess
**0.18–1.18**; execution totals 1,372, mean body excess **1.83–2.83**, maximum
18. The complete workload passes in **266 frames**; early-frame cutoff 15,
tail 2,620 below guard 2,646. These results strengthen the case for reducing
cache/protection/scheduler overhead before further arithmetic specialization.

## Private idle-job scan candidate

The measured empty native-job scan led to a separate candidate in
`build/m3-perf/idle-scan/source`, based on the qualified hot-PC source snapshot.
It checks `SP_STATE` through `scheduler_owner_pointer` and selects an owner's
architecture only when that owner is `PROC_WAIT_JOB`. An empty scan restores
`sched_ptr` to `VM_SLOT`; its scan cursor, owed native turn, cancellation,
pending-cache and active-native paths retain their existing behavior. The
candidate changes only the staged scheduler, adds 15 resident bytes, and uses
the exact qualified hot-PC checker. Its final admitted scheduler tail is
**1,985 PHI2**, below the unchanged **2,331 PHI2** guard.

The complete 128-byte-cache benchmark in
`build/m3-perf/idle-scan/benchmark-128/result.json` passes in **150 frames**,
versus **172** for `build/m3-perf/hot-pc/benchmark-128-verified/result.json`:
22 fewer frames, a 12.79% reduction. Both retire 36,358 opcodes, reproduce all
192 image bytes and the complete live PAL scanout, and report zero missed
synchronization, active-line DMA, NMI or recovery events. Native scheduler
contracts pass all **252 assertions** across the 64- and 128-byte profiles.
These are functional-emulator observations of a private candidate; adoption
and the final integrated runtime are handled separately.

One initial 64-byte autonomous fairness trial failed the unchanged four-chunk
limit with sampled deltas `[161,155]`; its raw logs and `failure.json` remain
in `idle-scan/source/build/m3-perf/native-regressions/64/`. The unchanged hot-PC
control and a separate idle-scan repeat both pass their complete autonomous
suites. A targeted read diagnostic then proves the observer skew: with no
`wait` command between monitor reads, one owner's chunk counter advances
28→36 while the other's advances 26→31. Separate running-owner reads cannot
represent the same scheduler instant. Its coherently paused deltas are
`[81,82]`, `[78,78]` and `[84,84]`, all within the original limit.

`scripts/m3_ue2.py` now pauses through `CONTROL=0`, waits 50 ms for the same
unwound scheduler boundary as its existing full snapshot, reads both PCB
records in one 256-byte request, and restores `CONTROL=1`. The strict
four-chunk fairness limit is unchanged. The proof is retained in
`build/m3-perf/idle-scan/fairness-read-check/result.json`; host regression
checks cover read skew and resuming the scheduler after a failed observation.

The corrected observer then runs the exact combined native candidate in a
separate immutable test clone. Both cache profiles pass all three autonomous
cases: fair memory jobs (including all 2,051 bytes and the end guard), sleep
and isolated fault, and pending-job cancellation. The 128-byte fair-job
deltas are `[164,165]`; the 64-byte deltas are `[163,164]`. Both sleep checks
observe five frames and zero wake-to-dispatch delay. Each profile also injects
and recovers one real CIA2 NMI and verifies PAL scanout with zero missed
synchronization and active-line DMA. The receipts are under
`build/m3-perf/idle-scan/combined-test-source/build/m3-perf/native-regressions/`;
these regression results do not replace the combined candidate's separate
larger-workload timing checks. Its separate native scheduler contracts pass
all 252 assertions across both cache profiles; receipts are
`idle-scan/combined-native-{128,64}-verified/result.json`. The first contract
assembly attempts lacked the harness alias for the new scheduler admission
entry and did not execute a target; those assembly logs remain retained.

## Timer and instrumentation qualification

An earlier live cascaded CIA2 A/B reader was rejected: its complete output
check passed, but accumulated profile counters overflowed and interval maxima
contained modulo-negative 65,536-PHI2 discontinuities (`$FFFF0007` and
`$FFFF000A`). Its invalid counters, protocol, bounds and rejection receipt are
retained in `build/m3-perf/profile-core/runs/128/instrumented/`. Those timings
are not accepted evidence. The precise cause of the live concatenation failure
was not established; the stopped cascaded timer used by the original native
1 MHz comparator is a separate measurement.

Accepted probes use **CIA2 timer A only**, counting PHI2. A high/low/high read
retries a torn high-byte boundary. Start minus end is a modulo-16-bit interval,
then accumulated into 32-bit totals, calls, minimum and maximum. A 32-bit
accumulation overflow rejects the run. Timer B remains stopped. The timer is
settled after start before calibration, and does not enable CIA2 interrupts.
The runtime enters with decimal mode clear; wrappers retain A, X, Y and all
processor flags around their own work, including admission carry and the IRQ
mask. No instructions are inserted into the renderer's pixel stream.

Each selected measured call must fit below the 65,536-PHI2 interval range.
The conditional qualification adds one whole PAL period (19,656 PHI2,
conservatively covering one qualified raster IRQ), all admitted-window ticks
for any preceding re-admitted VM opcodes, and the generated final opcode plus
scheduler tail. Admission rejects before a following IRQ; NMI, external pause,
timer reprogramming and unbounded jobs are excluded. The interval ceilings
are **26,317 PHI2** for `profile-A` (ABI1) and **26,557 PHI2** for
`profile-wrap` (ABI2). The other accepted groups have separately generated
ceilings, also below65,536PHI2; these two values are not universal ABI limits.
Post-run arithmetic receipts are saved alongside the original bounds; they do
not alter the executed instructions or original bound files. New builds write
this qualification directly into their generated bounds.

The generated control-flow audit follows actual wrapper calls. All torn-read
branches share at most three retries: one high-byte boundary before a single
raster IRQ, one interruption, and one boundary after it. An uninterrupted CIA
high/low/high triplet occupies at most 23 PHI2 under the conditional model,
well below the 256-PHI2 high-byte boundary period. The final strict admission
check runs after any generated deadline contraction; a provisional build is
never executed merely because it was assembled.

`scripts/m3_profile_timer_check.py` additionally runs a short standalone target
check: **65,539 calls**, a 1/128 sampling factor, 514 measured callees and 256
empty calibration calls. It deliberately crosses the 16-bit timer underflow,
checks the interval for discontinuity, and verifies registers and meaningful
flags on both sampled and skipped wrapper paths. Its passing result is
`build/m3-perf/profile-timer-final/result.json`. A previous harness-only flag
check captured flags before a final `LDA`, giving a false mismatch; that check
was corrected before any accepted timer result. One later repeat and a new
group's build were interrupted by insufficient disk space before a backend
started; no timing from those attempts is used.

Inclusive intervals retain nested instrumentation and any interrupt time.
Subtracting call count times the empty probe's maximum/minimum gives the
reported body-excess interval. It is useful for ranking bounded helper costs,
not a claim that the uninstrumented body cost was measured exactly. Paired
whole-workload elapsed overhead is recorded independently. Instrumentation is
diagnostic only: it reserves 576 bytes at `$FA00–$FC3F` from the unused font
area and borrows future numeric-code reserve. It makes no production RAM-fit
claim.

`sampling-counts.json` alongside each accepted run records exact lifetime
helper call counts: `sample_count * sample_factor + counter_remainder`.
The initialized byte counter's low bits retain the unsampled remainder;
calibration uses a factor of one. This reconstruction does not extrapolate
sampled timing to lifetime totals. New runner results include these counts
directly and bind a saved copy of the executed runner script.

## Reproduction

The default profile measures decode and execution from the preserved ABI1
source snapshot. `--categories` selects another bounded group. `--sample-mask
127` selects one in 128 calls; calibration remains dense. `--prepare-only`
assembles and qualifies the target without starting a backend. `--lines 128`
selects one cache profile. `--reuse-baseline` requires a completed matching
run, and `--baseline-build` can reuse its immutable artifacts. Existing ABI2
snapshots additionally use `--existing-snapshot`, `--manifest-name` and
`--host-profile-name`; the snapshot receipt must verify every supplied source
and host tool. Baseline and instrumented inputs may never mix ABIs.

```sh
python3 scripts/m3_profile.py \
  --out build/m3-perf/new-profile \
  --baseline build/m3-perf/baseline/source --lines 128 \
  --categories execute decode --sample-mask 127 \
  --emulator /path/to/ue2emu --config /path/to/c64u.toml \
  --flash /path/to/flash.bin --settings /path/to/ultimate.cfg \
  --kickass /path/to/KickAss.jar --java /path/to/java
python3 -m unittest discover -s tests/native -p test_m3_profile.py -v
```

The original ABI1 source snapshot and ABI2 wrap snapshot remain immutable.
Default cleanup removes only each completed profiler run's own private
firmware, REU and USB working copies after process exit. Linked artifacts,
source snapshots, counters and observations remain. `--keep-inputs` retains
those disposable execution copies.
