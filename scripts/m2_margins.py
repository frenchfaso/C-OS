#!/usr/bin/env python3
"""Execute the disabled-margin handoff lifecycle on an external UE2 backend."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import m0
from m0_ue2 import memory, writes

ROOT = Path(__file__).resolve().parents[1]


def run(args):
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").unlink(missing_ok=True)
    jar = args.kickass.expanduser().resolve()
    if not jar.is_file() or m0.digest(jar) != m0.KICK_SHA256:
        raise ValueError("Install the pinned Kick Assembler 5.25 jar; see docs/m0.md")
    image, first, symbols = m0.assemble(args.java, jar, ROOT / "tests/native/margins.asm", out, {})
    if first != 0x1200 or symbols["margin_module_end"] > 0x2000:
        raise ValueError("Invalid independent prepared-phase test image")
    usb = out / "usb"
    usb.mkdir(exist_ok=True)
    private_flash = out / "isolated-flash.bin"
    private_settings = out / "settings.cfg"
    shutil.copyfile(args.flash, private_flash)
    shutil.copyfile(args.settings, private_settings)
    commands = ["wait 6000", "monitor c64 halt"]
    commands += writes("ram", first, image)
    commands += ["monitor g 1200", "wait 30", "monitor c64 halt",
                 "monitor m ram 03e0 03ef", "monitor m ram 1080 10af",
                 "monitor status", "quit"]
    script = out / "run.ctl"
    script.write_text("\n".join(commands) + "\n")
    command = [str(args.emulator.resolve()), "run", "--config", str(args.config.resolve()),
               "--flash", str(private_flash), "--settings", str(private_settings),
               "--usb-dir", str(usb), "--headless", "--speed", "max", "--audio", "off",
               "--script", str(script)]
    with (out / "emulator.log").open("w") as log:
        process = subprocess.run(command, cwd=out, stdout=log, stderr=subprocess.STDOUT,
                                 timeout=args.timeout, check=False)
    log = (out / "emulator.log").read_text()
    if process.returncode:
        raise ValueError(f"UE2 exited {process.returncode}; inspect {out / 'emulator.log'}")
    report = memory(log, 0x3e0, 16)
    record = memory(log, 0x1080, 48)
    if report[:4] != b"MM2\x01" or report[4:6] != bytes([0, 66]):
        raise ValueError(f"Prepared-phase lifecycle failure: report={report.hex(' ')}")
    if record[0] != 0 or record[8] != 0 or record[15] != 2 or record[25] != 0:
        raise ValueError("Unexpected final ownership/completion/qualification state")
    result = dict(format="COSM2MARGINS1", qualification="Native lifecycle only; margin execution disabled",
                  lifecycle_assertions=66, failure=report[4], completions=record[15],
                  qualification_flag=record[25], zero_page_bytes=0, private_ram_bytes=48,
                  module_bytes=symbols["margin_module_end"] - symbols["margin_module_start"],
                  conservative_nmos_claim_cycle_bound=512, actual_phase_cost_measured=False,
                  backend_executable_sha256=m0.digest(args.emulator),
                  assembler_sha256=m0.KICK_SHA256, prg_sha256=m0.digest(out / "margins.prg"),
                  source_sha256=hashlib.sha256((ROOT / "native/margins.asm").read_bytes() +
                                              (ROOT / "tests/native/margins.asm").read_bytes() +
                                              (ROOT / "native/m2_abi.inc").read_bytes()).hexdigest(),
                  supplied_config=str(args.config.resolve()),
                  supplied_settings_sha256=m0.digest(args.settings), command=command)
    (out / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["emulator", "config", "flash", "settings"]:
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--kickass", type=Path,
                        default=os.environ.get("KICKASS_JAR", ROOT / "toolchain/KickAss.jar"))
    parser.add_argument("--java", default=os.environ.get("JAVA", "java"))
    parser.add_argument("--out", type=Path, default=ROOT / "build/m2/margins")
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()
    try:
        run(args)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f"m2_margins: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
