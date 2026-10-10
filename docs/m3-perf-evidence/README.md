# M3-P frozen delivery evidence

The selected 128-byte cache profile exceeds the original native 1 MHz
throughput on the unchanged 16x12 workload and the equivalent 32x24 workload.
The 64-byte profile remains below 1x; the 2x stretch goal is unmet. All six
normal captures retain exact output, live UPIC scanout and zero synchronization,
active-DMA or NMI/recovery violations. Physical Ultimate timing is pending.

Read [the English report](../m3-perf.md) and
[profiling semantics](../m3-perf-profile.md) before comparing these numbers.
GET_FRAME measures logical completion before cleanup, final dirty-cache
writeback and presentation. The native comparison has display disabled. No
collection overhead is subtracted and no displayed Mandelbrot FPS is claimed.

## Contents

| Location | Evidence |
| --- | --- |
| `verification.json` | Final current-source and staged-source integrity, regression and six measurements |
| `source-inventory-v2.json` | 95 exact source/control fingerprints |
| `normal-copy-index.json` | Original paths, sizes and hashes for benchmark/artifact copies |
| `benchmarks/` | Six normal receipts, logical/native output bytes, full live scanout images and monitor logs |
| `artifacts/` | Four exact normal maps, manifests, bounds, native/boot/renderer programs and pattern data |
| `host/` | Exact primary/larger objects, listings, functional profiles and larger reference |
| `normal-timing/` | Executed commands, closed-input cleanup journal and completed summary |
| `qualification/` | The unchanged 64-frame collection ceiling and reproducible compiled polling-residue audit |
| `regression/` | All 50 commands/logs and 39 result/bounds receipts from the full fresh ABI2 suite |
| `regression-copy-index.json` | Full-regression and rejected-observation copy provenance |
| `profiling/index.json` | Six accepted isolated profiler groups, baselines and timer qualification |
| `checkpoints/index.json` | All 13 development table rows and their exact identities/provenance limitations |
| `rejected/` | Stale size assertions, original unclassified DMA observation and two zero-event diagnostic repeats |
| `inventory.json` | Final file sizes and SHA256 values for this collection and its English reports |

Full 16 MiB REU images remain at their recorded `build/m3-perf/final-candidate/`
paths. The immutable full-suite source tree remains at
`build/m3-perf/final-v2/source/`. Private firmware/FAT inputs were reclaimed
after helper termination and ownership/hash/open-descriptor checks. Their
fingerprints and cleanup receipts remain; no firmware or backend executable
is redistributed here. The original ABI1 delivery and independent review
remain in their separate, unchanged directories.

## Recheck

The complete regression command and benchmark input/command paths are in the
report. Use a fresh output directory; runners refuse to replace prior evidence.
The full-suite normal native images are byte-identical to those measured here,
while wrapper/REU identities vary with manifest object paths.

From the repository root, verify this collection without executing a backend:

```sh
python3 - <<'PY'
from pathlib import Path
import hashlib, json
root = Path('docs/m3-perf-evidence')
manifest = json.loads((root / 'inventory.json').read_text())
for entry in manifest['files']:
    path = root / entry['path']
    assert path.stat().st_size == entry['bytes'], path
    assert hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256'], path
for path, expected in manifest['reports_sha256'].items():
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected, path
print('Frozen evidence and reports match')
PY
```

The original larger64 event remains unclassified: no raster witness was
recorded at the time. The old two-read classifier's wrap defects were reproduced
independently, but the two instrumented repeats observed no event and do not
explain the original one. The corrected coherent classifier passed 1,648 native
vectors and all six final normal runs. Historical invalid profiler intervals
and monitor-skew fairness readings remain referenced by the reports; they do
not contribute to accepted timing or establish a scheduler defect.

The implementation is frozen for the coordinator's independent review. M4
has not started; future OS modules beyond the retained numeric reserve remain
unsized.
