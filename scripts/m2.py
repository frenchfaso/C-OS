#!/usr/bin/env python3
"""Build the native M2 boot image using the existing Rust static linker."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import m0

ROOT = Path(__file__).resolve().parents[1]
NATIVE_REU = 0x8000
RENDERER_REU = 0xb000
DESCRIPTORS_REU = 0xc000
INITIALIZATION_REU = 0xc200
NATIVE_RAM = 0x1800
NATIVE_FILES = ["build_profile.inc", "hardware.inc", "probe.asm", "renderer.asm", "m2_abi.inc",
                "m2_boot.asm", "vm.asm", "cache.asm", "margins.asm"]
M3_FILES = ["build_profile.inc", "hardware.inc", "probe.asm", "renderer.asm", "m2_abi.inc",
            "m3_boot.asm", "m3_kernel.asm", "vm.asm", "cache.asm", "margins.asm",
            "scheduler.inc", "scheduler.asm", "jobs.asm"]


def command(arguments):
    run = subprocess.run([str(x) for x in arguments], cwd=ROOT, text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if run.returncode:
        raise ValueError(f"Command failed: {' '.join(map(str, arguments))}\n{run.stdout}")
    return run.stdout


def put24(target, offset, value):
    if not 0 <= value <= 0xffffff:
        raise ValueError(f"Value outside 24-bit space: {value}")
    target[offset:offset+3] = value.to_bytes(3, "little")


def initial_state(app):
    state = bytearray(128)
    state[0:2] = app["id"].to_bytes(2, "little")
    state[2:4] = m0.APPLICATION_ABI.to_bytes(2,"little")
    pointers = [app["heap"]["first"], app["heap"]["last"],
                app["data"]["start"] if app["data"]["length"] else 0,
                app["stack"]["last"]]
    for index, value in enumerate(pointers):
        put24(state, 16+index*3, value)
    put24(state, 28, app["entry"])
    put24(state, 31, app["stack"]["last"])
    state[34] = 128
    state[43:45] = app["id"].to_bytes(2, "little")
    for offset, key in [(45, "arena"), (51, "code"), (57, "heap"), (63, "stack")]:
        put24(state, offset, app[key]["first"])
        put24(state, offset+3, app[key]["last"])
    state[91:93] = b"\x01\x00"
    return state


def initialization_record(app):
    record = bytearray(16)
    for offset, value in [(0, app["data_seed"]["start"]), (3, app["data"]["start"]),
                          (6, app["data"]["length"]), (9, app["bss"]["start"]),
                          (12, app["bss"]["length"])]:
        put24(record, offset, value)
    return record


def memory_report(kernel, renderer, native_symbols, probe_symbols, line_size,
                  milestone="m2", extended=True, margin_enabled=False):
    normal = milestone == "m3"
    native_end = native_symbols["m3_native_end" if normal else "m2_native_end"]
    cache_work_bytes = native_symbols["cache_work_end"]-0x0350
    report = m0.budget(bytes(), renderer, native_symbols, probe_symbols)
    sections = {r["name"]: r for r in report["sections"]}
    def allocate(name, assembled=0, runtime=0):
        row = sections[name]
        if assembled+runtime > row["reserved_bytes"]:
            raise ValueError(f"M2 memory overflow in {name}")
        row.update(assembled_bytes=assembled, runtime_bytes=runtime,
                   uncommitted_bytes=row["reserved_bytes"]-assembled-runtime)
    # Legacy M2 includes its bootstrap/gap; normal M3 contains only the runtime.
    allocate("resident code", assembled=native_end-0x1200)
    allocate("VM registers (future)", runtime=126)
    sections["VM registers (future)"]["name"] = "active VM state and interpreter scratch"
    allocate("driver scratch", runtime=48 if normal else 61)
    allocate("PCBs (future)", runtime=512)
    sections["PCBs (future)"]["name"] = "four VM contexts"
    allocate("code cache (future)", runtime=8*line_size)
    sections["code cache (future)"]["name"] = "private code cache"
    allocate("data cache (future)", runtime=8*line_size)
    sections["data cache (future)"]["name"] = "shared data cache"
    allocate("diagnostics/global state", runtime=80+cache_work_bytes+2)
    allocate("metadata (future)", runtime=112)
    sections["metadata (future)"]["name"] = "cache metadata"
    allocate("desktop/diagnostics (future)", runtime=224 if normal else 320)
    allocate("hardware stack", runtime=256)
    if normal:
        allocate("DMA staging",runtime=176) # 128-byte coherent buffer plus 48-byte margin record/private area.
    sections["desktop/diagnostics (future)"]["name"] = "scheduler globals and syscall completion" if normal else "diagnostic command mailbox and snapshot"
    report.update(format="COSM3MAP1" if normal else "COSM2MAP1", cache_line_bytes=line_size,
                  milestone=milestone, extended_diagnostics=extended,
                  normal_build=normal and not extended and not margin_enabled,
                  native_ram_first=0x1200 if normal else NATIVE_RAM,
                  runtime_admission_first_line=260 if normal and not extended and not margin_enabled else 280,
                  runtime_admission_last_line=311 if normal and not extended and not margin_enabled else 299,
                  scheduler_admission_early_last_line=20 if normal and not extended and not margin_enabled else None,
                  scheduler_latest_admission_guard_phi2=2331 if normal and not extended and not margin_enabled else 4410,
                  dma_admission_early_last_line=20 if normal and not extended and not margin_enabled else None,
                  dma_latest_admission_guard_phi2=2331 if normal and not extended and not margin_enabled else 4410,
                  runtime_admission_early_first_line=0 if normal and not extended and not margin_enabled else None,
                  runtime_admission_early_last_line=50 if normal and not extended and not margin_enabled else None,
                  latest_admission_guard_phi2=441 if normal and not extended and not margin_enabled else 4410,
                  resident_assembled_bytes=native_end-0x1200,
                  m0_probe_assembled_bytes=probe_symbols["resident_end"]-probe_symbols["resident_start"],
                  resident_alignment_and_loader_bytes=0 if normal else NATIVE_RAM-probe_symbols["resident_end"],
                  m2_native_assembled_bytes=len(kernel),
                  native_assembled_bytes=len(kernel),
                  diagnostic_harness_assembled_bytes=0 if normal else native_symbols["m2_command_harness_end"]-native_symbols["m2_command_harness_start"],
                  interpreter_assembled_bytes=native_symbols["vm_end"]-native_symbols["vm_start"],
                  interpreter_table_bytes=native_symbols["vm_tables_end"]-native_symbols["vm_tables_start"],
                  interpreter_instruction_bytes=native_symbols["vm_tables_start"]-native_symbols["vm_start"],
                  cache_assembled_bytes=native_symbols["cache_code_end"]-native_symbols["cache_code_start"],
                  code_cache_runtime_bytes=8*line_size,
                  data_cache_runtime_bytes=8*line_size,
                  cache_metadata_bytes=112,
                  cache_work_area_reserved_bytes=96,
                  cache_work_area_used_bytes=cache_work_bytes,
                  cache_argument_and_scratch_zero_page_bytes=31,
                  margin_module_assembled_bytes=native_symbols["margin_module_end"]-native_symbols["margin_module_start"],
                  margin_record_bytes=32,margin_private_scratch_bytes=16,
                  margin_record_first=0x1080,margin_private_scratch_first=0x10a0,
                  margin_scratch_within_existing_staging_reservation=True,
                  active_architecture_and_bounds_bytes=96,
                  interpreter_scratch_bytes=30,
                  application_abi=m0.APPLICATION_ABI,
                  instruction_dispatch_entries=59,
                  multiply_assembled_bytes=native_symbols["vm_e_ld8"]-native_symbols["vm_e_mulu"],
                  multiply_scratch_first=native_symbols["V_PRODUCT"],
                  multiply_scratch_bytes=4,
                  multiply_scratch_reuses_dead_decode_state=True,
                  multiply_fixed_iterations=16,
                  diagnostic_mailbox_and_snapshot_reserved_bytes=0 if normal else 320,
                  observed_hardware_stack_bytes=None,
                  normal_stack_static_bound=18 if normal else 14,
                  irq_stack_static_bound=10 if margin_enabled else 8,
                  combined_stack_static_bound=(18 if normal else 14)+(10 if margin_enabled else 8)+4,
                  stack_bound_conditions="No nested IRQ or recursive NMI; margin qualification stays zero; optional idle hook adds two IRQ call-frame bytes",
                  numerical_future_target=4096,
                  numeric_target_shortfall=max(0,4096-(0x4000-native_end)),
                  numeric_shortfall_disposition="normal build must preserve the future 4 KiB target" if normal and not extended and not margin_enabled else "diagnostic or experimental artifact; no claim of production numeric headroom")
    if normal:
        report.update(
            scheduler_assembled_bytes=native_symbols["scheduler_module_end"]-native_symbols["scheduler_module_start"],
            jobs_assembled_bytes=native_symbols["jobs_module_end"]-native_symbols["jobs_module_start"],
            scheduler_global_reserved_bytes=128,
            scheduler_completion_bytes=42,
            scheduler_completion_and_replacement_staging_bytes=96,
            scheduler_pcb_metadata_bytes=128,
            scheduler_scratch_zero_page_bytes=17,
            runtime_video_and_entry_assembled_bytes=native_symbols["vm_start"]-native_symbols["m3_native_start"],
            native_link_does_not_import_bootstrap=True,
            stack_sentinel_byte=0xa5,
            bootstrap_reclaimed=True,
            bootstrap_reclaimed_first=0x0801,bootstrap_reclaimed_last=0x11ff,
            temporary_boot_staging_first=0x0600,temporary_boot_staging_last=0x07ff,
            resident_future_numeric_available_bytes=min(4096,max(0,0x4000-native_end)),
            resident_future_numeric_first=native_end,
            resident_future_numeric_last=native_end+4096-1,
            resident_headroom_after_numeric_target=0x4000-native_end-4096,
            future_modules=[
                dict(name="numeric core/conversions/bridge",reserved_bytes=4096,
                     assembled_bytes=0,shortfall=max(0,4096-(0x4000-native_end))),
                dict(name="event rings",reserved_bytes=512,assembled_bytes=0),
                dict(name="font",reserved_bytes=768,assembled_bytes=0),
                dict(name="cursor save-under",reserved_bytes=128,assembled_bytes=0),
                dict(name="shell/input/graphics/UCI/SID/audio code",reserved_bytes=None,
                     assembled_bytes=0,status="not yet sized; shares remaining resident and renderer preparation headroom")])
    return report


def build(args):
    milestone = getattr(args,"milestone","m2")
    normal = milestone == "m3"
    extended = bool(getattr(args,"extended_diagnostics",True))
    native_ram = 0x1200 if normal else NATIVE_RAM
    native_files = M3_FILES if normal else NATIVE_FILES
    jar = Path(args.kickass).expanduser().resolve()
    if not jar.is_file() or m0.digest(jar) != m0.KICK_SHA256:
        raise ValueError("Install the pinned Kick Assembler 5.25 jar; see docs/m0.md")
    tools = ROOT/"target/release"
    if not args.skip_host_build:
        command(["cargo", "build", "--locked", "--release"] + (["--offline"] if args.offline else []))
    manifest_path = Path(args.manifest).resolve()
    if manifest_path == ROOT/"manifests/m1.json":
        for name in ["linear", "calls", "spin"]:
            command([tools/"cosasm", f"apps/{name}.casm", "-o", f"build/{name}.cobj"])
    config = json.loads(manifest_path.read_text())
    source_snapshot = {name:(ROOT/"native"/name).read_bytes() for name in native_files}
    inputs = b"".join(source_snapshot.values())
    inputs += Path(__file__).read_bytes()
    inputs += json.dumps(config,sort_keys=True,separators=(",", ":")).encode()
    for app in config["apps"]:
        inputs += (ROOT/app["object"]).read_bytes()
    inputs += f"line={args.cache_line};delay={args.line_delay};margin={int(args.margin_hook)};milestone={milestone};extended={int(extended)}".encode()
    if normal:
        inputs += (ROOT/"scripts/m3.py").read_bytes()
    tag = int.from_bytes(hashlib.sha256(inputs).digest()[:4],"little")
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=milestone+"-",dir=out.parent) as temporary:
        stage=Path(temporary)
        prefix=stage/milestone
        command([tools/"cospack",manifest_path,"--root",ROOT,"--out",prefix,"--build-tag",str(tag)])
        linked=json.loads((stage/f"{milestone}.manifest.json").read_text())
        image=bytearray((stage/f"{milestone}.reu").read_bytes())
        for app in linked["apps"]:
            if app["data_seed"]["start"]+app["data_seed"]["length"] > NATIVE_REU:
                raise ValueError(f"App {app['id']} initialization seed overlaps native images at $008000")
        sources=stage/"sources"
        sources.mkdir()
        for name in native_files:
            (sources/name).write_bytes(source_snapshot[name])
        variables=dict(lineDelay=args.line_delay,buildTag=tag,renderBytes=0,
                       m2=1,m3=int(normal),extendedDiagnostics=int(extended),
                       appCount=len(linked["apps"]),cacheLine=args.cache_line,nativeBytes=0,marginEnabled=int(args.margin_hook))
        if normal:
            (sources/"m3-margins.inc").write_text(
                '#import "margins.asm"\n' if args.margin_hook or extended else
                '.const MARGIN_RECORD = $1080\n.const MARGIN_RECORD_BYTES = 32\n'
                '.const MARGIN_PRIVATE = $10a0\n.const MARGIN_PRIVATE_BYTES = 16\n'
                '.label margin_qualified = MARGIN_RECORD+25\n'
                '.label margin_state = MARGIN_RECORD\n'
                'margin_module_start:\nmargin_reset:\n'
                '    lda #0\n    ldx #47\n!:\n    sta MARGIN_RECORD,x\n'
                '    dex\n    bpl !-\n    rts\n'
                'margin_revoke_owner:\n    sec\n    rts\n'
                'margin_discard_cancelled:\nmargin_consume:\nmargin_irq_hook:\n    rts\n'
                'margin_module_end:\n')
            kernel,address,ns=m0.assemble(args.java,jar,sources/"m3_kernel.asm",stage,variables)
            if address!=native_ram or ns["m3_native_end"]>0x4000:
                raise ValueError("M3 native image exceeds local resident budget")
            variables["nativeBytes"]=len(kernel)
            variables["marginEntry"]=ns["margin_irq_hook"]
        renderer,address,rs=m0.assemble(args.java,jar,sources/"renderer.asm",stage,variables)
        if address!=0xf000 or rs["renderer_end"]>0xfa00:
            raise ValueError("Renderer outside its authorized destination")
        variables["renderBytes"]=len(renderer)
        (sources/"renderer-addresses.inc").write_text(
            f".const renderer_irq = ${rs['irq']:04x}\n.const renderer_nmi = ${rs['nmi']:04x}\n"+
            (f".const m2_kernel_start = ${ns['m3_kernel_entry']:04x}\n" if normal else ""))
        if normal:
            bootstrap,address,bs=m0.assemble(args.java,jar,sources/"m3_boot.asm",stage,variables)
            if address!=0x801 or bs["m3_bootstrap_end"]>native_ram:
                raise ValueError("M3 bootstrap overlaps final resident destination")
            ns.update({name:value for name,value in bs.items() if name not in ns})
        else:
            complete,address,ns=m0.assemble(args.java,jar,sources/"m2_boot.asm",stage,variables)
            if address!=0x801 or ns["m2_native_end"]>0x4000:
                raise ValueError("M2 native image exceeds local resident budget")
            variables["nativeBytes"]=ns["m2_native_end"]-NATIVE_RAM
            complete,address,ns=m0.assemble(args.java,jar,sources/"m2_boot.asm",stage,variables)
            kernel=complete[NATIVE_RAM-address:]
            if len(kernel)!=variables["nativeBytes"]:
                raise ValueError("Native image length changed after loader length was resolved")
            bootstrap=complete[:ns["m2_bootstrap_end_with_margin"]-address]
        ranges=[(NATIVE_REU,NATIVE_REU+len(kernel),"resident native"),
                (RENDERER_REU,RENDERER_REU+len(renderer),"renderer"),
                (DESCRIPTORS_REU,DESCRIPTORS_REU+512,"initial contexts"),
                (INITIALIZATION_REU,INITIALIZATION_REU+64,"initialization descriptors")]
        previous=NATIVE_REU
        for first,end,name in ranges:
            if first<previous or end>0x10000:
                raise ValueError(f"Native boot reserve overlap/overflow in {name}")
            previous=end
        image[NATIVE_REU:NATIVE_REU+len(kernel)]=kernel
        image[RENDERER_REU:RENDERER_REU+len(renderer)]=renderer
        for slot,app in enumerate(linked["apps"]):
            image[DESCRIPTORS_REU+slot*128:DESCRIPTORS_REU+(slot+1)*128]=initial_state(app)
            image[INITIALIZATION_REU+slot*16:INITIALIZATION_REU+(slot+1)*16]=initialization_record(app)
        (stage/f"{milestone}.reu").write_bytes(image)
        (stage/f"{milestone}.prg").write_bytes(address.to_bytes(2,"little")+bootstrap)
        (stage/"native.bin").write_bytes(kernel)
        (stage/"pattern.columns").write_bytes(m0.pattern())
        report=memory_report(kernel,renderer,ns,ns,args.cache_line,milestone,extended,args.margin_hook)
        report.update(build_tag=tag,line_delay=args.line_delay,margin_hook_enabled=args.margin_hook,margin_activation_qualified=False,bootstrap_load_bytes=len(bootstrap),
                      assembler_sha256=m0.KICK_SHA256,
                      source_sha256=hashlib.sha256(inputs).hexdigest(),
                      native_source_sha256={name:hashlib.sha256(data).hexdigest() for name,data in source_snapshot.items()},
                      reu_boot_images=[dict(first=f,last=e-1,bytes=e-f,name=n) for f,e,n in ranges],
                      reu_seed_limit_exclusive=NATIVE_REU,
                      renderer_symbols=rs,
                      artifact_sha256={name:m0.digest(stage/name) for name in
                          [f"{milestone}.prg",f"{milestone}.reu","native.bin","renderer.prg","pattern.columns",f"{milestone}.manifest.json"]},
                      symbols=ns)
        (stage/"map.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
        lines=[f"C-OS {milestone.upper()} cumulative local RAM map; inclusive bounds",
               "first last reserved assembled runtime remaining name"]
        for row in report["sections"]:
            lines.append(f"{row['first']:04x} {row['last']:04x} {row['reserved_bytes']:8} {row['assembled_bytes']:9} {row['runtime_bytes']:7} {row.get('uncommitted_bytes',row['reserved_bytes']):9} {row['name']}")
        lines += [f"Diagnostic harness: {report['diagnostic_harness_assembled_bytes']} assembled bytes.",
                  f"Runtime admission: PAL {report['runtime_admission_first_line']}–{report['runtime_admission_last_line']}; latest-start guard {report['latest_admission_guard_phi2']} PHI2 ticks.",
                  f"Future numeric target: 4096 within existing resident budget; shortfall: {report['numeric_target_shortfall']}.",
                  "Hardware stack depth: measured in fresh backend results; M0 bound does not apply.",
                  "Physical hardware timing qualification remains pending."]
        if normal:
            lines += [
                f"Normal bootstrap: $0801-${ns['m3_bootstrap_end']-1:04x}; final resident image begins $1200.",
                f"Scheduler/jobs: {report['scheduler_assembled_bytes']}/{report['jobs_assembled_bytes']} assembled bytes.",
                f"Future numeric interval: ${report['resident_future_numeric_first']:04x}-${report['resident_future_numeric_last']:04x}; headroom after target: {report['resident_headroom_after_numeric_target']} bytes.",
                "Future shell/input/graphics/UCI/SID/audio code remains unsized within the same fixed map; no claim that all remaining services fit."]
        (stage/"map.txt").write_text("\n".join(lines)+"\n")
        out.mkdir(exist_ok=True)
        m0.publish(stage,out)
    print(f"{milestone.upper()} {args.cache_line}-byte cache: resident={report['resident_assembled_bytes']}, VM={report['interpreter_assembled_bytes']}, cache={report['cache_assembled_bytes']}, diagnostics={report['diagnostic_harness_assembled_bytes']}; numeric shortfall={report['numeric_target_shortfall']}; tag=${tag:08x}")
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest",type=Path,default=ROOT/"manifests/m1.json")
    parser.add_argument("--out",type=Path,default=ROOT/"build/m2/128")
    parser.add_argument("--cache-line",type=int,choices=[64,128],default=128)
    parser.add_argument("--margin-hook",action="store_true",help="Emit the optional idle hook; no margin execution profile is qualified")
    parser.add_argument("--line-delay",type=int,default=140)
    parser.add_argument("--kickass",default=os.environ.get("KICKASS_JAR",ROOT/"toolchain/KickAss.jar"))
    parser.add_argument("--java",default=os.environ.get("JAVA","java"))
    parser.add_argument("--offline",action="store_true")
    parser.add_argument("--skip-host-build",action="store_true")
    args=parser.parse_args()
    if not 1<=args.line_delay<=255:
        parser.error("line delay must be1..255")
    try:
        build(args)
    except (ValueError,OSError) as error:
        print(f"m2: {error}",file=sys.stderr)
        return 1
    return 0


if __name__=="__main__":
    raise SystemExit(main())
