#!/usr/bin/env python3
"""Verify native cache rollback against physical REU bytes and DMA observations."""
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


def scenarios():
    for index in range(128):
        yield dict(index=index, native=bool(index & 64),
                   post_writeback=bool(index & 32), requester_first=bool(index & 16),
                   victim=(index >> 2) & 3, requester=index & 3)


def validate(rows, physical_a, physical_b, line):
    results = []
    for case in scenarios():
        index = case["index"]
        row = rows[index * 32:(index + 1) * 32]
        issues = []

        def require(condition, message):
            if not condition:
                issues.append(message)

        post = case["post_writeback"]
        victim = case["victim"]
        requester = case["requester"]
        native = case["native"]
        revoked = victim != 0
        reused = victim >= 2
        # One legitimate old-victim STASH happens before cancellation if the
        # checkpoint is after write-back, or later only for a still-live A.
        old_stash = int(post or not revoked)
        stash_bytes = (old_stash + int(reused)) * line
        extra_native_fetch = int(native and requester == 3)
        dma = old_stash + int(reused) + 1 + extra_native_fetch
        expected_a = 0x77 if reused else 0x66 if old_stash else 0xa5
        generation = bytes([0x79 if requester == 1 else 0x78,
                            0x57 if requester == 2 else 0x56])
        require(row[0] == index and row[31] == 0x55, "scenario did not complete")
        require(row[1] == (3 if native else 1), "wrong initial continuation phase")
        require(row[2] == (0 if native else 2) if post else row[2] == row[1],
                "wrong write-back checkpoint phase")
        if post:
            require(not row[5] & 2, "rollback snapshot reintroduced DIRTY after STASH")
        if requester != 3:
            require(row[3] == 0, "requester cancellation left a pending phase")
            if victim == 0:
                require(row[4] & 7 == (1 if post else 3),
                        "canceling only B lost or dirtied live A")
            if victim in [1, 2]:
                require(row[4] & 3 == 0, "explicitly revoked victim was resurrected")
            if victim == 3 and not case["requester_first"] and not (native and post):
                require(row[4] & 3 == 0, "stale victim was restored by requester rollback")
        if not case["requester_first"] and victim in [1, 2] and not (native and post):
            require(not row[5] & 1, "victim revocation retained rollback validity")
        require(row[10] == 0, "old pending/native continuation survived retirement")
        require(row[11] & 7 == 1, "replacement line is not valid and clean")
        require(row[12] == dma, f"DMA directions {row[12]} != {dma}")
        require(int.from_bytes(row[13:15], "little") == stash_bytes,
                "revoked or already-clean bytes were written back")
        require(int.from_bytes(row[16:18], "little") == line + extra_native_fetch,
                "unexpected FETCH byte count")
        require(row[18] == 1 and row[19:21] == generation,
                "replacement owner/incarnation is wrong")
        require(row[21:24] == bytes([0, index, 7]), "replacement physical tag is wrong")
        require(row[24] == 0xa5, "replacement logical byte differs from physical REU")
        expected_native = expected_a if extra_native_fetch else 0xcc
        require(row[25] == expected_native, "old native read executed or observed stale bytes")
        require(row[30] == 0, "DMA range validation rejected a valid transaction")
        start = index * 256
        require(physical_a[start:start + line] == bytes([expected_a]) * line,
                f"physical A must contain ${expected_a:02x}, not revoked buffer bytes")
        require(physical_a[start + line:start + 256] == bytes([0xa5]) * (256 - line),
                "write-back crossed its line boundary")
        require(physical_b[start:start + 256] == bytes([0xa5]) * 256,
                "read-only replacement changed physical B")
        results.append(dict(**case, status="fail" if issues else "pass", issues=issues,
                            state_bytes=row.hex(), expected_physical_a=expected_a,
                            expected_dma_directions=dma, expected_stash_bytes=stash_bytes))
    return results


