#!/usr/bin/env python3
"""Resume review benchmarks serially, preserving the timed-out first attempt."""
from pathlib import Path
from fractions import Fraction
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from check_m3_perf import reclaim
OUT = ROOT/'build/review-benchmarks'
LOGS = OUT/'logs'
records = []

def run(name, argv, clean=None):
    args = list(map(str,argv))
    log = LOGS/(name+'.log')
    assert not log.exists(), log
    print(name,flush=True)
    with log.open('w') as stream:
        result = subprocess.run(args,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
    records.append(dict(name=name,command=args,returncode=result.returncode,
                        log=str(log),log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
    (OUT/'continuation-commands.json').write_text(json.dumps(records,indent=2)+'\n')
    if result.returncode:
        raise RuntimeError(f'{name}: see {log}')
    if clean:
        reclaim(clean,ROOT,records,OUT/'continuation-cleanup.json')

backend = ['--emulator','/Users/frenchfaso/Documents/Code/C64/UE2-C64U-Emulator/target/release/ue2emu',
           '--config','/Users/frenchfaso/Documents/Code/C64/runtime/c64u.toml',
           '--flash','/Users/frenchfaso/Documents/Code/C64/runtime/flash.bin',
           '--settings','/Users/frenchfaso/Documents/Code/C64/runtime/ultimate.cfg']
assembler = ['--kickass','/Users/frenchfaso/Documents/Code/C64/toolchain/kickassembler/KickAss.jar',
             '--java','/Library/Java/JavaVirtualMachines/temurin-25.jdk/Contents/Home/bin/java']
core = '/Users/frenchfaso/Documents/Code/C64/UE2-C64U-Emulator/vendor/trx64-core/src'
accepted = {f'primary-{line}-run{i}':f'primary-{line}-run{i}' for line in (128,64)
            for i in range(1,3 if line==128 else 2)}
accepted.update({f'primary-native-control-run{i}':f'primary-native-control-run{i}' for i in (1,2)})
for line in (128,64):
    build=OUT/f'larger-{line}'
    if line==64:
        run('larger-64-build',[sys.executable,'scripts/m3.py','--manifest',OUT/'larger.json',
            '--cache-line',line,'--out',build,'--skip-host-build']+assembler)
        run('larger-64-bounds',[sys.executable,'scripts/m2_bounds.py','--build',build,
            '--out',build/'bounds.json','--cpu-core',core])
    for i in range(1,3 if line==128 else 2):
        key=f'larger-{line}-run{i}'
        name=key+'-retry1' if line==128 and i==1 else key
        dest=OUT/name
        assert not dest.exists(),dest
        run(name,[sys.executable,'review-evidence/benchmark_transport.py','--build',build,'--out',dest,
            '--host-profile',OUT/'larger-host-profile.json','--application',ROOT/'apps/mandelbrot-32x24.casm',
            '--workload','larger']+backend+assembler,clean=dest)
        accepted[key]=name

original=(ROOT/'tests/native/mandelbrot_32x24_1mhz.asm').read_text()
primary=(OUT/'primary-native-control.asm').read_text()
body=primary[primary.index('\nmultiply:\n'):primary.index('\nprogram_end:\n')]
control=OUT/'larger-native-control.asm'
assert not control.exists()
control.write_text(original[:original.index('\nmultiply:\n')]+body+original[original.index('\nprogram_end:\n'):])
for i in (1,2):
    name=f'larger-native-control-run{i}'
    dest=OUT/name
    assert not dest.exists()
    run(name,[sys.executable,'review-evidence/benchmark_transport.py','--native-only','--native-source',control,
        '--build',OUT/'larger-128','--out',dest,'--host-profile',OUT/'larger-host-profile.json',
        '--application',ROOT/'apps/mandelbrot-32x24.casm','--workload','larger']+backend+assembler,clean=dest)
    accepted[name]=name

oracles={}
for workload,w,h,step in [('primary',16,12,64),('larger',32,24,32)]:
    expected=bytearray();iterations=negative=0
    for y in range(h):
        for x in range(w):
            cx,cy=Fraction(-512+step*x,256),Fraction(-384+step*y,256)
            zx=zy=Fraction(0);count=0
            while count<16:
                xx,yy=Fraction((zx*zx*256).__floor__(),256),Fraction((zy*zy*256).__floor__(),256)
                if xx+yy>=4:break
                xy=zx*zy*256
                negative+=int(xy<0 and xy.denominator!=1)
                zx,zy=xx-yy+cx,2*Fraction(xy.__floor__(),256)+cy
                count+=1
            iterations+=count;expected.append(count)
    assert bytes(expected)==(OUT/(workload+'-expected.bin')).read_bytes()
    oracles[workload]=dict(width=w,height=h,step=step,limit=16,iterations=iterations,
                          negative_fractional_products=negative,sha256=hashlib.sha256(expected).hexdigest())
    for key,path in accepted.items():
        if not key.startswith(workload+'-'):continue
        result=json.loads((OUT/path/'result.json').read_text())
        assert (OUT/path/'native1mhz/image.bin').read_bytes()==expected
        if result['cos']:assert (OUT/path/'cos/image.bin').read_bytes()==expected
primary=(OUT/'primary-expected.bin').read_bytes();larger=(OUT/'larger-expected.bin').read_bytes()
assert primary==bytes(larger[2*y*32+2*x] for y in range(12) for x in range(16))
(OUT/'summary.json').write_text(json.dumps(dict(accepted_paths=accepted,oracles=oracles,
    excluded_attempt='larger-128-run1: monitor socket timeout during wait 1000, no result',
    continuation='Fresh outputs; unchanged target timing, workload and artifacts; serial retry',
    transport_socket_timeout_seconds=300,
    transport_wrapper_sha256=hashlib.sha256((ROOT/'review-evidence/benchmark_transport.py').read_bytes()).hexdigest()),indent=2)+'\n')
print('All remaining benchmark runs passed',flush=True)
