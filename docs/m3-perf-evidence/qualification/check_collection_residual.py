#!/usr/bin/env python3
"""Reproduce the extra polling-gate residual without modifying source or RAM.

Run from the C-OS repository root. sys.settrace captures the verified checker's
existing function/finish_bound closures when analyze returns. It changes no
instructions, admission branch choices, source files or build inputs.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path.cwd()
checker = ROOT / 'scripts/m2_bounds.py'
spec = importlib.util.spec_from_file_location('collection_bounds', checker)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

rows = []
for variant in ('128', '64', 'larger-128', 'larger-64'):
    state = {}

    def trace(frame, event, arg):
        if frame.f_code is module.analyze.__code__ and event == 'return':
            state.update(function=frame.f_locals['function'],
                         finish=frame.f_locals['finish_bound'],
                         symbols=frame.f_locals['symbols'])
        return trace

    sys.settrace(trace)
    try:
        report = module.analyze(ROOT / 'build/m3-perf/final-candidate' / variant)
    finally:
        sys.settrace(None)
    raw = state['function'](state['symbols']['scheduler_video_admit'])
    hook = state['finish'](raw, 0)
    assert raw == (22, 3, 89)
    assert hook['conditional_total_phi2_upper_bound'] == 23
    # Reviewed scheduler_tick's top gate is followed by BCS tick_done/RTS.
    # Worst branch4 + RTS6 fast cycles, separately rounded: ceil(10/48) = 1.
    suffix = 1
    first = report['last_opcode_admission_audit']['scheduler_tick'][
        'conditional_total_phi2_upper_bound']
    total = hook['conditional_total_phi2_upper_bound'] + suffix + first + 1
    assert total == 2071 and total < 40 * 63
    rows.append(dict(variant=variant, scheduler_video_admit=hook,
                     refused_tick_branch_and_return_phi2=suffix,
                     polling_residual_allowance_phi2=24,
                     scheduler_first_unit_upper_phi2=first,
                     outer_bridge_allowance_phi2=1,
                     window_first_unit_upper_phi2=total,
                     complete_window_phi2=2520,
                     complete_window_slack_phi2=2520-total,
                     map_sha256=report['map_sha256'],
                     native_sha256=report['artifact_sha256']['native.bin'],
                     checker_sha256=hashlib.sha256(checker.read_bytes()).hexdigest()))

print(json.dumps(dict(format='COSM3COLLECTIONRESIDUAL1', status='conditional-pass',
                     variants=rows,
                     assumptions='Qualified admitted continuations return before IRQ58; '
                     'continued PAL scanout without missed synchronization; no NMI/recovery. '
                     'Only the top scheduler polling refusal can be suspended at IRQ58 and '
                     'resume when the renderer returns at line259/260.'), indent=2))
