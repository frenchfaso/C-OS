#!/usr/bin/env python3
"""Conservatively bound admitted M2/M3 units from assembled control flow."""
import argparse
from bisect import bisect_right
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
# Maximum taken backward edges per subroutine invocation. The initial loop
# iteration is counted separately, so cap15 means at most16 iterations.
LOOP_CAPS = {
    'vm_retire': 7, 'vm_multiply_bit': 15, 'vm_e_shl_loop': 14, 'vm_e_shr_loop': 14,
    'vm_e_sar_loop': 14, 'vm_e_token_increment': 7,
    'cache_unpin': 15, 'cache_require_data': 7, 'cache_clock_scan': 15,
    'cache_code_hit': 3, 'cache_read_byte': 2, 'cache_write_byte': 2,
    'cache_native_begin': 2, 'cache_native_transfer': 2,
    'cache_native_dma': 2, 'cache_native_find_dirty': 7,
    'cache_native_write_done': 15,
    'cache_invalidate_scan': 15,
    'vm_save_loop': 95, 'vm_load_loop': 95,
    'scheduler_enqueue': 4, 'scheduler_dequeue': 2,
    'scheduler_has_job': 3, 'scheduler_native_scan': 3,
    'scheduler_remove_scan': 4, 'scheduler_remove_shift': 3,
    'scheduler_wake_reu': 3, 'scheduler_wake_timed_scan': 3,
    'jobs_memory_ready': 2, 'jobs_overlap_order': 2,
    'jobs_validate': 2, 'jobs_validate_last': 2,
    'jobs_validate_code': 2, 'jobs_validate_code_end': 2,
    'jobs_error_outputs': 15, 'jobs_clear_outputs': 7,
}
# These retries are bounded by the timing model, rather than a finite counter.
# Seven instructions and three I/O reads occupy at most23PHI2 under this model.
# A torn high-low-high read can therefore cross at most one low-byte rollover;
# its immediately following retry finishes before the next256PHI2 rollover.
CONDITIONAL_LOOP_CAPS = {'scheduler_timer_read': 1}
HELPERS = [
    'jobs_step', 'jobs_accept', 'jobs_validate', 'jobs_complete',
    'scheduler_native_phase', 'scheduler_select', 'scheduler_cancel_current',
    'scheduler_wake_reu', 'scheduler_wake_timed', 'scheduler_frame_tick',
    'scheduler_enqueue', 'scheduler_dequeue', 'scheduler_has_job',
    'scheduler_timer_read', 'scheduler_account_native',
    'cache_invalidate_owner',
]
BRANCHES = {0x10, 0x30, 0x50, 0x70, 0x90, 0xb0, 0xd0, 0xf0}
IO_RMW = {0x0e, 0x1e, 0x2e, 0x3e, 0x4e, 0x5e, 0x6e, 0x7e,
          0xce, 0xde, 0xee, 0xfe}
# Official NMOS instructions reachable in these modules. Unknown opcodes and
# unrecognized cycles fail closed rather than receiving an assumed bound.
LENGTHS = {}
for length, opcodes in [
    (1, '0a 4a 2a 6a 18 38 58 78 b8 d8 f8 aa 8a a8 98 ba 9a e8 ca c8 88 '
        '48 08 68 28 60 40 ea'),
    (2, 'a9 a5 b5 a1 b1 85 95 81 91 a2 a6 b6 86 96 a0 a4 b4 84 94 '
        'c9 c5 d5 c1 d1 e0 e4 c0 c4 69 65 75 61 71 e9 e5 f5 e1 f1 '
        '29 25 35 21 31 09 05 15 01 11 49 45 55 41 51 24 '
        '06 16 46 56 26 36 66 76 e6 f6 c6 d6 10 30 50 70 90 b0 d0 f0'),
    (3, 'ad bd b9 8d 9d 99 ae be 8e ac bc 8c cd dd d9 ec cc '
        '6d 7d 79 ed fd f9 2d 3d 39 0d 1d 19 4d 5d 59 2c '
        '0e 1e 4e 5e 2e 3e 6e 7e ee fe ce de 4c 6c 20'),
]:
    LENGTHS.update({int(opcode, 16): length for opcode in opcodes.split()})

# MOS Technology, MCS6500 Hardware Manual, publication6500-10A (Jan1976),
# AppendixA. Every variable-page read and branch receives its worst case.
# Original-manufacturer cycle diagrams are transcribed at the reference URL;
# this is NMOS timing, including dummy RMW writes, rather than CMOS timing.
NMOS_REFERENCE = 'https://xotmatrix.com/6502/6502-single-cycle-execution.html'
CYCLES = {}
for cycles, opcodes in [
    (2, '0a 4a 2a 6a 18 38 58 78 b8 d8 f8 aa 8a a8 98 ba 9a e8 ca c8 88 ea '
        'a9 a2 a0 c9 e0 c0 69 e9 29 09 49'),
    (3, 'a5 a6 a4 c5 e4 c4 65 e5 25 05 45 24 85 86 84 4c 48 08'),
    (4, 'b5 b6 b4 d5 75 f5 35 15 55 95 96 94 ad ae ac cd ec cc '
        '6d ed 2d 0d 4d 2c 8d 8e 8c 10 30 50 70 90 b0 d0 f0 68 28'),
    (5, 'bd b9 be bc dd d9 7d 79 fd f9 3d 39 1d 19 5d 59 9d 99 '
        '06 26 46 66 e6 c6 6c'),
    (6, 'a1 c1 61 e1 21 01 41 81 b1 d1 71 f1 31 11 51 91 '
        '0e 2e 4e 6e ee ce 16 36 56 76 f6 d6 60 40 20'),
    (7, '1e 3e 5e 7e fe de'),
]:
    CYCLES.update({int(opcode, 16): cycles for opcode in opcodes.split()})