def run(args, line, diagnostics):
    profile = "extended" if diagnostics else "normal"
    out = Path(args.out).resolve() / str(line) / profile
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").unlink(missing_ok=True)
    # Only small source files are staged. Imported runtime sources belong to the
    # current repository; an optional cache source permits a negative baseline.
    stage = out / "stage"
    stage.mkdir(exist_ok=True)
    cache_source = Path(args.cache_source).resolve()
    cache_hash = sha256(cache_source)
    fixture_hash = sha256(ROOT / "tests/native/cache_rollback.asm")
    abi_hash = sha256(ROOT / "native/m2_abi.inc")
    profile_hash = sha256(ROOT / "native/build_profile.inc")
    cache = cache_source.read_text().replace('#import "m2_abi.inc"',
                                             f'#import "{ROOT / "native/m2_abi.inc"}"')
    (stage / "cache.asm").write_text(cache)
    fixture = (ROOT / "tests/native/cache_rollback.asm").read_text()
    fixture = fixture.replace('#import "../../native/m2_abi.inc"',
                              f'#import "{ROOT / "native/m2_abi.inc"}"')
    fixture = fixture.replace('#import "../../native/cache.asm"', '#import "cache.asm"')
    (stage / "fixture.asm").write_text(fixture)
    prg = out / "cache-rollback.prg"
    command = [args.java, "-jar", str(Path(args.kickassembler).resolve()),
               str(stage / "fixture.asm"), "-odir", str(out), "-o", str(prg),
               "-vicesymbols", f":cacheLine={line}", f":extendedDiagnostics={diagnostics}"]
    with (out / "assembler.log").open("w") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    usb = out / "usb"
    usb.mkdir(exist_ok=True)
    image = usb / "rollback.reu"
    image.write_bytes(bytes([0xa5]) * (16 * 1024 * 1024))
    flash = out / "isolated-flash.bin"
    shutil.copyfile(args.flash, flash)
    settings = out / "settings.cfg"
    settings.write_text(Path(args.settings).read_text() +
                        "\n[C64 and Cartridge Settings]\nRAM Expansion Unit=Enabled\n"
                        "REU Size=16 MB\nREU Preload=Enabled\n"
                        "REU Preload Image=/Usb0/rollback.reu\n")
    binary = prg.read_bytes()
    commands = ["wait 6000", 'expect-console "REU Load: Loaded" 30000',
                "monitor c64 halt"]
    commands += writes("ram", int.from_bytes(binary[:2], "little"), binary[2:])
    commands += ["monitor g 1200", "wait 500", "monitor c64 halt", "monitor m ram 0200 02ff"]
    for start in range(0x3000, 0x4000, 1024):
        commands.append(f"monitor m ram {start:04x} {start + 1023:04x}")
    for start in range(0x1060000, 0x1068000, 1024):
        commands.append(f"monitor fw-memory {start:08x} {start + 1023:08x}")
    for start in range(0x1070000, 0x1078000, 1024):
        commands.append(f"monitor fw-memory {start:08x} {start + 1023:08x}")
    commands.append("quit")
    control = out / "run.ctl"
    control.write_text("\n".join(commands) + "\n")
    command = [str(Path(args.emulator).resolve()), "run", "--config",
               str(Path(args.config).resolve()), "--flash", str(flash), "--settings", str(settings),
               "--usb-dir", str(usb), "--headless", "--speed", "max", "--audio", "off",
               "--script", str(control)]
    with (out / "emulator.log").open("w") as log:
        subprocess.run(command, cwd=out, stdout=log, stderr=subprocess.STDOUT,
                       timeout=60, check=True)
    log = (out / "emulator.log").read_text()
    report = memory(log, 0x200, 256)
    rows = memory(log, 0x3000, 4096)
    physical_a = memory(log, 0x1060000, 32768, prefix="FW")
    physical_b = memory(log, 0x1070000, 32768, prefix="FW")
    (out / "rows.bin").write_bytes(rows)
    (out / "physical-a.bin").write_bytes(physical_a)
    (out / "physical-b.bin").write_bytes(physical_b)
    cases = validate(rows, physical_a, physical_b, line)
    failed = [case for case in cases if case["issues"]]
    completed = report[255] == 0x55
    evidence = dict(format="COSCACHEROLLBACK1", status="pass" if completed and not failed else "fail",
                    cache_line=line, extended_diagnostics=bool(diagnostics), scenarios=128,
                    failures=len(failed), completed=completed,
                    cache_source_sha256=cache_hash,
                    fixture_source_sha256=fixture_hash,
                    abi_source_sha256=abi_hash, profile_source_sha256=profile_hash,
                    prg_sha256=sha256(prg), rows_sha256=hashlib.sha256(rows).hexdigest(),
                    physical_a_sha256=hashlib.sha256(physical_a).hexdigest(),
                    physical_b_sha256=hashlib.sha256(physical_b).hexdigest(),
                    supplied_config_sha256=sha256(args.config), supplied_flash_sha256=sha256(args.flash),
                    supplied_settings_sha256=sha256(args.settings),
                    emulator_path=str(Path(args.emulator).resolve()), cases=cases)
    (out / "result.json").write_text(json.dumps(evidence, indent=2) + "\n")
    if not args.keep_inputs:
        # Exact disposable inputs created by this run; retain PRG/log/control and
        # compact observations. No review copy or user artifact is removed.
        image.unlink()
        flash.unlink()
        shutil.rmtree(out / "run/usb-dir", ignore_errors=True)
    if failed or not evidence["completed"]:
        first = failed[0] if failed else dict(index="completion", issues=["fixture did not halt"])
        raise ValueError(f"{line}/{profile}: {len(failed)} failed scenarios; first {first['index']}: "
                         + "; ".join(first["issues"]))
    return {key: value for key, value in evidence.items() if key != "cases"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["emulator", "config", "flash", "settings", "kickassembler"]:
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--java", default="java")
    parser.add_argument("--out", default=str(ROOT / "build/cache-rollback"))
    parser.add_argument("--cache-source", default=str(ROOT / "native/cache.asm"))
    parser.add_argument("--lines", nargs="+", type=int, choices=[64, 128], default=[128, 64])
    parser.add_argument("--profiles", nargs="+", choices=["extended", "normal"],
                        default=["extended", "normal"])
    parser.add_argument("--keep-inputs", action="store_true")
    args = parser.parse_args()
    results = [run(args, line, int(profile == "extended"))
               for line in args.lines for profile in args.profiles]
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"cache rollback check failed: {error}", file=sys.stderr)
        sys.exit(1)
