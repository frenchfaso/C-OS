#!/usr/bin/env python3
"""Exercise real REU DMA cancellation/coherence using an isolated UE2 backend."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from m0_ue2 import memory, writes  # noqa: E402


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(args, line):
    out = Path(args.out).resolve() / str(line)
    out.mkdir(parents=True, exist_ok=True)
    prg = out / "cache-cancel.prg"
    command = [args.java, "-jar", str(Path(args.kickassembler).resolve()),
               str(ROOT / "tests/native/cache_cancel.asm"), "-odir", str(out),
               "-o", str(prg), "-vicesymbols", f":cacheLine={line}"]
    with (out / "assembler.log").open("w") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    usb = out / "usb"
    usb.mkdir(exist_ok=True)
    (usb / "cache.reu").write_bytes(bytes([0xa5]) * (16 * 1024 * 1024))
    flash = out / "isolated-flash.bin"
    shutil.copyfile(args.flash, flash)
    settings = out / "settings.cfg"
    settings.write_text(Path(args.settings).read_text() +
                        "\n[C64 and Cartridge Settings]\nRAM Expansion Unit=Enabled\n"
                        "REU Size=16 MB\nREU Preload=Enabled\n"
                        "REU Preload Image=/Usb0/cache.reu\n")
    binary = prg.read_bytes()
    commands = ["wait 6000", 'expect-console "REU Load: Loaded" 30000',
                "monitor c64 halt"]
    commands += writes("ram", int.from_bytes(binary[:2], "little"), binary[2:])
    commands += ["monitor g 1200", "wait 100", "monitor c64 halt",
                 "monitor m ram 0300 03af", "monitor m ram fd80 fdef",
                 f"monitor fw-memory 01060000 {0x1060000 + 8 * line - 1:08x}",
                 "monitor fw-memory 01070000 01070003", "quit"]
    script = out / "run.ctl"
    script.write_text("\n".join(commands) + "\n")
    command = [str(Path(args.emulator).resolve()), "run", "--config",
               str(Path(args.config).resolve()), "--flash", str(flash),
               "--settings", str(settings), "--usb-dir", str(usb),
               "--headless", "--speed", "max", "--audio", "off",
               "--script", str(script)]
    with (out / "emulator.log").open("w") as log:
        subprocess.run(command, cwd=out, stdout=log, stderr=subprocess.STDOUT,
                       timeout=50, check=True)
    log = (out / "emulator.log").read_text()
    report = memory(log, 0x300, 0xb0)
    metadata = memory(log, 0xfd80, 112)
    physical = memory(log, 0x1060000, 8 * line, prefix="FW")
    code = memory(log, 0x1070000, 4, prefix="FW")
    expected = bytearray([0xa5]) * (8 * line)
    expected[0] = 0x40
    if report[0] != 0x55:
        raise ValueError(f"{line}-byte native fixture failed phase ${report[0]:02x}")
    if report[0x20:0x28] != bytes(range(0x40, 0x48)) or physical != expected:
        raise ValueError(f"{line}-byte dirty logical/physical memory mismatch")
    if code != bytes([0xa5, 0x66, 0xa5, 0xa5]):
        raise ValueError(f"{line}-byte physical code update mismatch")
    if report[0x30:0x32] != bytes([8, 1]):
        raise ValueError(f"{line}-byte canceled/stale request snapshot mismatch")
    counters = {name: int.from_bytes(report[offset:offset+4], "little")
                for name, offset in [("fetch_bytes", 0x81), ("stash_bytes", 0x85),
                                     ("stale", 0x91), ("native_reads", 0x95),
                                     ("native_writes", 0x99),
                                     ("dma_calls", 0x9d)]}
    if counters != dict(fetch_bytes=11 * line + 1, stash_bytes=line + 1,
                        stale=1, native_reads=1, native_writes=1, dma_calls=14):
        raise ValueError(f"{line}-byte DMA counter mismatch: {counters}")
    flags = metadata[64:80]
    if flags[8] & 7 != 1 or any(flag & 7 != 3 for flag in flags[9:16]):
        raise ValueError(f"{line}-byte unrelated dirty lines were lost")
    evidence = dict(cache_line=line, status="pass", counters=counters,
                    observed_stack_bytes=report[0x1c],
                    logical_first_bytes=report[0x20:0x28].hex(),
                    physical_sha256=hashlib.sha256(physical).hexdigest(),
                    prg_sha256=sha256(prg), cache_source_sha256=sha256(ROOT / "native/cache.asm"),
                    fixture_source_sha256=sha256(ROOT / "tests/native/cache_cancel.asm"),
                    supplied_config_sha256=sha256(args.config),
                    supplied_flash_sha256=sha256(args.flash),
                    supplied_settings_sha256=sha256(args.settings),
                    emulator_path=str(Path(args.emulator).resolve()))
    (out / "result.json").write_text(json.dumps(evidence, indent=2) + "\n")
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["emulator", "config", "flash", "settings", "kickassembler"]:
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--java", default="java")
    parser.add_argument("--out", default=str(ROOT / "build/cache-cancel"))
    args = parser.parse_args()
    results = [run(args, line) for line in [128, 64]]
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"cache cancellation check failed: {error}", file=sys.stderr)
        sys.exit(1)
