# M3-R: memory budget and 2x throughput before M4

Specification 0.1, revision 8 — October 10, 2026. Normative supplement to
[SPEC.md](SPEC.md) and [PERFORMANCE.md](PERFORMANCE.md).

The user requires enough memory for the planned OS and at least 2x native
original-C64 application throughput to justify continuing this VM architecture.
This is the next implementation step. M4 and additional feature milestones
wait for its independent review. Start with memory accounting, then qualify
space recovery and further general VM optimizations together: a speedup that
consumes the future OS budget does not close this gate.

## 1 Frozen starting point

The published M0–M3-P implementation is commit
`e7e1752b6666da96a9ad70a022674eb7ce2b530b`. Its runtime sources match the
independently tested delivery; publication only adjusted documentation and
excluded the old UI mockup. Preserve the earlier evidence and use fresh build
and report paths. The [independent review](../docs/m3-perf-review.md) records:

| Item | Starting value |
| --- | ---: |
| Native resident runtime, both cache profiles | 7,525 bytes |
| Resident interval `$1200–$3FFF` | 11,776 bytes |
| Planned numeric core/bridge reserve | 4,096 bytes |
| Remaining space in that interval after the reserve | 155 bytes |
| UPIC renderer within its separate 2,560-byte reservation | 2,289 bytes |
| Primary 16x12 Mandelbrot, 128-byte lines | 95 PAL frames |
| Larger 32x24 Mandelbrot, 128-byte lines | 382 PAL frames |
| Speedup against improved native controls | 1.287637x / 1.314340x |

155 bytes is neither total free physical RAM nor capacity for all missing
services. Some currently unused ranges are already promised to event queues,
font, cursor, desktop state or numeric code. Both benchmark programs contain
232 bytecode bytes and fit two 128-byte code lines. Do not generalize those
measurements to larger code working sets.

## 2 Complete accounting before relocation

Generate one machine-readable allocation manifest and a readable map from the
build. Cover all 65,536 local addresses, zero page, hardware stack, I/O hole,
vectors, bootstrap lifetimes and REU system reservations. For every allocation
record bounds, owner, alignment/contiguity, actual code/table/data bytes,
reserved bytes, lifetime, interrupt visibility and read/write users. Distinguish
measured use, intentionally reserved future space and genuinely reusable space.
Make overlaps and missing reservations fail the build. Aliases need explicit
mutually exclusive lifetimes; they are not independent free allocations.

Break down code by assembled module and identify hot versus cold paths from
evidence. Audit initialization, recovery, bulk clear/copy, cache, raster and
bootstrap accesses, not only the steady-state dispatcher. Keep normal and
instrumented layouts separate. Count loader/linker padding and any trampolines.
Report the normal, IRQ and NMI stack bounds separately from observed depth.

Assign explicit allowances and placement to remaining native graphics/input,
compositor/desktop, file/UCI/RTC, SID/audio and numeric work, together with
events, handles, descriptors, font, cursor, dirty lists and scratch. Distinguish
native code from bytecode and cold REU data. Justify estimates with concrete
minimal designs, existing primitives or small assembled sizing experiments;
placeholders of zero bytes and `TBD` do not demonstrate a funded plan. These
experiments do not implement the full M4–M7 features or claim their completion.

The planning target is at least **2,048 bytes of unassigned usable native-code
headroom after the 4,096-byte numeric allowance and named future-module
allowances**, with explicit loadable regions. Tiny fragmented holes cannot be
summed as if they formed one code segment. This is a capacity target to prove,
not a claim about the current map. If it cannot be met, report the exact gap
and a concrete map/architecture choice for review; do not spend promised memory
silently. The two float formats and four-process contract remain in scope.

## 3 Recover space with the smallest justified change

Evaluate ordinary simplification, duplicate tables/check paths, boot-only
relocation, measured state lifetimes and cold metadata/bytecode in the REU
first. Preserve the invariants behind every removed runtime check. Keep the
128-byte cache as the performance reference; shrinking it is not an acceptable
default solution when it destroys the measured workload throughput. Any cache
change needs a measured byte/cycle tradeoff and multiprocess regression.

The 160 framebuffer columns have 56 unused bytes each, 8,960 bytes in total.
M3-R may qualify uses of `base(column)+200` through `base(column)+255`:

- Keep the 256-byte stride, 320x200 visible pixels, palette and I/O visibility.
  The tails are inside the existing 40,960-byte reservation; report visible
  pixel storage and tail allocations separately without double counting.
- Prove that every renderer read, initialization, clear, blit, DMA, NMI recovery
  and future framebuffer primitive respects the ownership boundary. A page
  fill or whole-column transfer must not erase another owner's tail data.
- Prefer suitable bounded data/tables or storage that frees a useful existing
  interval. Account for split records, addressing/lookup costs and copies. No
  tail automatically provides a contiguous font, cache line or code segment.
