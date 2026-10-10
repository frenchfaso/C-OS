#!/usr/bin/env python3
"""Execute the assembled active-raster classifier with stable and torn reads.

Only absolute I/O operands are mapped to RAM in a private native harness.
This checks branch behavior, carry and X/Y/SP; it does not qualify live timing
or supply evidence that a particular live diagnostic event was false.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import m0
import m2_bounds
from m3_benchmark import Session


def sha(value):
    return hashlib.sha256(value).hexdigest()


def vectors():
    stable = [(0x80 if line >= 256 else 0, line & 255,
               0x80 if line >= 256 else 0, int(60 <= line < 260))
              for line in range(312)]
    # A transition to line 256 is active; the PAL 311 -> 0 wrap is inactive.
    torn = [(first, low, second, int(second == 0x80))
            for first, second in ((0, 0x80), (0x80, 0))
            for low in range(256)]
    return bytes(value for row in stable + torn for value in row)


def map_io(original):
    """Keep actual opcodes/branch displacements; reject unexpected control flow."""
    routine = bytearray(original)
    high_reads, low_reads, offset = 0, 0, 0
    branches, starts, sites = [], set(), []
    allowed = {0x2c, 0xad, 0xc9, 0x90, 0xb0, 0x10, 0x30, 0x18, 0x38, 0x60}
    while offset < len(routine):
        starts.add(offset)
        opcode = routine[offset]
        if opcode not in allowed:
            raise ValueError(f'Unexpected classifier opcode ${opcode:02x} at {offset}')
        length = m2_bounds.LENGTHS[opcode]
        if offset + length > len(routine):
            raise ValueError('Truncated classifier instruction')
        if opcode in (0x90, 0xb0, 0x10, 0x30):
            relative = routine[offset + 1]
            branches.append(offset + 2 + (relative if relative < 128 else relative - 256))
        if opcode in (0x2c, 0xad):
            instruction = bytes(routine[offset:offset + 3])
            if instruction == b'\x2c\x11\xd0':
                address = 0x0300 if high_reads == 0 else 0x0302
                high_reads += 1
            elif instruction == b'\xad\x12\xd0':
                address = 0x0301
                low_reads += 1
            else:
                raise ValueError('Unexpected classifier absolute read operand')
            sites.append(dict(offset=offset + 1, original_operand=list(routine[offset + 1:offset + 3]),
                              fixture_operand=list(address.to_bytes(2, 'little'))))
            routine[offset + 1:offset + 3] = address.to_bytes(2, 'little')
        offset += length
    if (high_reads, low_reads) != (3, 2):
        raise ValueError('Classifier requires one first and two confirming high reads')
    if any(target not in starts for target in branches):
        raise ValueError('Classifier branch escapes routine or enters an operand')
    if not routine or routine[-1] != 0x60:
        raise ValueError('Classifier must end with RTS')
    changed = {site['offset'] + delta for site in sites for delta in (0, 1)}
    if any(a != b and i not in changed for i, (a, b) in enumerate(zip(original, routine))):
        raise ValueError('Classifier mutation extends beyond I/O operands')
    return bytes(routine), sites


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
    // Start carry opposite to expected, so either result must be established.
    cmp #1
    ldx #$55
    ldy #$aa
    eor #1
    lsr
    jsr classify
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
    bne more
    lda $0201
    cmp #>{count}
    beq finished
more:
    jmp next
finished:
    lda #$55
    sta $0204
halt:
    jmp halt
classify:
    .byte {code}
inputs:
    .import binary "vectors.bin"
'''


def check(args):
    build, out = args.build.resolve(), args.out.resolve()
    if out.exists():
        raise ValueError('Preserve prior classifier evidence; choose a fresh output directory')
    metadata = json.loads((build / 'map.json').read_text())
    native = (build / 'native.bin').read_bytes()
    if sha(native) != metadata['artifact_sha256']['native.bin']:
        raise ValueError('Native image differs from the build map')
    symbols, origin = metadata['symbols'], metadata['native_ram_first']
    first, end = symbols['raster_active'], symbols['m3_recover_nmi']
    if not origin <= first < end <= origin + len(native):
        raise ValueError('Classifier symbol range is outside native image')
    original = native[first - origin:end - origin]
    routine, sites = map_io(original)
    inputs = vectors()
    count = len(inputs) // 4
    out.mkdir(parents=True)
    (out / 'vectors.bin').write_bytes(inputs)
    (out / 'raster_active.asm').write_text(fixture(routine, count))
    _, load_origin, labels = m0.assemble(args.java, args.kickass.resolve(),
                                        out / 'raster_active.asm', out, {})
    if load_origin != 0x0801 or not 0x080d <= labels['start'] < labels['classify']:
        raise ValueError('Unexpected classifier fixture entry')
    assembled = (out / 'raster_active.prg').read_bytes()
    relocated = labels['classify'] - load_origin + 2
    if assembled[relocated:relocated + len(routine)] != routine:
        raise ValueError('Fixture assembler changed extracted classifier instructions')
    session = Session(args, out / 'backend')
    try:
        session.load(out / 'raster_active.prg', labels['start'])
        session.command('wait 1000')
        report = session.read(0x0200, 5)
        actual = session.read(0x4000, count)
        (out / 'actual-results.bin').write_bytes(actual)
        (out / 'native-report.bin').write_bytes(report)
        if report != count.to_bytes(2, 'little') + b'\0\0\x55' or actual != inputs[3::4]:
            raise ValueError('Native raster classifier failed: ' + report.hex(' '))
        result = dict(format='COSM3RASTERACTIVE1', status='pass', failures=0,
                      stable_pal_lines=312, torn_high_bit_vectors=512, native_cases=count,
                      active_interval=dict(first_line=60,last_line=259),
                      torn_zero_to_high_active=True, torn_high_to_zero_inactive=True,
                      x_y_preserved=True, hardware_stack_unwound=True,
                      a_and_noncarry_flags='scratch',
                      native_image_sha256=sha(native), map_sha256=sha((build / 'map.json').read_bytes()),
                      input_vectors_sha256=sha(inputs), actual_results_sha256=sha(actual),
                      original_classifier_sha256=sha(original), original_classifier=list(original),
                      fixture_classifier=list(routine), mapped_io_operands=sites,
                      only_modified_fields='Absolute I/O operands mapped to fixture RAM',
                      original_opcodes_and_branch_displacements_retained=True,
                      prg_sha256=sha(assembled), supplied_input_sha256=session.input_sha256,
                      runner_sha256=sha(Path(__file__).read_bytes()),
                      qualification='Assembled native branch behavior with scripted stable/torn inputs; live timing and any live event require separate evidence')
        (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(dict(status='pass', native_cases=count, build=str(build))))
        return result
    finally:
        session.close()


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
        print('check_m3_raster_active: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