if CYCLES.keys() != LENGTHS.keys():
    raise ValueError('Every recognized NMOS instruction needs an explicit cycle maximum')


def verify_cpu_core(directory):
    """Cross-check actual legal micro-op patterns, not unused cycle metadata."""
    table = (directory / 'tables.rs').read_text()
    cpu = (directory / 'cpu.rs').read_text()
    entries = {int(opcode, 16): pattern for opcode, pattern in re.findall(
        r't\[0x([0-9a-f]+)\] = e\("[a-z]+", "[a-z]+", [0-9]+, "([a-z_]+)"\);', table)}
    patterns = {name: len(re.findall(r'"[a-z_]+"', operations)) for name, operations in re.findall(
        r'"([a-z_]+)" => &\[([^\]]+)\]', table)}
    for opcode, maximum in CYCLES.items():
        pattern = entries.get(opcode)
        if pattern not in patterns:
            raise ValueError(f'CPU core has no explicit legal pattern for ${opcode:02x}')
        extra = 2 if pattern == 'rel' else int(pattern in ('absx_read', 'absy_read', 'indy_read'))
        if patterns[pattern] + extra != maximum:
            raise ValueError(f'CPU core and NMOS cycle maximum disagree for ${opcode:02x}')
    # These reviewed engine hooks add the conditional branch/page-cross cycles.
    # The legal path uses microcode.len(), not MicroEntry.cycles. The latter has
    # inconsistent EOR metadata in this backend and is not a timing authority.
    for required in ('microcode.len()', 'branch taken = +1 cycle', 'page cross = +1',
                     '"read_ea_pgx"', '"read_ea_pgy"'):
        if required not in cpu:
            raise ValueError('Unrecognized CPU microcode execution: ' + required)
    return dict(official_opcodes_checked=len(CYCLES), actual_microcode_patterns=True,
                tables_sha256=digest(table.encode()), cpu_sha256=digest(cpu.encode()),
                nominal_cycle_field_used=False)


def check_admission(report):
    """Reject a window that cannot finish every audited admitted unit/tail."""
    candidates = dict(report['results'])
    candidates.update({name: bound for name, bound in report['last_opcode_admission_audit'].items()
                       if isinstance(bound, dict)})
    for name, bound in candidates.items():
        guards = report.get('admission_guard_phi2', {})
        domain = ('vm' if name.startswith('vm_step') or name == 'late_vm_return_tail' else
                  'dma' if name.startswith('cache_') else 'scheduler')
        guard = guards.get(domain, report['latest_admission_guard_phi2'])
        if bound['conditional_total_phi2_upper_bound'] >= guard:
            raise ValueError(f'Unsafe admission: {name} reaches the next raster IRQ guard')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def add(left, right):
    return tuple(a + b for a, b in zip(left, right))


def maxima(choices):
    # Independent maxima for instruction count, I/O count and CPU cycles are conservative
    # even when the two maximizing paths differ.
    return tuple(max(choice[index] for choice in choices) for index in range(3))


def relative(opcode, address, target):
    """Encode a reviewed branch; a changed/out-of-range target fails closed."""
    displacement = target - (address + 2)
    if not -128 <= displacement <= 127:
        raise ValueError('Admission branch target is out of range')
    return bytes((opcode, displacement & 255))


