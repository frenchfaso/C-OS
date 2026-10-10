#!/usr/bin/env python3
"""Compare actual native vm_run with full vm_step at protection boundaries.

A trusted private harness supplies complete contexts and coherent cache lines
to the frozen resident binary. No resident byte is patched. The fixture tests
VM semantics; video deadlines and complete workloads are qualified separately.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import m0
import m2_bounds
from m2_compare import describe
from m3_benchmark import Session

ROOT = Path(__file__).resolve().parents[1]
BASE = 0x040000
NOP = bytes((0, 0, 0, 0))


def sha(value):
    return hashlib.sha256(value).hexdigest()


def put(state, offset, value, width):
    state[offset:offset + width] = value.to_bytes(width, 'little')


def context(code, fuel=8, base=BASE, pc=None, generation=1):
    state = bytearray(96)
    for index, value in enumerate((17, 35, 0x8000, 0xffff, 0x1234, 0xabcd, 3, 0x55aa)):
        put(state, index * 2, value, 2)
    for index in range(4):
        put(state, 16 + index * 3, BASE + 0x800 + index * 3, 3)
    put(state, 28, base if pc is None else pc, 3)
    put(state, 31, BASE + 0x3fff, 3)
    state[34] = fuel
    put(state, 43, 0x1234, 2)
    for offset, first, last in ((45, min(base, BASE), max(base + len(code) - 1, BASE + 0x3fff)),
                                (51, base, base + len(code) - 1),
                                (57, BASE + 0x100, BASE + 0x3bff),
                                (63, BASE + 0x3c00, BASE + 0x3fff)):
        put(state, offset, first, 3)
        put(state, offset + 3, min(last, 0xffffff), 3)
    put(state, 91, generation, 2)
    return state


def cases(line):
    result = []

    def add(name, code, expected, *, initial=None, **options):
        result.append(dict(name=name, code=list(code), initial=list(initial or context(code)),
                           expected=expected, **options))

    for fuel in (0, 1, 2, 3, 4, 5, 8, 16, 127, 128):
        # JMP back to a known valid first PC prevents fall-through from
        # becoming the stopping condition even for a long quantum.
        code = NOP * 3 + bytes((0x20, 0, 0, 4))
        add(f'fuel-{fuel}', code, dict(outcome=1, fuel=0, retired=fuel),
            initial=context(code, fuel=fuel))
    for position in range(6):
        prefix = bytes((3, 0x10, 0, 0)) * position  # ADD R0,R1
        for kind, word, outcome, fault, retired in (
                ('yield', bytes((0x37, 0, 0, 0)), 3, 0, position + 1),
                ('trap', bytes((0x38, 0, 0xcd, 0xab)), 5, 9, position + 1),
                ('syscall', bytes((0x36, 1, 0, 0)), 4, 0, position + 1),
                ('malformed', bytes((0xff, 0, 0, 0)), 5, 1, position)):
            code = prefix + word + NOP
            expected = dict(outcome=outcome, retired=retired, r0=17 + 35 * position)
            if fault:
                expected['fault'] = fault
            add(f'{kind}-position-{position}', code, expected)
    for offset in (-4, 1, 2, 3, 16):
        code = NOP * 4
        add(f'invalid-initial-pc-{offset}', code, dict(outcome=5, fault=2, retired=0, fuel=8),
            initial=context(code, pc=BASE + offset))
    for name, code in (('invalid-fallthrough', bytes((2, 0, 0xcd, 0xab))),
                       ('invalid-jump-alignment', bytes((0x20, 1, 0, 4)) + NOP),
                       ('invalid-jump-range', bytes((0x20, 0, 1, 4)) + NOP)):
        add(name, code, dict(outcome=5, fault=2, retired=0, fuel=8, r0=17))
    add('exit-invalid-fallthrough', bytes((0x36, 0, 0, 0)),
        dict(outcome=4, retired=1, fuel=7, pc=BASE, pending=1))
    for target, name, expected in ((BASE + 1, 'invalid-ret-target', dict(outcome=5, fault=2, retired=0)),
                                   (BASE + 8, 'valid-ret-target', dict(outcome=3, retired=2, pc=BASE + 12))):
        code = bytes((0x22, 0, 0, 0)) + NOP + bytes((0x37, 0, 0, 0)) + NOP
        initial = context(code)
        put(initial, 31, BASE + 0x3ffc, 3)
        add(name, code, expected, initial=initial, data_address=BASE + 0x3ffd,
            data=list(target.to_bytes(3, 'little')))
    code = NOP * (line // 4 + 2)
    add('code-miss-after-one-run', code, dict(outcome=2, retired=1, fuel=7, pc=BASE + line),
        initial=context(code, pc=BASE + line - 4), cached_lines=1)
    for slot in (0, 1, 2, 3):
        add(f'owner-{slot}-warm', NOP * 3, dict(outcome=1, retired=1, fuel=0),
            initial=context(NOP * 3, fuel=1), slot=slot)
        add(f'owner-{slot}-stale-generation', NOP * 3, dict(outcome=2, retired=0, fuel=8),
            initial=context(NOP * 3, generation=2), slot=slot, cache_generation=1)
        imported = context(NOP * 3, pc=BASE + 1, generation=2)
        add(f'owner-{slot}-import-invalid-after-reuse', NOP * 3,
            dict(outcome=5, fault=2, retired=0, fuel=8), initial=imported, slot=slot, imported=True)
    for fuel in (0, 1, 8):
        add(f'pending-nmi-fuel-{fuel}', NOP * 3,
            dict(outcome=1 if fuel == 0 else 7, retired=0, fuel=fuel),
            initial=context(NOP * 3, fuel=fuel), nmi=1)
    for name, outcome, pending in (('fault-retained', 5, 0), ('stopped-retained', 6, 0),
                                   ('pending-syscall-retained', 0, 1)):
        initial = context(NOP * 3, pc=BASE + 1)
        initial[69], initial[90] = outcome, pending
        add(name, NOP * 3, dict(outcome=4 if pending else outcome, retired=0, fuel=8), initial=initial)
    add('scheduler-native-job-single-op', NOP * 4, dict(outcome=0, retired=1, fuel=7, pc=BASE + 4),
        scheduler_job=True, single_reference=True)
    # Independent absolute u24 range/alignment/overflow outcomes, so a defect
    # shared by both entrypoints cannot pass merely through equality.
    for base in (0x000000, 0x0000fc, 0x000100, 0x00fffc, 0x010000,
                 0x7ffffc, 0x800000, 0xfffff8):
        code = NOP * 2 + bytes((0x37, 0, 0, 0)) + NOP
        if base + len(code) > 1 << 24:
            code = NOP * 2
            initial = context(code, fuel=1, base=base)
            expected = dict(outcome=1, retired=1, fuel=0)
        else:
            initial = context(code, base=base)
            expected = dict(outcome=3, retired=3, pc=base + 12)
        add(f'u24-range-{base:06x}', code, expected, initial=initial, base=base)
    add('u24-next-overflow', NOP, dict(outcome=5, fault=3, retired=0, fuel=8),
        initial=context(NOP, base=0xfffffc), base=0xfffffc)
    return result


def seeds(case, line):
    metadata, code, data, work = bytearray(112), bytearray(1024), bytearray(1024), bytearray(96)
    slot = case.get('slot', 0)
    initial = bytes(case['initial'])
    generation = case.get('cache_generation', int.from_bytes(initial[91:93], 'little'))

    def tag(index, address):
        for offset, value in ((0, address & 255), (16, (address >> 8) & 255),
                              (32, address >> 16), (48, slot), (64, 1),
                              (80, generation & 255), (96, generation >> 8)):
            metadata[offset + index] = value

    first = case.get('base', BASE)
    for index in range(case.get('cached_lines', 2)):
        address = (first & ~(line - 1)) + index * line
        if address > 0xffffff:
            continue
        entry = slot * 2 + index
        tag(entry, address)
        for offset in range(line):
            guest = address + offset - first
            if 0 <= guest < len(case['code']):
                code[entry * line + offset] = case['code'][guest]
    if 'data' in case:
        address = case['data_address'] & ~(line - 1)
        tag(8, address)
        offset = case['data_address'] - address
        data[offset:offset + len(case['data'])] = bytes(case['data'])
    return metadata, code, data, work


def fixture(symbols):
    return f'''* = $4000
start:
    sei
    cld
    lda #$35
    sta $01
    ldx #$ff
    txs
    lda #0
    sta $d030
    sta $d011
    sta $6600
    sta $6601
    sta $6602
    sta $03b1
    ldx #127
clear_globals:
    sta $fe00,x
    dex
    bpl clear_globals
    ldx #0
clear_pcbs:
    sta $0400,x
    sta $0500,x
    inx
    bne clear_pcbs
    lda #$7f
    sta $dd0d
    lda $dd0d
    jsr ${symbols['cache_reset']:04x}
    ldx #95
copy_context:
    lda $6800,x
    sta $02,x
    sta $0400,x
    dex
    bpl copy_context
    lda $6b01
    sta $03b0
    // Save the supplied context into its actual owner slot before importing.
    jsr ${symbols['vm_save_context']:04x}
    lda $6b03
    beq context_ready
    lda #0
    sta $1e
    sta $1f
    lda #4
    sta $20
    jsr ${symbols['vm_load_context']:04x}
context_ready:
    lda $6b02
    sta ${symbols['nmi_pending']:04x}
    ldx #111
copy_metadata:
    lda $6900,x
    sta $fd80,x
    dex
    bpl copy_metadata
    ldx #95
copy_work:
    lda $6a00,x
    sta $0350,x
    dex
    bpl copy_work
    ldx #0
copy_buffers:
    .for (var page=0;page<4;page++) {{
        lda $7000+page*256,x
        sta $0800+page*256,x
        lda $7400+page*256,x
        sta $0c00+page*256,x
    }}
    inx
    bne copy_buffers
    lda $6b00
    beq run_optimized
    cmp #2
    beq run_scheduler
run_reference:
    jsr ${symbols['vm_step']:04x}
    lda $6b04
    bne finished
    lda $47
    beq run_reference
    jmp finished
run_optimized:
    jsr ${symbols['vm_run']:04x}
    jmp finished
run_scheduler:
    lda #0
    sta $fe09
    sta $fe5d
    lda #1
    sta $0460
    lda #3
    sta $04e0
    jsr ${symbols['scheduler_vm_phase']:04x}
finished:
    tsx
    stx $6601
    lda #$55
    sta $6600
halt:
    jmp halt
'''


def expected(case, state):
    actual = describe(state)
    actual['r0'] = actual['r'][0]
    for field, value in case['expected'].items():
        if actual[field] != value:
            raise ValueError(f"{case['name']}: independent {field} expectation {value}, got {actual[field]}")


def execute(session, case, line, mode):
    metadata, code, data, work = seeds(case, line)
    session.command('monitor c64 halt')
    session.write(0x6800, case['initial'])
    session.write(0x6900, metadata)
    session.write(0x6a00, work)
    session.write(0x6b00, bytes((mode, case.get('slot', 0), case.get('nmi', 0),
                               int(case.get('imported', False)), int(case.get('single_reference', False)))))
    session.write(0x7000, code)
    session.write(0x7400, data)
    session.command('monitor g 4000')
    session.command('wait 1000')
    session.command('monitor c64 halt')
    if session.read(0x6600, 2) != b'\x55\xff':
        raise ValueError(case['name'] + ': native harness did not finish with unwound stack')
    snapshot = dict(state=list(session.read(2, 96)), metadata=list(session.read(0xfd80, 112)),
                    cache_work=list(session.read(0x350, 96)),
                    code=list(session.read(0x800, 1024)), data=list(session.read(0xc00, 1024)))
    expected(case, snapshot['state'])
    return snapshot


def check(args):
    build, out = args.build.resolve(), args.out.resolve()
    if out.exists():
        raise ValueError('Preserve prior native evidence; choose a fresh output directory')
    metadata = json.loads((build / 'map.json').read_text())
    native = (build / 'native.bin').read_bytes()
    if sha(native) != metadata['artifact_sha256']['native.bin']:
        raise ValueError('Native image differs from its map')
    ram = bytearray(65536)
    origin = metadata['native_ram_first']
    ram[origin:origin + len(native)] = native
    m2_bounds.verify_valid_pc_wrapper(ram, metadata['symbols'])
    out.mkdir(parents=True)
    (out / 'hot-pc.asm').write_text(fixture(metadata['symbols']))
    m0.assemble(args.java, args.kickass.resolve(), out / 'hot-pc.asm', out, {})
    corpus = cases(metadata['cache_line_bytes'])
    (out / 'cases.json').write_text(json.dumps(corpus, indent=2) + '\n')
    session = Session(args, out / 'backend')
    rows = []
    try:
        session.command('monitor c64 halt')
        session.write(origin, native)
        fixture_prg = (out / 'hot-pc.prg').read_bytes()
        session.write(0x4000, fixture_prg[2:])
        for case in corpus:
            baseline = execute(session, case, metadata['cache_line_bytes'], 1)
            candidate = execute(session, case, metadata['cache_line_bytes'],
                                2 if case.get('scheduler_job') else 0)
            if baseline != candidate:
                field = next(key for key in baseline if baseline[key] != candidate[key])
                raise ValueError(case['name'] + ': first full-step/run divergence in ' + field)
            row = dict(name=case['name'], passed=True, snapshot=candidate)
            rows.append(row)
            (out / 'snapshots.json').write_text(json.dumps(rows, indent=2) + '\n')
        if session.read(origin, len(native)) != native:
            raise ValueError('Fixture modified the frozen resident binary')
        result = dict(format='COSM3HOTPC1', status='pass', cases=len(rows), failures=0,
                      current_pc_invariant='Full first step on every vm_run/import; only a preceding RUN can reach the private validated-PC entry',
                      comparison='vm_run versus repeated full vm_step, stopped at identical first boundary',
                      scheduler_job_comparison='Production scheduler_vm_phase with a second owner WAIT_JOB versus one full vm_step',
                      native_resident_bytes_unchanged=True, hardware_stack_unwound=True,
                      build_tag=metadata['build_tag'], cache_line=metadata['cache_line_bytes'],
                      native_sha256=sha(native), map_sha256=sha((build / 'map.json').read_bytes()),
                      corpus_sha256=sha((out / 'cases.json').read_bytes()),
                      snapshots_sha256=sha((out / 'snapshots.json').read_bytes()),
                      prg_sha256=sha(fixture_prg), runner_sha256=sha(Path(__file__).read_bytes()),
                      supplied_input_sha256=session.input_sha256,
                      qualification='Native semantics with trusted context/cache seeds and video disabled; independent live timing/scanout required')
    finally:
        session.close()
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(status='pass', native_cases=len(rows))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('emulator', 'config', 'flash', 'settings', 'kickass', 'build', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--java', default='java')
    check(parser.parse_args())


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        print('check_m3_hot_pc: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
