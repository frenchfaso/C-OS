#!/usr/bin/env python3
"""Reproduce M3 autonomous correctness, memory gates and target workload time."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import m2

ROOT = Path(__file__).resolve().parents[1]


def run(arguments, output=None):
    command = [str(value) for value in arguments]
    print('+ ' + ' '.join(command), flush=True)
    if output is None:
        subprocess.run(command, cwd=ROOT, check=True)
    else:
        with Path(output).open('w') as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, check=True)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def sources():
    paths = [ROOT / name for name in ['Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml']]
    for directory in ['native', 'src', 'scripts', 'tests', 'apps', 'manifests', 'specs']:
        paths.extend(path for path in sorted((ROOT / directory).rglob('*'))
                     if path.is_file() and '__pycache__' not in path.parts)
    return {str(path.relative_to(ROOT)): digest(path) for path in paths}


def validate_build(destination, manifest):
    """Bind an existing pack to its actual files and current build inputs."""
    report = read(destination / 'map.json')
    normal = report['format'] == 'COSM3MAP1'
    names = m2.M3_FILES if normal else m2.NATIVE_FILES
    payload = b''.join((ROOT / 'native' / name).read_bytes() for name in names)
    payload += (ROOT / 'scripts/m2.py').read_bytes()
    config = read(ROOT / manifest)
    payload += json.dumps(config, sort_keys=True, separators=(',', ':')).encode()
    for app in config['apps']:
        payload += (ROOT / app['object']).read_bytes()
    payload += (f"line={report['cache_line_bytes']};delay={report['line_delay']};"
                f"margin={int(report['margin_hook_enabled'])};"
                f"milestone={'m3' if normal else 'm2'};"
                f"extended={int(report['extended_diagnostics'])}").encode()
    if normal:
        payload += (ROOT / 'scripts/m3.py').read_bytes()
    fingerprint = hashlib.sha256(payload).hexdigest()
    if fingerprint != report['source_sha256']:
        raise ValueError(f'{destination}: existing build inputs changed')
    if int.from_bytes(bytes.fromhex(fingerprint)[:4], 'little') != report['build_tag']:
        raise ValueError(f'{destination}: build tag differs from source fingerprint')
    for name, expected in report['artifact_sha256'].items():
        if digest(destination / name) != expected:
            raise ValueError(f'{destination}: changed artifact {name}')
    return fingerprint


def validate_m2_receipt(path):
    evidence = read(path)
    if evidence.get('format') != 'COSM2RESULT1' or evidence.get('status') != 'pass':
        raise ValueError('Reuse requires a successful complete M0–M2 receipt')
    for variant in evidence['variants']:
        destination = ROOT / 'build/m2' / str(variant['cache_line'])
        validate_build(destination, 'manifests/m1.json')
        for name, expected in variant['artifact_sha256'].items():
            if digest(destination / name) != expected:
                raise ValueError(f'M2 receipt no longer matches {destination / name}')
    if digest(ROOT / 'build/m2-fixtures.json') != evidence['fixtures_sha256']:
        raise ValueError('M2 fixture receipt no longer matches the current fixtures')
    return dict(path=str(path.resolve()), sha256=digest(path),
                reason='M3 scheduler-only correction; all M2 pack inputs and artifacts revalidated')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['emulator', 'config', 'flash', 'settings', 'kickass']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--java', default='java')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--reuse-m2-evidence', type=Path,
                        help='Reuse a complete passing M0–M2 receipt only if its build inputs and artifacts still match')
    args = parser.parse_args()
    python = sys.executable
    build = ROOT / 'build'
    out = build / 'm3'
    out.mkdir(parents=True, exist_ok=True)
    result_path = build / 'm3-results.json'
    result_path.unlink(missing_ok=True)
    backend = sum((['--' + name, getattr(args, name).resolve()]
                   for name in ['emulator', 'config', 'flash', 'settings']), [])
    assembler = ['--kickass', args.kickass.resolve(), '--java', args.java]
    offline = ['--offline'] if args.offline else []
    source_before = sources()
    input_paths = {name: getattr(args, name).resolve()
                   for name in ['emulator', 'config', 'flash', 'settings', 'kickass']}
    java_path = shutil.which(args.java)
    if java_path is None:
        raise ValueError(f'Java executable is unavailable: {args.java}')
    input_paths['java'] = Path(java_path).resolve()
    input_before = {name: dict(path=str(path), sha256=digest(path))
                    for name, path in input_paths.items()}
    reused_m2 = validate_m2_receipt(args.reuse_m2_evidence) if args.reuse_m2_evidence else None

    run(['cargo', 'build', '--locked', '--release', '--bins'] + offline)
    run([ROOT / 'target/release/cosasm', 'apps/mandelbrot.casm', '-o',
         build / 'mandelbrot.cobj'])
    run([python, 'scripts/mandelbrot_reference.py', '--out',
         build / 'mandelbrot-reference.bin'], build / 'mandelbrot-reference.json')
    run([ROOT / 'target/release/cospack', 'manifests/m3.json', '--root', ROOT,
         '--out', build / 'mandelbrot-host', '--build-tag', 3])
    run([ROOT / 'target/release/cosbench', build / 'mandelbrot-host.manifest.json',
         '--app', 'Mandelbrot', '--bytes', 192, '--out', build / 'mandelbrot-host.bin',
         '--expected', build / 'mandelbrot-reference.bin'],
        build / 'mandelbrot-host-profile.json')
    variants = []
    for line in [128, 64]:
        destination = out / str(line)
        command = [python, 'scripts/m3.py', '--manifest', 'manifests/m3.json',
                   '--cache-line', line, '--out', destination, '--skip-host-build'] + assembler
        run(command)
        names = ['m3.prg', 'm3.reu', 'm3.manifest.json', 'native.bin',
                 'renderer.prg', 'pattern.columns', 'map.json', 'map.txt']
        hashes = {name: digest(destination / name) for name in names}
        run(command)
        if hashes != {name: digest(destination / name) for name in names}:
            raise ValueError(f'Repeated normal M3 {line}-byte build changed an artifact')
        if read(destination / 'map.json')['numeric_target_shortfall']:
            raise ValueError('Normal M3 lost its future 4 KiB numeric reservation')
        run([python, 'scripts/m2_bounds.py', '--build', destination,
             '--out', destination / 'bounds.json'])
        variants.append(dict(cache_line=line, artifact_sha256=hashes))
    # Build M3 first: its artifact tests run in the cumulative M2 regression.
    if reused_m2 is None:
        run([python, 'scripts/check_m2.py'] + backend + assembler + offline)
    else:
        # Recheck host and M3 artifact assertions; the target M0–M2 receipt is
        # reused only for unchanged M2 binaries and source inputs.
        run(['cargo', 'fmt', '--all', '--', '--check'])
        run(['cargo', 'test', '--locked'] + offline)
        run(['cargo', 'clippy', '--locked'] + offline + ['--all-targets', '--', '-D', 'warnings'])
        run([python, '-m', 'unittest', 'discover', '-s', 'tests/native', '-v'])
    run([python, 'tests/native/check_cache_rollback.py'] + backend +
        ['--kickassembler', args.kickass.resolve(), '--java', args.java])
    contracts = []
    autonomous = []
    benchmarks = []
    for line in [128, 64]:
        contract_out = build / 'm3-contract' / str(line)
        run([python, 'scripts/m3_ue2.py', '--native-contract', '--cache-line', line,
             '--out', contract_out, '--timeout', 90] + backend + assembler)
        contracts.append(read(contract_out / 'result.json'))
        autonomous_out = build / 'm3-autonomous' / str(line)
        run([python, 'scripts/m3_ue2.py', '--suite', '--cache-line', line,
             '--out', autonomous_out, '--milliseconds', 24000, '--timeout', 90]
            + backend + assembler)
        autonomous.append(read(autonomous_out / 'result.json'))
        benchmark_out = out / 'benchmark' / str(line)
        run([python, 'scripts/m3_benchmark.py', '--build', out / str(line),
             '--out', benchmark_out] + backend + assembler)
        benchmarks.append(read(benchmark_out / 'result.json'))
    source_after = sources()
    if source_before != source_after:
        raise ValueError('Sources changed while the complete verification was running')
    for name, path in input_paths.items():
        if digest(path) != input_before[name]['sha256']:
            raise ValueError(f'External input changed during verification: {name}')
    for line in [128, 64]:
        validate_build(out / str(line), 'manifests/m3.json')
    evidence = dict(format='COSM3RESULT1', status='pass', reproducible=True,
                    qualification='Complete functional emulation; physical Ultimate timing pending',
                    m2=read(build / 'm2-results.json'), variants=variants,
                    bounds=[read(out / str(line) / 'bounds.json') for line in [128, 64]],
                    native_contracts=contracts, autonomous_suites=autonomous, benchmarks=benchmarks,
                    cache_rollback=[read(build / 'cache-rollback' / str(line) / profile / 'result.json')
                                    for line in [128, 64] for profile in ['extended', 'normal']],
                    host_profile=read(build / 'mandelbrot-host-profile.json'),
                    source_sha256=source_after, sources_unchanged_during_run=True,
                    external_inputs=input_before, reused_m2_evidence=reused_m2,
                    executed_entry_sha256=source_before['scripts/check_m3.py'],
                    verification_command=[sys.executable] + sys.argv,
                    host_tool_versions={name: subprocess.check_output([name, '--version'], text=True).strip()
                                        for name in ['cargo', 'rustc']})
    result_path.write_text(json.dumps(evidence, indent=2) + '\n')
    print(f'M3 complete functional verification passed: {result_path}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'check_m3: {error}', file=sys.stderr)
        raise SystemExit(1)
