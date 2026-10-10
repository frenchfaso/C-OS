#!/usr/bin/env python3
"""Verify the diagnostic interval reader and wrappers on the target backend."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from m0 import assemble
from m3_benchmark import Session
from m3_profile import CATEGORIES, PROFILE_BASE, PROFILE_BYTES, profiler_source, metrics

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/m3-perf/profile-timer-check')
    for name in ['emulator', 'config', 'flash', 'settings', 'kickass']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--java', default='java')
    args = parser.parse_args()
    args.out = args.out.resolve()
    for name in ['emulator', 'config', 'flash', 'settings', 'kickass']:
        setattr(args, name, getattr(args, name).resolve())
    args.out.mkdir(parents=True, exist_ok=True)
    source = args.out / 'timer.asm'
    code = '''* = $080d
entry:
    sei
    cld
    ldx #$ff
    txs
    lda #$35
    sta $01
    lda #$7f
    sta $dc0d
    sta $dd0d
    lda $dc0d
    lda $dd0d
    lda #0
    sta $d011
    sta $d020
    sta $d030
    lda #$8f
    sta $d031
    jsr profile_init
    lda #0
    sta $40
    sta $41
loop:
    jsr profile_wrap_0
    inc $40
    bne loop
    inc $41
    bne loop
    lda #127
    sta $fc30
force_wrap_wait:
    lda $dd05
    bne force_wrap_wait
    lda $dd04
    cmp #16
    bcs force_wrap_wait
    jsr profile_wrap_0
    lda #$a5
    ldx #$33
    ldy #$66
    lda #$a5
    sec
    php
    pla
    sta $310
    lda #$a5
    jsr profile_wrap_0
    sta $301
    stx $302
    sty $303
    php
    pla
    sta $311
    lda #127
    sta $fc30
    lda #$a5
    ldx #$33
    ldy #$66
    lda #$a5
    sec
    php
    pla
    sta $312
    lda #$a5
    jsr profile_wrap_0
    sta $304
    stx $305
    sty $306
    php
    pla
    sta $313
    lda #$55
    sta $300
finished:
    jmp finished
'''
    for _, routine in CATEGORIES:
        if routine not in ['profile_nop', 'vm_step']:
            code += routine + ':\n'
    code += '    rts\nvm_step:\n    .for (var i=0;i<512;i++) { nop }\n    rts\n' + profiler_source(127)
    source.write_text(code)
    assemble(args.java, args.kickass, source, args.out, {})
    session = Session(args, args.out)
    try:
        session.load(args.out / 'timer.prg', 0x80d)
        session.command('wait 4000')
        record = session.read(0x300, 0x14)
        if (record[0] != 0x55 or record[1:4] != b'\xa5\x33\x66'
            or record[4:7] != b'\xa5\x33\x66'
            or any((record[before] & 0xcf) != (record[before + 1] & 0xcf) for before in [0x10, 0x12])):
            raise ValueError('Target diagnostic wrapper changed registers/flags or did not complete')
        data = session.read(PROFILE_BASE, PROFILE_BYTES)
        (args.out / 'counters.bin').write_bytes(data)
        measured = metrics(data)
        wraps = int.from_bytes(data[0x224:0x226], 'little')
        if measured['vm_step']['calls'] != 514 or not wraps:
            raise ValueError('Target sparse probe count or timer-wrap exercise differs')
        if measured['vm_step']['maximum_phi2_ticks'] > 32:
            raise ValueError('Target empty wrapper timer difference has a discontinuity')
        result = dict(status='pass', completed_calls=65539, sample_factor=128,
                      observed_interval_wraps=wraps, register_flags_record=list(record),
                      profile=measured, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                      prg_sha256=hashlib.sha256((args.out / 'timer.prg').read_bytes()).hexdigest(),
                      supplied_input_sha256=session.input_sha256,
                      qualification='Target turbo profile; no IRQ; sparse short probes cross 16-bit CIA2A wrap')
        (args.out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({key: result[key] for key in ['status', 'completed_calls', 'observed_interval_wraps']}))
    finally:
        session.close()
        (args.out / 'isolated-flash.bin').unlink(missing_ok=True)
        shutil.rmtree(args.out / 'run/usb-dir', ignore_errors=True)


if __name__ == '__main__':
    main()
