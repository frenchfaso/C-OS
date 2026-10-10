#!/usr/bin/env python3
"""Allow slow host transport while retaining the frozen target measurement."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import m3_benchmark

original_command = m3_benchmark.Session.command

def patient_command(self, *args, **kwargs):
    # Host socket deadline only. No target command, clock, binary, pause,
    # sampling point or emulated wait duration is changed or added.
    self.socket.settimeout(300)
    return original_command(self, *args, **kwargs)

m3_benchmark.Session.command = patient_command
m3_benchmark.main()
