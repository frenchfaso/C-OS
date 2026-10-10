#!/usr/bin/env python3
"""Package completed independent evidence and an English repository review."""
from pathlib import Path
import hashlib
import json
import shutil

ROOT=Path(__file__).resolve().parents[1]
REPO=Path('/Users/frenchfaso/Documents/Code/C64/C-OS')
BENCH=ROOT/'build/review-benchmarks'
FULL=ROOT/'build/m3-perf/full'
DEST=REPO/'docs/m3-perf-review-evidence'
read=lambda p:json.loads(p.read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
verified=read(ROOT/'review-evidence/verification.json')
assert verified['status']=='pass'
assert not DEST.exists()
DEST.mkdir()
copied=[]
def copy(source,name):
    destination=DEST/name
    destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source,destination)
    assert sha(source)==sha(destination)
    copied.append(dict(path=name,original_path=str(source),bytes=destination.stat().st_size,sha256=sha(destination)))

for name in ['verification.json','source-inventory.json','external-inputs.json','delivery-check.json',
             'historical-preservation.json','profile-counter-audit.json','full-regression.log',
             'benchmarks.log','benchmark-continuation.log','profile-timer.log']:
    copy(ROOT/'review-evidence'/name,name)
for name in ['run_benchmarks.py','continue_benchmarks.py','benchmark_transport.py','audit_final.py','publish_review.py']:
    copy(ROOT/'review-evidence'/name,'reproduction/'+name)
for name in ['result.json','commands.json','host-receipts.json','external-inputs.json','preparation.json','cleanup.json']:
    copy(FULL/name,'regression/'+name)
for p in sorted((FULL/'logs').glob('*.log')):
    copy(p,'regression/logs/'+p.name)
for rel in read(FULL/'result.json')['result_files']:
    copy(FULL/'source'/rel,'regression/results/'+rel)
for name in ['result.json','counters.bin','timer.asm','timer.prg','protocol.log']:
    copy(ROOT/'build/review-profile-timer'/name,'profile-timer/'+name)
for name in ['commands.json','continuation-commands.json','cleanup.json','continuation-cleanup.json','summary.json']:
    copy(BENCH/name,'benchmarks/'+name)
for p in sorted((BENCH/'logs').glob('*.log')):
    copy(p,'benchmarks/logs/'+p.name)
summary=read(BENCH/'summary.json')
for logical,actual in summary['accepted_paths'].items():
    source=BENCH/actual
    for name in ['result.json','native1mhz/image.bin','native1mhz/protocol.log']:
        copy(source/name,'benchmarks/'+logical+'/'+name)
    if read(source/'result.json')['cos']:
        for name in ['cos/image.bin','cos/protocol.log','cos/scanout.png']:
            copy(source/name,'benchmarks/'+logical+'/'+name)
for name in ['primary-native-control.asm','larger-native-control.asm','primary-expected.bin',
             'larger-expected.bin','primary.cobj','larger.cobj','primary-host-profile.json',
             'larger-host-profile.json','primary.json','larger.json']:
    copy(BENCH/name,'benchmarks/inputs/'+name)
for name in ['apps/mandelbrot.casm','apps/mandelbrot-32x24.casm',
             'tests/native/mandelbrot_1mhz.asm','tests/native/mandelbrot_32x24_1mhz.asm']:
    copy(ROOT/name,'benchmarks/inputs/'+Path(name).name)
for variant in ('primary-128','primary-64','larger-128','larger-64'):
    for name in ['native.bin','map.json','map.txt','bounds.json','m3.manifest.json']:
        copy(BENCH/variant/name,'artifacts/'+variant+'/'+name)
rejected=BENCH/'larger-128-run1'
for name in ['cos/protocol.log','cos/emulator.log','native1mhz/protocol.log']:
    copy(rejected/name,'rejected/larger-128-transport-timeout/'+name)

rows=[]
for workload in ('primary','larger'):
    for line in (128,64):
        needle=f'{workload}-{line}-run1'
        result=next(row for row in verified['benchmarks'] if row['name'].startswith(needle))
        rows.append('| '+('16x12' if workload=='primary' else '32x24')+f" | {line} | {result['frames']:,} | {result['cos_phi2']:,} | {result['original_ratio']:.6f}x | {result['faster_native_ratio']:.6f}x | {result['faster_native_lower']:.6f}x |")
performance='\n'.join(rows)
controls={workload:read(BENCH/f'{workload}-native-control-run1/result.json')['native']['elapsed_phi2_ticks']
          for workload in ('primary','larger')}
report=f'''# Independent M3-P review

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
{performance}

The unchanged historical comparator repeats 2,682,768 PHI2 for 16x12 and
11,005,565 PHI2 for 32x24. As an independent robustness check, only its multiply
routine was replaced with the same general combined-product shift/add and
signed high-half correction used by MULS. Coordinates, loops, escape ordering,
precision, output stores, timer and 1 MHz/no-REU configuration remain unchanged.
Both native control repetitions agree: **{controls['primary']:,}** and
**{controls['larger']:,} PHI2**, respectively. This is a separately labelled
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

The original private review is `{ROOT}`. Reproduction drivers retain its
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
'''
report_path=REPO/'docs/m3-perf-review.md'
assert not report_path.exists()
report_path.write_text(report)
(DEST/'README.md').write_text('# Independent M3-P review evidence\n\nRead [the review](../m3-perf-review.md) for scope, results and limitations.\nThe inventory binds all byte-identical copies and original paths.\n')
copied.append(dict(path='README.md',bytes=(DEST/'README.md').stat().st_size,sha256=sha(DEST/'README.md')))
inventory=dict(format='COSM3PERFREVIEWFILES1',review_sha256=sha(report_path),files=copied,
               qualification='Independent functional emulation and conditional timing; physical hardware pending')
(DEST/'inventory.json').write_text(json.dumps(inventory,indent=2)+'\n')
print(json.dumps(dict(review=str(report_path),evidence_files=len(copied),
                      evidence_bytes=sum(row['bytes'] for row in copied)),indent=2))