- Define exact ranges and lifetimes in the allocation manifest. Keep vectors,
  I/O, active pixels and any raster-owned scratch unavailable. Verify canaries
  and complete scanout under compute, cache misses, NMI recovery and cancellation.
- If fragmented executable placement is proposed, first measure actual code
  capacity after jumps/alignment plus branch/page/timing effects and loading
  cost. Do not build a generic overlay system simply to use every hole.

An internal map revision preserving these contracts is within this step's
scope and must update loader, pack, maps, bounds and tests together. Compact
200-byte-stride pixels, I/O banking, native overlays, translated execution or
changed bytecode are alternative designs to evaluate only when simpler options
are insufficient. Document their measured benefit and cost before adoption;
coordinate any normative/ABI change with the specification owner. Horizontal
margin work remains disabled, and VM/REU work remains outside active lines.

## 4 At least 2x on real work

Profile the residual normal target cost: fetched/decoded instructions,
validation, dispatch, arithmetic, cache transactions, scheduling and unused
admissible windows. Keep elapsed time, nested sample costs and counts distinct.
Evaluate general optimizations individually with byte/cycle deltas and verified
output. Code size, metadata, scratch and cache effects belong in each result.
No application-specific Mandelbrot, image-render or ray-trace syscall may
replace the userspace work. Keep fault, fuel, retirement, cancellation and
native-job fairness semantics; a fused internal path still accounts for each
logical instruction and exits at the required boundaries.

Preserve both frozen Mandelbrot algorithms, precision, parameters, rounding
and complete outputs. Keep comparisons to the original native programs, but
use the independently improved native controls as the primary acceptance
baseline. Their sources and receipts are in
`docs/m3-perf-review-evidence/benchmarks/inputs/` and the corresponding
`primary-native-control-run*` / `larger-native-control-run*` directories.
The native controls take 2,404,431 and 9,868,842 PHI2 ticks. If a further fair
native improvement is found, report it and use the stronger comparator; never
weaken the native implementation to manufacture a pass.

With the existing timing model, the conservative speedup is
`(native_ticks - 64) / (cos_frames * 19656 + 19656)`. A ratio of at least 2
therefore requires at most **60 frames for 16x12 and 250 frames for 32x24**
against these controls. These are derived acceptance limits, not performance
predictions. Requalify timing collection overhead and bounds after relevant
changes; if the timer changes, derive the corresponding conservative limit.
Do not subtract a merely estimated C-OS collection cost to reach the target.

Add one modest non-Mandelbrot image workload, preferably a fixed-point triangle
rasterizer, with a reasonably optimized native 1 MHz counterpart and an
independent complete-output oracle. Freeze geometry, fill convention, precision,
clipping, output and timing scope before optimization. Exercise a genuine code
working set beyond the current 256-byte two-line fit, using useful algorithmic
work rather than padding. It needs neither C-Script nor floats nor a full 3D
engine. Report it separately; no favorable average can conceal a failing case.
At least 2x conservatively on both Mandelbrot sizes and this second workload
family is the minimum evidence for this gate, not a promise for every app.

For each accepted workload repeat normal, autonomous, UPIC-active runs at least
twice. Validate every output byte, a live complete scanout, cache ownership and
zero unexpected synchronization/DMA/recovery events. State logical completion
versus flush/presentation explicitly. Test the 64-byte compatibility profile
for correctness and report its performance; it need not meet 2x if 128 remains
the selected production profile. Preserve four-process fairness tests and
cancel responsiveness separately from single-application throughput.

## 5 Review outcome and alternatives

Completion requires the funded allocation plan and usable headroom, measured
normal binaries, updated timing/scratch/stack proofs, deterministic builds,
the applicable full regression and the repeated conservative 2x workload
results. Small experiments do not qualify a whole future OS. Future numeric
implementation must still prove its 4 KiB estimate, semantics and timing.
Physical Ultimate validation remains separate from emulator qualification.

If justified simple optimizations cannot meet either gate, deliver the best
measured state and identify where the remaining time and space go. Compare a
small number of concrete options, such as a smaller interpreter, bounded
predecoded/threaded execution or ahead-of-time native compilation of suitable
code. Preserve the user's linear-memory, enforced-preemption and kernel-owned
video requirements in the comparison. Give expected gains tied to measurements,
local/REU costs, protection/timing implications and the smallest validating
experiment. A decision memo is not a performance pass and does not authorize
starting M4 or replacing the architecture without review.

Deliver English reports under `docs/m3-resource-*.md`, evidence under
`docs/m3-resource-evidence/`, and fresh build paths. Freeze source and tool
hashes before the final regression and independent rerun. Coordinate proposed
spec changes through the project messageboard; the coordinator owns `specs/*`
and independent-review files, while the dev owns implementation and its reports.
The periodic monitor remains disabled; completion is communicated through the
existing task and the user.
