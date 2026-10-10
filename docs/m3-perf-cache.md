# M3-P cache and application locality experiments

The three adopted cache hot paths retain the matching, owner/generation,
rollback, DMA and guest protection checks. Only data entries 8–15 can acquire
PIN through `cache_require_data`, so `cache_unpin` clears those eight entries.
The trusted cache callers select indices 0–15; a 32-byte constant pointer table
replaces address reconstruction. Complete, four-byte-aligned instructions
cannot cross a 64- or 128-byte cache line, so the code hit copies four bytes
without a loop. No architectural or cache scratch storage is added.

The adopted source is SHA256
`291ff44a8011f0397115a7b1c7d7f5884b24763d93dfba503d4f38749157aa5b`.
The lookup tables use 32 assembled bytes; removal of the old address helper and
unrolling the copy produce net cache growth of 19 bytes for 128-byte lines and
13 bytes for 64-byte lines. On the measured wrap-window checkpoint both full
resident images use 7,421 bytes and retain 259 bytes after the planned 4 KiB
numeric reserve. Future modules remain unsized.

An independent, small assembled-binary NMOS instruction runner checks all 16
line pointers and every aligned fetch offset in all eight code buffers. It
finds 263→135 CPU cycles for unpin, 147→85 for a 128-byte code hit, and 159→85
for a 64-byte code hit. The copy unroll itself saves 35 cycles. These ordinary
RAM instruction counts exclude caller JSR, IRQ/NMI, memory stalls and scanout
suspension; they are not whole-workload PHI2 attribution. The source and exact
binary receipts are in `build/m3-perf/cache-opt/hotpaths.json` and the measured
wrap-artifact recheck in `build/m3-perf/cache-wrap/hotpaths.json`.

## Target measurements

All runs compute the unchanged 16×12, limit-16, signed-Q8.8 image, with full
UPIC scanout and disabled margins. Every 192-byte output has SHA256
`2e62867fb2ecf558567623cd291435f3269a930383edb8602b8ff0c6aab0ca5c`.
All 64,000 live scanout pixels and both output rows match; missed sync, active
DMA, NMI and recovery counters are zero. The native PAL 1 MHz comparison
repeats 2,682,768 PHI2 ticks. Frame-based estimates retain one-period
quantization and the conservative 64-frame collection ceiling; no overhead is
subtracted from the main ratio.

| Frozen runtime/application | Cache line | Retired | Frames | Native/C-OS ratio | Actual code fills |
| --- | ---: | ---: | ---: | ---: | ---: |
| Register inline, narrow window | 128 | 36,358 | 427 | 0.319639 | unavailable in old receipt |
| Register inline, narrow window | 64 | 36,358 | 666 | 0.204934 | 3,561 in exact rerun |
| Shared aligned Q8 helper, narrow window | 128 | 42,970 | 588 | 0.232119 | 2 |
| Shared aligned Q8 helper, narrow window | 64 | 42,970 | 631 | 0.216301 | 768 |
| Register inline, wrap window | 128 | 36,358 | 232 | 0.588301 | 2 |
| Register inline, wrap window and fast cache | 128 | 36,358 | 206 | 0.662553 | 2 |
| Register inline, wrap window and fast cache | 64 | 36,358 | 338 | 0.403805 | 3,561 |

The shared helper puts its 116 hot bytes inside two 64-byte cache lines. It
reduces code fills from 3,561 to 768, but adds 6,612 CALL/RET retirements and
stack data accesses. This lowers elapsed time by 5.26% for 64-byte lines and
raises it by 37.70% for 128-byte lines. It was retained as an experiment. The
code fill counters are normal target u16 modulo event counters, not execution
time. A separately labeled host model follows the exact alternating-victim
two-line policy and matches the measured counts; it makes no target timing
claim.

The fast cache's 128-byte comparison changes only cache.asm from the frozen
wrap-window runtime and lowers elapsed frames by 11.21%. Both profiles have a
conditional last-opcode-plus-scheduler-tail bound of 2,241 PHI2 ticks versus a
2,331-tick entry guard. The source snapshot is unchanged after both runs.
The complete source/artifact bindings are in
`build/m3-perf/cache-wrap/summary.json`.

The initial private shared-helper runner mistakenly labeled already captured
normal counters as unavailable. Its original completed receipts remain
unchanged. `build/m3-perf/registers-shared/counter-correction.json` decodes the
intact raw cache-work bytes and cites their exact native source. A later
inline-64 run uses the corrected observation runner and reproduces 666 frames
with 3,561 target code fills.

## Regression and preservation

The exact optimized cache passes all 512 physical rollback cases across both
cache sizes and normal/extended diagnostics, plus both native cancellation
and coherence fixtures with the expected 14 DMA directions and byte-exact
physical REU contents. Receipts are in
`build/m3-perf/cache-wrap/physical-summary.json` and `cancel/*/result.json`.
These targeted checks supplement the parent task's cumulative regression.

Original M3 delivery/review evidence and neighboring projects are preserved.
Private completed backend flash, REU and USB working images are removed only
after source/ownership, nlink=1, hash and exact lsof checks. Cleanup receipts
retain before/after df measurements. A concurrent ENOSPC prevented one cleanup
journal write; one completed private REU input was hash-checked and recorded in
tool output before unlink, then its receipt was saved after space was freed.
No compiled shipping pack, result, image, scanout or protocol log was removed.
Physical Ultimate timing remains unqualified; the greater-than-1× objective
is still open at this cache checkpoint.

