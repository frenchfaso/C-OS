# M3-P: VM performance before M4

Specification 0.1, revision 7 — October 10, 2026. Normative implementation
supplement to [SPEC.md](SPEC.md) and [PERFORMANCE.md](PERFORMANCE.md).

Revision 8 follow-up: this document preserves the completed M3-P contract.
The current pre-M4 priority and stronger memory/2x acceptance gate are in
[M3-RESOURCE-GATE.md](M3-RESOURCE-GATE.md); the earlier >1x exit target below
does not satisfy that new gate.

The user has authorized target profiling, VM optimization and general native
integer multiplication, aiming above original native PAL C64 throughput.
This step precedes M4. It is not a compiler, float, UI or hardware-service
milestone. Preserve the M3 delivery and review as the frozen ABI 1 baseline.

## 1 Target profile and attribution

1. Preserve exact baseline sources, tool inputs, normal build identities,
   equivalent native program and full output before changing implementation.
2. Profile actual target execution: VM fetch/decode/validation/dispatch,
   arithmetic, cache/REU service, scheduler/context work and time unavailable
   for computation. Use target timers or an explicitly validated target-cycle
   profiler. Host wall-clock speed is not application throughput.
3. State whether each category measures elapsed time, executing CPU cycles,
   sampled attribution or an event count. Avoid double-counting nested phases
   or including scanout in an arithmetic CPU total. The old multiplication
   opcode share of 95.09% does not determine its elapsed-time share.
4. Keep an instrumented build separate from the normal benchmark. Measure its
   overhead, verify equivalent output and do not report its changed timing as
   the production result. Use coarse bounded counters/samples where sufficient;
   do not add a permanent expensive timer read to every normal opcode.
5. Maintain a compact table of measured changes: exact source/artifact identity,
   retired opcodes, target elapsed ticks/frames, relevant cache/job costs,
   resident code/scratch budget and comparison with the native baseline.

## 2 General integer multiplication

SPEC §8.3 is authoritative. ABI 2 adds exactly these four-byte encodings:

| Bytes | Instruction | Inputs | Outputs |
| --- | --- | --- | --- |
| `39 00 00 00` | `MULU` | R0 and R1 as unsigned 16-bit integers | R0 low16, R1 high16 of exact unsigned 32-bit product |
| `3A 00 00 00` | `MULS` | R0 and R1 as signed 16-bit integers | R0 low16, R1 high16 of exact two's-complement 32-bit product |

Both inputs are captured before either output is changed. R2–R7, every P
register and SP are preserved. No additional status register or persistent
arithmetic flags are introduced. These operations do not accept a precision,
viewport, Q format, destination image or application-specific parameter.

An admitted multiplication is one indivisible, bounded VM instruction: one
retirement and one fuel credit. Complete code/next-PC validation and timing
admission precede any result. Deferral or fetch failure preserves operands,
PC, fuel and retirement count. No partial product is visible at a scheduler
boundary, and cancellation cannot leave a detached arithmetic completion.
It uses CPU-local scratch owned by that invocation and returns with the
hardware stack unwound. Count its execution within VM time, not as a second
native-job entitlement. The actual implementation and dispatcher tail must
fit the qualified window; document worst-case inputs, loops and stack/scratch.

Verify zero, one, maximum unsigned values, both signed extrema, mixed signs,
carry propagation through all four bytes, operand equality and deterministic
varied operands against independent exact products. Include `FFFF*FFFF` in
both signedness modes, `8000*8000`, `8000*FFFF`, and malformed reserved fields.
Test zero/one fuel, fetch misses, invalid fall-through, video deferral and
interleaved owners; verify unchanged non-result registers and exact retirement.
Use native differential tests for these properties, not just host execution.

Q8.8 remains library/application behavior. An application may select the
middle 16 product bits to implement its specified floor division by 256, or
inline that sequence. General source-language multiplication keeps its
existing fixed-width wrapping semantics. NUM_OP and COS-NUM-1 are unchanged.

