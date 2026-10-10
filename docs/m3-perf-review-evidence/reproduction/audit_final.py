#!/usr/bin/env python3
"""Independent review acceptance checks; runs only after both suites finish."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
REPO = Path('/Users/frenchfaso/Documents/Code/C64/C-OS')
BENCH = ROOT/'build/review-benchmarks'
FULL = ROOT/'build/m3-perf/full'

def read(path):
    return json.loads(path.read_text())

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

source = read(ROOT/'review-evidence/source-inventory.json')['source_sha256']
for rel, expected in source.items():
    assert sha(ROOT/rel) == expected, rel
    assert sha(REPO/rel) == expected, rel
for entry in read(ROOT/'review-evidence/external-inputs.json').values():
    assert sha(Path(entry['path'])) == entry['sha256'], entry['path']

full = read(FULL/'result.json')
assert full['status'] == 'pass' and full['sources_unchanged_during_run']
commands = read(FULL/'commands.json')
assert len(commands) == 50 and all(row['returncode'] == 0 for row in commands)
for row in commands:
    assert sha(FULL/row['log']) == row['log_sha256']
for rel, expected in full['result_files'].items():
    assert sha(FULL/'source'/rel) == expected, rel

summary = read(BENCH/'summary.json')
benchmarks = []
for workload, size, expected_frames in [('primary', 192, {128:95,64:257}),
                                      ('larger', 768, {128:382,64:1040})]:
    expected = (BENCH/(workload+'-expected.bin')).read_bytes()
    assert len(expected) == size
    control = [read(BENCH/f'{workload}-native-control-run{i}/result.json') for i in (1,2)]
    assert control[0]['native']['elapsed_phi2_ticks'] == control[1]['native']['elapsed_phi2_ticks']
    faster_native = control[0]['native']['elapsed_phi2_ticks']
    for line in (128,64):
        build = BENCH/f'{workload}-{line}'
        metadata = read(build/'map.json')
        manifest = read(build/'m3.manifest.json')
        assert sha(build/'native.bin') == metadata['artifact_sha256']['native.bin']
        assert (build/'native.bin').read_bytes() == (FULL/f'source/build/m3/{line}/native.bin').read_bytes()
        historical = REPO/f'build/m3-perf/final-candidate/{line if workload == "primary" else "larger-"+str(line)}'
        assert (build/'native.bin').read_bytes() == (historical/'native.bin').read_bytes()
        code = manifest['apps'][0]['code']
        packet = (build/'m3.reu').read_bytes()
        bytecode = packet[code['first']:code['last']+1]
        assert bytecode[:12] == bytes.fromhex('36 02 00 00 13 21 14 00 13 22 16 00')
        assert bytecode[-20:-8] == bytes.fromhex('36 02 00 00 13 21 18 00 13 22 1a 00')
        assert len(bytecode) == 232
        assert manifest['apps'][0]['data']['start'] % 128 == 0
        for repeat in range(1, 3 if line == 128 else 2):
            logical_name = f'{workload}-{line}-run{repeat}'
            path = BENCH/summary['accepted_paths'][logical_name]
            result = read(path/'result.json')
            cos = result['cos']
            assert cos['elapsed_frames'] == expected_frames[line]
            assert cos['scanout']['all_64000_pixels_and_both_output_rows_match']
            assert (path/'cos/image.bin').read_bytes() == expected
            assert (path/'native1mhz/image.bin').read_bytes() == expected
            report = bytes(cos['report'])
            for offset in (0x12,0x14,0x1a,0x1e):
                assert report[offset:offset+2] == b'\0\0', (path,offset)
            pcs = bytes(cos['pcbs'])
            contexts = [pcs[128*i:128*i+96] for i in range(4)]
            contexts[cos['active_slot']] = bytes(cos['active_state'])
            cache = bytes(cos['metadata'])
            valid_entries = 0
            for i in range(16):
                flags = cache[64+i]
                assert not flags & 16, (path,i,'PIN remains set')
                if not flags & 1:
                    continue
                owner = cache[48+i]
                assert owner == 0
                generation = cache[80+i] + 256*cache[96+i]
                assert generation == int.from_bytes(contexts[owner][91:93], 'little')
                valid_entries += 1
            ticks = cos['elapsed_phi2_ticks_estimate']
            assert ticks == 19656*cos['elapsed_frames']
            assert result['speedup_estimate'] == result['native']['elapsed_phi2_ticks']/ticks
            benchmarks.append(dict(name=path.name, frames=cos['elapsed_frames'],
                cos_phi2=ticks, original_native_phi2=result['native']['elapsed_phi2_ticks'],
                original_ratio=result['speedup_estimate'], original_lower=result['speedup_interval'][0],
                faster_native_phi2=faster_native, faster_native_ratio=faster_native/ticks,
                faster_native_lower=(faster_native-64)/(ticks+19656),
                retired=cos['retired'], valid_cache_entries=valid_entries,
                cache_counts=cos['cache_compact_counters_modulo_65536'],
                source_bytecode_bytes=len(bytecode), result_sha256=sha(path/'result.json')))
timer = read(ROOT/'build/review-profile-timer/result.json')
assert timer['status'] == 'pass' and timer['completed_calls'] == 65539
assert timer['observed_interval_wraps'] > 0
result = dict(format='COSM3PERFINDEPENDENTREVIEW1',status='pass',
    source_files_verified=len(source), external_inputs_verified=14,
    source_stable_after_review=True, full_suite_commands=len(commands),
    full_suite_results=len(full['result_files']), full_suite_result_sha256=sha(FULL/'result.json'),
    benchmarks=benchmarks, profile_timer_calls=timer['completed_calls'],
    profile_timer_wraps=timer['observed_interval_wraps'],
    history=read(ROOT/'review-evidence/historical-preservation.json'),
    hardware_qualified=False, periodic_monitor_enabled=False)
(ROOT/'review-evidence/verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