def admission_windows(ram, symbols, m3):
    """Recognize complete assembled hooks, including gating and return edges.

    Matching only a D012/CMP fragment cannot prove admission: an inverted
    D011 branch or a changed branch target could also match that fragment.
    Keep the legacy hook exact, and reject an unreviewed replacement.
    """
    prefix = 'm3' if m3 else 'm2'
    safe = symbols[prefix + '_admission_safe']
    if ram[safe:safe + 2] != b'\x18\x60':
        raise ValueError('Unrecognized admission success return')
    coherent = m3 and 'm3_raster_admit' in symbols
    split = coherent and 'm3_vm_raster_admit' in symbols
    if coherent:
        raster = symbols['m3_raster_admit']
        post, reject = symbols['m3_raster_post'], symbols['m3_raster_reject']
        early_end, post_first, post_end = ram[raster + 9], ram[post + 4], ram[post + 8]
        if (early_end, post_first, post_end) not in ((21, 4, 56), (11, 4, 56), (0, 24, 44)):
            raise ValueError('Unrecognized coherent PAL admission intervals')
        signature = bytearray(b'\x2c\x11\xd0')
        signature += relative(0x30, raster + len(signature), post)
        signature += b'\xad\x12\xd0\xc9' + bytes((early_end,))
        signature += relative(0xb0, raster + len(signature), reject)
        signature += b'\x2c\x11\xd0'
        signature += relative(0x30, raster + len(signature), reject)
        signature += b'\x18\x60'
        if raster + len(signature) != post:
            raise ValueError('Unrecognized coherent PAL post-frame entry')
        signature += b'\xad\x12\xd0\xc9' + bytes((post_first,))
        signature += relative(0x90, raster + len(signature), reject)
        signature += b'\xc9' + bytes((post_end,))
        signature += relative(0xb0, raster + len(signature), reject)
        signature += b'\x2c\x11\xd0'
        signature += relative(0x10, raster + len(signature), reject)
        signature += b'\x18\x60'
        if raster + len(signature) != reject:
            raise ValueError('Unrecognized coherent PAL rejection entry')
        signature += b'\x38\x60'
        if ram[raster:raster + len(signature)] != signature:
            raise ValueError('Unrecognized coherent PAL raster admission function')
        if split:
            vm_raster = symbols['m3_vm_raster_admit']
            vm_early_end = ram[vm_raster + 9]
            if (vm_early_end, early_end, post_first, post_end) not in ((51, 21, 4, 56), (0, 0, 24, 44)):
                raise ValueError('Unrecognized separate VM PAL admission intervals')
            vm_signature = bytearray(b'\x2c\x11\xd0')
            vm_signature += relative(0x30, vm_raster + len(vm_signature), post)
            vm_signature += b'\xad\x12\xd0\xc9' + bytes((vm_early_end,))
            vm_signature += relative(0xb0, vm_raster + len(vm_signature), reject)
            vm_signature += b'\x2c\x11\xd0'
            vm_signature += relative(0x30, vm_raster + len(vm_signature), reject)
            vm_signature += b'\x18\x60'
            if (vm_raster + len(vm_signature) != raster or
                    ram[vm_raster:raster] != vm_signature):
                raise ValueError('Unrecognized separate coherent VM admission function')
    windows = {}
    hooks = [('vm_video_admit', 'video'), ('vm_dma_admit', 'dma')]
    if split:
        hooks.append(('scheduler_video_admit', 'video'))
    for entry, kind in hooks:
        start = symbols[entry]
        deferred = symbols[prefix + '_' + kind + '_deferred']
        counter = ({'video': 0x0316, 'dma': 0x0318} if m3 else
                   {'video': 0xfe05, 'dma': 0xfe07})[kind]
        tail = (b'\xee' + counter.to_bytes(2, 'little') + b'\xd0\x03\xee' +
                (counter + 1).to_bytes(2, 'little') + b'\x38\x60')
        if ram[deferred:deferred + len(tail)] != tail:
            raise ValueError(f'Unrecognized admission deferral return in {entry}')
        expected = bytearray((0xa5, symbols['nmi_pending']))
        expected += relative(0xd0, start + len(expected), deferred)
        expected += b'\xad\xb1\x03'
        expected += relative(0xf0, start + len(expected), safe)
        if kind == 'dma':
            for address in (0x0337, 0x034b):
                expected += b'\xad' + address.to_bytes(2, 'little') + b'\xc9\x02'
                expected += relative(0xb0, start + len(expected), deferred)
        if coherent:
            selected_raster = vm_raster if split and entry == 'vm_video_admit' else raster
            selected_early_end = vm_early_end if split and entry == 'vm_video_admit' else early_end
            expected += b'\x20' + selected_raster.to_bytes(2, 'little')
            expected += relative(0xb0, start + len(expected), deferred)
            expected += b'\x18\x60'
            if ram[start:start + len(expected)] != expected:
                raise ValueError(f'Unrecognized coherent PAL admission hook in {entry}')
            intervals = ([dict(first_line=0, last_line=selected_early_end - 1)] if selected_early_end else [])
            intervals += [dict(first_line=256 + post_first, last_line=255 + post_end)]
            windows[entry] = dict(first_line=256 + post_first,
                                 last_line=selected_early_end - 1 if selected_early_end else 255 + post_end,
                                 wraps_frame=bool(selected_early_end), coherent_high_low_high=True,
                                 intervals=intervals)
            continue
        expected += b'\x2c\x11\xd0'
        expected += relative(0x10, start + len(expected), deferred)
        expected += b'\xad\x12\xd0\xc9'
        first_offset = ram[start + len(expected)]
        expected.append(first_offset)
        expected += relative(0x90, start + len(expected), deferred)
        expected.append(0xc9)
        last_exclusive = ram[start + len(expected)]
        expected.append(last_exclusive)
        expected += relative(0xb0, start + len(expected), deferred)
        expected += b'\x18\x60'
        if ram[start:start + len(expected)] != expected:
            raise ValueError(f'Unrecognized PAL admission hook in {entry}')
        first, last = 256 + first_offset, 255 + last_exclusive
        if first > last or last > 311:
            raise ValueError(f'Invalid PAL admission interval in {entry}')
        windows[entry] = dict(first_line=first, last_line=last)
    if split and windows['scheduler_video_admit'] != windows['vm_dma_admit']:
        raise ValueError('Scheduler and DMA admission windows differ')
    if not split and windows['vm_video_admit'] != windows['vm_dma_admit']:
        raise ValueError('VM and DMA admission windows differ')
    return windows


def admission_guard(windows, entry='vm_video_admit'):
    """Distance from the latest admitted line's end to the next IRQ58."""
    window = windows[entry]
    intervals = window.get('intervals', [window])
    return min(((58 - (interval['last_line'] + 1)) % 312) * 63
               for interval in intervals)