## 3 ABI migration

The shared application ABI constant becomes 2. Update objects/manifests,
bundler-generated constants, REU header checking, startup R1, SYS_INFO,
reference VM, diagnostics and future SDK descriptor fields consistently.
Container names/layouts stay COSOBJ1/COSPACK1/COSREU01; COS-NUM-1 stays unchanged.
Reject ABI 1 and mixed inputs explicitly. Rebuild current fixtures for ABI 2
and test rejection of a correctly paired but old-ABI pack, not merely a
mismatched build tag. No dual-ABI interpreter is required. Retain historical
documentation/evidence with its original ABI and hashes.

## 4 Optimization boundaries

Use the measurements to prioritize bounded dispatch/decoding, register use,
code/data locality, coherent cache fast paths and avoidable scheduler work.
Native multiplication is required but not assumed sufficient for the goal.
Cheap improvements such as the independently tested low-bit mask may be
adopted where still relevant; keep total work/output equivalent.

Any omitted runtime check needs an explicit invariant and validation boundary.
For example, immutable code can support validated decode information, but
guest-derived addresses, stack returns and dynamic control flow still require
their protection checks. Cache/predecode metadata must be invalidated on
owner/incarnation changes. A matching build tag is not proof of valid guest
instruction contents: any fast-path validation cache must follow actual
validation of the corresponding immutable bytes. Retain precise faults, read-only code, no partial
stores, retry without extra fuel and an accessible cancellation path.

An optimized dispatch loop must retain one credit and retirement for every
logical instruction, including hidden helper sequences. It must stop at the
same fault/wait/fuel boundaries and preserve the next queue's owed turn. A
long native instruction must not silently bypass native-job fairness.

Use more non-display time only after proving complete entry/body/return bounds,
wrap-safe raster admission and normal scanout integrity. Keep all VM, REU and
service work outside the 200 active lines. Horizontal-margin work remains
disabled; this milestone does not qualify or enable it.

Track total assembled code, tables, zero page, scratch, stack, caches and
reserved future modules. The original 409/403-byte headroom after the planned
4 KiB numeric reserve is not a budget for the whole future OS. Recover space
from measured redundancy and state unsized future costs explicitly. Do not
count the same memory twice, silently spend the numeric reserve or introduce
an overlay/JIT framework as a prerequisite for this step.

## 5 Equivalent workload and exit review

Keep the original 16x12, limit-16 signed-Q8.8 Mandelbrot parameters, escape
order, rounding and all 192 expected bytes unchanged. The new guest may use
the general multiply, inline helpers and better register allocation. Count
the resulting instructions; the baseline's 693,194 retirements are not a
requirement for optimized code. Arithmetic and loop work still run on target.

Compare normal autonomous UPIC-active runs at both cache sizes with the
unchanged native 1 MHz implementation first. Report logical completion,
dirty-cache visibility, omitted final flush/presentation, initial cache state,
timing uncertainty and collection overhead exactly as in PERFORMANCE.md.
Re-establish the collection ceiling and raster bounds after timing-relevant
changes. Keep timing resolution sufficient for the faster workload; if frame
quantization becomes material, use a qualified finer target timer. Validate
full image bytes and a genuinely live full scanout before accepting a result.

Aim for a conservative measured ratio above 1x. If achieved, repeat and add a
larger deterministic image with equally specified work, precision and an
equivalent native baseline; do not extrapolate FPS or other workloads from
the tiny case. If still below target, continue justified optimization based on
the residual profile. Report a concrete remaining limitation when further
progress requires an architectural decision; do not hide the gap or start M4
as if the performance objective had been achieved.

Deliver deterministic builds, updated bounds/maps, ABI migration tests, the
complete applicable host/native/cache/scheduler regressions, full benchmark
inputs/outputs and an English report with before/after evidence. Preserve
independent ownership of the coordinator's review documents. Freeze the final
sources and publish their hashes for independent reruns before further edits.
Emulator qualification and physical Ultimate qualification remain separate.
