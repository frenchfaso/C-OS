#!/usr/bin/env python3
"""Run the original M0 artifacts against a user-supplied UE2/TRX64 backend.

UE2 and its firmware/ROMs are external developer dependencies; no files from
that project are modified or distributed by C-OS.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from m0 import pattern_pixel
from png_rgb import read_rgb

ROOT = Path(__file__).resolve().parents[1]


def writes(space, address, data):
    return [f"monitor wr {space if space != 'fw' else ''} {address+i:08x} {data[i:i+128].hex(' ')}"
            for i in range(0,len(data),128)]


def memory(log, first, length, prefix="R"):
    found = {}
    for address, values in re.findall(r"^>"+prefix+r":([0-9a-fA-F]+)((?:\s+[0-9a-fA-F]{2})+)",log,re.M):
        address = int(address,16)
        for i,value in enumerate(bytes.fromhex(values)):
            found[address+i] = value
    missing = [a for a in range(first,first+length) if a not in found]
    if missing:
        raise ValueError(f"Missing monitor memory dump at ${missing[0]:x}")
    return bytes(found[a] for a in range(first,first+length))


def scanout_geometry(path):
    width,height,rows = read_rgb(path)
    if (width,height) != (720,576):
        raise ValueError("This adapter qualifies the PAL 720x576, 15/8 horizontal, 2x vertical profile")
    white = max((p for row in rows for p in row),key=lambda p:sum(p))
    white_rows = []
    for y,row in enumerate(rows):
        positions = [x for x,p in enumerate(row) if p==white]
        if positions and len(positions)>500 and positions[-1]-positions[0]+1==len(positions):
            white_rows.append((y,positions[0],positions[-1]+1))
    if len(white_rows)!=4:
        raise ValueError("Top/bottom one-pixel white edges are missing or clipped")
    y0,left,right = white_rows[0]
    if white_rows != [(y0,left,right),(y0+1,left,right),(y0+398,left,right),(y0+399,left,right)]:
        raise ValueError("Scanout does not contain exactly 200 consecutive PAL source lines")
    stripe = rows[y0+2*100]
    starts = [left]+[x for x in range(left+1,right) if stripe[x] != stripe[x-1]]+[right]
    if len(starts)-1 != 320:
        raise ValueError(f"Expected 320 separately visible stripe/edge pixels, got {len(starts)-1}")
    centers = [(starts[x]+starts[x+1]-1)//2 for x in range(320)]
    # Derive RGBs from the 16 labeled uniform bars. RGB is firmware-configured;
    # C64 palette indices, geometry and pixel order are the contract.
    palette = [rows[y0+2*30][centers[i*20+10]] for i in range(16)]
    if len(set(palette)) != 16:
        raise ValueError("Capture does not distinguish all 16 palette indices")
    for y in range(200):
        for sy in [y0+y*2,y0+y*2+1]:
            for x in range(320):
                if rows[sy][centers[x]] != palette[pattern_pixel(x,y)]:
                    raise ValueError(f"Scanout pixel mismatch at source ({x},{y}), output row {sy}")
    return dict(source_width=320,source_height=200,output_width=width,output_height=height,
                output_rectangle=[left,y0,right-left,400],
                separately_visible_stripe_pixels=320,
                all_64000_pixels_and_both_output_rows_match=True,
                palette_rgb=[list(p) for p in palette],
                first_and_last_pixels_visible=True,even_low_odd_high=True)


def run(args):
    out = Path(args.out).resolve()
    out.mkdir(parents=True,exist_ok=True)
    (out/"result.json").unlink(missing_ok=True)
    build = Path(args.build).resolve()
    spec = json.loads((build/"map.json").read_text())
    image = bytearray((build/"diagnostic.reu").read_bytes())
    prg = (build/"probe.prg").read_bytes()
    sentinel = bytes((i*73+29)&255 for i in range(256))
    commands = ["wait 6000"]
    if not args.no_reu:
        commands += ['expect-console "REU Load: Loaded" 30000']
    commands += ["monitor c64 halt","monitor cart","monitor clock"]
    # The firmware preloads a private copy. Sentinel bytes exercise restoration
    # of nonzero contents; the published diagnostic pack stays byte-identical.
    for bank,value in enumerate(sentinel):
        image[0x40+bank*65536] = value
    image[0x4000:0x4100] = sentinel
    if args.bad_pack:
        image[8] ^= 1
    usb = out/"usb"
    usb.mkdir(exist_ok=True)
    (usb/"diagnostic.reu").write_bytes(image)
    settings = out/"settings.cfg"
    settings.write_text(Path(args.settings).read_text()+
                        "\n[C64 and Cartridge Settings]\nREU Preload=Enabled\nREU Preload Image=/Usb0/diagnostic.reu\n"+
                        (f"REU Size={args.reu_size}\n" if args.reu_size else "")+
                        ("RAM Expansion Unit=Disabled\n" if args.no_reu else "")+
                        (f"\n[U64 Specific Settings]\nTurbo Control=Manual\nCPU Speed={args.manual_turbo}\n" if args.manual_turbo else "")+
                        ("\n[U64 Specific Settings]\nSystem Mode=NTSC\n" if args.ntsc else ""))
    for bank in range(256):
        commands.append(f"monitor fw-memory {0x1000040+bank*65536:08x} {0x1000040+bank*65536:08x}")
    commands += ["monitor fw-memory 01004000 010040ff"]
    commands += writes("ram",int.from_bytes(prg[:2],"little"),prg[2:])
    commands += ["monitor g 1200",f"wait {args.milliseconds}",f"png {out/'scanout.png'}","monitor c64 halt",
                 "monitor status","monitor m ram 0300 034f",
                 "monitor m ram 4000 cfff","monitor m ram e000 efff",
                 "monitor clock","monitor cart"]
    for bank in range(256):
        commands.append(f"monitor fw-memory {0x1000040+bank*65536:08x} {0x1000040+bank*65536:08x}")
    commands += ["monitor fw-memory 01004000 010040ff","quit"]
    (out/"run.ctl").write_text("\n".join(commands)+"\n")
    shutil.copyfile(args.flash,out/"isolated-flash.bin")
    command = [str(Path(args.emulator).resolve()),"run","--config",str(Path(args.config).resolve()),
               "--flash",str(out/"isolated-flash.bin"),"--settings",str(settings),"--usb-dir",str(usb),
               "--headless","--speed","max","--audio","off","--script",str(out/"run.ctl")]
    with (out/"emulator.log").open("w") as log:
        process = subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,cwd=out,
                                 timeout=args.timeout,check=False)
    log = (out/"emulator.log").read_text()
    if process.returncode:
        raise ValueError(f"UE2 exited {process.returncode}; inspect {out/'emulator.log'}")
    report = memory(log,0x300,80)
    if report[:4] != b"M0R1" or report[4] != args.expect_status:
        raise ValueError(f"Probe failed: report={report.hex(' ')}")
    before = re.split(r"c64\s+running at \$1200",log,maxsplit=1)[0]
    for bank,value in enumerate(sentinel):
        expected = memory(before,0x1000040+bank*65536,1,"FW")
        if memory(log,0x1000040+bank*65536,1,"FW") != expected:
            raise ValueError(f"Alias probe failed to preserve physical bank {bank}")
    if memory(log,0x1004000,256,"FW") != memory(before,0x1004000,256,"FW"):
        raise ValueError("DMA benchmark failed to preserve the independently seeded REU contents")
    geometry = None
    if report[4] == 1:
        columns = memory(log,0x4000,36864)+memory(log,0xe000,4096)
        if columns != (build/"pattern.columns").read_bytes():
            raise ValueError("Framebuffer differs from independent host diagnostic pattern")
        geometry = scanout_geometry(out/"scanout.png")
    u16 = lambda offset: int.from_bytes(report[offset:offset+2],"little")
    measured = []
    names = [("setup",1),("timer",0),("FETCH",1),("FETCH",16),("FETCH",64),
             ("FETCH",128),("FETCH",256),("STASH",1),("STASH",16),
             ("STASH",64),("STASH",128),("STASH",256)]
    for i,(direction,length) in enumerate(names):
        offset = 32+i*4
        measured.append(dict(direction=direction,bytes=length,
                             minimum_phi2_ticks=u16(offset),maximum_phi2_ticks=u16(offset+2)))
    result = dict(format="COSM0UE2RESULT1",qualification="Functional emulation only; hardware timing pending",
                  backend_executable_sha256=hashlib.sha256(Path(args.emulator).read_bytes()).hexdigest(),
                  supplied_config=str(Path(args.config).resolve()),
                  supplied_settings_sha256=hashlib.sha256(Path(args.settings).read_bytes()).hexdigest(),
                  executed_private_reu_sha256=hashlib.sha256(image).hexdigest(),
                  artifact_sha256=spec["artifact_sha256"],line_delay=spec["line_delay"],
                  raster_lines=u16(5),slow_cpu_loop_count=u16(7),fast_cpu_loop_count=u16(9),
                  expected_status=args.expect_status,actual_status=report[4],
                  reu_banks=u16(12),restore_errors=report[14],alias_detected=report[15],
                  scanouts=u16(16),missed_syncs=u16(18),nmi_count=u16(20),
                  deferred_dma=u16(22),runtime_dma_pairs=u16(24),active_dma_violations=u16(26),
                  maximum_observed_stack_bytes=report[28],
                  framebuffer_matches=bool(geometry),timings=measured if geometry else [],
                  independent_reu_restoration_matches=True,scanout=geometry,
                  sample_emulated_milliseconds=args.milliseconds)
    if geometry and (result["raster_lines"] != 312 or result["reu_banks"] != 256 or result["restore_errors"]):
        raise ValueError("PAL/REU qualification failed")
    if geometry and (not result["scanouts"] or result["missed_syncs"] or result["active_dma_violations"]):
        raise ValueError("Raster qualification failed")
    (out/"result.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for argument in ["emulator","config","flash","settings"]:
        parser.add_argument("--"+argument,required=True,type=Path)
    parser.add_argument("--build",default=ROOT/"build/m0",type=Path)
    parser.add_argument("--out",default=ROOT/"build/m0/ue2",type=Path)
    parser.add_argument("--milliseconds",type=int,default=2000)
    parser.add_argument("--timeout",type=int,default=120)
    parser.add_argument("--expect-status",type=lambda text:int(text,0),default=1)
    parser.add_argument("--reu-size",choices=["128 KB","256 KB","512 KB","1 MB","2 MB","4 MB","8 MB","16 MB"])
    parser.add_argument("--no-reu",action="store_true")
    parser.add_argument("--manual-turbo",type=int,choices=[1,16,32,48,64])
    parser.add_argument("--ntsc",action="store_true")
    parser.add_argument("--bad-pack",action="store_true")
    parser.add_argument("--suite",action="store_true",help="Run geometry, preservation and rejected-profile cases")
    args=parser.parse_args()
    try:
        if args.suite:
            (args.out/"suite.json").unlink(missing_ok=True)
            cases=[("pal64-reu16",{}),
                   ("reu128",dict(reu_size="128 KB",expect_status=0xe3)),
                   ("reu512",dict(reu_size="512 KB",expect_status=0xe3)),
                   ("reu2m",dict(reu_size="2 MB",expect_status=0xe3)),
                   ("reu8m",dict(reu_size="8 MB",expect_status=0xe3)),
                   ("reu-absent",dict(no_reu=True,expect_status=0xe3)),
                   ("turbo32",dict(manual_turbo=32,expect_status=0xe2,milliseconds=6500)),
                   ("turbo48",dict(manual_turbo=48,expect_status=0xe2,milliseconds=6500)),
                   ("ntsc",dict(ntsc=True,expect_status=0xe1)),
                   ("bad-pack",dict(bad_pack=True,expect_status=0xe4))]
            summary=[]
            for name,changes in cases:
                case=copy.copy(args)
                case.out=args.out/name
                for key,value in changes.items():
                    setattr(case,key,value)
                print(f"Running {name}",flush=True)
                run(case)
                result=json.loads((case.out/"result.json").read_text())
                summary.append(dict(case=name,status=result["actual_status"],
                                    reu_banks=result["reu_banks"],
                                    fast_cpu_loop_count=result["fast_cpu_loop_count"],
                                    restored=result["independent_reu_restoration_matches"]))
            (args.out/"suite.json").write_text(json.dumps(summary,indent=2)+"\n")
        else:
            run(args)
    except (ValueError,OSError,subprocess.TimeoutExpired) as error:
        print(f"m0_ue2: {error}",file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
