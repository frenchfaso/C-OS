#!/usr/bin/env python3
"""Start an autonomous M3 kernel and collect target state without opcode commands."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

from m0_ue2 import memory, scanout_geometry
from m0_ue2 import writes
import m0
import m2
from m2_compare import integer, metadata_entries
from m2_ue2 import Target


class AutonomousTarget(Target):
    def __init__(self,args):
        self.args=args
        self.out=Path(args.out).resolve()
        self.out.mkdir(parents=True,exist_ok=True)
        (self.out/'result.json').unlink(missing_ok=True)
        build=Path(args.build)
        self.spec=json.loads((build/'map.json').read_text())
        self.line=self.spec['cache_line_bytes']
        loaded={name:(build/name).read_bytes() for name in ['m3.prg','m3.reu','m3.manifest.json']}
        self.loaded_artifact_sha256={name:hashlib.sha256(data).hexdigest() for name,data in loaded.items()}
        for name,digest in self.loaded_artifact_sha256.items():
            if digest!=self.spec['artifact_sha256'][name]:
                raise ValueError(f'M3 startup artifact differs from map: {name}')
        self.input_sha256={name:m0.digest(Path(getattr(args,name)))
                           for name in ['emulator','config','flash','settings']}
        self.input_sha256['runner']=m0.digest(Path(__file__))
        self.linked=json.loads(loaded['m3.manifest.json'])
        self.log=(self.out/'protocol.log').open('w')
        self.trace=(self.out/'snapshots.jsonl').open('w')
        self.emulog=(self.out/'emulator.log').open('w')
        usb=self.out/'usb';usb.mkdir(exist_ok=True)
        image=loaded['m3.reu']
        (usb/'diagnostic.reu').write_bytes(image)
        self.private_image_sha256=hashlib.sha256(image).hexdigest()
        shutil.copyfile(args.flash,self.out/'isolated-flash.bin')
        settings=self.out/'settings.cfg'
        settings.write_text(Path(args.settings).read_text()+'\n[C64 and Cartridge Settings]\nREU Preload=Enabled\nREU Preload Image=/Usb0/diagnostic.reu\n')
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
        command=[str(Path(args.emulator).resolve()),'run','--config',str(Path(args.config).resolve()),
                 '--flash',str(self.out/'isolated-flash.bin'),'--settings',str(settings),'--usb-dir',str(usb),
                 '--headless','--speed','max','--audio','off','--control',f'127.0.0.1:{port}']
        self.process=subprocess.Popen(command,stdout=self.emulog,stderr=subprocess.STDOUT,cwd=self.out)
        deadline=time.monotonic()+15
        while True:
            try:
                self.socket=socket.create_connection(('127.0.0.1',port),timeout=args.timeout)
                break
            except OSError:
                if self.process.poll() is not None or time.monotonic()>deadline:
                    raise ValueError('Backend did not open its local control endpoint')
                time.sleep(.05)
        self.socket.settimeout(args.timeout)
        self.socket.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        self.stream=self.socket.makefile('rwb',buffering=0)
        self.command('wait 6000')
        self.command('expect-console "REU Load: Loaded" 30000')
        self.command('monitor c64 halt')
        prg=loaded['m3.prg']
        self.write(int.from_bytes(prg[:2],'little'),prg[2:])
        self.command('monitor g 080d')
        self.command(f'wait {getattr(args,"startup_milliseconds",1000)}')
        report=self.read(0x300,80)
        if report[:5]!=b'M0R1\x01':
            raise ValueError(f'Native M3 bootstrap failed: {report.hex(" ")}')
        self.initial_report=report

    def snapshot(self):
        # One bounded diagnostic pause only, never execution control per opcode.
        self.write(0xfe0d,[0])
        # More than two PAL periods: an already-admitted phase/turn finishes
        # and the outer scheduler observes CONTROL before any state is read.
        self.command('wait 50')
        contexts=[self.read(0x400+slot*128,128) for slot in range(4)]
        active=self.read(2,96);slot=self.read(0x3b0,1)[0]
        if slot<4:
            contexts[slot]=active+contexts[slot][96:]
        globals_=self.read(0xfe00,128)
        metadata=self.read(0xfd80,112)
        data=self.read(0xc00,8*self.line)
        return dict(contexts=[list(x) for x in contexts],active_slot=slot,
                    globals=list(globals_),metadata=list(metadata),data_cache=list(data),
                    cache_work=list(self.read(0x350,96)),report=list(self.read(0x300,80)),
                    margin_record=list(self.read(0x1080,48)),stack_page=list(self.read(0x100,256)))

    def pending_job_pair(self):
        # Live monitor commands let the target progress between owner reads.
        # Use the same unwound scheduler boundary as snapshot(), then resume.
        self.write(0xfe0d,[0])
        try:
            self.command('wait 50')
            pair=self.read(0x500,256)
            return pair[:128],pair[128:]
        finally:
            self.write(0xfe0d,[1])

    def logical(self,snapshot,address,length):
        result=bytearray(self.read(address,length,True))
        for entry in metadata_entries(snapshot['metadata']):
            if entry['index']<8 or entry['flags']&3!=3:
                continue
            first=max(address,entry['tag']);last=min(address+length,entry['tag']+self.line)
            if first<last:
                offset=(entry['index']-8)*self.line+first-entry['tag']
                result[first-address:last-address]=bytes(snapshot['data_cache'][offset:offset+last-first])
        return bytes(result)


def run(args):
    target=None
    try:
        target=AutonomousTarget(args)
        target.command(f'wait {args.milliseconds}')
        snapshot=target.snapshot()
        report=snapshot['report']
        result=dict(format='COSM3UE2RESULT1',qualification='Functional emulation; physical Ultimate timing pending',
                    autonomous=True,host_opcode_commands=0,cache_line_bytes=target.line,
                    build_tag=target.spec['build_tag'],artifact_sha256=target.spec['artifact_sha256'],
                    loaded_artifact_sha256=target.loaded_artifact_sha256,input_sha256=target.input_sha256,
                    backend_executable_sha256=hashlib.sha256(Path(args.emulator).read_bytes()).hexdigest(),
                    frame=integer(snapshot['globals'],0,4),missed_syncs=integer(report,18,2),
                    active_dma_violations=integer(report,26,2),snapshot=snapshot)
        touched=[i for i,value in enumerate(snapshot['stack_page']) if value!=0xa5]
        result['stack_touched_depth_lower_bound']=256-min(touched) if touched else 0
        if result['missed_syncs'] or result['active_dma_violations']:
            raise ValueError('Autonomous M3 violated video timing')
        for slot,app in enumerate(target.linked['apps']):
            state=snapshot['contexts'][slot]
            print(f"M3 slot{slot} {app['name']}: retired{integer(state,35,8)}, state{state[96]}, fuel{state[34]}, R0{integer(state,0,2)}",flush=True)
        (Path(args.out)/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        return result
    finally:
        if target is not None:target.close()


def native_contract(args):
    out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True)
    (out/'result.json').unlink(missing_ok=True)
    root=Path(__file__).resolve().parents[1]
    jar=args.kickass.resolve()
    if not jar.is_file() or m0.digest(jar)!=m0.KICK_SHA256:
        raise ValueError('The pinned Kick Assembler5.25 jar is required')
    sources=out/'sources';sources.mkdir(exist_ok=True)
    files=['build_profile.inc','m2_abi.inc','scheduler.inc','vm.asm','cache.asm','scheduler.asm','jobs.asm']
    for name in files:shutil.copyfile(root/'native'/name,sources/name)
    source=root/'tests/native/m3_scheduler.asm'
    shutil.copyfile(source,sources/source.name)
    assembled_source_sha256=hashlib.sha256((sources/source.name).read_bytes()+
                                  b''.join((sources/name).read_bytes() for name in files)).hexdigest()
    image,first,symbols=m0.assemble(args.java,jar,sources/source.name,out,
                                    dict(cacheLine=args.cache_line,extendedDiagnostics=1))
    usb=out/'usb';usb.mkdir(exist_ok=True)
    shutil.copyfile(args.flash,out/'isolated-flash.bin')
    shutil.copyfile(args.settings,out/'settings.cfg')
    commands=['wait 6000','monitor c64 halt']+writes('ram',first,image)
    commands+=['monitor g 1200','wait 100','monitor c64 halt','monitor m ram 03e0 03ef',
               'monitor m ram fe00 fe7f','monitor m ram 0400 05ff','monitor status','quit']
    script=out/'run.ctl';script.write_text('\n'.join(commands)+'\n')
    command=[str(args.emulator.resolve()),'run','--config',str(args.config.resolve()),
             '--flash',str(out/'isolated-flash.bin'),'--settings',str(out/'settings.cfg'),
             '--usb-dir',str(usb),'--headless','--speed','max','--audio','off','--script',str(script)]
    with (out/'emulator.log').open('w') as log:
        process=subprocess.run(command,cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=args.timeout,check=False)
    if process.returncode:raise ValueError(f'Native scheduler contract backend exited{process.returncode}')
    log=(out/'emulator.log').read_text();report=memory(log,0x3e0,16)
    if report[:6]!=b'MS3\x01\x00\x7e':
        raise ValueError(f'Native scheduler contract failed: {report.hex(" ")}; inspect {out / "emulator.log"}')
    result=dict(format='COSM3SCHEDULER1',native_assertions=126,failures=report[4],cache_line_bytes=args.cache_line,
                autonomous=True,host_opcode_commands=0,qualification='Native contract emulation; raster integration tested separately',
                backend_executable_sha256=m0.digest(args.emulator),assembler_sha256=m0.KICK_SHA256,
                source_sha256=assembled_source_sha256,
                prg_sha256=m0.digest(out/'m3_scheduler.prg'),
                scheduler_bytes=symbols['scheduler_module_end']-symbols['scheduler_module_start'],
                jobs_bytes=symbols['jobs_module_end']-symbols['jobs_module_start'])
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2),flush=True)
    return result


def cia2_nmi_recovery(target):
    # Pause at an architectural boundary, then use the documented I/O lens.
    # "wr ram" writes backing RAM and cannot arm a CIA timer.
    before=target.snapshot()
    for address,value in [(0xdd0e,0),(0xdd05,0),(0xdd04,128),
                          (0xdd0d,0x81),(0xdd0e,0x19)]:
        target.command(f'monitor wr io {address:04x} {value:02x}')
    target.command('wait 100')
    after=target.snapshot()
    for key in ['contexts','metadata','data_cache','cache_work']:
        if before[key]!=after[key]:
            raise ValueError('Real CIA2 NMI recovery changed '+key)
    nmis=(integer(after['report'],20,2)-integer(before['report'],20,2))&0xffff
    recoveries=(integer(after['report'],30,2)-integer(before['report'],30,2))&0xffff
    if not nmis or not recoveries:
        raise ValueError('CIA2 one-shot did not invoke and recover the installed NMI')
    if integer(after['report'],18,2) or integer(after['report'],26,2):
        raise ValueError('CIA2 NMI recovery violated video timing')
    if after['margin_record'][0] or after['margin_record'][25]:
        raise ValueError('CIA2 recovery activated the disabled margin record')
    target.write(0xfe0d,[1])
    return dict(actual_cia2_one_shot=True,monitor_lens='io',native_sp_preserved=True,
                nmis=nmis,recoveries=recoveries,architecture_cache_and_continuations_unchanged=True,
                before=before,after=after)


def autonomous_suite(args):
    """Trusted startup/observations only; the target schedules every instruction."""
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    (out/'result.json').unlink(missing_ok=True)
    root=Path(__file__).resolve().parents[1]
    inputs=out/'inputs';inputs.mkdir(exist_ok=True)
    loop=''' .entry start
.code
start: PLI P0,progress
loop: ADDI R2,1
ST16 R2,P0,0
'''+('NOP\n'*300)+'''JMP loop
.data
.byte '''+','.join(['0']*127)+'''
progress: .word 0
.byte $5a
'''
    fill=''' .entry start
.code
start: PLI P0,buffer
LDI R1,$a5
LDI R2,2051
LDI R3,0
SYSCALL $0a
ST16 R0,P2,0
LDI R0,31
SYSCALL 0
.data
.word $ffff
.bss
buffer: .space 2051
guard: .space 1
'''
    pattern=bytes((i*37+11)&255 for i in range(2051))
    copy=''' .entry start
.code
start: PLI P0,buffer
PLI P1,source
LDI R2,2051
LDI R3,0
SYSCALL $0b
ST16 R0,P2,0
LDI R0,32
SYSCALL 0
.data
.word $ffff
source: .byte '''+','.join(map(str,pattern))+'''
.bss
buffer: .space 2051
guard: .space 1
'''
    sleep=''' .entry start
.code
start: SYSCALL 2
ST16 R1,P2,0
ST16 R2,P2,2
LDI R0,5
SYSCALL 3
SYSCALL 2
ST16 R1,P2,4
ST16 R2,P2,6
LDI R0,33
SYSCALL 0
.data
.byte 0,0,0,0,0,0,0,0
'''
    fault='.entry start\nstart: TRAP 23\n'
    cancel=fill.replace('2051','30000')
    results=[]
    for case,sources in [('fair-jobs',[loop,loop,fill,copy]),
                         ('sleep-fault',[loop,loop,sleep,fault]),
                         ('cancel-job',[loop,loop,cancel,copy])]:
        apps=[]
        for slot,source in enumerate(sources):
            path=inputs/f'{case}-{slot}.casm';path.write_text(source)
            obj=path.with_suffix('.cobj')
            m2.command([root/'target/release/cosasm',path,'-o',obj])
            apps.append(dict(id=slot+1,name=f'{case}-{slot}',object=str(obj.relative_to(root)),
                             arena_start=0x40000+slot*0x10000,arena_size=0x10000,
                             stack_size=1024,heap_min=128))
        manifest=inputs/f'{case}.json'
        manifest.write_text(json.dumps(dict(format='COSPACK1',abi=m0.APPLICATION_ABI,numeric_profile='COS-NUM-1',
                         target='c64u-pal-upic320',storage=dict(mode='discover',directory='cos',marker='.cos-volume'),
                         apps=apps),indent=2)+'\n')
        build=out/'build'
        m2.command([sys.executable,root/'scripts/m3.py','--manifest',manifest,'--out',build,
                    '--cache-line',args.cache_line,'--kickass',args.kickass,'--java',args.java,
                    '--offline','--skip-host-build','--require-numeric-fit'])
        target_args=argparse.Namespace(**vars(args))
        target_args.build=build;target_args.out=out/'backend';target_args.startup_milliseconds=250
        target=None
        try:
            target=AutonomousTarget(target_args)
            fairness_sample=None;nmi=None
            if case=='cancel-job':
                # Observe a genuinely pending, already-progressing job before
                # making one trusted cancellation request.
                for _ in range(30):
                    before=target.read(0x500,128)
                    if before[96]==3 and integer(before,124,4)>0:break
                    target.command('wait 200')
                else:raise ValueError('cancel-job: target never started the cancellable job')
                # One trusted owner-cancellation request; no instruction driving.
                target.write(0xfe0e,[3])
            elif case=='fair-jobs':
                for _ in range(30):
                    a,b=target.pending_job_pair()
                    if a[96]==3 and b[96]==3:break
                    target.command('wait 200')
                else:raise ValueError('fair-jobs: both jobs were never simultaneously pending')
                initial_phases=[integer(a,124,4),integer(b,124,4)]
                target.command('wait 400')
                a,b=target.pending_job_pair()
                fairness_sample=[(integer(s,124,4)-initial)&0xffffffff
                                 for s,initial in zip([a,b],initial_phases)]
                if min(fairness_sample)<1 or abs(fairness_sample[0]-fairness_sample[1])>4:
                    raise ValueError(f'fair-jobs: native owner rotation differs: {fairness_sample}')
                nmi=cia2_nmi_recovery(target)
            target.command(f'wait {1500 if case=="sleep-fault" else args.milliseconds}')
            target.command(f'png {out / (case+".png")}')
            geometry=scanout_geometry(out/(case+'.png'))
            snapshot=target.snapshot();g=snapshot['globals'];states=snapshot['contexts']
            (out/(case+'-snapshot.json')).write_text(json.dumps(snapshot,indent=2)+'\n')
            report=snapshot['report']
            if snapshot['margin_record'][0] or snapshot['margin_record'][25]:
                raise ValueError(f'{case}: default-disabled margin record became active')
            if integer(report,18,2) or integer(report,26,2):
                raise ValueError(f'{case}: video synchronization/DMA violation')
            retired=[integer(s,35,8) for s in states]
            if min(retired[:2])<100:
                raise ValueError(f'{case}: a non-yield loop did not progress: {retired}')
            progress=[]
            for slot in [0,1]:
                address=target.linked['apps'][slot]['symbols']['progress']
                progress.append(integer(target.logical(snapshot,address,2),0,2))
            if min(progress)<1:
                raise ValueError(f'{case}: loop progress stores are absent')
            if case=='sleep-fault':
                if states[2][96]!=0 or states[3][96]!=5 or integer(states[3],76,2)!=23:
                    raise ValueError(f'{case}: EXIT/fault isolation failed')
                app=target.linked['apps'][2]
                timing=target.logical(snapshot,app['data']['start'],8)
                elapsed=(integer(timing,4,4)-integer(timing,0,4))&0xffffffff
                if not 5<=elapsed<15:
                    raise ValueError(f'{case}: sleep elapsed{elapsed} frames')
                wake=integer(g,96+8,4);dispatch=integer(g,112+8,4)
                latency=(dispatch-wake)&0xffffffff
                if latency>2:
                    raise ValueError(f'{case}: wake-to-dispatch latency{latency} frames')
            else:
                slots=[2,3] if case=='fair-jobs' else [3]
                for slot in slots:
                    app=target.linked['apps'][slot]
                    if states[slot][96]!=0 or integer(states[slot],0,2)!=slot+29:
                        raise ValueError(f'{case}: long job slot{slot} did not exit successfully')
                    if target.logical(snapshot,app['data']['start'],2)!=b'\0\0':
                        raise ValueError(f'{case}: slot{slot} syscall status is nonzero')
                    expected=bytes([0xa5])*2051 if slot==2 else pattern
                    actual=target.logical(snapshot,app['symbols']['buffer'],2052)
                    if actual!=expected+b'\0':
                        raise ValueError(f'{case}: full job data or end guard differs')
                    if integer(g,72+slot*2,2)!=1 or integer(states[slot],120,4)!=2051:
                        raise ValueError(f'{case}: completion count/native bytes differ')
                if case=='cancel-job':
                    if states[2][96]!=0 or states[2][90] or g[15]!=1:
                        raise ValueError(f'{case}: cancelled owner remained active')
                    if any(e['flags']&1 and e['owner']==2 for e in metadata_entries(snapshot['metadata'])):
                        raise ValueError(f'{case}: cancelled owner retained cache lines')
            touched=[i for i,v in enumerate(snapshot['stack_page']) if v!=0xa5]
            result=dict(case=case,autonomous=True,host_opcode_commands=0,retired=retired,
                        progress=progress,frame=integer(g,0,4),native_max_phi2=integer(g,84,2),
                        native_ticks=[integer(g,24+i*4,4) for i in range(4)],
                        dma_bytes=[integer(g,40+i*4,4) for i in range(4)],
                        switches=[integer(g,16+i*2,2) for i in range(4)],
                        native_bytes=[integer(s,120,4) for s in states],
                        native_chunks=[integer(s,124,4) for s in states],
                        completions=[integer(g,72+i*2,2) for i in range(4)],
                        stack_touched_depth_lower_bound=256-min(touched) if touched else 0,
                        missed_syncs=integer(report,18,2),active_dma_violations=integer(report,26,2),
                        scanout=geometry,build_tag=target.spec['build_tag'],
                        artifact_sha256=target.spec['artifact_sha256'],snapshot=snapshot)
            result.update(loaded_artifact_sha256=target.loaded_artifact_sha256,input_sha256=target.input_sha256)
            if case=='sleep-fault':result.update(sleep_frames=elapsed,wake_dispatch_frames=latency)
            if fairness_sample is not None:
                result['simultaneous_native_phase_counts']=fairness_sample
                result['native_phase_sample_method']='CONTROL=0, 50ms boundary settle, single 256-byte PCB read, CONTROL=1'
            if nmi is not None:result['cia2_nmi_recovery']=nmi
            if case=='cancel-job':result['cancelled_pending_job_before']=list(before)
            (out/(case+'.json')).write_text(json.dumps(result,indent=2)+'\n')
            results.append(result)
            print(f'M3 autonomous {case}: pass, retired{retired}, frame{result["frame"]}',flush=True)
        finally:
            if target is not None:target.close()
    result=dict(format='COSM3AUTONOMOUS1',cache_line_bytes=args.cache_line,cases=results,
                qualification='Functional emulation; physical Ultimate timing pending',
                host_opcode_commands=0,input_sha256=results[-1]['input_sha256'],
                backend_executable_sha256=results[-1]['input_sha256']['emulator'])
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['emulator','config','flash','settings','out']:
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--build',type=Path)
    p.add_argument('--native-contract',action='store_true')
    p.add_argument('--suite',action='store_true')
    p.add_argument('--cache-line',type=int,choices=[64,128],default=128)
    p.add_argument('--kickass',type=Path)
    p.add_argument('--java',default='java')
    p.add_argument('--timeout',type=float,default=30)
    p.add_argument('--milliseconds',type=int,default=1000)
    return p


if __name__=='__main__':
    try:
        args=parser().parse_args()
        if args.native_contract:native_contract(args)
        elif args.suite:autonomous_suite(args)
        elif args.build is not None:run(args)
        else:raise ValueError('--build or --native-contract is required')
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        print(f'm3_ue2: {error}',file=sys.stderr)
        raise SystemExit(1)