def verify_map_windows(spec, windows):
    """A map label cannot qualify different admission bytes or a wider window."""
    if 'runtime_admission_first_line' not in spec:
        return  # Small independently encoded unit-test maps have no policy fields.
    intervals = windows['vm_video_admit'].get('intervals', [windows['vm_video_admit']])
    described = [dict(first_line=spec['runtime_admission_first_line'],
                      last_line=spec['runtime_admission_last_line'])]
    early = spec.get('runtime_admission_early_last_line')
    if early is not None:
        described.insert(0, dict(first_line=spec['runtime_admission_early_first_line'],
                                 last_line=early))
    actual = [dict(first_line=value['first_line'], last_line=value['last_line'])
              for value in intervals]
    if described != actual or spec['latest_admission_guard_phi2'] != admission_guard(windows):
        raise ValueError('Build map admission windows differ from the assembled hooks')
    if 'scheduler_video_admit' in windows:
        for prefix, entry in (('scheduler', 'scheduler_video_admit'), ('dma', 'vm_dma_admit')):
            early = next((value['last_line'] for value in windows[entry]['intervals']
                          if value['first_line'] == 0), None)
            if (spec.get(prefix + '_admission_early_last_line') != early or
                    spec.get(prefix + '_latest_admission_guard_phi2') != admission_guard(windows, entry)):
                raise ValueError('Build map separate admission windows differ from the assembled hooks')


def verify_split_scheduler(ram, symbols):
    """Prove all tick VM returns and the re-admitted native fallback edge."""
    tick = symbols['scheduler_tick']
    vm_first = symbols['scheduler_tick_vm_first']
    done = symbols['scheduler_tick_done']
    vm_done = symbols['scheduler_tick_vm_done']
    native_done = symbols['scheduler_tick_native_done']
    body = bytearray(b'\xad\x0d\xfe')

    def branch(opcode, target):
        body.extend(relative(opcode, tick + len(body), target))

    def call(name):
        body.extend(b'\x20' + symbols[name].to_bytes(2, 'little'))

    branch(0xf0, done)
    call('scheduler_video_admit')
    branch(0xb0, done)
    body += b'\xad\x0e\xfe\xf0\x13\x38\xe9\x01\x29\x03'
    call('scheduler_select')
    call('scheduler_cancel_current')
    body += b'\xa9\x00\x8d\x0e\xfe\xee\x0f\xfe'
    call('scheduler_wake_timed')
    body += b'\xad\x0a\xfe'
    branch(0xf0, vm_first)
    call('scheduler_native_phase')
    branch(0x90, native_done)
    call('scheduler_vm_phase')
    body += b'\x60'
    if tick + len(body) != vm_first:
        raise ValueError('Unrecognized scheduler VM-first entry')
    call('scheduler_vm_phase')
    branch(0x90, vm_done)
    call('scheduler_video_admit')
    fallback_branch = tick + len(body)
    branch(0xb0, done)
    call('scheduler_native_phase')
    body += b'\x60'
    if tick + len(body) != vm_done:
        raise ValueError('Unrecognized scheduler VM-done entry')
    body += b'\xa9\x01\x8d\x0a\xfe\x60'
    if tick + len(body) != native_done:
        raise ValueError('Unrecognized scheduler native-done entry')
    body += b'\xa9\x00\x8d\x0a\xfe'
    if tick + len(body) != done:
        raise ValueError('Unrecognized scheduler final return')
    body += b'\x60'
    if ram[tick:tick + len(body)] != body or tick + len(body) != symbols['scheduler_vm_phase']:
        raise ValueError('Unrecognized separately admitted scheduler tick')
    # Both full-run and native-job one-op paths enter exactly the result tail.
    timestamp = symbols['scheduler_vm_timestamp_done']
    result = symbols['scheduler_vm_result']
    single = symbols['scheduler_vm_single']
    dispatch = (b'\x20' + symbols['scheduler_has_job'].to_bytes(2, 'little') +
                relative(0xb0, timestamp + 3, single) +
                b'\x20' + symbols['vm_run'].to_bytes(2, 'little') +
                b'\x4c' + result.to_bytes(2, 'little') +
                b'\x20' + symbols['vm_step'].to_bytes(2, 'little'))
    if single != timestamp + 11 or result != timestamp + len(dispatch) or ram[timestamp:result] != dispatch:
        raise ValueError('Unrecognized scheduler VM result dispatch')
    return dict(refused_fallback_branch=fallback_branch,
                vm_first_return_suffix=vm_first + 3, native_first_return_suffix=vm_first - 1,
                native_fallback_rechecks_scheduler_admission=True,
                every_vm_call_enters_result_tail=True)


