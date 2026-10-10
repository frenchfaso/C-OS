#!/usr/bin/env python3
"""Execute the assembled PAL gate against stable and torn raster input vectors.

Only the three I/O addresses in a private copy of the verified gate are mapped
to fixture RAM. This proves native branch behavior and register/stack effects;
it is not a raster timing qualification or a substitute for live UPIC tests.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import m0
import m2_bounds
from m3_benchmark import Session

ROOT = Path(__file__).resolve().parents[1]


def sha(value):
    return hashlib.sha256(value).hexdigest()


def vectors(intervals):
    stable = [(0x80 if line >= 256 else 0, line & 255,
               0x80 if line >= 256 else 0,
               int(not any(window['first_line'] <= line <= window['last_line']
                           for window in intervals)))
              for line in range(312)]
    torn = [(first, low, second, 1) for first, second in ((0, 0x80), (0x80, 0))
            for low in range(256)]
    return bytes(value for row in stable + torn for value in row)


def fixture(routine, count):
    code = ','.join(f'${value:02x}' for value in routine)
    return f'''* = $0801
BasicUpstart2(start)
start:
    sei
    cld
    ldx #$ff
    txs
    lda #0
    sta $d030
    sta $d011
    sta $0200
    sta $0201
    sta $0202
    sta $0203
    sta $0204
    sta $f9
    lda #$40
    sta $fa
    lda #<inputs
    sta $fb
    lda #>inputs
    sta $fc
next:
    ldy #0
    lda ($fb),y
    sta $0300
    iny
    lda ($fb),y
    sta $0301
    iny
    lda ($fb),y
    sta $0302
    iny
    lda ($fb),y
    sta $0303
    ldx #$55
    ldy #$aa
    jsr gate
    php
    pla
    and #1
    sta $ff
    cpx #$55
    beq !+
    lda $ff
    ora #2
    sta $ff
!:
    cpy #$aa
    beq !+
    lda $ff
    ora #4
    sta $ff
!:
    tsx
    cpx #$ff
    beq !+
    lda $ff
    ora #8
    sta $ff
!:
    ldy #0
    lda $ff
    sta ($f9),y
    cmp $0303
    beq !+
    inc $0202
    bne !+
    inc $0203
!:
    inc $f9
    bne !+
    inc $fa
!:
    clc
    lda $fb
    adc #4
    sta $fb
    bcc !+
    inc $fc
!:
    inc $0200
    bne !+
    inc $0201
!:
    lda $0200
    cmp #<{count}
    bne next_more
    lda $0201
    cmp #>{count}
    beq finished
next_more:
    jmp next
finished:
    lda #$55
    sta $0204
halt:
    jmp halt
gate:
    .byte {code}
inputs:
    .import binary "vectors.bin"
'''


def check(args):
    build, out = args.build.resolve(), args.out.resolve()
    if out.exists():
        raise ValueError('Preserve prior gate evidence; choose a fresh output directory')
    metadata = json.loads((build / 'map.json').read_text())
    native = (build / 'native.bin').read_bytes()
    if sha(native) != metadata['artifact_sha256']['native.bin']:
        raise ValueError('Native image differs from the build map')
    symbols, origin = metadata['symbols'], metadata['native_ram_first']
    ram = bytearray(65536)
    ram[origin:origin + len(native)] = native
    windows = m2_bounds.admission_windows(ram, symbols, True)
    if not windows['vm_video_admit'].get('coherent_high_low_high'):
        raise ValueError('This fixture requires the qualified coherent PAL gate')
    split = 'm3_vm_raster_admit' in symbols
    gates = [('vm_video_admit', 'm3_vm_raster_admit' if split else 'm3_raster_admit')]
    if split:
        gates.append(('scheduler_video_admit', 'm3_raster_admit'))
    out.mkdir(parents=True)
    session = Session(args, out / 'backend')
    rows = []
    try:
        for entry, label in gates:
            destination = out / entry if split else out
            if split:
                destination.mkdir()
            rows.append(check_gate(args, session, destination, entry, label, ram, symbols,
                                   windows[entry]['intervals'], split))
    finally:
        session.close()
    result = dict(rows[0]) if not split else dict(
        format='COSM3ADMISSION1', status='pass', failures=0,
        native_cases=sum(row['native_cases'] for row in rows), gate_results=rows,
        separate_vm_and_scheduler_gates=True,
        scheduler_dma_share_verified_native_gate=True)
    result.update(native_image_sha256=sha(native), map_sha256=sha((build / 'map.json').read_bytes()),
                  supplied_input_sha256=session.input_sha256,
                  runner_sha256=sha(Path(__file__).read_bytes()))
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(status='pass', native_cases=result['native_cases'], build=str(build))))


def check_gate(args, session, out, entry, label, ram, symbols, intervals, split):
    original = bytes(ram[symbols[label]:symbols['m3_raster_reject'] + 2])
    routine = bytearray(original)
    # Walk instructions, so accidental operand bytes cannot become patch sites.
    high_reads, low_reads, offset = 0, 0, 0
    while offset < len(routine):
        instruction = bytes(routine[offset:offset + 3])
        if instruction == b'\x2c\x11\xd0':
            address = 0x0300 if high_reads == 0 else 0x0302
            routine[offset + 1:offset + 3] = address.to_bytes(2, 'little')
            high_reads += 1
        elif instruction == b'\xad\x12\xd0':
            routine[offset + 1:offset + 3] = b'\x01\x03'
            low_reads += 1
        offset += m2_bounds.LENGTHS[routine[offset]]
    # Both early/post paths have their own low and second-high instruction.
    expected_sites = (5, 3) if split and label == 'm3_vm_raster_admit' else (3, 2)
    if (high_reads, low_reads) != expected_sites:
        raise ValueError('Unexpected coherent gate read sites')
    inputs = vectors(intervals)
    count = len(inputs) // 4
    (out / 'vectors.bin').write_bytes(inputs)
    (out / 'admission.asm').write_text(fixture(routine, count))
    _, origin, labels = m0.assemble(args.java, args.kickass.resolve(), out / 'admission.asm', out, {})
    if origin != 0x0801 or not 0x080d <= labels['start'] < labels['gate']:
        raise ValueError('Unexpected native admission fixture entry')
    session.load(out / 'admission.prg', labels['start'])
    session.command('wait 1000')
    report = session.read(0x0200, 5)
    output = session.read(0x4000, count)
    expected = inputs[3::4]
    if report != count.to_bytes(2, 'little') + b'\0\0\x55' or output != expected:
        raise ValueError('Native coherent gate failed: ' + entry + ' ' + report.hex(' '))
    (out / 'actual-results.bin').write_bytes(output)
    result = dict(format='COSM3ADMISSION1', status='pass', entry=entry, stable_pal_lines=312,
                      torn_high_bit_vectors=512, native_cases=count, failures=0,
                      admitted_intervals=intervals,
                      input_vectors_sha256=sha(inputs), actual_results_sha256=sha(output),
                      original_gate_sha256=sha(original), original_gate=list(original),
                      fixture_gate=list(routine), only_modified_fields='I/O operands mapped to fixture RAM',
                      x_y_preserved=True, hardware_stack_unwound=True,
                      prg_sha256=sha((out / 'admission.prg').read_bytes()),
                      qualification='Native branch behavior with scripted coherent/torn read values; live raster timing is separately qualified')
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


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
        print('check_m3_admission: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
