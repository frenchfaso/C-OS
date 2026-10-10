#!/usr/bin/env python3
"""Verify that the current bootstrap rejects a correctly tagged frozen ABI1 pack."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

import m0
from m3_benchmark import Session

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(args):
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    result_path = out / 'result.json'
    result_path.unlink(missing_ok=True)
    old = args.old_build.resolve()
    old_map = json.loads((old / 'map.json').read_text())
    old_manifest = json.loads((old / 'm3.manifest.json').read_text())
    old_image = old / 'm3.reu'
    header = old_image.read_bytes()[:16]
    if (old_manifest['abi'] != 1 or header[12:14] != b'\x01\x00'
            or sha(old_image) != old_map['artifact_sha256']['m3.reu']):
        raise ValueError('The negative test requires the intact frozen ABI1 M3 pack')
    tag = int.from_bytes(header[8:12], 'little')
    if tag != old_manifest['build_tag'] or tag != old_map['build_tag']:
        raise ValueError('Frozen ABI1 pack tag mismatch')
    current = args.build.resolve()
    spec = json.loads((current / 'map.json').read_text())
    linked = json.loads((current / 'm3.manifest.json').read_text())
    if linked['abi'] != m0.APPLICATION_ABI or m0.APPLICATION_ABI != 2:
        raise ValueError('Current build must use ABI2')
    for name in ['m3.prg', 'm3.reu', 'm3.manifest.json', 'native.bin', 'renderer.prg']:
        if sha(current / name) != spec['artifact_sha256'][name]:
            raise ValueError('Current artifact differs from its map: ' + name)
    sources = out / 'sources'
    sources.mkdir(exist_ok=True)
    files = ['build_profile.inc', 'hardware.inc', 'm2_abi.inc', 'm3_boot.asm', 'probe.asm']
    source_hashes = {}
    for name in files:
        shutil.copyfile(ROOT / 'native' / name, sources / name)
        source_hashes[name] = sha(sources / name)
    rs = spec['renderer_symbols']
    (sources / 'renderer-addresses.inc').write_text(
        f'.const renderer_irq = ${rs["irq"]:04x}\n'
        f'.const renderer_nmi = ${rs["nmi"]:04x}\n'
        f'.const m2_kernel_start = ${spec["symbols"]["m3_kernel_entry"]:04x}\n')
    variables = dict(buildTag=tag, lineDelay=spec['line_delay'],
                     nativeBytes=(current / 'native.bin').stat().st_size,
                     renderBytes=(current / 'renderer.prg').stat().st_size - 2,
                     appCount=header[14], cacheLine=spec['cache_line_bytes'],
                     m2=1, m3=1, extendedDiagnostics=0, marginEnabled=0)
    image, origin, symbols = m0.assemble(args.java, args.kickass.resolve(),
                                        sources / 'm3_boot.asm', out, variables)
    if origin != 0x801:
        raise ValueError('Unexpected bootstrap origin')
    expected = image[symbols['expected_header'] - origin:
                     symbols['expected_header'] - origin + 16]
    if expected[:12] != header[:12] or expected[14:] != header[14:]:
        raise ValueError('Diagnostic loader does not pair exactly with the old tag/count')
    if expected[12:14] != b'\x02\x00':
        raise ValueError('Current loader does not check ABI2')
    # Reassemble the current loader with the old tag. The complete old pack is
    # untouched; every checked header field agrees except the application ABI.
    session = Session(args, out / 'backend', old_image)
    try:
        session.load(out / 'm3_boot.prg', 0x80d)
        session.command('wait 3000')
        report = session.read(0x300, 80)
        if report[:5] != b'M0R1\xe4':
            raise ValueError('Correctly tagged ABI1 pack was not rejected: ' + report.hex(' '))
        result = dict(format='COSABI2REJECTION1', status='pass',
                      expected_boot_error=0xe4, report=list(report),
                      frozen_abi1_pack=str(old_image), frozen_abi1_pack_sha256=sha(old_image),
                      old_build_tag=tag, current_build_tag=spec['build_tag'],
                      expected_header=list(expected), old_header=list(header),
                      only_differing_checked_header_field='Application ABI: 1 versus 2',
                      diagnostic_bootstrap_sha256=sha(out / 'm3_boot.prg'),
                      current_bootstrap_source_sha256=source_hashes,
                      input_sha256=session.input_sha256,
                      private_reu_sha256=session.private_image_sha256,
                      runner_sha256=sha(__file__),
                      qualification='Emulated bootstrap rejection before loading native runtime')
    finally:
        session.close()
    if source_hashes != {name: sha(ROOT / 'native' / name) for name in files}:
        raise ValueError('Bootstrap sources changed during ABI rejection test')
    result_path.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(status='pass', old_build_tag=tag, boot_error=0xe4)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['emulator', 'config', 'flash', 'settings', 'kickass', 'build', 'old-build', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--java', default='java')
    check(parser.parse_args())


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        print('check_abi2: ' + str(error), file=sys.stderr)
        sys.exit(1)