def verify_active_classifier(ram, symbols):
    """Prove finite reporting for stable reads and both PAL high-bit tears."""
    active = symbols['raster_active']
    inactive = symbols['m3_not_active']
    yes = symbols['m3_is_active']
    post = active + 19
    signature = bytearray(b'\x2c\x11\xd0')
    signature += relative(0x30, active + len(signature), post)
    signature += b'\xad\x12\xd0\xc9\x3c\x2c\x11\xd0'
    signature += relative(0x30, active + len(signature), yes)
    signature += relative(0x90, active + len(signature), inactive)
    signature += b'\x38\x60\xad\x12\xd0\xc9\x04\x2c\x11\xd0'
    signature += relative(0x10, active + len(signature), inactive)
    signature += relative(0x90, active + len(signature), yes)
    signature += b'\x18\x60\x38\x60'
    if (inactive != active + 31 or yes != active + 33 or
            symbols['m3_recover_nmi'] != active + len(signature) or
            ram[active:active + len(signature)] != signature):
        raise ValueError('Unrecognized coherent active-raster classifier')
    completed = symbols['vm_dma_completed']
    counter = (b'\xee\x1d\x03\xad\xb1\x03\xf0\x0d\x20' +
               active.to_bytes(2, 'little') +
               b'\x90\x08\xee\x1a\x03\xd0\x03\xee\x1b\x03\x60')
    if completed + len(counter) != active or ram[completed:active] != counter:
        raise ValueError('Unrecognized active-raster DMA completion counter')
    return dict(active_first_line=60, active_last_line=259,
                coherent_high_low_high=True, retries=0,
                low_to_high_transition_active=True, high_to_low_transition_inactive=True,
                maximum_io_reads_per_call=3, x_y_and_ram_scratch_preserved=True,
                transition_separation_min_phi2=56 * 63,
                qualification='DMA caller masks IRQ through the completion observation; no NMI/recovery; two high-bit transitions cannot occur within the bounded read triplet')


def verify_batch_wrapper(ram, symbols):
    """Prove the four-step structure and the sole skipped video predicate."""
    run, step, admitted = (symbols[name] for name in ('vm_run', 'vm_step', 'vm_step_admitted'))
    expected = (b'\xa9\x03\x8d\xb2\x03\x20' + step.to_bytes(2, 'little') +
                b'\xa5\x47\xd0\x0f\x20' + admitted.to_bytes(2, 'little') +
                b'\xa5\x47\xd0\x08\xce\xb2\x03\xd0\xf4\x4c' +
                run.to_bytes(2, 'little') + b'\x60')
    if (ram[run:run + len(expected)] != expected or symbols['vm_run_block'] != run + 12 or
            symbols['vm_run_return'] != run + 27 or admitted != step + 4):
        raise ValueError('Unrecognized four-step vm_run wrapper')
    video, attempt, boundary = (symbols[name] for name in ('vm_check_video', 'vm_attempt', 'vm_boundary'))
    prelude = (b'\xa2\x01\xd0\x02\xa2\x00\x86\x7f'
               b'\xa5\x47\xc9\x05\xf0\x0c\xc9\x06\xf0\x08'
               b'\xa5\x5c\xf0\x05\xa9\x04\x85\x47\x60'
               b'\xa5\x24\xd0\x05\xa9\x01\x4c' + boundary.to_bytes(2, 'little'))
    gate = (bytes((0xa5, symbols['nmi_pending'])) + b'\xd0\x09\xa5\x7f\xf0\x0a\x20' +
            symbols['vm_video_admit'].to_bytes(2, 'little') + b'\x90\x05\xa9\x07\x4c' +
            boundary.to_bytes(2, 'little'))
    if (video != step + len(prelude) or attempt != video + len(gate) or
            ram[step:video] != prelude or ram[video:attempt] != gate):
        raise ValueError('Unrecognized admitted vm_step video-only bypass')
    return dict(block_instructions=4, additional_admitted_steps=3,
                shared_scratch_flag=0x7f, remaining_counter_address=0x03b2,
                initialized_on_each_block=True, per_step_nmi_check=True,
                following_refused_admission_prefix_included=True)


def verify_valid_pc_wrapper(ram, symbols):
    """Recognize a full first step and a private, already-validated-PC loop."""
    run, step, valid = (symbols[name] for name in ('vm_run', 'vm_step', 'vm_step_valid_pc'))
    wrapper = (b'\x20' + step.to_bytes(2, 'little') + b'\xa5\x47\xd0\x07\x20' +
               valid.to_bytes(2, 'little') + b'\xa5\x47\xf0\xf9\x60')
    if (ram[run:run + len(wrapper)] != wrapper or symbols['vm_run_valid_pc'] != run + 7 or
            symbols['vm_run_return'] != run + 14 or valid != step + 4):
        raise ValueError('Unrecognized validated-current-PC vm_run wrapper')
    video, attempt, boundary = (symbols[name] for name in ('vm_check_video', 'vm_attempt', 'vm_boundary'))
    prelude = (b'\xa2\x01\xd0\x02\xa2\x00\x86\x7f'
               b'\xa5\x47\xc9\x05\xf0\x0c\xc9\x06\xf0\x08'
               b'\xa5\x5c\xf0\x05\xa9\x04\x85\x47\x60'
               b'\xa5\x24\xd0\x05\xa9\x01\x4c' + boundary.to_bytes(2, 'little'))
    gate = (b'\x20' + symbols['vm_video_admit'].to_bytes(2, 'little') +
            b'\x90\x05\xa9\x07\x4c' + boundary.to_bytes(2, 'little'))
    attempt_prefix = (b'\xa9\x00\x85\x78\x85\x7b\x85\x77\x85\x48\x85\x4d'
                      b'\xa5\x1e\x85\x66\xa5\x1f\x85\x67\xa5\x20\x85\x68'
                      b'\xa5\x7f\xf0\x08\x20' + symbols['vm_check_pc'].to_bytes(2, 'little') +
                      b'\x90\x03\x4c' + symbols['vm_fault_boundary'].to_bytes(2, 'little'))
    if (video != step + len(prelude) or attempt != video + len(gate) or
            ram[step:video] != prelude or ram[video:attempt] != gate or
            ram[attempt:attempt + len(attempt_prefix)] != attempt_prefix):
        raise ValueError('Unrecognized validated-current-PC-only bypass')
    return dict(shared_scratch_flag=0x7f, every_entry_first_step_checks_current_pc=True,
                every_step_video_admitted=True, boundary_returns_before_reentry=True,
                qualification='A preceding RUN step published a validated next PC; IRQ preserves VM architecture and bounds; every scheduler/import/standalone entry uses the full first step')