## Keeping row-constant cy in P3

The separate application `apps/mandelbrot-registers-pointer-cy.casm` keeps cy
in unused P3, then reads its low16 with PGETLO during each iteration. P3 is
never dereferenced; its 24-bit values range from 65,152 to 65,920 without
24-bit overflow, and their low16 exactly match the old signed row coordinates.
Row increment remains the same opcode count, and startup saves one opcode.
The real SP, output P0 and timestamp scratch P2 are unchanged. This is an
application register-allocation change with the same general ISA.

On native binaries byte-identical to the fast-cache wrap checkpoint, the
complete host and target images match. Both retire 36,357 instructions.
The 128-byte run falls from 206 to 203 frames (0.672345× native, 1.46% less
elapsed time), and the 64-byte run from 338 to 328 frames (0.416116× native,
2.96% less elapsed time). Their code/data/writeback counters are 2/3/0 and
3,381/4/0 respectively. The 64-byte gain also includes the changed code
placement after removing one startup opcode; it is not attributed solely to
the cheaper cy read. Full scanout and all benchmark integrity checks pass;
the native comparison still repeats 2,682,768 ticks. Evidence and exact source
bindings are in `build/m3-perf/pointer-cy/summary.json`. This candidate remains
separate from the canonical app so the parent task can combine it with later
VM experiments deliberately.

## Conditional instruction cleanup (private hot-PC checkpoint)

A separate private change to `vm_effect_done` skips the full unpin scan when `V_ACCESS=0`; successful memory/stack accesses retain the original cleanup, and all wait/fault/fuel/video boundaries and accepted completions retain unconditional cleanup. This adds four bytes to the frozen hot-PC source, with no cache source changes (accepted SHA256 `291ff44a8011f0397115a7b1c7d7f5884b24763d93dfba503d4f38749157aa5b`). The child did not edit canonical `vm.asm`.

The boundary invariant is inductive: only `cache_require_data` sets PIN; it is reachable from memory/stack prepare after setting `V_ACCESS=1`. A nonaccess attempt sets no pins and enters from a clear boundary. Cross-line misses globally unpin before wait, and invalid loaded RET targets still use the global fault cleanup. Native jobs use the DMA staging buffer and coherent flush/invalidation rather than data pins. The exact staged source and detailed pin-lifetime proof are in `build/m3-perf/unpin-skip/source-snapshot.json` and `pin-lifetime.md`.

| Frozen runtime and same register application | Frames | Original PAL1MHz / C-OS estimate | Resident bytes |
| --- | ---: | ---: | ---: |
| Hot-PC baseline | 172 | 0.793523× | 7,456 |
| Conditional successful-effect cleanup | 156 | 0.874910× | 7,460 |

This is 9.30% less elapsed target time, with the same 36,358 retired opcodes, 2 code misses, 3 data misses, no dirty writebacks, reference output SHA, all 64,000 live scanout pixels, and zero raster/DMA/NMI-recovery violations. The independent native baseline remains 2,682,768 PHI2 ticks. GET_FRAME has one-frame quantization; conservative collection overhead is retained without subtraction.

All 304 selected ABI2 fixtures passed separately with 128-byte and 64-byte lines: 271 noninvalid cases plus 33 malformed memory/stack encodings. There were 940 architectural actions per size, 440/471 waits and 465/510 cache-service directions. The existing target checker rejected PIN at every captured boundary: 1,846/1,922 emitted metadata snapshots contained zero pins. Real CIA2 NMI preserved state and cache continuation, with zero raster or DMA violations. Both native scheduler contracts passed all 126 assertions. `unpin-skip/summary.json` binds results, fixture and source hashes. These are emulation results; physical Ultimate qualification remains pending.

The assembled cleanup at `$1454` is `a5 7b f0 03 20 08 1e 60`; its branch stays on one page. It saves 135 NMOS CPU cycles per nonaccess retirement and adds five per access retirement, yielding 4,742,430 CPU cycles saved from the unchanged host histogram (35,173 nonaccess / 1,185 access). This instruction calculation excludes stalls, interrupts, admission and DMA, and is not an elapsed-PHI2 estimate.

A separate prepared-index candidate clears only first/last data entries after successful access. It retains global cleanup for all waits/faults/boundaries and keeps the cache source unchanged. It assembles to 7,479 resident bytes (+19 beyond minimal) and measured 155 frames, 0.880555×, for the same retired count, miss counters, image and scanout. That one-frame difference overlaps GET_FRAME quantization; the parent selected the smaller conditional-skip candidate. Prepared-index evidence is kept under `build/m3-perf/unpin-prepared` and the variant is not adopted.

The prepared-index candidate also passed all 304 selected target cases at both line sizes, with zero PIN leakage across 1,848/1,920 emitted metadata snapshots and real CIA2 NMI state/cache preservation. This validates its narrow cleanup invariant but does not resolve the one-frame performance quantization. Its private sources/results remain preserved; exact closed backend input copies were reclaimed under separate cleanup receipts.
