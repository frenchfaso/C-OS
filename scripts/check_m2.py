#!/usr/bin/env python3
"""Build and verify the complete M2 delivery, including current M0/M1 checks."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(arguments):
    command = [str(value) for value in arguments]
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["emulator", "config", "flash", "settings", "kickass"]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--java", default="java")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    python = sys.executable
    offline = ["--offline"] if args.offline else []
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    result = build / "m2-results.json"
    result.unlink(missing_ok=True)
    backend = sum((["--" + name, getattr(args, name).resolve()]
                   for name in ["emulator", "config", "flash", "settings"]), [])
    assembler = ["--kickass", args.kickass.resolve(), "--java", args.java]
    run(["cargo", "fmt", "--all", "--", "--check"])
    run(["cargo", "test", "--locked"] + offline)
    run(["cargo", "clippy", "--locked"] + offline + ["--all-targets", "--", "-D", "warnings"])
    run([python, "scripts/check_m1.py"] + offline)
    run([python, "scripts/m0.py"] + assembler)
    variants = []
    for line in [128, 64]:
        out = build / "m2" / str(line)
        command = [python, "scripts/m2.py", "--cache-line", line, "--out", out,
                   "--skip-host-build"] + assembler
        run(command)
        names = ["m2.prg", "m2.reu", "native.bin", "renderer.prg",
                 "pattern.columns", "m2.manifest.json", "map.json", "map.txt"]
        first = {name: digest(out / name) for name in names}
        run(command)
        if first != {name: digest(out / name) for name in names}:
            raise ValueError(f"Repeated {line}-byte native build changed an artifact")
        run([python, "scripts/m2_bounds.py", "--build", out,
             "--out", out / "bounds.json"])
        variants.append(dict(line=line, build=out, hashes=first))
    fixtures = build / "m2-fixtures.json"
    run([ROOT / "target/release/cosfixtures", fixtures, "--manifest", build / "m1.manifest.json"])
    run([python, "-m", "unittest", "discover", "-s", "tests/native", "-v"])
    run([python, "scripts/m0_ue2.py"] + backend + ["--suite"])
    run([python, "tests/native/check_cache_cancel.py"] + backend +
        ["--kickassembler", args.kickass.resolve(), "--java", args.java])
    # The margin lifecycle checker uses only ordinary CPU execution. It must
    # never enable the experimental timed hook to establish the M2 contract.
    run([python, "scripts/m2_margins.py"] + backend + assembler)
    reports = []
    for variant in variants:
        out = build / "m2/ue2" / str(variant["line"])
        run([python, "scripts/m2_ue2.py"] + backend +
            ["--build", variant["build"], "--out", out, "--fixtures", fixtures])
        native = json.loads((out / "result.json").read_text())
        reports.append(native)
    evidence = dict(format="COSM2RESULT1", status="pass",
                    qualification="Complete functional emulation; physical Ultimate timing pending",
                    reproducible=True, fixtures_sha256=digest(fixtures),
                    fixture_cases=len(json.loads(fixtures.read_text())["cases"]),
                    m0_suite=json.loads((build / "m0/ue2/suite.json").read_text()),
                    m1=json.loads((build / "m1-results.json").read_text()),
                    margin_lifecycle=json.loads((build / "m2/margins/result.json").read_text()),
                    cache_lifecycle=[json.loads((build / f"cache-cancel/{line}/result.json").read_text())
                                     for line in [128, 64]],
                    bounds=[json.loads((build / f"m2/{line}/bounds.json").read_text())
                            for line in [128, 64]],
                    variants=[dict(cache_line=v["line"], artifact_sha256=v["hashes"])
                              for v in variants], native=reports)
    result.write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"M2 complete functional verification passed: {result}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"check_m2: {error}", file=sys.stderr)
        raise SystemExit(1)
