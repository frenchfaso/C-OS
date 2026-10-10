#!/usr/bin/env python3
"""Verify the current ABI2 delivery in a private, fingerprinted source snapshot.

Preparation alone runs no emulator. The full run never reuses an ABI1 M2
receipt or writes the original repository's build outputs. Cargo's target
directory is shared to avoid duplicating its dependency artifacts.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ('native', 'src', 'scripts', 'tests', 'apps', 'manifests', 'specs')
METADATA = ('Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml', 'README.md')
HOST_BINS = ('cosasm', 'cosbench', 'cosdis', 'cosfixtures', 'cospack', 'cosrun')
M0_CASES = (
    ('pal64-reu16', []),
    ('reu128', ['--reu-size', '128 KB', '--expect-status', '0xe3']),
    ('reu512', ['--reu-size', '512 KB', '--expect-status', '0xe3']),
    ('reu2m', ['--reu-size', '2 MB', '--expect-status', '0xe3']),
    ('reu8m', ['--reu-size', '8 MB', '--expect-status', '0xe3']),
    ('reu-absent', ['--no-reu', '--expect-status', '0xe3']),
    ('turbo32', ['--manual-turbo', '32', '--expect-status', '0xe2', '--milliseconds', '6500']),
    ('turbo48', ['--manual-turbo', '48', '--expect-status', '0xe2', '--milliseconds', '6500']),
    ('ntsc', ['--ntsc', '--expect-status', '0xe1']),
    ('bad-pack', ['--bad-pack', '--expect-status', '0xe4']),
)


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def inventory(root):
    paths = [root / name for name in METADATA if (root / name).is_file()]
    for name in DIRECTORIES:
        paths.extend(path for path in sorted((root / name).rglob('*'))
                     if path.is_file() and '__pycache__' not in path.parts
                     and path.suffix != '.pyc')
    if any(path.is_symlink() for path in paths):
        raise ValueError('Source snapshots require regular files, without symlinks')
    return {str(path.relative_to(root)): sha(path) for path in paths}


def prepare(root, out, target):
    """Create a new snapshot only; never replace a prior run or evidence."""
    root, out, target = root.resolve(), out.resolve(), target.resolve()
    if not out.is_relative_to(root / 'build/m3-perf'):
        raise ValueError('Private output must be inside this repository\'s build/m3-perf')
    if out.exists():
        raise ValueError(f'Preserve existing evidence; choose a fresh --out: {out}')
    if target.is_relative_to(out) or not target.is_dir():
        raise ValueError('Cargo target must be an existing directory outside the private output')
    before = inventory(root)
    stage = out / 'source'
    stage.mkdir(parents=True)
    for name in before:
        destination = stage / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, destination)
    if before != inventory(stage) or before != inventory(root):
        raise ValueError('Source bytes changed while the private snapshot was copied')
    (stage / 'target').symlink_to(target, target_is_directory=True)
    result = dict(format='COSM3PERFPREPARE1', source_root=str(root), stage_root=str(stage),
                  cargo_target_dir=str(target), source_sha256=before,
                  runner_sha256=before['scripts/check_m3_perf.py'],
                  prepared_at=datetime.now(timezone.utc).isoformat(),
                  emulation_executed=False, canonical_build_outputs_copied=False)
    write(out / 'preparation.json', result)
    return result


def cleanup_candidates(directory):
    """Exact disposable backend inputs, excluding compiled packs and captures."""
    directory = directory.resolve()
    return sorted(path for path in directory.rglob('*') if path.is_file() and
                  (path.name == 'isolated-flash.bin' or
                   (path.parent.name == 'usb' and
                    path.name in ('diagnostic.reu', 'cache.reu', 'rollback.reu')) or
                   disposable_usb_clone(path)))


def disposable_usb_clone(path):
    """Recognize one backend-created image from its local ownership manifest.

    The firmware's FAT image is a sparse container, rather than a byte copy of
    its REU input. Preserve the ownership manifest, and journal the image hash
    before reclaiming it after the helper exits and lsof reports no descriptor.
    """
    if (not re.fullmatch(r'image-[0-9]+\.img', path.name) or
            not re.fullmatch(r'usb-[0-9a-f]+', path.parent.name) or
            path.parents[1].name != 'usb-dir' or path.parents[2].name != 'run'):
        return False
    manifest = path.parent / 'manifest.json'
    if manifest.is_symlink() or not manifest.is_file():
        return False
    try:
        value = read(manifest)
        return (value['version'] == 1 and value['image'] == path.name and
                Path(value['host_root']).resolve() == path.parents[3] / 'usb' and
                value['label'] == 'USB' and value['size'] == path.stat().st_size and
                not value['skipped'] and
                set(value['entries']) <= {'diagnostic.reu', 'cache.reu', 'rollback.reu'} and
                all(not entry['dir'] for entry in value['entries'].values()))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def reclaim(directory, stage, commands, journal):
    """Reclaim owned input copies only after helper exit and an open-file check."""
    directory, stage = directory.resolve(), stage.resolve()
    if not directory.is_relative_to(stage / 'build'):
        raise ValueError('Cleanup is confined to this private stage\'s build directory')
    if not commands or commands[-1]['returncode'] != 0:
        raise ValueError('Cleanup requires a completed successful helper process')
    candidates = cleanup_candidates(directory)
    if not candidates:
        return
    lsof = shutil.which('lsof')
    if lsof is None:
        raise ValueError('lsof is required before reclaiming private backend inputs')
    stats = {}
    for path in candidates:
        if path.is_symlink() or path.resolve() != path or not path.is_relative_to(directory):
            raise ValueError(f'Unsafe private input path: {path}')
        stat = path.stat()
        if stat.st_nlink != 1 or stat.st_uid != os.getuid():
            raise ValueError(f'Private input is shared or owned by another user: {path}')
        stats[path] = stat
    opened = subprocess.run([lsof, '-t', '--', *map(str, candidates)],
                            text=True, capture_output=True, check=False)
    if opened.returncode not in (0, 1) or opened.stdout.strip():
        raise ValueError('Private backend input is still open, or lsof failed; retain it')
    entries = []
    for path in candidates:
        stat = stats[path]
        value = dict(path=str(path.relative_to(stage)), sha256=sha(path), bytes=stat.st_size,
                     completed_helper=commands[-1]['name'], open_file_check='lsof: no open descriptors')
        now = path.stat()
        if (now.st_ino, now.st_size, now.st_mtime_ns, now.st_nlink) != (
                stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_nlink):
            raise ValueError('Private input changed during cleanup validation')
        entries.append(value)
    # Persist the exact checked allowlist before unlinking. Other files, including
    # firmware-created run/usb-dir clones, remain available for inspection.
    previous = read(journal) if journal.exists() else []
    write(journal, previous + entries)
    for path in candidates:
        path.unlink()


class Receipt:
    def __init__(self, out, environment):
        self.out = out
        self.environment = environment
        self.commands = []
        (out / 'logs').mkdir(parents=True, exist_ok=True)

    def run(self, name, command, clean=None, output=None):
        arguments = list(map(str, command))
        print('+ ' + ' '.join(arguments), flush=True)
        log = self.out / 'logs' / (name + '.log')
        started = datetime.now(timezone.utc).isoformat()
        with log.open('w') as stream:
            process = subprocess.run(arguments, cwd=ROOT, env=self.environment,
                                     stdout=stream, stderr=subprocess.STDOUT, check=False)
        row = dict(name=name, command=arguments, cwd=str(ROOT), started_at=started,
                   finished_at=datetime.now(timezone.utc).isoformat(),
                   returncode=process.returncode, log=str(log.relative_to(self.out)), log_sha256=sha(log))
        self.commands.append(row)
        write(self.out / 'commands.json', self.commands)
        if process.returncode:
            raise ValueError(f'{name} failed ({process.returncode}); inspect {log}')
        if output is not None:
            shutil.copyfile(log, output)
        if clean is not None:
            reclaim(clean, ROOT, self.commands, self.out / 'cleanup.json')
        return row


def external_inputs(args):
    paths = {name: getattr(args, name).resolve()
             for name in ('emulator', 'config', 'flash', 'settings', 'kickass')}
    for name in ('java', 'cargo', 'rustc', 'lsof'):
        executable = shutil.which(args.java if name == 'java' else name)
        if executable is None:
            raise ValueError('Missing executable: ' + name)
        paths[name] = Path(executable).resolve()
    paths['python'] = Path(sys.executable).resolve()
    for name in ('tables.rs', 'cpu.rs'):
        paths['cpu_core_' + name] = args.cpu_core.resolve() / name
    for name in ('cargo', 'rustc'):
        actual = subprocess.check_output(['rustup', 'which', name], text=True).strip()
        paths[name + '_toolchain'] = Path(actual).resolve()
    return {name: dict(path=str(path), sha256=sha(path)) for name, path in paths.items()}


def full_run(args):
    out = ROOT.parent
    prepared = read(out / 'preparation.json')
    if prepared['stage_root'] != str(ROOT) or inventory(ROOT) != prepared['source_sha256']:
        raise ValueError('Staged sources differ from their preparation receipt')
    environment = dict(os.environ, CARGO_TARGET_DIR=prepared['cargo_target_dir'])
    receipt = Receipt(out, environment)
    inputs = external_inputs(args)
    write(out / 'external-inputs.json', inputs)
    build = ROOT / 'build'
    build.mkdir(exist_ok=True)
    python = sys.executable
    tools = ROOT / 'target/release'
    backend = sum((['--' + name, getattr(args, name).resolve()]
                   for name in ('emulator', 'config', 'flash', 'settings')), [])
    assembler = ['--kickass', args.kickass.resolve(), '--java', args.java]
    offline = ['--offline'] if args.offline else []
    receipt.run('host-fmt', ['cargo', 'fmt', '--all', '--', '--check'])
    receipt.run('host-test', ['cargo', 'test', '--locked'] + offline)
    passed = sum(int(value) for value in re.findall(r'test result: ok\. (\d+) passed;',
                 (out / 'logs/host-test.log').read_text()))
    if passed != 62:
        raise ValueError(f'Expected 62 current Rust tests, got {passed}')
    receipt.run('host-clippy', ['cargo', 'clippy', '--locked'] + offline +
                ['--all-targets', '--', '-D', 'warnings'])
    receipt.run('host-release', ['cargo', 'build', '--locked', '--release', '--bins'] + offline)
    host = dict(tests_passed=passed, abi=2, fmt=True, clippy_warnings=0,
                tool_versions={name: subprocess.check_output([name, '--version'], text=True).strip()
                               for name in ('cargo', 'rustc')},
                binaries={name: sha(tools / name) for name in HOST_BINS})
    write(out / 'host-receipts.json', dict(host, commands=receipt.commands.copy()))
    receipt.run('m1', [python, 'scripts/check_m1.py'] + offline)
    receipt.run('m0-build', [python, 'scripts/m0.py'] + assembler)
    receipt.run('workload-object', [tools / 'cosasm', 'apps/mandelbrot.casm', '-o', build / 'mandelbrot.cobj'])
    variants = []
    for milestone, manifest in (('m3', 'manifests/m3.json'), ('m2', 'manifests/m1.json')):
        for line in (128, 64):
            destination = build / milestone / str(line)
            command = [python, f'scripts/{milestone}.py', '--manifest', manifest,
                       '--cache-line', line, '--out', destination, '--skip-host-build'] + assembler
            receipt.run(f'{milestone}-{line}-build', command)
            names = [f'{milestone}.prg', f'{milestone}.reu', f'{milestone}.manifest.json',
                     'native.bin', 'renderer.prg', 'pattern.columns', 'map.json', 'map.txt']
            first = {name: sha(destination / name) for name in names}
            receipt.run(f'{milestone}-{line}-repeat', command)
            if first != {name: sha(destination / name) for name in names}:
                raise ValueError(f'{milestone}/{line}: repeat artifacts differ')
            report = read(destination / 'map.json')
            if read(destination / f'{milestone}.manifest.json')['abi'] != 2:
                raise ValueError('A current pack unexpectedly uses an older ABI')
            if milestone == 'm3' and report['numeric_target_shortfall']:
                raise ValueError('Normal M3 lost its 4 KiB numeric reservation')
            receipt.run(f'{milestone}-{line}-bounds', [python, 'scripts/m2_bounds.py',
                        '--build', destination, '--out', destination / 'bounds.json',
                        '--cpu-core', args.cpu_core.resolve()])
            variants.append(dict(milestone=milestone, cache_line=line, artifact_sha256=first))
    fixtures = build / 'm2-fixtures.json'
    receipt.run('fixtures', [tools / 'cosfixtures', fixtures, '--manifest', build / 'm1.manifest.json'])
    cases = read(fixtures)['cases']
    if len(cases) != 654:
        raise ValueError(f'Expected the entire 654-case ABI2 corpus, got {len(cases)}')
    receipt.run('python-tests', [python, '-m', 'unittest', 'discover', '-s', 'tests/native', '-v'])
    m0_suite = []
    for name, flags in M0_CASES:
        destination = build / 'm0/ue2' / name
        receipt.run('m0-' + name, [python, 'scripts/m0_ue2.py', '--out', destination] + backend + flags,
                    clean=destination)
        result = read(destination / 'result.json')
        m0_suite.append(dict(case=name, result=str((destination / 'result.json').relative_to(ROOT)),
                             result_sha256=sha(destination / 'result.json'), status=result['actual_status']))
    write(build / 'm0/ue2/suite.json', m0_suite)
    receipt.run('cache-cancel', [python, 'tests/native/check_cache_cancel.py'] + backend +
                ['--kickassembler', args.kickass.resolve(), '--java', args.java], clean=build / 'cache-cancel')
    rollback = []
    for line in (128, 64):
        for profile in ('extended', 'normal'):
            destination = build / 'cache-rollback' / str(line) / profile
            receipt.run(f'rollback-{line}-{profile}', [python, 'tests/native/check_cache_rollback.py'] +
                        backend + ['--kickassembler', args.kickass.resolve(), '--java', args.java,
                                   '--lines', line, '--profiles', profile, '--keep-inputs'], clean=destination)
            result = read(destination / 'result.json')
            if result['status'] != 'pass' or result['scenarios'] != 128 or result['failures']:
                raise ValueError('Physical rollback scenarios failed')
            rollback.append(str((destination / 'result.json').relative_to(ROOT)))
    receipt.run('margins', [python, 'scripts/m2_margins.py'] + backend + assembler,
                clean=build / 'm2/margins')
    native, contracts, autonomous, admission, hot_pc, raster_active = [], [], [], [], [], []
    admission_cases = 0
    hot_pc_cases = 0
    raster_active_cases = 0
    for line in (128, 64):
        normal_build = build / 'm3' / str(line)
        normal_symbols = read(normal_build / 'map.json')['symbols']
        destination = build / 'm3-admission' / str(line)
        receipt.run(f'm3-{line}-admission', [python, 'scripts/check_m3_admission.py'] + backend +
                    assembler + ['--build', build / 'm3' / str(line), '--out', destination],
                    clean=destination)
        result = read(destination / 'result.json')
        expected_cases = 1648 if 'm3_vm_raster_admit' in normal_symbols else 824
        if result['status'] != 'pass' or result['native_cases'] != expected_cases or result['failures']:
            raise ValueError('Native coherent admission vectors failed')
        admission_cases += result['native_cases']
        admission.append(str((destination / 'result.json').relative_to(ROOT)))
        if 'm3_vm_raster_admit' in normal_symbols:
            destination = build / 'm3-raster-active' / str(line)
            receipt.run(f'm3-{line}-raster-active', [python, 'scripts/check_m3_raster_active.py'] +
                        backend + assembler + ['--build', normal_build, '--out', destination],
                        clean=destination)
            result = read(destination / 'result.json')
            if result['status'] != 'pass' or result['native_cases'] != 824 or result['failures']:
                raise ValueError('Native coherent active-raster reporting vectors failed')
            raster_active_cases += result['native_cases']
            raster_active.append(str((destination / 'result.json').relative_to(ROOT)))
        if 'vm_step_valid_pc' in normal_symbols:
            destination = build / 'm3-hot-pc' / str(line)
            receipt.run(f'm3-{line}-hot-pc', [python, 'scripts/check_m3_hot_pc.py'] + backend +
                        assembler + ['--build', normal_build, '--out', destination], clean=destination)
            result = read(destination / 'result.json')
            if result['status'] != 'pass' or result['cases'] != 74 or result['failures']:
                raise ValueError('Native current-PC invariant vectors failed')
            hot_pc_cases += result['cases']
            hot_pc.append(str((destination / 'result.json').relative_to(ROOT)))
        destination = build / 'm2/ue2' / str(line)
        receipt.run(f'm2-{line}-differential', [python, 'scripts/m2_ue2.py'] + backend +
                    ['--build', build / 'm2' / str(line), '--out', destination, '--fixtures', fixtures],
                    clean=destination)
        result = read(destination / 'result.json')
        if result['cases'] != 654:
            raise ValueError('Native differential did not execute the complete ABI2 corpus')
        native.append(str((destination / 'result.json').relative_to(ROOT)))
        destination = build / 'm3-contract' / str(line)
        receipt.run(f'm3-{line}-contract', [python, 'scripts/m3_ue2.py', '--native-contract',
                    '--cache-line', line, '--out', destination, '--timeout', 90] + backend + assembler,
                    clean=destination)
        result = read(destination / 'result.json')
        if result['native_assertions'] != 126:
            raise ValueError('Native M3 contract assertion count changed')
        contracts.append(str((destination / 'result.json').relative_to(ROOT)))
        destination = build / 'm3-autonomous' / str(line)
        receipt.run(f'm3-{line}-autonomous', [python, 'scripts/m3_ue2.py', '--suite',
                    '--cache-line', line, '--out', destination, '--milliseconds', 24000,
                    '--timeout', 90] + backend + assembler, clean=destination)
        if len(read(destination / 'result.json')['cases']) != 3:
            raise ValueError('Autonomous M3 suite omitted a pack')
        autonomous.append(str((destination / 'result.json').relative_to(ROOT)))
    destination = build / 'abi2-rejection'
    receipt.run('abi2-rejection', [python, 'scripts/check_abi2.py'] + backend + assembler +
                ['--build', build / 'm3/128', '--old-build', args.old_build.resolve(), '--out', destination],
                clean=destination)
    if inventory(ROOT) != prepared['source_sha256'] or external_inputs(args) != inputs:
        raise ValueError('Frozen source or external tool/input changed during verification')
    if inventory(Path(prepared['source_root'])) != prepared['source_sha256']:
        raise ValueError('Original current sources changed after the private snapshot was prepared')
    if host['binaries'] != {name: sha(tools / name) for name in HOST_BINS}:
        raise ValueError('Shared host executable changed during verification')
    results = sorted(path for path in build.rglob('*.json') if path.name in ('result.json', 'bounds.json', 'm1-results.json'))
    evidence = dict(format='COSM3PERFRESULT1', status='pass', application_abi=2,
                    qualification='Functional emulation; physical Ultimate timing pending',
                    source_sha256=prepared['source_sha256'], sources_unchanged_during_run=True,
                    external_inputs=inputs, host=host, variants=variants,
                    differential_cases_per_profile=654, fixtures_sha256=sha(fixtures),
                    physical_rollback_scenarios=512, native_m3_assertions=252,
                    native_coherent_admission_cases=admission_cases, admission=admission,
                    native_current_pc_invariant_cases=hot_pc_cases, hot_pc=hot_pc,
                    native_active_raster_reporting_cases=raster_active_cases,
                    raster_active=raster_active,
                    autonomous_packs=6, m0_suite=m0_suite, native=native, contracts=contracts,
                    autonomous=autonomous, rollback=rollback,
                    abi2_rejection=str((destination / 'result.json').relative_to(ROOT)),
                    result_files={str(path.relative_to(ROOT)): sha(path) for path in results},
                    commands_sha256=sha(out / 'commands.json'), cleanup_sha256=sha(out / 'cleanup.json'),
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    benchmark_scope='Separate final workload timing evidence; this runner verifies regressions')
    write(out / 'result.json', evidence)
    print('ABI2 complete functional regression passed: ' + str(out / 'result.json'), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('emulator', 'config', 'flash', 'settings', 'kickass'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--java', default='java')
    parser.add_argument('--old-build', type=Path, required=True,
                        help='Intact original ABI1 build, normally absolute build/m3/128')
    parser.add_argument('--out', type=Path, default=ROOT / 'build/m3-perf/final')
    parser.add_argument('--cargo-target-dir', type=Path, default=ROOT / 'target')
    parser.add_argument('--cpu-core', type=Path,
                        help='trx64-core src directory; default inferred from the backend executable')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--execute-staged', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.cpu_core is None:
        args.cpu_core = args.emulator.resolve().parents[2] / 'vendor/trx64-core/src'
    if args.execute_staged:
        full_run(args)
        return
    prepared = prepare(ROOT, args.out, args.cargo_target_dir)
    if args.prepare_only:
        print('Private source snapshot prepared; no emulator executed: ' + str(args.out.resolve()))
        return
    command = [sys.executable, Path(prepared['stage_root']) / 'scripts/check_m3_perf.py', '--execute-staged']
    for name in ('emulator', 'config', 'flash', 'settings', 'kickass', 'old_build', 'cpu_core'):
        command += ['--' + name.replace('_', '-'), getattr(args, name).resolve()]
    command += ['--java', args.java]
    if args.offline:
        command.append('--offline')
    subprocess.run(list(map(str, command)), check=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print('check_m3_perf: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
