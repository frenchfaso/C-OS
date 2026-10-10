#!/usr/bin/env python3
"""Reproduce the minimal assemble -> disassemble -> execute delivery."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def command(args, expected=0):
    result = subprocess.run([str(arg) for arg in args], cwd=ROOT, text=True,
                            capture_output=True, check=False)
    if result.returncode != expected:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(map(str, args))}\n"
                           f"{result.stdout}{result.stderr}")
    return result.stdout


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Use already cached Cargo dependencies")
    args = parser.parse_args()
    cargo = ["cargo", "build", "--locked", "--release"] + (["--offline"] if args.offline else [])
    command(cargo)
    tools = ROOT / "target" / "release"
    build = ROOT / "build"
    build.mkdir(exist_ok=True)

    def assemble_and_pack():
        for name in ["linear", "calls", "spin"]:
            command([tools / "cosasm", f"apps/{name}.casm", "-o", f"build/{name}.cobj"])
            (build / f"{name}.unlinked.dis").write_text(command([tools / "cosdis", f"build/{name}.cobj"]))
        command([tools / "cospack", "manifests/m1.json", "--out", "build/m1"])
        command([tools / "cospack", "manifests/empty.json", "--out", "build/empty"])

    assemble_and_pack()
    artifacts = ["linear.cobj", "calls.cobj", "spin.cobj", "m1.reu", "m1.manifest.json", "m1.asm", "m1.map.txt"]
    original = {name: sha(build / name) for name in artifacts}
    assemble_and_pack()
    if original != {name: sha(build / name) for name in artifacts}:
        raise RuntimeError("Repeated assembly/linking changed an artifact")
    programs = {}
    for name in ["Linear", "Calls"]:
        output = command([tools / "cosrun", "build/m1.manifest.json", "--app", name,
                          "--fuel", "3", "--trace", f"build/{name.lower()}.trace.jsonl"])
        result = json.loads(output)
        (build / f"{name.lower()}.result.json").write_text(output)
        if result["outcome"] != {"Stopped": {"code": 0}}:
            raise RuntimeError(f"{name} did not exit successfully")
        if name == "Linear" and result["context"]["r"][3:5] != [0xABCD, 4]:
            raise RuntimeError("Linear memory example returned unexpected data")
        if name == "Calls" and (result["context"]["r"][2] != 42 or
                                result["context"]["sp"] != result["context"]["p"][1]):
            raise RuntimeError("Nested calls changed the saved stack or result")
        programs[name] = result
    output = command([tools / "cosrun", "build/m1.manifest.json", "--app", "Spin",
                      "--fuel", "3", "--slices", "6", "--trace", "build/spin.trace.jsonl"], expected=2)
    result = json.loads(output)
    (build / "spin.result.json").write_text(output)
    if result["outcome"] != "SliceLimit" or result["context"]["retired"] != 18 or result["context"]["r"][2] != 9:
        raise RuntimeError("Non-yielding loop did not resume deterministically")
    programs["Spin"] = result
    manifest = json.loads((build / "m1.manifest.json").read_text())
    image = (build / "m1.reu").read_bytes()
    for app in manifest["apps"]:
        code = image[app["code"]["first"]:app["code"]["last"] + 1]
        binary = build / f"{app['name'].lower()}.bytecode"
        binary.write_bytes(code)
        (build / f"{app['name'].lower()}.linked.dis").write_text(
            command([tools / "cosdis", "build/m1.manifest.json", "--app", app["name"]]))
    report = dict(format="COSM1RESULT1", qualification="Host semantic verification only",
                  artifact_sha256=original, reproducible=True, programs=programs)
    (build / "m1-results.json").write_text(json.dumps(report, indent=2) + "\n")
    print("M1 pipeline passed: Linear=0xABCD, Calls=42 with restored SP, Spin=18 opcodes/9 increments.")
    print("Repeated objects, linked image, manifest, constants and map are byte-identical.")


if __name__ == "__main__":
    main()