def analyze(build, cpu_core=None):
    map_bytes = (build / 'map.json').read_bytes()
    spec = json.loads(map_bytes)
    if spec['format'] not in ['COSM2MAP1', 'COSM3MAP1'] or spec['cache_line_bytes'] not in [64, 128]:
        raise ValueError('Expected an assembled COSM2MAP1 or COSM3MAP1 build')
    m3 = spec['format'] == 'COSM3MAP1'
    prg_name = 'm3.prg' if m3 else 'm2.prg'
    native_origin = spec.get('native_ram_first', 0x1800)
    if native_origin != (0x1200 if m3 else 0x1800):
        raise ValueError('Unexpected resident native origin')
    symbols = spec['symbols']
    prg = (build / prg_name).read_bytes()
    native = (build / 'native.bin').read_bytes()
    for filename, data in [(prg_name, prg), ('native.bin', native)]:
        if digest(data) != spec['artifact_sha256'][filename]:
            raise ValueError(f'{filename} differs from the build map')
    ram = bytearray(65536)
    origin = int.from_bytes(prg[:2], 'little')
    ram[origin:origin + len(prg) - 2] = prg[2:]
    ram[native_origin:native_origin + len(native)] = native
    windows = admission_windows(ram, symbols, m3)
    verify_map_windows(spec, windows)
    guard = admission_guard(windows)
    batch = verify_batch_wrapper(ram, symbols) if m3 and 'vm_step_admitted' in symbols else None
    valid_pc = verify_valid_pc_wrapper(ram, symbols) if m3 and 'vm_step_valid_pc' in symbols else None
    if batch and valid_pc:
        raise ValueError('Combined dispatch optimizations require a separate review')
    split = verify_split_scheduler(ram, symbols) if 'scheduler_video_admit' in windows else None
    if split and (not valid_pc or batch):
        raise ValueError('Separate late admission requires the reviewed per-opcode VM wrapper')
    active_classifier = verify_active_classifier(ram, symbols) if split else None
    named = sorted((address, name) for name, address in symbols.items()
                   if 0x1200 <= address < 0x4000)
    positions = [address for address, _ in named]

    def label(address):
        return named[bisect_right(positions, address) - 1][1]

    handlers = tuple(int.from_bytes(ram[symbols['vm_handlers'] + index * 2:
                                        symbols['vm_handlers'] + index * 2 + 2], 'little')
                     for index in range(59))
    if any(not symbols['vm_e_nop'] <= handler < symbols['vm_tables_start']
           for handler in handlers):
        raise ValueError('The 59-entry interpreter dispatch table is outside VM handlers')
    backedges = {}
    active_functions = set()

    @lru_cache(None)
    def function(entry, last_opcode_only=False, denied_admission=False, refused_fallback=False):
        if last_opcode_only and entry == symbols['vm_run']:
            if batch:
                # The last admitted block may run one full step and three
                # admitted steps. Charge all four plus the next refused gate
                # before the wrapper can return; preceding successful blocks
                # and their execution time are excluded.
                first = function(symbols['vm_step'])
                following = function(symbols['vm_step_admitted'])
                refused = function(symbols['vm_step'], denied_admission=True)
                return add(add(first, tuple(3 * cost for cost in following)),
                           add(refused, (27, 0, 116)))
            if valid_pc:
                last = maxima([function(symbols['vm_step']), function(symbols['vm_step_valid_pc'])])
                if split:
                    refused = maxima([function(symbols['vm_step'], denied_admission=True),
                                       function(symbols['vm_step_valid_pc'], denied_admission=True)])
                    return add(add(last, refused), (7, 0, 32))
                return add(last, (4, 0, 19))
            # vm_run re-admits each opcode. This summary retains only its final
            # step and the JSR/LDA/BEQ/RTS wrapper, never an entire 128-step run.
            wrapper = ram[entry:entry + 8]
            if (wrapper[0] != 0x20 or int.from_bytes(wrapper[1:3], 'little') != symbols['vm_step']
                    or wrapper[3] != 0xa5 or wrapper[5] != 0xf0 or wrapper[6] != 0xf9
                    or wrapper[7] != 0x60):
                raise ValueError('Unrecognized final-opcode vm_run wrapper')
            return add(function(symbols['vm_step']), (4, 0, 6 + 3 + 4 + 6))
        if entry in active_functions:
            raise ValueError(f'Recursive native call at {label(entry)}')
        active_functions.add(entry)
        active_paths = set()

        @lru_cache(None)
        def path(pc, budgets):
            key = (pc, budgets)
            if key in active_paths:
                raise ValueError(f'Unbounded native cycle at ${pc:04x} ({label(pc)})')
            active_paths.add(key)
            opcode = ram[pc]
            if opcode not in LENGTHS:
                raise ValueError(f'Unknown opcode ${opcode:02x} at ${pc:04x}')
            length = LENGTHS[opcode]
            target = int.from_bytes(ram[pc + 1:pc + 3], 'little')
            io = 0
            if length == 3 and opcode not in [0x20, 0x4c, 0x6c] and 0xd000 <= target <= 0xdfff:
                io = 3 if opcode in IO_RMW else 1
            if opcode not in CYCLES:
                raise ValueError(f'No explicit NMOS cycle maximum for ${opcode:02x}')
            cost = (1, io, CYCLES[opcode])
            if opcode in [0x60, 0x40]:
                result = cost
            elif opcode == 0x20:
                result = add(cost, add(function(target, last_opcode_only), path(pc + 3, budgets)))
            elif opcode == 0x4c:
                result = add(cost, path(target, budgets))
            elif opcode == 0x6c:
                if not symbols['vm_execute'] <= pc < symbols['vm_e_nop']:
                    raise ValueError(f'Unrecognized indirect jump at ${pc:04x}')
                result = add(cost, maxima([path(handler, budgets) for handler in handlers]))
            elif opcode in BRANCHES:
                offset = ram[pc + 1]
                destination = (pc + 2 + (offset if offset < 128 else offset - 256)) & 0xffff
                forced = None
                if batch and entry in (symbols['vm_step'], symbols['vm_step_admitted']):
                    if pc == symbols['vm_step'] + 2:
                        forced = True  # Verified LDX #1 / BNE skips LDX #0.
                    elif pc == symbols['vm_check_video'] + 6:
                        forced = entry == symbols['vm_step_admitted']
                    elif pc == symbols['vm_check_video'] + 11 and denied_admission:
                        forced = False  # Only the next refused admission prefix.
                if valid_pc and entry in (symbols['vm_step'], symbols['vm_step_valid_pc']):
                    if pc == symbols['vm_step'] + 2:
                        forced = True
                    elif pc == symbols['vm_attempt'] + 26:
                        forced = entry == symbols['vm_step_valid_pc']
                    elif pc == symbols['vm_check_video'] + 3 and denied_admission:
                        forced = False  # Verified BCC vm_attempt after the gate.
                if split and refused_fallback and pc == split['refused_fallback_branch']:
                    forced = True  # Exact scheduler-gate BCS refuses native fallback.
                choices = [] if forced is True else [path(pc + 2, budgets)]
                destination_label = label(destination)
                if forced is False:
                    pass
                elif destination < pc and destination_label in (LOOP_CAPS | CONDITIONAL_LOOP_CAPS):
                    conditional = destination_label in CONDITIONAL_LOOP_CAPS
                    cap = (CONDITIONAL_LOOP_CAPS if conditional else LOOP_CAPS)[destination_label]
                    used = dict(budgets).get(pc, 0)
                    backedges[f'{pc:04x}'] = dict(target=destination,
                                                label=destination_label, taken_edge_cap=cap,
                                                basis='conditional timer rollover' if conditional else 'structural loop')
                    if used < cap:
                        changed = dict(budgets)
                        changed[pc] = used + 1
                        choices.append(path(destination, tuple(sorted(changed.items()))))
                else:
                    # Backward error/return edges are harmless. A new cyclic
                    # backedge without an explicit cap is rejected by path().
                    choices.append(path(destination, budgets))
                result = add(cost, maxima(choices))
            else:
                result = add(cost, path(pc + length, budgets))
            active_paths.remove(key)
            return result

        result = path(entry, ())
        active_functions.remove(entry)
        return result

    sys.setrecursionlimit(20000)
    def finish_bound(value, dma):
        count, io, cycles = value
        # Include a caller JSR6; retain the prior uniform7 comparison alongside
        # the explicit NMOS maximum. Slow I/O7PHI2/access and DMA are unchanged.
        cpu = cycles + CYCLES[0x20]
        uniform = 7 * (count + 1)
        local = (cpu + 47) // 48 + 7 * io
        return dict(instruction_visits=count, cpu_cycle_upper_bound=cpu,
                    uniform_cpu_cycle_upper_bound=uniform,
                    uniform_cpu_io_phi2_upper_bound=(uniform + 47) // 48 + 7 * io,
                    uniform_conditional_total_phi2_upper_bound=(uniform + 47) // 48 + 7 * io + dma,
                    io_access_upper_bound=io, cpu_io_phi2_upper_bound=local,
                    dma_phi2_allowance=dma,
                    conditional_total_phi2_upper_bound=local + dma)

    def bound(entry, dma, last_opcode_only=False):
        return finish_bound(function(symbols[entry], last_opcode_only), dma)

    results = {entry: bound(entry, 0 if entry == 'vm_step' else 511)
               for entry in ['vm_step', 'cache_service', 'cache_native_read', 'cache_native_write']}
    if batch:
        results['vm_step_admitted'] = bound('vm_step_admitted', 0)
    if valid_pc:
        results['vm_step_valid_pc'] = bound('vm_step_valid_pc', 0)
    helpers = {entry: bound(entry, 511 if entry in ['jobs_step', 'scheduler_native_phase'] else 0)
               for entry in HELPERS if entry in symbols} if m3 else {}
    audit = {}
    if m3:
        for entry in ['scheduler_vm_result', 'scheduler_vm_phase', 'scheduler_tick']:
            audit[entry] = bound(entry, 511 if entry == 'scheduler_tick' else 0,
                                 last_opcode_only=True)
        if split:
            last = maxima([function(symbols['vm_step']), function(symbols['vm_step_valid_pc'])])
            refused = maxima([function(symbols['vm_step'], denied_admission=True),
                               function(symbols['vm_step_valid_pc'], denied_admission=True)])
            returns = maxima([
                function(split['vm_first_return_suffix'], refused_fallback=True),
                function(split['native_first_return_suffix'])])
            # Last admitted step can return RUN, then one more step refuses
            # video or stops for zero credit. Include both JSRs and both wrapper
            # tests/return, the fixed JMP to the complete result tail, and the
            # final tick suffix. A successful fallback has a new scheduler gate
            # and is independently bounded by the scheduler admission guard.
            late = add(add(last, refused), add((8, 0, 35),
                       add(function(symbols['scheduler_vm_result']), returns)))
            audit['late_vm_return_tail'] = finish_bound(late, 0)
            audit['late_vm_return_tail']['components'] = {
                'last_admitted_step': finish_bound(last, 0),
                'following_refused_or_zero_credit_step': finish_bound(refused, 0),
                'result_tail': finish_bound(function(symbols['scheduler_vm_result']), 0),
                'tick_return_or_refused_fallback': finish_bound(returns, 0)}
        audit['qualification'] = (('These overapproximations summarize vm_run as its final '
                                  'bounded four-instruction block plus its following refused '
                                  'admission prefix; preceding successful block time is excluded. '
                                  'They are not whole-quantum execution bounds. The VM result '
                                  'tail includes fixed syscall acceptance and context saving.') if batch else
                                 ('These overapproximations summarize vm_run as its final '
                                  're-admitted opcode only; preceding opcode time is excluded. '
                                  'They are not whole-quantum execution bounds. The VM result '
                                  'tail includes fixed syscall acceptance and context saving.'))
        if split:
            audit['qualification'] += (' The separate late-VM tail excludes the already executed '
                'scheduler prefix, includes a following refused VM entry and the complete result '
                'tail, and proves both tick return paths. Native fallback refusal is forced only '
                'at the verified scheduler-gate branch; successful fallback is qualified by its '
                'new scheduler admission. Interrupt/recovery assumptions remain conditional.')
    report = dict(format='COSM3STATICBOUND1' if m3 else 'COSM2STATICBOUND1',
                build_format=spec['format'], native_ram_first=native_origin,
                extended_diagnostics=spec.get('extended_diagnostics', True),
                build_tag=spec['build_tag'],
                cache_line_bytes=spec['cache_line_bytes'], artifact_sha256=spec['artifact_sha256'],
                map_sha256=digest(map_bytes), checker_sha256=digest(Path(__file__).read_bytes()),
                uniform_cycles_per_instruction=7,
                cpu_cycle_model='Official NMOS per-opcode maxima; page-cross reads and branches use worst case',
                cpu_cycle_reference=NMOS_REFERENCE,
                opcode_cycle_maxima={f'{opcode:02x}': cycles for opcode, cycles in sorted(CYCLES.items())},
                cpu_core_verification=verify_cpu_core(cpu_core) if cpu_core is not None else None,
                qualified_model_fast_cycles_per_phi2=48, extra_phi2_per_io_access=7,
                pal_admission_windows=windows, pal_lines_per_frame=312,
                bounded_dispatch_block=batch,
                validated_current_pc_loop=valid_pc,
                pal_phi2_per_line=63, next_raster_irq_line=58,
                latest_admission_guard_phi2=guard, loops=LOOP_CAPS,
                separate_admission_domains=split,
                active_raster_reporting=active_classifier,
                admission_guard_phi2=dict(vm=guard,
                    scheduler=admission_guard(windows, 'scheduler_video_admit') if split else guard,
                    dma=admission_guard(windows, 'vm_dma_admit')),
                conditional_loops=CONDITIONAL_LOOP_CAPS if m3 else {}, backedges=backedges,
                results=results, separately_bounded_helpers=helpers,
                last_opcode_admission_audit=audit,
                timer_read_model=dict(read_triplet_instruction_visits=7,
                                      read_triplet_io_accesses=3,
                                      read_triplet_phi2_upper_bound=23,
                                      low_byte_rollover_period_phi2=256,
                                      retry_taken_edge_cap=1,
                                      assumptions='Continuous CIA timer, no external reprogramming; no IRQ or repeated NMI interruption spanning a 256-PHI2 period during the read') if m3 else None,
                structural_preconditions='VM contexts are 96 bytes; at most four process slots and four runnable queue entries; scalar width 1..3; cache has 16 entries',
                qualification='Conditional fixed emulated turbo profile; physical memory/I/O/DMA stall bounds pending',
                scope='Admitted results cover one vm_step or one service/native call. M3 helper results are separate call bounds, not an admission guarantee for scheduler_tick or vm_run; vm_run rechecks admission before every opcode. Initialization, outer recovery polling, IRQ and NMI time are excluded')
    check_admission(report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, default=ROOT / 'build/m2/128')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--cpu-core', type=Path, help='Cross-check local trx64-core src/tables.rs and src/cpu.rs')
    args = parser.parse_args()
    if args.out:
        args.out.unlink(missing_ok=True)
    result = analyze(args.build.resolve(), args.cpu_core.resolve() if args.cpu_core else None)
    encoded = json.dumps(result, indent=2) + '\n'
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded)
    print(encoded, end='')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, IndexError, RecursionError) as error:
        print(f'm2_bounds: {error}', file=sys.stderr)
        sys.exit(1)
