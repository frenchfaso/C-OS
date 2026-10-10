# Real-workload performance contract

October 10, 2026. Companion to SPEC.md revision 8. The measurement contract
continues to apply to the frozen ABI 1 baseline and the ABI 2 performance work.

## Goal and scope

The application-throughput requirement for continuing the VM architecture is
now **at least 2× an original PAL C64 running reasonably optimized native
6510 code**. The [M3-R gate](M3-RESOURCE-GATE.md) defines the required pre-M4
workloads and evidence. This is a target, not a measured claim; the earlier
greater-than-1× milestone remains historical. Report results per workload rather than using a favorable
average to hide regressions. Input latency and uninterrupted UPIC scanout remain
separate requirements from SPEC.md §16.

Use complete computations that produce an image or a sequence of frames:

| Workload | First scope | When |
| --- | --- | --- |
| Mandelbrot | Fixed viewport, iteration limit, escape test, rounding and output palette; bytecode fixed-point arithmetic is sufficient | First autonomous baseline in M3 |
| Small ray tracer | Fixed scene, camera, rays per pixel, shading and recursion limit | After the necessary numeric helpers; float24 and float32 are separate profiles |
| Simple 3D rasterizer | Fixed geometry and camera sequence, clipping, fill convention, depth precision and shading | After the necessary arithmetic and graphics facilities |

Start with a small deterministic image that finishes in practical test time,
then add larger cases. An 80×50 Mandelbrot is a reasonable first fixture; record
the actual dimensions and never compare different dimensions as a speedup.
Do not implement the entire compiler, both float types, ray tracer and desktop
as prerequisites for completing M3. Its first application may be assembly for
the VM. Later C-Script versions must disclose their compiler and generated code.

## Fair comparison

- The baseline is a reasonably optimized native 6502/6510 program at PAL 1 MHz,
  without turbo or REU acceleration. BASIC timing may be additional context,
  but cannot establish the primary speedup. Publish its source, build options,
  memory footprint and relevant optimization choices.
- Both sides perform the same algorithm and work: dimensions, viewport/scene,
  iterations, precision, rounding, early exits, clipping, shading and output
  representation. The baseline's code, data and output must fit a real 64 KiB
  C64 memory map. Larger C-OS-only scenes are capability demonstrations, not
  directly comparable speedups.
- Validate the entire output, preferably with a byte-identical checksum and
  an independent reference. Any tolerance must be justified in advance and
  reported with the exact mismatches; reducing precision or quality creates
  another benchmark profile. Do not compare float24 against a more expensive
  higher-precision baseline and attribute the difference solely to the VM.
- The timed computation runs on the target CPU autonomously, including loop
  control and arithmetic. The host may start it and collect its final result;
  it must not execute the workload or issue a mailbox command per opcode,
  iteration or pixel.
- In the primary C-OS run, 320×200 UPIC stays active, scheduling remains enabled,
  and optional horizontal-margin work stays disabled until independently
  qualified. Display-off runs may diagnose the cost of scanout, but are labeled
  separately. Use one compute app plus an otherwise idle kernel first; report
  concurrent-app throughput and responsiveness as separate scenarios.
- Measure target elapsed time from workload start through completion of the
  entire logical output. Include cache misses, required REU transfers,
  scheduling and native-service work. If dirty cache bytes remain at completion,
  validate them coherently and state that the boundary is logical completion;
  report any required final flush/upload separately or include it consistently.
  State initial cache conditions and report cold/warm runs where relevant.
- Before graphics services exist, M3 may time production of a complete image in
  application memory. This is an image-computation result, not visible frame
  rate. Later report composition, upload and presentation time separately, plus
  end-to-end time to the last complete visible frame. A classic VIC-II display
  cannot be assumed equivalent to unrestricted UPIC; distinguish equivalent
  computed images from presentation capabilities.
- Use emulated target cycles/PHI2 ticks or a qualified target timer with explicit
  wrap handling. Host wall-clock time, debugger waits and scanouts accumulated
  during diagnostic pauses are not application throughput. Identify emulator,
  firmware, configuration and artifacts; distinguish emulation from hardware
  qualification. Timer collection overhead must be bounded and reported.

For a fixed workload, `speedup = native_C64_elapsed / C_OS_elapsed`. For an
animation, count only complete frames from the same prescribed sequence.

## Optimization policy

First address measured costs: diagnostic overhead, available time outside the
active raster interval, dispatch/validation, cache locality and arithmetic
helpers. M2's PAL lines 280–299 are a conservative diagnostic admission window,
not the intended final utilization of all non-display time. Widen it only with
revised opcode/service bounds, wrap-safe deadline admission and video evidence.
Do not infer a safe budget from nominal 64 MHz alone.

The ABI 1 M3 baseline lowers multiplication to bytecode. ABI 2 now specifies
general full-product MULU/MULS instructions in SPEC §8.3; integer division and
remaining wide arithmetic continue as VM sequences or bytecode routines.
Implement the specified operations consistently across host model, assembler,
disassembler, kernel, pack/version checks and compiler lowering when available.
Preserve fuel, fault atomicity and bounded execution. Profile actual target
costs before attributing elapsed-time gains to arithmetic or making claims
about Mandelbrot, ray tracing or 3D. No further implicit ISA extension is
authorized merely by a benchmark result.

Ordinary specified native services are part of C-OS and may be used, with their
time and call counts reported. Do not add a Mandelbrot/ray-tracing/frame-render
syscall that moves the entire benchmark out of userspace and then label it VM
speed. Distinguish application throughput from interpreter-only measurements.

M3 must produce a reproducible first baseline and identify its dominant costs;
it need not already reach 1× or 2×. If a target is missed, publish the result and
the smallest justified next optimization. Preserve isolation, exact resumption,
fairness, the memory budget and raster safety. Do not introduce a JIT, a second
scheduler or alternate bytecode format merely to meet an unmeasured estimate.

## Current priority: M3-R before M4

The [independent M3-P review](../docs/m3-perf-review.md) reproduces 1.436694x
and 1.465730x on the two Mandelbrot workloads with 128-byte lines, or
1.287637x and 1.314340x against separately improved native controls. The
64-byte profile remains below 1x. The user now requires a credible memory
budget and at least 2x before further feature work. Follow
[M3-RESOURCE-GATE.md](M3-RESOURCE-GATE.md). The earlier M3 and M3-P results,
sources, comparators and evidence identities remain unchanged.

Pursue at least 2x through measured iterations, not just an instruction-rate
improvement or a favorable small working set. Use repeated equivalent outputs,
conservative timing and the stronger native controls. If the goal remains
unmet, identify the measured residual costs and compare concrete architecture
alternatives before beginning feature work. Missing
the goal never permits changing the image, precision, baseline, timing scope,
preemption or active-video requirement to manufacture a pass.
