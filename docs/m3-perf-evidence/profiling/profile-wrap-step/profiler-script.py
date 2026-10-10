#!/usr/bin/env python3
"""Profile autonomous M3 target costs in a frozen, isolated source snapshot."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
FRAME_TICKS = 312 * 63
CATEGORIES = [
    ('vm_step', 'vm_step'), ('code_fetch', 'cache_fetch_code'),
    ('pc_bounds', 'vm_check_pc'), ('decode', 'vm_decode_operands'),
    ('preflight', 'vm_preflight'), ('execute', 'vm_execute'),
    ('cache_unpin', 'cache_unpin'), ('data_read', 'cache_read_prepared'),
    ('data_write', 'cache_write_prepared'), ('scheduler_tick', 'scheduler_tick'),
    ('native_phase', 'scheduler_native_phase'), ('cache_service', 'cache_service'),
    ('video_admission', 'vm_video_admit'), ('dma_admission', 'vm_dma_admit'),
    ('fixed_syscall', 'jobs_accept'), ('empty_probe', 'profile_nop'),
]
PROFILE_BASE = 0xfa00
PROFILE_BYTES = 0x240


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text())


def save_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


def snapshot(destination, evidence, existing=False):
    """Copy only verified small build inputs and the ABI-matched host linker."""
    destination.mkdir(parents=True, exist_ok=True)
    receipt = destination.parent / 'source-snapshot.json'
    if receipt.exists():
        recorded = load_json(receipt)
        for name, expected in recorded['source_sha256'].items():
            if digest(destination / name) != expected:
                raise ValueError(f'Frozen source changed: {name}')
        for name, expected in recorded.get('host_tool_sha256', {}).items():
            if digest(destination / 'target/release' / name) != expected:
                raise ValueError(f'Frozen host tool changed: {name}')
        if existing:
            tool_hash = recorded.get('host_tool_sha256', {}).get('cospack') or recorded['source_sha256'].get('target/release/cospack')
            if tool_hash != digest(destination / 'target/release/cospack'):
                raise ValueError('Existing source receipt does not bind its host linker')
            return dict(format='COSM3PERFEXISTINGSNAPSHOT1',
                        source_receipt_sha256=digest(receipt), source_sha256=recorded['source_sha256'],
                        host_tool_sha256={'cospack': digest(destination / 'target/release/cospack')},
                        reviewed_frames={})
        return recorded
    if existing:
        raise ValueError('Existing snapshot requires its source-snapshot.json receipt')
    verified = load_json(evidence)
    if verified['status'] != 'pass' or not verified['sources_unchanged_during_run']:
        raise ValueError('Baseline evidence is not a completed source-stable pass')
    names = [name for name in verified['source_sha256']
             if name.startswith(('native/', 'scripts/', 'apps/', 'manifests/'))]
    names += ['build/mandelbrot.cobj', 'build/mandelbrot-host-profile.json',
              'scripts/mandelbrot_reference.py']
    recorded = {}
    for name in sorted(set(names)):
        source = ROOT / name
        if not source.is_file():
            continue
        actual = digest(source)
        if name in verified['source_sha256'] and actual != verified['source_sha256'][name]:
            raise ValueError(f'Working source differs from reviewed baseline: {name}')
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        recorded[name] = actual
    linker = destination / 'target/release/cospack'
    linker.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'target/release/cospack', linker)
    linker.chmod((ROOT / 'target/release/cospack').stat().st_mode)
    result = dict(format='COSM3PERFBASELINE1', verification_sha256=digest(evidence),
                  source_sha256=recorded, host_tool_sha256={'cospack': digest(linker)},
                  reviewed_frames={str(line): bench['cos']['elapsed_frames']
                                   for line, bench in zip([128, 64], verified['benchmarks'])})
    save_json(receipt, result)
    return result


def asm_probe(index, action):
    # Preserve original registers and ALL flags, including admission carry/I.
    return f'''    php
    pha
    txa
    pha
    tya
    pha
    ldx #{index * 16}
    jsr profile_{action}
    pla
    tay
    pla
    tax
    pla
    plp
'''


def profiler_source(sample_mask=0):
    head = '''#importonce
// Generated diagnostics only. Font reservation $fa00..$fc3f is private.
.const PROFILE_NOW = $fc00
.const PROFILE_DELTA = $fc04
.const PROFILE_INDEX = $fc08
.const PROFILE_FLAGS = $fc09
.const PROFILE_CAL_LEFT = $fc0a
.const PROFILE_OVERFLOW = $fc22
.const PROFILE_INTERVAL_WRAPS = $fc24
.const PROFILE_SAMPLE = $fc30
profile_init:
    lda #0
    ldx #0
!:
    sta $fa00,x
    sta $fb00,x
    dex
    bne !-
    ldx #$3f
!:
    sta $fc00,x
    dex
    bpl !-
    lda #$ff
    ldx #0
!:
    .for (var i=0;i<4;i++) { sta $fa08+i,x }
    txa
    clc
    adc #16
    tax
    lda #$ff
    bne !-
    // Disable CIA2 NMI sources; the interval timer never interrupts.
    lda #$7f
    sta $dd0d
    lda $dd0d
    lda #$10
    sta $dd0e
    lda #$10
    sta $dd0f
    lda #$ff
    sta $dd04
    sta $dd05
    sta $dd06
    sta $dd07
    lda #1
    sta $dd0e
profile_timer_settle:
    lda $dd04
    cmp #$f0
    bcs profile_timer_settle
    lda #0
    sta PROFILE_CAL_LEFT
profile_calibrate:
    jsr profile_wrap_15
    dec PROFILE_CAL_LEFT
    bne profile_calibrate
    rts
// A high/low/high, retrying a torn high-byte boundary. Each measured call
// must be independently bounded below 65536 PHI2, including one raster IRQ.
// A modulo-16-bit interval avoids concatenating an unsettled B cascade step.
profile_read:
profile_read_again:
    lda $dd05
    sta PROFILE_NOW+1
    lda $dd04
    sta PROFILE_NOW
    lda $dd05
    cmp PROFILE_NOW+1
    bne profile_read_again
    lda #0
    sta PROFILE_NOW+2
    sta PROFILE_NOW+3
    rts
profile_begin:
    jsr profile_read
    .for (var i=0;i<4;i++) {
        lda PROFILE_NOW+i
        sta $fb00+i,x
    }
    rts
profile_end:
    stx PROFILE_INDEX
    tsx
    lda $0106,x
    sta PROFILE_FLAGS
    ldx PROFILE_INDEX
    jsr profile_read
    sec
    .for (var i=0;i<2;i++) {
        lda $fb00+i,x
        sbc PROFILE_NOW+i
        sta PROFILE_DELTA+i
    }
    bcs !+
    inc PROFILE_INTERVAL_WRAPS
    bne !+
    inc PROFILE_INTERVAL_WRAPS+1
!:
    lda #0
    sta PROFILE_DELTA+2
    sta PROFILE_DELTA+3
    clc
    .for (var i=0;i<4;i++) {
        lda $fa00+i,x
        adc PROFILE_DELTA+i
        sta $fa00+i,x
    }
    bcc !+
    inc PROFILE_OVERFLOW
!:
    inc $fa04,x
    bne !+
    inc $fa05,x
    bne !+
    inc $fa06,x
    bne !+
    inc $fa07,x
    bne !+
    inc PROFILE_OVERFLOW
!:
    .for (var i=3;i>=0;i--) {
        lda PROFILE_DELTA+i
        cmp $fa08+i,x
        bcc profile_min_update
        bne profile_max_check
    }
profile_min_update:
    .for (var i=0;i<4;i++) {
        lda PROFILE_DELTA+i
        sta $fa08+i,x
    }
profile_max_check:
    .for (var i=3;i>=0;i--) {
        lda PROFILE_DELTA+i
        cmp $fa0c+i,x
        bcc profile_carry
        bne profile_max_update
    }
profile_max_update:
    .for (var i=0;i<4;i++) {
        lda PROFILE_DELTA+i
        sta $fa0c+i,x
    }
profile_carry:
    lda PROFILE_FLAGS
    and #1
    beq profile_end_done
    clc
    .for (var i=0;i<4;i++) {
        lda $fb04+i,x
        adc PROFILE_DELTA+i
        sta $fb04+i,x
    }
    bcc !+
    inc PROFILE_OVERFLOW
!:
    inc $fb08,x
    bne profile_end_done
    inc $fb09,x
    bne profile_end_done
    inc $fb0a,x
    bne profile_end_done
    inc $fb0b,x
    bne profile_end_done
    inc PROFILE_OVERFLOW
profile_end_done:
    rts
profile_nop:
    rts
'''
    wrappers = []
    for index, (_, routine) in enumerate(CATEGORIES):
        sampling = ''
        if sample_mask and index != 15:
            sampling = f'''    php
    pha
    txa
    pha
    ldx #{index}
    inc PROFILE_SAMPLE,x
    lda PROFILE_SAMPLE,x
    and #{sample_mask}
    beq profile_sample_{index}
    pla
    tax
    pla
    plp
    jsr {routine}
    rts
profile_sample_{index}:
    pla
    tax
    pla
    plp
'''
        wrappers.append(f'profile_wrap_{index}:\n' + sampling + asm_probe(index, 'begin') +
                        f'    jsr {routine}\n' + asm_probe(index, 'end') + '    rts\n')
    # Initial min-fill must end when the 8-bit offset wraps, not on A=$ff.
    head = head.replace('    lda #$ff\n    bne !-\n    // Disable',
                        '    lda #$ff\n    cpx #0\n    bne !-\n    // Disable')
    return head + '\n'.join(wrappers)


def instrument(baseline, destination, selected=None, last_line=None, sample_mask=0):
    selected = set(selected or [name for name, _ in CATEGORIES[:-1]])
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(baseline, destination)
    substitutions = {}
    for file in ['m3_kernel.asm', 'vm.asm', 'cache.asm', 'scheduler.asm', 'jobs.asm']:
        path = destination / 'native' / file
        text = path.read_text()
        for index, (_, routine) in enumerate(CATEGORIES[:-1]):
            if CATEGORIES[index][0] not in selected:
                continue
            pattern = rf'\bjsr {re.escape(routine)}\b'
            text, count = re.subn(pattern, f'jsr profile_wrap_{index}', text)
            if count:
                substitutions[f'{file}:{routine}'] = count
        if file == 'm3_kernel.asm':
            text = text.replace('    jsr margin_reset\n', '    jsr margin_reset\n    jsr profile_init\n')
            text = text.replace('m3_native_end:\n', '#import "profile.asm"\nm3_native_end:\n')
            for suffix in ['video', 'dma']:
                if last_line is not None:
                    text = text.replace(f'    cmp #44\n    bcs m3_{suffix}_deferred',
                                        f'    cmp #{last_line - 255}\n    bcs m3_{suffix}_deferred')
            if 'M3_ADMISSION_EARLY_END' in text and last_line is not None:
                early_end = last_line + 1 if last_line < 256 else 0
                text = re.sub(r'^\.const M3_ADMISSION_EARLY_END = .*$',
                              f'.const M3_ADMISSION_EARLY_END = {early_end}', text, flags=re.M)
                if last_line >= 256:
                    text = text.replace('cmp #(EXTENDED_DIAGNOSTICS == 0 && MARGIN_ENABLED == 0 ? 56 : 44)',
                                        f'cmp #{last_line - 255}')
        path.write_text(text)
    (destination / 'native/profile.asm').write_text(profiler_source(sample_mask))
    return substitutions


def metrics(data):
    if len(data) != PROFILE_BYTES or data[0x222]:
        raise ValueError('Invalid/overflowed target profile counters')
    def word(offset):
        return int.from_bytes(data[offset:offset + 4], 'little')
    result = {}
    for index, (name, routine) in enumerate(CATEGORIES):
        offset = index * 16
        result[name] = dict(routine=routine, inclusive_phi2_ticks=word(offset),
                            calls=word(offset + 4), minimum_phi2_ticks=word(offset + 8),
                            maximum_phi2_ticks=word(offset + 12),
                            carry_set_phi2_ticks=word(0x104 + offset),
                            carry_set_calls=word(0x108 + offset))
        value = result[name]
        if value['calls'] and (not 0 < value['minimum_phi2_ticks'] <= value['maximum_phi2_ticks'] < 65536
            or not value['calls'] * value['minimum_phi2_ticks'] <= value['inclusive_phi2_ticks'] <= value['calls'] * value['maximum_phi2_ticks']
            or value['carry_set_calls'] > value['calls'] or value['carry_set_phi2_ticks'] > value['inclusive_phi2_ticks']):
            raise ValueError('Invalid/discontinuous target profile interval records')
    calibration = result['empty_probe']
    if calibration['calls'] != 256 or not 0 < calibration['minimum_phi2_ticks'] <= calibration['maximum_phi2_ticks'] < 1024:
        raise ValueError('Empty-probe timer calibration failed')
    for value in result.values():
        count, raw = value['calls'], value['inclusive_phi2_ticks']
        value['body_excess_vs_empty_interval_phi2_ticks'] = [
            max(0, raw - count * calibration['maximum_phi2_ticks']),
            max(0, raw - count * calibration['minimum_phi2_ticks'])]
    return result


def build(args, source, out, line, profiled, modules, last_line=299):
    m2, m0 = modules
    m2.ROOT = source
    m0.ROOT = source
    original = list(m2.M3_FILES)
    if profiled:
        m2.M3_FILES = original + ['profile.asm']
    try:
        options = argparse.Namespace(milestone='m3', extended_diagnostics=False,
            cache_line=line, line_delay=140, margin_hook=False, skip_host_build=True,
            offline=True, kickass=args.kickass, java=args.java,
            manifest=source / args.manifest_name, out=out)
        report = m2.build(options)
        report['profile_diagnostic'] = profiled
        report['profiler_reserved_font_bytes'] = PROFILE_BYTES if profiled else 0
        report['profiler_numeric_reserve_borrowed_bytes'] = report['numeric_target_shortfall'] if profiled else 0
        report['runtime_admission_last_line'] = last_line
        report['latest_admission_guard_phi2'] = (369 - last_line) * 63
        save_json(out / 'map.json', report)
        return report
    finally:
        m2.M3_FILES = original


def profile_bounds(baseline, build_path, selected):
    # Audit the actual generated call graph. vm_run's final step is its actual
    # assembled JSR destination, including the total-step wrapper if selected.
    source = (baseline / 'scripts/m2_bounds.py').read_text()
    # A provisional generated build may need an earlier diagnostic deadline.
    # Only the outer profiler may admit execution, after the final audit fits.
    source = source.replace("raise ValueError(f'Unsafe admission: {name} reaches the next raster IRQ guard')", 'pass')
    # Preserve the frozen checker's exact coherent-admission signature while
    # allowing only the generated, earlier early-frame deadline to differ.
    if 'm3_raster_admit' in (baseline / 'native/m3_kernel.asm').read_text():
        symbols = m3_symbols(build_path)
        image = (build_path / 'native.bin').read_bytes()
        early_end = image[symbols['m3_raster_admit'] - 0x1200 + 9]
        post_end = image[symbols['m3_raster_post'] - 0x1200 + 8]
        source = source.replace("b'\\xad\\x12\\xd0\\xc9\\x15'", repr(b'\xad\x12\xd0\xc9' + bytes([early_end])))
        source = source.replace("b'\\xc9\\x38'", repr(bytes([0xc9, post_end])))
        post_last = 255 + post_end
        window = dict(first_line=260, last_line=early_end - 1 if early_end else post_last,
                      wraps_frame=bool(early_end), coherent_high_low_high=True,
                      intervals=([dict(first_line=0, last_line=early_end - 1)] if early_end else []) +
                                [dict(first_line=260, last_line=post_last)])
        source = re.sub(r"windows\[entry\] = dict\(first_line=260, last_line=20, wraps_frame=True,\s*coherent_high_low_high=True,\s*intervals=\[dict\(first_line=0, last_line=20\),\s*dict\(first_line=260, last_line=311\)\]\)",
                        'windows[entry] = ' + repr(window), source)
    source = source.replace("return add(function(symbols['vm_step']), (4, 0))",
                            "return add(function(int.from_bytes(ram[symbols['vm_run'] + 1:symbols['vm_run'] + 3], 'little')), (4, 0))")
    if 'vm_step' in selected:
        source = source.replace("!= symbols['vm_step']", "!= symbols['profile_wrap_0']")
        source = source.replace("symbols['vm_step'].to_bytes(2, 'little')",
                                "symbols['profile_wrap_0'].to_bytes(2, 'little')")
        source = source.replace("return add(function(symbols['vm_step']), (4, 0, 6 + 3 + 4 + 6))",
                                "return add(function(symbols['profile_wrap_0']), (4, 0, 6 + 3 + 4 + 6))")
    caller = 'profile_wrap_9' if 'scheduler_tick' in selected else 'scheduler_tick'
    source = source.replace("['scheduler_vm_result', 'scheduler_vm_phase', 'scheduler_tick']",
                            repr(['scheduler_vm_result', 'scheduler_vm_phase', 'scheduler_tick', caller]))
    # All four torn-read branches share one retry budget. At most one IRQ may
    # interrupt a read: one rollover before, one interruption, one rollover
    # after are allowed. Continuous timers/no NMI/reprogramming are required.
    source = source.replace('used = dict(budgets).get(pc, 0)',
        "budget_pc = symbols['profile_read_again'] if destination_label == 'profile_read_again' else pc\n                    used = dict(budgets).get(budget_pc, 0)")
    source = source.replace('changed[pc] = used + 1', 'changed[budget_pc] = used + 1')
    audit_source = build_path / 'profile_bounds.py'
    audit_source.write_text(source)
    namespace = {'__file__': str(audit_source), '__name__': 'profile_cfg_audit'}
    exec(compile(source, str(audit_source), 'exec'), namespace)
    namespace['CONDITIONAL_LOOP_CAPS']['profile_read_again'] = 3
    result = namespace['analyze'](build_path)
    tail = result['last_opcode_admission_audit'][caller]['conditional_total_phi2_upper_bound']
    result['profile_read_retry_model'] = 'Shared cap3: one high-byte boundary before an IRQ, one IRQ interruption, one boundary after it; no NMI/reprogramming. Coherent CIA2A high-low-high; each uninterrupted triplet <=23PHI2; modular16-bit interval. Selected calls must be below65536PHI2 including IRQ time.'
    result['instrumented_tick_caller'] = caller
    result['instrumented_final_admitted_tail_phi2_bound'] = tail
    intervals = result['pal_admission_windows']['vm_video_admit'].get('intervals',
                [result['pal_admission_windows']['vm_video_admit']])
    admitted_window_ticks = sum(interval['last_line'] - interval['first_line'] + 1
                                for interval in intervals) * 63
    interval_bound = FRAME_TICKS + admitted_window_ticks + tail
    if interval_bound >= 65536:
        raise ValueError('Selected profiler call interval can exceed the16-bit timer range')
    result['profile_interval_phi2_upper_bound'] = interval_bound
    result['profile_interval_bound_basis'] = (
        'One complete PAL period conservatively covers one raster IRQ; '
        'all admitted window ticks cover preceding re-admitted VM opcodes; '
        'the full generated final opcode plus scheduler tail is added. '
        'Admission rejects before the following IRQ; no NMI, external pause, '
        'timer reprogramming or unbounded job. Conditional fixed emulator profile.')
    result['transformed_checker_sha256'] = digest(audit_source)
    save_json(build_path / 'profile-bounds.json', result)
    return result


def collect(args, out, build_path, profiled, session_class, logical_bytes, reference):
    spec = load_json(build_path / 'map.json')
    manifest = load_json(build_path / 'm3.manifest.json')
    for name, expected in spec['artifact_sha256'].items():
        if digest(build_path / name) != expected:
            raise ValueError(f'Executed staged artifact differs: {name}')
    app = manifest['apps'][0]
    session = session_class(args, out, build_path / 'm3.reu')
    try:
        session.load(build_path / 'm3.prg', 0x080d)
        for second in range(args.max_target_seconds):
            session.command('wait 1000')
            state = session.read(0x460, 1)[0]
            if state == 5:
                raise ValueError('Autonomous profiled workload faulted')
            if state == 0 and session.read(0x300, 5) == b'M0R1\x01' and second > 0:
                break
        else:
            raise ValueError('Autonomous workload exceeded target deadline')
        session.command('wait 50')
        png = out / 'scanout.png'
        session.command(f'png {png}')
        from m0_ue2 import scanout_geometry
        geometry = scanout_geometry(png)
        # The whole workload ran freely; this halt only captures final evidence.
        session.command('monitor c64 halt')
        metadata = session.read(0xfd80, 112)
        line = spec['cache_line_bytes']
        buffers = session.read(0x0c00, 8 * line)
        physical = session.read(app['heap']['first'], 192, True)
        output = logical_bytes(app['heap']['first'], physical, metadata, buffers, line)
        if output != reference()[0]:
            raise ValueError('Complete autonomous image differs from independent reference')
        timing_address = app['data']['start'] + 20
        times = logical_bytes(timing_address, session.read(timing_address, 8, True), metadata, buffers, line)
        first, last = [int.from_bytes(times[start:start + 4], 'little') for start in [0, 4]]
        frames = (last - first) & 0xffffffff
        if not 0 < frames < 0x80000000:
            raise ValueError('Invalid frame counter elapsed time')
        slot = session.read(0x3b0, 1)[0]
        context = session.read(2 if slot == 0 else 0x400, 96)
        retired = int.from_bytes(context[35:43], 'little')
        expected = load_json(args.baseline / args.host_profile_name)['retired']
        if retired != expected:
            raise ValueError('Target retired count differs from frozen functional reference')
        report = session.read(0x300, 80)
        for offset in [0x12, 0x14, 0x1a, 0x1e]:
            if int.from_bytes(report[offset:offset + 2], 'little'):
                raise ValueError(f'Raster/DMA/NMI condition failed at report ${offset:02x}')
        profile_bytes = session.read(PROFILE_BASE, PROFILE_BYTES) if profiled else None
        if profiled:
            (out / 'counters.bin').write_bytes(profile_bytes)
        (out / 'image.bin').write_bytes(output)
        result = dict(elapsed_frames=frames, elapsed_phi2_ticks_estimate=frames * FRAME_TICKS,
                    frame_quantization_phi2_ticks=FRAME_TICKS, retired=retired,
                    image_sha256=hashlib.sha256(output).hexdigest(),
                    profile=metrics(profile_bytes) if profiled else None,
                    profile_timer_interval_bits=16 if profiled else None,
                    profile_interval_wraps_modulo_65536=int.from_bytes(profile_bytes[0x224:0x226], 'little') if profiled else None,
                    build_tag=spec['build_tag'], artifact_sha256=spec['artifact_sha256'],
                    map_sha256=digest(build_path / 'map.json'), report=list(report),
                    supplied_input_sha256=session.input_sha256,
                    private_reu_sha256=session.private_image_sha256,
                    private_settings_sha256=session.private_settings_sha256, scanout=geometry)
        save_json(out / 'result.json', result)
        return result
    finally:
        session.close()
        if not args.keep_inputs:
            for path in [out / 'isolated-flash.bin', out / 'usb/diagnostic.reu']:
                path.unlink(missing_ok=True)
            shutil.rmtree(out / 'run/usb-dir', ignore_errors=True)


def m3_symbols(build_path):
    return {name: int(value, 16) for value, name in
            re.findall(r'al C:([0-9a-fA-F]+) \.([^\s]+)', (build_path / 'm3_kernel.vs').read_text())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/m3-perf')
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--existing-snapshot', action='store_true')
    parser.add_argument('--manifest-name', default='manifests/m3.json')
    parser.add_argument('--host-profile-name', default='build/mandelbrot-host-profile.json')
    parser.add_argument('--baseline-build', type=Path,
                        help='Reuse exact completed baseline artifact directory rather than rebuilding it')
    parser.add_argument('--evidence', type=Path, default=ROOT / 'docs/m3-evidence/verification.json')
    for name in ['emulator', 'config', 'flash', 'settings', 'kickass']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--java', default='java')
    parser.add_argument('--lines', type=int, nargs='+', choices=[128, 64], default=[128, 64])
    parser.add_argument('--categories', nargs='+', choices=[name for name, _ in CATEGORIES[:-1]],
                        default=['execute', 'decode'])
    parser.add_argument('--max-target-seconds', type=int, default=1200)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--keep-inputs', action='store_true')
    parser.add_argument('--sample-mask', type=int, choices=[0, 1, 3, 7, 15, 31, 63, 127], default=0)
    parser.add_argument('--reuse-baseline', type=Path,
                        help='Reuse one completed staged run after exact source, artifact, input and output checks')
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.baseline = (args.baseline or args.out / 'baseline/source').resolve()
    for name in ['evidence', 'emulator', 'config', 'flash', 'settings', 'kickass']:
        setattr(args, name, getattr(args, name).resolve())
    args.out.mkdir(parents=True, exist_ok=True)
    runner_snapshot = args.out / 'profiler-script.py'
    runner_snapshot.write_bytes(Path(__file__).read_bytes())
    result_path = args.out / 'result.json'
    result_path.unlink(missing_ok=True)
    receipt = snapshot(args.baseline, args.evidence, args.existing_snapshot)
    generated = args.out / 'instrumented/source'
    selected = set(args.categories)
    substitutions = instrument(args.baseline, generated, selected, sample_mask=args.sample_mask)
    # Every helper resolves ROOT from the frozen small source tree. No adjacent
    # working native source or ABI2 host linker participates in baseline builds.
    sys.path.insert(0, str(args.baseline / 'scripts'))
    m2, m0 = importlib.import_module('m2'), importlib.import_module('m0')
    benchmark = importlib.import_module('m3_benchmark')
    reference = importlib.import_module('mandelbrot_reference').image
    logical = importlib.import_module('m2_compare').logical_bytes
    results = []
    for line in args.lines:
        uninstrumented_build = args.baseline_build.resolve() if args.baseline_build else args.out / 'baseline' / str(line)
        profiled_build = args.out / 'instrumented' / str(line)
        if args.baseline_build:
            if not args.reuse_baseline:
                raise ValueError('Baseline-build reuse requires completed baseline execution evidence')
            baseline_map = load_json(uninstrumented_build / 'map.json')
            for name, expected in baseline_map['artifact_sha256'].items():
                if digest(uninstrumented_build / name) != expected:
                    raise ValueError(f'Reused baseline artifact changed: {name}')
        else:
            baseline_map = build(args, args.baseline, uninstrumented_build, line, False, (m2, m0))
        profile_map = build(args, generated, profiled_build, line, True, (m2, m0))
        bounds = profile_bounds(args.baseline, profiled_build, selected)
        tail = bounds['instrumented_final_admitted_tail_phi2_bound']
        window = bounds['pal_admission_windows']['vm_video_admit']
        wrapped = window.get('wraps_frame', False)
        original_last = window['last_line'] + (312 if wrapped else 0)
        last_absolute = min(original_last, 369 - (tail + 63) // 63)
        last_line = last_absolute % 312
        if last_absolute < 270:
            raise ValueError('Selected probes cannot fit a useful diagnostic admission window; select fewer categories')
        if last_absolute < original_last:
            substitutions = instrument(args.baseline, generated, selected, last_line, args.sample_mask)
            profile_map = build(args, generated, profiled_build, line, True, (m2, m0), last_line)
            bounds = profile_bounds(args.baseline, profiled_build, selected)
        if bounds['instrumented_final_admitted_tail_phi2_bound'] >= bounds['latest_admission_guard_phi2']:
            raise ValueError('Generated profiler exceeds its diagnostic admission guard')
        if args.prepare_only:
            continue
        if args.reuse_baseline:
            baseline = load_json(args.reuse_baseline)
            supplied = {name: digest(getattr(args, name)) for name in ['emulator', 'config', 'flash', 'settings']}
            if (baseline['artifact_sha256'] != baseline_map['artifact_sha256']
                or baseline['map_sha256'] != digest(uninstrumented_build / 'map.json')
                or baseline['supplied_input_sha256'] != supplied
                or baseline['image_sha256'] != hashlib.sha256(reference()[0]).hexdigest()
                or baseline['retired'] != load_json(args.baseline / args.host_profile_name)['retired']
                or not baseline['scanout']['all_64000_pixels_and_both_output_rows_match']
                or any(int.from_bytes(bytes(baseline['report'][offset:offset + 2]), 'little')
                       for offset in [0x12, 0x14, 0x1a, 0x1e])):
                raise ValueError('Reused baseline does not match complete current frozen execution inputs/output')
        else:
            baseline = collect(args, args.out / 'runs' / str(line) / 'baseline', uninstrumented_build,
                               False, benchmark.Session, logical, reference)
        profiled = collect(args, args.out / 'runs' / str(line) / 'instrumented', profiled_build,
                           True, benchmark.Session, logical, reference)
        if baseline['image_sha256'] != profiled['image_sha256'] or baseline['retired'] != profiled['retired']:
            raise ValueError('Paired complete-output/retirement checks differ')
        result = dict(cache_line=line, baseline=baseline, instrumented=profiled,
                      reviewed_baseline_frames=receipt['reviewed_frames'].get(str(line)),
                      observed_instrumentation_elapsed_frames=profiled['elapsed_frames'] - baseline['elapsed_frames'],
                      observed_instrumentation_phi2_ticks_estimate=(profiled['elapsed_frames'] - baseline['elapsed_frames']) * FRAME_TICKS,
                      instrumentation_code_bytes=profile_map['resident_assembled_bytes'] - baseline_map['resident_assembled_bytes'],
                      selected_categories=sorted(selected), bounds_sha256=digest(profiled_build / 'profile-bounds.json'),
                      sample_factor=args.sample_mask + 1, baseline_reused_from=str(args.reuse_baseline) if args.reuse_baseline else None,
                      instrumented_last_admission_line=last_line,
                      conservative_instrumented_tail_phi2_bound=bounds['instrumented_final_admitted_tail_phi2_bound'])
        save_json(args.out / str(line) / 'result.json', result)
        results.append(result)
        print(f"Profile{line}: baseline{baseline['elapsed_frames']}frames / instrumented{profiled['elapsed_frames']}frames; output verified", flush=True)
    if not args.prepare_only:
        snapshot(args.baseline, args.evidence, args.existing_snapshot)
        result = dict(format='COSM3PERFPROFILE1', status='pass', baseline_receipt=receipt,
                      generated_substitutions=substitutions, profiler_script_sha256=digest(runner_snapshot),
                      profiler_source_sha256=digest(generated / 'native/profile.asm'),
                      profile_ram_first=PROFILE_BASE, profile_ram_bytes=PROFILE_BYTES,
                      categories_are_inclusive=True, variants=results,
                      measurement_model='Coherent live CIA2A PHI2 16-bit interval; every measured call below65536PHI2 including interrupt. Accumulated32-bit totals. Empty probes calibrated before IRQ enable. Nested samples inclusive, not disjoint percentages. Sparse samples are systematically selected and not lifetime-exact totals.',
                      cost_interval_scope='Body excess versus empty wrapper; retains nested probe costs and any interrupt time. Paired total elapsed overhead is observed independently; no opcode-frequency Amdahl inference.',
                      qualification='Autonomous target execution in the existing functional emulator; physical Ultimate timing pending')
        save_json(result_path, result)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        print(f'm3_profile: {error}', file=sys.stderr)
        raise SystemExit(1)
