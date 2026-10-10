#!/usr/bin/env python3
"""Conservatively bound admitted M2/M3 units from assembled control flow."""
import argparse
from bisect import bisect_right
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
# Maximum taken backward edges per subroutine invocation. The initial loop
# iteration is counted separately, so cap15 means at most16 iterations.
LOOP_CAPS = {
    'vm_retire': 7, 'vm_e_shl_loop': 14, 'vm_e_shr_loop': 14,
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


def digest(data):
    return hashlib.sha256(data).hexdigest()


def add(left, right):
    return tuple(a + b for a, b in zip(left, right))


def maxima(choices):
    # Independent maxima for instruction count and I/O count are conservative
    # even when the two maximizing paths differ.
    return tuple(max(choice[index] for choice in choices) for index in range(2))


def analyze(build):
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
    windows = {}
    for entry in ['vm_video_admit', 'vm_dma_admit']:
        start = symbols[entry]
        hook = ram[start:start + 96]
        raster = hook.find(b'\xad\x12\xd0')
        compare = hook[raster + 3:raster + 11] if raster >= 0 else b''
        if len(compare) != 8 or bytes(compare[index] for index in [0, 2, 4, 6]) != b'\xc9\x90\xc9\xb0':
            raise ValueError(f'Unrecognized PAL admission comparisons in {entry}')
        first, last = 256 + compare[1], 255 + compare[5]
        if first > last or last > 311:
            raise ValueError(f'Invalid PAL admission interval in {entry}')
        windows[entry] = dict(first_line=first, last_line=last)
    if windows['vm_video_admit'] != windows['vm_dma_admit']:
        raise ValueError('VM and DMA admission windows differ')
    last_line = windows['vm_video_admit']['last_line']
    guard = (312 - (last_line + 1) + 58) * 63
    named = sorted((address, name) for name, address in symbols.items()
                   if 0x1200 <= address < 0x4000)
    positions = [address for address, _ in named]

    def label(address):
        return named[bisect_right(positions, address) - 1][1]

    handlers = tuple(int.from_bytes(ram[symbols['vm_handlers'] + index * 2:
                                        symbols['vm_handlers'] + index * 2 + 2], 'little')
                     for index in range(57))
    if any(not symbols['vm_e_nop'] <= handler < symbols['vm_tables_start']
           for handler in handlers):
        raise ValueError('The 57-entry interpreter dispatch table is outside VM handlers')
    backedges = {}
    active_functions = set()

    @lru_cache(None)
    def function(entry, last_opcode_only=False):
        if last_opcode_only and entry == symbols['vm_run']:
            # vm_run re-admits each opcode. This summary retains only its final
            # step and the JSR/LDA/BEQ/RTS wrapper, never an entire 128-step run.
            return add(function(symbols['vm_step']), (4, 0))
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
            cost = (1, io)
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
                choices = [path(pc + 2, budgets)]
                destination_label = label(destination)
                if destination < pc and destination_label in (LOOP_CAPS | CONDITIONAL_LOOP_CAPS):
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
    def bound(entry, dma, last_opcode_only=False):
        count, io = function(symbols[entry], last_opcode_only)
        # Include an additional caller JSR, and charge every reachable official
        # opcode7cycles, dominating branch/page-cross costs. Slow I/O receives
        # another full7PHI2cycles per bus access; synchronous DMA is separate.
        cpu = 7 * (count + 1)
        local = (cpu + 47) // 48 + 7 * io
        return dict(instruction_visits=count, cpu_cycle_upper_bound=cpu,
                    io_access_upper_bound=io, cpu_io_phi2_upper_bound=local,
                    dma_phi2_allowance=dma,
                    conditional_total_phi2_upper_bound=local + dma)

    results = {entry: bound(entry, 0 if entry == 'vm_step' else 511)
               for entry in ['vm_step', 'cache_service', 'cache_native_read', 'cache_native_write']}
    helpers = {entry: bound(entry, 511 if entry in ['jobs_step', 'scheduler_native_phase'] else 0)
               for entry in HELPERS if entry in symbols} if m3 else {}
    audit = {}
    if m3:
        for entry in ['scheduler_vm_result', 'scheduler_vm_phase', 'scheduler_tick']:
            audit[entry] = bound(entry, 511 if entry == 'scheduler_tick' else 0,
                                 last_opcode_only=True)
        audit['qualification'] = ('These overapproximations summarize vm_run as its final '
                                  're-admitted opcode only; preceding opcode time is excluded. '
                                  'They are not whole-quantum execution bounds. The VM result '
                                  'tail includes fixed syscall acceptance and context saving.')
    return dict(format='COSM3STATICBOUND1' if m3 else 'COSM2STATICBOUND1',
                build_format=spec['format'], native_ram_first=native_origin,
                extended_diagnostics=spec.get('extended_diagnostics', True),
                build_tag=spec['build_tag'],
                cache_line_bytes=spec['cache_line_bytes'], artifact_sha256=spec['artifact_sha256'],
                map_sha256=digest(map_bytes), checker_sha256=digest(Path(__file__).read_bytes()),
                uniform_cycles_per_instruction=7,
                qualified_model_fast_cycles_per_phi2=48, extra_phi2_per_io_access=7,
                pal_admission_windows=windows, pal_lines_per_frame=312,
                pal_phi2_per_line=63, next_raster_irq_line=58,
                latest_admission_guard_phi2=guard, loops=LOOP_CAPS,
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, default=ROOT / 'build/m2/128')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.out:
        args.out.unlink(missing_ok=True)
    result = analyze(args.build.resolve())
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
