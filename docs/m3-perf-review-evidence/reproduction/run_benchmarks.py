#!/usr/bin/env python3
"""Independent review runs, including a separately labelled native control."""
from pathlib import Path
from fractions import Fraction
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from check_m3_perf import reclaim

OUT = ROOT / 'build/review-benchmarks'
OUT.mkdir(parents=True, exist_ok=False)
LOGS = OUT / 'logs'
LOGS.mkdir()
records = []

def run(name, argv, clean=None):
    args = list(map(str, argv))
    print(name, flush=True)
    log = LOGS / (name + '.log')
    with log.open('w') as stream:
        result = subprocess.run(args, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    records.append(dict(name=name, command=args, returncode=result.returncode,
                        log=str(log), log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
    (OUT / 'commands.json').write_text(json.dumps(records, indent=2) + '\n')
    if result.returncode:
        raise RuntimeError(f'{name}: see {log}')
    if clean:
        reclaim(clean, ROOT, records, OUT / 'cleanup.json')

backend = ['--emulator', '/Users/frenchfaso/Documents/Code/C64/UE2-C64U-Emulator/target/release/ue2emu',
           '--config', '/Users/frenchfaso/Documents/Code/C64/runtime/c64u.toml',
           '--flash', '/Users/frenchfaso/Documents/Code/C64/runtime/flash.bin',
           '--settings', '/Users/frenchfaso/Documents/Code/C64/runtime/ultimate.cfg']
assembler = ['--kickass', '/Users/frenchfaso/Documents/Code/C64/toolchain/kickassembler/KickAss.jar',
             '--java', '/Library/Java/JavaVirtualMachines/temurin-25.jdk/Contents/Home/bin/java']
core = '/Users/frenchfaso/Documents/Code/C64/UE2-C64U-Emulator/vendor/trx64-core/src'
summaries = []
oracles = {}

for workload, width, height, step in [('primary', 16, 12, 64), ('larger', 32, 24, 32)]:
    expected = bytearray()
    iterations = negative_fractional = 0
    for y in range(height):
        cy = Fraction(-384 + step*y, 256)
        for x in range(width):
            cx = Fraction(-512 + step*x, 256)
            zx = zy = Fraction(0)
            count = 0
            while count < 16:
                xx = Fraction((zx*zx*256).__floor__(), 256)
                yy = Fraction((zy*zy*256).__floor__(), 256)
                if xx + yy >= 4:
                    break
                xy = zx*zy*256
                negative_fractional += int(xy < 0 and xy.denominator != 1)
                zx, zy = xx - yy + cx, 2*Fraction(xy.__floor__(), 256) + cy
                count += 1
            iterations += count
            expected.append(count)
    expected_path = OUT / (workload + '-expected.bin')
    expected_path.write_bytes(expected)
    oracles[workload] = dict(width=width, height=height, step=step, limit=16,
                            iterations=iterations, negative_fractional_products=negative_fractional,
                            sha256=hashlib.sha256(expected).hexdigest())
    app = ROOT / 'apps' / ('mandelbrot.casm' if workload == 'primary' else 'mandelbrot-32x24.casm')
    obj = OUT / (workload + '.cobj')
    run(workload+'-object', [ROOT/'target/release/cosasm', app, '-o', obj])
    manifest = json.loads((ROOT/'manifests/m3.json').read_text())
    manifest['apps'][0]['object'] = str(obj.relative_to(ROOT))
    manifest_path = OUT / (workload+'.json')
    manifest_path.write_text(json.dumps(manifest, indent=2)+'\n')
    profile = OUT / (workload+'-host-profile.json')
    for line in (128, 64):
        build = OUT / f'{workload}-{line}'
        run(f'{workload}-{line}-build', [sys.executable, 'scripts/m3.py', '--manifest', manifest_path,
            '--cache-line', line, '--out', build, '--skip-host-build'] + assembler)
        run(f'{workload}-{line}-bounds', [sys.executable, 'scripts/m2_bounds.py', '--build', build,
            '--out', build/'bounds.json', '--cpu-core', core])
        if line == 128:
            run(workload+'-host', [ROOT/'target/release/cosbench', build/'m3.manifest.json',
                '--app', 'Mandelbrot', '--bytes', width*height, '--out', OUT/(workload+'-host.bin'),
                '--expected', expected_path])
            profile.write_bytes((LOGS/(workload+'-host.log')).read_bytes())
        for repeat in range(2 if line == 128 else 1):
            name = f'{workload}-{line}-run{repeat+1}'
            dest = OUT / name
            run(name, [sys.executable, 'scripts/m3_benchmark.py', '--build', build, '--out', dest,
                '--host-profile', profile, '--application', app, '--workload', workload] + backend + assembler,
                clean=dest)
            d = json.loads((dest/'result.json').read_text())
            assert (dest/'cos/image.bin').read_bytes() == expected
            assert (dest/'native1mhz/image.bin').read_bytes() == expected
            summaries.append(dict(name=name, frames=d['cos']['elapsed_frames'],
                native_phi2=d['native']['elapsed_phi2_ticks'], cos_phi2=d['cos']['elapsed_phi2_ticks_estimate'],
                ratio=d['speedup_estimate'], lower=d['speedup_interval'][0],
                retired=d['cos']['retired'], fills=d['cos']['cache_compact_counters_modulo_65536']))

    original = ROOT/'tests/native'/('mandelbrot_1mhz.asm' if workload == 'primary' else 'mandelbrot_32x24_1mhz.asm')
    source = original.read_text()
    start, end = source.index('\nmultiply:\n'), source.index('\nprogram_end:\n')
    replacement = '''
multiply:
    // Review control: same general combined product algorithm as ABI2 MULS.
    // Original inputs remain intact; caller still reads full product bytes1/2.
    lda right
    sta product
    lda right+1
    sta product+1
    lda #0
    sta product+2
    sta product+3
    ldx #16
review_multiply_bit:
    lda product
    lsr
    bcc review_multiply_shift
    clc
    lda product+2
    adc left
    sta product+2
    lda product+3
    adc left+1
    sta product+3
review_multiply_shift:
    ror product+3
    ror product+2
    ror product+1
    ror product
    dex
    bne review_multiply_bit
    lda left+1
    bpl review_multiply_right_sign
    sec
    lda product+2
    sbc right
    sta product+2
    lda product+3
    sbc right+1
    sta product+3
review_multiply_right_sign:
    lda right+1
    bpl review_multiply_done
    sec
    lda product+2
    sbc left
    sta product+2
    lda product+3
    sbc left+1
    sta product+3
review_multiply_done:
    rts
'''
    control = OUT / (workload+'-native-control.asm')
    control.write_text(source[:start]+replacement+source[end:])
    assert control.read_text().split('\nmultiply:\n')[0] == source[:start]
    assert control.read_text().split('\nprogram_end:\n')[1] == source[end+len('\nprogram_end:\n'):]
    for repeat in range(2):
        name = f'{workload}-native-control-run{repeat+1}'
        dest = OUT/name
        run(name, [sys.executable, 'scripts/m3_benchmark.py', '--native-only', '--native-source', control,
            '--build', OUT/(workload+'-128'), '--out', dest, '--host-profile', profile,
            '--application', app, '--workload', workload] + backend + assembler, clean=dest)
        d = json.loads((dest/'result.json').read_text())
        assert (dest/'native1mhz/image.bin').read_bytes() == expected
        summaries.append(dict(name=name, native_phi2=d['native']['elapsed_phi2_ticks'],
                              source_sha256=d['native']['source_sha256']))

primary = (OUT/'primary-expected.bin').read_bytes()
larger = (OUT/'larger-expected.bin').read_bytes()
assert primary == bytes(larger[y*2*32+x*2] for y in range(12) for x in range(16))
(OUT/'summary.json').write_text(json.dumps(dict(oracles=oracles, runs=summaries), indent=2)+'\n')
print(json.dumps(summaries, indent=2), flush=True)
