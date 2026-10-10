#!/usr/bin/env python3
"""Build original M0 diagnostics and verify their assembled memory contract."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
APPLICATION_ABI = 2
KICK_SHA256 = "9592a39336e73a1db8b4a7749256d62d29b113b1c7f0f6c86ea43870ebd9ae1f"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def symbols(path):
    return {name: int(address, 16) for address, name in
            re.findall(r"al C:([0-9a-fA-F]+) \.([^\s]+)", Path(path).read_text())}


def assemble(java, jar, source, stage, variables):
    output = stage / (source.stem + ".prg")
    command = [java, "-jar", str(jar), str(source), "-o", str(output),
               "-odir", str(stage), "-vicesymbols"]
    command.extend(f":{key}={value}" for key, value in variables.items())
    run = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, check=False)
    (stage / (source.stem + ".assembly.log")).write_text(run.stdout)
    if run.returncode or re.search(r"Made.*?[1-9]\d* failed", run.stdout):
        raise ValueError(run.stdout)
    if not output.is_file():
        raise ValueError("Assembler produced no PRG")
    image = output.read_bytes()
    address = int.from_bytes(image[:2], "little")
    if len(image) < 3 or address + len(image) - 2 > 65536:
        raise ValueError("Invalid generated PRG range")
    return image[2:], address, symbols(stage / (source.stem + ".vs"))


def publish(stage,out):
    """Publish the validated artifact set, restoring the previous set on error."""
    files=sorted(p for p in stage.iterdir() if p.is_file())
    backups=stage/"backups"
    backups.mkdir()
    previous=[]
    for i,path in enumerate(files):
        destination=out/path.name
        backup=backups/str(i)
        if destination.exists():
            if not destination.is_file():
                raise ValueError(f"Artifact destination is not a file: {destination}")
            shutil.copyfile(destination,backup)
            previous.append(backup)
        else:
            previous.append(None)
    published=[]
    try:
        for i,path in enumerate(files):
            os.replace(path,out/path.name)
            published.append(i)
    except OSError:
        for i in reversed(published):
            destination=out/files[i].name
            if previous[i] is None:
                destination.unlink()
            else:
                os.replace(previous[i],destination)
        raise


def pattern_pixel(x, y):
    if y == 0 or y == 199:
        return 1
    if x == 0:
        return 2
    if x == 319:
        return 3
    if 80 <= y < 120:
        return 1 if x % 2 == 0 else 0
    return x // 20


def pattern():
    out = bytearray(40960)
    for c in range(160):
        for y in range(200):
            out[c * 256 + y] = pattern_pixel(c * 2, y) | pattern_pixel(c * 2 + 1, y) << 4
    return out


def budget(probe, renderer, rs, ps):
    # Every address below is the reservation in SPEC 5.2, not claimed emitted code.
    ranges = [(0,2,"6510 ports"),(2,128,"VM registers (future)"),
              (128,192,"driver scratch"),(192,256,"raster scratch"),
              (256,512,"hardware stack"),(512,768,"nibble table"),
              (768,1024,"diagnostics/global state"),(1024,1536,"PCBs (future)"),
              (1536,2048,"event rings (future)"),(2048,3072,"code cache (future)"),
              (3072,4096,"data cache (future)"),(4096,4608,"DMA staging"),
              (4608,16384,"resident code"),(16384,53248,"framebuffer part 1"),
              (53248,57344,"I/O"),(57344,61440,"framebuffer part 2"),
              (61440,64000,"renderer"),(64000,64768,"font (future)"),
              (64768,64896,"cursor (future)"),(64896,65024,"metadata (future)"),
              (65024,65530,"desktop/diagnostics (future)"),(65530,65536,"vectors")]
    previous = 0
    rows = []
    for start, end, name in ranges:
        if start != previous or end <= start:
            raise ValueError("Reservation overlap/gap")
        previous = end
        rows.append(dict(name=name, first=start, last=end-1, reserved_bytes=end-start,
                         assembled_bytes=0, runtime_bytes=0))
    def allocation(name, assembled=0, runtime=0):
        record = next(r for r in rows if r["name"] == name)
        if assembled + runtime > record["reserved_bytes"]:
            raise ValueError(f"Budget overflow in {name}")
        record.update(assembled_bytes=assembled, runtime_bytes=runtime,
                      uncommitted_bytes=record["reserved_bytes"]-assembled-runtime)
    allocation("resident code", ps["resident_end"]-ps["resident_start"])
    allocation("renderer", len(renderer))
    allocation("driver scratch", runtime=17)
    allocation("raster scratch", runtime=2)
    allocation("nibble table", runtime=256)
    allocation("diagnostics/global state", runtime=80)
    allocation("DMA staging", runtime=512)
    allocation("framebuffer part 1", runtime=36864)
    allocation("framebuffer part 2", runtime=4096)
    allocation("vectors", runtime=6)
    # Deepest normal call chain = 6 bytes. An IRQ can add 3 hardware bytes,
    # 3 saved registers and a two-byte JSR, and a single NMI adds 4: 18 bytes.
    allocation("hardware stack", runtime=18)
    return dict(format="COSM0MAP1", sections=rows, local_ram=65536,
                framebuffer_reservation=40960, framebuffer_displayed_bytes=32000,
                io_window=4096, directly_usable_non_framebuffer_ram=20480,
                resident_assembled_bytes=ps["resident_end"]-ps["resident_start"],
                renderer_assembled_bytes=len(renderer),
                normal_stack_static_bound=18,
                stack_bound_conditions="One IRQ plus one NMI; no recursive NMI assumption",
                bootstrap_load_bytes=len(probe),
                bootstrap_padding_is_not_resident_code=True,
                numeric_future_target_within_resident_budget=4096,
                shared_reu=16777216, system_reu_reservation=262144,
                app_reu_available=16515072)


def build(args):
    jar = Path(args.kickass).expanduser().resolve()
    if not jar.is_file():
        raise ValueError("Install Kick Assembler 5.25 at toolchain/KickAss.jar or set KICKASS_JAR")
    if digest(jar) != KICK_SHA256:
        raise ValueError("KickAss.jar does not match the pinned 5.25 SHA-256")
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="m0-", dir=out.parent) as tmp:
        stage = Path(tmp)
        sources = stage / "sources"
        sources.mkdir()
        for name in ["build_profile.inc", "hardware.inc", "renderer.asm", "probe.asm"]:
            shutil.copyfile(ROOT / "native" / name, sources / name)
        inputs = b"".join((sources / n).read_bytes() for n in ["build_profile.inc","hardware.inc","renderer.asm","probe.asm"])
        tag = int.from_bytes(hashlib.sha256(inputs + str(args.line_delay).encode()).digest()[:4], "little")
        variables = dict(lineDelay=args.line_delay,buildTag=tag,renderBytes=0,m2=0,appCount=0,marginEnabled=0)
        renderer, address, rs = assemble(args.java, jar, sources / "renderer.asm", stage, variables)
        if address != 0xf000 or rs["renderer_end"] > 0xfa00:
            raise ValueError("Renderer segment outside the map")
        (sources / "renderer-addresses.inc").write_text(
            f".const renderer_irq = ${rs['irq']:04x}\n.const renderer_nmi = ${rs['nmi']:04x}\n"
            ".const m2_boot_load = $0000\n.const m2_kernel_start = $0000\n")
        variables["renderBytes"] = len(renderer)
        probe, address, ps = assemble(args.java, jar, sources / "probe.asm", stage, variables)
        if address != 0x801 or address+len(probe) > 0x4000:
            raise ValueError("Bootstrap PRG must remain below $4000")
        image = bytearray(16777216)
        image[:16] = b"COSREU01" + tag.to_bytes(4,"little") + APPLICATION_ABI.to_bytes(2,"little") + b"\x00\x00"
        image[0x1000:0x1000+len(renderer)] = renderer
        (stage / "diagnostic.reu").write_bytes(image)
        (stage / "pattern.columns").write_bytes(pattern())
        report = budget(probe, renderer, rs, ps)
        report.update(build_tag=tag, line_delay=args.line_delay,
                      renderer_pixel_cpu_cycles=2520, immediate_preparation_cpu_cycles=160,
                      artifact_sha256={n:digest(stage/n) for n in ["probe.prg","renderer.prg","diagnostic.reu","pattern.columns"]},
                      source_sha256=hashlib.sha256(inputs).hexdigest(),
                      assembler_sha256=KICK_SHA256,
                      symbols={"probe":ps,"renderer":rs})
        (stage / "map.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
        lines = ["C-OS M0 memory budget (inclusive bounds)",
                 "Actual assembly and runtime allocations are distinct from future reservations.",
                 "first last   reserved assembled runtime remaining name"]
        for row in report["sections"]:
            lines.append(f"{row['first']:04x}  {row['last']:04x}  {row['reserved_bytes']:8} {row['assembled_bytes']:9} {row['runtime_bytes']:7} {row.get('uncommitted_bytes',row['reserved_bytes']):9} {row['name']}")
        lines.extend(["Hardware stack static bound: 18 bytes (one IRQ and one NMI).",
                      "Numeric core future target: 4096 bytes, within existing resident code reserve.",
                      "REU: 16777216 shared physical bytes; 262144 system; 16515072 application."])
        (stage / "map.txt").write_text("\n".join(lines)+"\n")
        # Validate everything before publication; restore the set on failure.
        out.mkdir(parents=True,exist_ok=True)
        publish(stage,out)
        print(f"Built {out}: resident {report['resident_assembled_bytes']} bytes; renderer {len(renderer)} bytes")
        print(f"build_tag=${tag:08x}; delay={args.line_delay}; hardware timing remains unqualified")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kickass",default=os.environ.get("KICKASS_JAR",ROOT/"toolchain/KickAss.jar"))
    parser.add_argument("--java",default=os.environ.get("JAVA","java"))
    parser.add_argument("--line-delay",type=int,default=140,help="Provisional 320-dot hardware phase; qualify on backend")
    parser.add_argument("--out",default=ROOT/"build/m0")
    args = parser.parse_args()
    if not 1 <= args.line_delay <= 255:
        parser.error("line delay must be 1..255")
    try:
        build(args)
    except (ValueError,OSError) as error:
        print(f"m0: {error}",file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
