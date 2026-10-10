#!/usr/bin/env python3
"""Autonomous image computation versus native PAL1MHz, with target time only."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

from m2_ue2 import Target
from m2_compare import logical_bytes
from mandelbrot_reference import WIDTH, HEIGHT, LIMIT, image as reference_image
from m0 import assemble

ROOT = Path(__file__).resolve().parents[1]
FRAME_TICKS = 312*63
COLLECTION_BOUND_FRAMES = 64
COORDINATE_STEP = 64


def image():
    return reference_image(WIDTH, HEIGHT, LIMIT, COORDINATE_STEP)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Session(Target):
    """Reuse the proven monitor transport; no M2 opcode commands are issued."""
    def __init__(self,args,out,image_path=None):
        self.out=Path(out).resolve();self.out.mkdir(parents=True,exist_ok=True)
        self.log=(self.out/'protocol.log').open('w')
        self.emulog=(self.out/'emulator.log').open('w')
        self.input_sha256={name:sha(getattr(args,name))
                           for name in ['emulator','config','flash','settings']}
        usb=self.out/'usb';usb.mkdir(exist_ok=True)
        settings=self.out/'settings.cfg'
        extra='\n[C64 and Cartridge Settings]\n'
        if image_path:
            shutil.copyfile(image_path,usb/'diagnostic.reu')
            extra+='REU Preload=Enabled\nREU Preload Image=/Usb0/diagnostic.reu\n'
        else:
            extra+='REU Preload=Disabled\nRAM Expansion Unit=Disabled\n'
        settings.write_text(Path(args.settings).read_text()+extra)
        flash=self.out/'isolated-flash.bin';shutil.copyfile(args.flash,flash)
        if sha(flash)!=self.input_sha256['flash']:
            raise ValueError('Private firmware copy differs from supplied flash')
        self.private_settings_sha256=sha(settings)
        self.private_image_sha256=sha(usb/'diagnostic.reu') if image_path else None
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
        command=[str(Path(args.emulator).resolve()),'run','--config',str(Path(args.config).resolve()),
            '--flash',str(flash),'--settings',str(settings),'--usb-dir',str(usb),
            '--headless','--speed','max','--audio','off','--control',f'127.0.0.1:{port}']
        self.process=subprocess.Popen(command,cwd=self.out,stdout=self.emulog,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+20
        while True:
            try:
                self.socket=socket.create_connection(('127.0.0.1',port),timeout=60);break
            except OSError:
                if self.process.poll() is not None or time.monotonic()>deadline:
                    raise ValueError('Backend did not open control endpoint')
                time.sleep(.05)
        self.socket.settimeout(60);self.socket.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        self.stream=self.socket.makefile('rwb',buffering=0)
        self.command('wait 6000')
        if image_path:self.command('expect-console "REU Load: Loaded" 30000')

    def load(self,path,entry):
        self.command('monitor c64 halt')
        prg=Path(path).read_bytes();self.write(int.from_bytes(prg[:2],'little'),prg[2:])
        self.command(f'monitor g {entry:04x}')


def native(args):
    out=Path(args.out)/'native1mhz';out.mkdir(parents=True,exist_ok=True)
    _,_,labels=assemble(args.java,args.kickass,args.native_source,out,{})
    prg=out/(args.native_source.stem+'.prg')
    session=Session(args,out)
    try:
        session.load(prg,0x80d)
        for _ in range(24):
            session.command('wait 1000')
            if session.read(0x300,1)==b'\x55':break
        else:raise ValueError('Native1MHz computation did not finish within24targetseconds')
        record=session.read(0x300,8);output=session.read(0x6000,WIDTH*HEIGHT)
        expected,_=image()
        if output!=expected:raise ValueError('Native baseline complete image differs from independent reference')
        slow_count=int.from_bytes(record[1:3],'little')
        if slow_count!=16:raise ValueError(f'Baseline is not the accepted1MHz profile: loop count{slow_count}')
        elapsed=int.from_bytes(record[4:8],'little')
        if elapsed<65536:raise ValueError('Baseline did not exercise cascaded timer wrap')
        (out/'image.bin').write_bytes(output)
        return dict(elapsed_phi2_ticks=elapsed,timer='CIA2A PHI2, B counts A underflows; stopped coherent32-bit downcounter',
            timer_collection_overhead_upper_phi2_ticks=64,display='VIC display disabled; image computation only',
            no_reu_access=True,executed_slow_cpu_loop_count=slow_count,
            code_and_constants_bytes=labels['baseline_end']-0x80d,
            output_bytes=WIDTH*HEIGHT,zero_page_bytes=0x23-2,stack_page_reserved_bytes=256,
            flat_prg_bytes=prg.stat().st_size-2,
            supplied_input_sha256=session.input_sha256,
            private_settings_sha256=session.private_settings_sha256,
            prg_sha256=sha(prg),source_sha256=sha(args.native_source),image_sha256=hashlib.sha256(output).hexdigest(),
            monitor_status=session.command('monitor status'))
    finally:session.close()


def cos(args):
    build=Path(args.build);spec=json.loads((build/'map.json').read_text())
    if spec['format']!='COSM3MAP1' or not spec['normal_build']:
        raise ValueError('Primary benchmark requires a normal autonomous M3 build')
    for name in ['m3.prg','m3.reu','m3.manifest.json']:
        if sha(build/name)!=spec['artifact_sha256'][name]:
            raise ValueError(f'{name} differs from its published build map')
    manifest=json.loads((build/'m3.manifest.json').read_text())
    if len(manifest['apps'])!=1 or manifest['apps'][0]['name']!='Mandelbrot':
        raise ValueError('Benchmark requires sole Mandelbrot app')
    app=manifest['apps'][0]
    if app['data']['start'] % 128 or app['data']['length'] < 28:
        raise ValueError('Timestamp collection bound requires the aligned scratch data line')
    bounds=json.loads((build/'bounds.json').read_text())
    if bounds['map_sha256']!=sha(build/'map.json') or bounds['build_tag']!=spec['build_tag'] or bounds['checker_sha256']!=sha(ROOT/'scripts/m2_bounds.py'):
        raise ValueError('Benchmark collection bound differs from its build map')
    header=(build/'m3.reu').read_bytes()[:16]
    if (header[:8]!=b'COSREU01' or int.from_bytes(header[8:12],'little')!=manifest['build_tag']
            or manifest['build_tag']!=spec['build_tag'] or manifest['abi']!=2
            or header[12:14]!=b'\x02\x00' or header[14]!=len(manifest['apps']) or header[15]):
        raise ValueError('REU header, manifest, ABI2 and map build tags differ')
    session=Session(args,Path(args.out)/'cos',build/'m3.reu')
    try:
        session.load(build/'m3.prg',0x80d)
        for second in range(args.max_target_seconds):
            session.command('wait 1000')
            # Owner metadata STOPPED follows explicit syscall exit. Host polls
            # only the completion; it does not issue opcodes or pixel commands.
            state=session.read(0x460,1)[0]
            if state==0 and session.read(0x300,5)==b'M0R1\x01' and second>0:break
            if state==5:raise ValueError('Mandelbrot process faulted')
        else:raise ValueError('C-OS autonomous benchmark exceeded target time limit')
        # Capture a live scanout: halting the CPU also stops timed border writes.
        png=Path(args.out).resolve()/'cos/scanout.png'
        session.command('wait 50')
        session.command(f'png {png}')
        from m0_ue2 import scanout_geometry
        geometry=scanout_geometry(png)
        session.command('monitor c64 halt')
        state=session.read(2,96);pcbs=session.read(0x400,512)
        active_slot=session.read(0x3b0,1)[0]
        owner_state=state if active_slot==0 else pcbs[:96]
        retired=int.from_bytes(owner_state[35:43],'little')
        host_profile=json.loads(args.host_profile.read_text())
        if retired!=host_profile['retired']:
            raise ValueError('Target retired count differs from the functional host profile')
        metadata=session.read(0xfd80,112);buffers=session.read(0xc00,8*json.loads((build/'map.json').read_text())['cache_line_bytes'])
        cache_work=session.read(0x350,96)
        physical=session.read(app['heap']['first'],WIDTH*HEIGHT,True)
        line=json.loads((build/'map.json').read_text())['cache_line_bytes']
        output=logical_bytes(app['heap']['first'],physical,metadata,buffers,line)
        if output!=image()[0]:raise ValueError('C-OS complete logical image differs from independent reference')
        timings=session.read(app['data']['start']+20,8,True)
        timings=logical_bytes(app['data']['start']+20,timings,metadata,buffers,line)
        begin=int.from_bytes(timings[:4],'little');end=int.from_bytes(timings[4:8],'little');frames=(end-begin)&0xffffffff
        if not 0<frames<0x80000000:raise ValueError('Invalid monotonic frame timing')
        report=session.read(0x300,80);u16=lambda n:int.from_bytes(report[n:n+2],'little')
        if u16(0x12) or u16(0x1a):raise ValueError('Normal benchmark missed synchronization or DMA overlapped active lines')
        if u16(0x14) or u16(0x1e):raise ValueError('Benchmark NMI recovery invalidates the timer collection ceiling')
        (Path(args.out)/'cos/image.bin').write_bytes(output)
        return dict(elapsed_frames=frames,elapsed_phi2_ticks_estimate=frames*FRAME_TICKS,
            elapsed_phi2_ticks_uncertainty=FRAME_TICKS,timer='GET_FRAME u32 unsigned difference; onePALperiod quantization',
            start_frame=begin,end_frame=end,timer_collection_guest_opcodes=6,
            timer_collection_native_fixed_services=2,completion='Logical image before process cleanup; coherent dirty-cache overlay',
            timer_collection_overhead_upper_frames=COLLECTION_BOUND_FRAMES,
            timer_collection_overhead_upper_phi2_ticks=COLLECTION_BOUND_FRAMES*FRAME_TICKS,
            timer_collection_bound_model='6 retirements + at most10 miss attempts +14 DMA phases +2 fuel rotations =32 progressing units, each charged2 PAL periods',
            timer_collection_bound_conditions='Sole runnable owner; no unrelated jobs, cancellation, NMI recovery or external pause; PAL IRQ and next complete260-299 admission window; conditional CFG timing model',
            timer_collection_elapsed_scope='Conservative ceiling for all six timestamp opcodes; only a subset lies inside the measured GET_FRAME interval; overhead is not subtracted',
            bounds_sha256=sha(build/'bounds.json'),
            image_sha256=hashlib.sha256(output).hexdigest(),physical_image_sha256=hashlib.sha256(physical).hexdigest(),
            physical_dirty_difference_bytes=sum(a!=b for a,b in zip(output,physical)),
            build_tag=manifest['build_tag'],artifact_sha256=json.loads((build/'map.json').read_text())['artifact_sha256'],
            supplied_input_sha256=session.input_sha256,
            private_settings_sha256=session.private_settings_sha256,
            executed_private_reu_sha256=session.private_image_sha256,
            report=list(report),pcbs=list(pcbs),active_state=list(state),metadata=list(metadata),data_cache=list(buffers),
            active_slot=active_slot,retired=retired,
            cache_work=list(cache_work),
            cache_compact_counters_modulo_65536={name:int.from_bytes(cache_work[offset:offset+2],'little')
                for name,offset in [('code_misses',34),('data_misses',36),('dirty_writebacks',38)]},
            cache_counter_scope='Normal diagnostic u16 modulo counters; not lifetime-exact totals',
            scanout=geometry,initial_cache='Empty at kernel initialization; start GET_FRAME warms its initial code line; output/data cold',
            qualification='Functional emulation only; physical Ultimate timing pending')
    finally:session.close()


def main():
    global WIDTH, HEIGHT, COORDINATE_STEP
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['emulator','config','flash','settings','kickass','build','out']:
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--java',default='java');parser.add_argument('--max-target-seconds',type=int,default=600)
    parser.add_argument('--native-only',action='store_true')
    parser.add_argument('--host-profile',type=Path,default=ROOT/'build/mandelbrot-host-profile.json')
    parser.add_argument('--application',type=Path,default=ROOT/'apps/mandelbrot.casm')
    parser.add_argument('--workload',choices=['primary','larger'],default='primary',
                        help='Fixed equivalent profiles:16x12/step64 or32x24/step32, both limit16')
    parser.add_argument('--native-source',type=Path,
                        help='Native source for the selected equivalent workload')
    args=parser.parse_args()
    if args.workload=='larger':
        WIDTH,HEIGHT,COORDINATE_STEP=32,24,32
    if args.native_source is None:
        args.native_source=ROOT/'tests/native'/('mandelbrot_1mhz.asm' if args.workload=='primary' else 'mandelbrot_32x24_1mhz.asm')
    for name in ['emulator','config','flash','settings','kickass','build','out','host_profile','application','native_source']:
        setattr(args,name,getattr(args,name).resolve())
    args.out.mkdir(parents=True,exist_ok=True)
    result_path=args.out/'result.json';result_path.unlink(missing_ok=True)
    input_hashes={name:sha(getattr(args,name)) for name in ['emulator','config','flash','settings','kickass']}
    sources=[Path(__file__).resolve(),args.application,args.host_profile,args.native_source,
             ROOT/'scripts/mandelbrot_reference.py',ROOT/'src/bin/cosbench.rs']
    source_hashes={str(path.relative_to(ROOT)):sha(path) for path in sources}
    n=native(args);c=None if args.native_only else cos(args)
    if input_hashes!={name:sha(getattr(args,name)) for name in input_hashes}:
        raise ValueError('A supplied benchmark input changed during execution')
    if source_hashes!={str(path.relative_to(ROOT)):sha(path) for path in sources}:
        raise ValueError('A benchmark source changed during execution')
    result=dict(format='COSM3BENCH1',width=WIDTH,height=HEIGHT,limit=LIMIT,
        workload=args.workload,viewport=dict(cx_first=-512,cy_first=-384,step=COORDINATE_STEP),
        arithmetic='signed Q8.8, fullsigned32 product floor>>8',
        native=n,cos=c,backend_sha256=sha(args.emulator),config_sha256=sha(args.config),settings_sha256=sha(args.settings),
        reference_sha256=sha(ROOT/'scripts/mandelbrot_reference.py'),vm_application_sha256=sha(args.application),
        host_profile=json.loads(args.host_profile.read_text()))
    result['input_sha256']=input_hashes
    result['source_sha256']=source_hashes
    if c:
        result['speedup_estimate']=n['elapsed_phi2_ticks']/c['elapsed_phi2_ticks_estimate']
        result['speedup_interval']=[max(1,n['elapsed_phi2_ticks']-n['timer_collection_overhead_upper_phi2_ticks'])/(c['elapsed_phi2_ticks_estimate']+FRAME_TICKS),
            n['elapsed_phi2_ticks']/max(1,c['elapsed_phi2_ticks_estimate']-FRAME_TICKS-c['timer_collection_overhead_upper_phi2_ticks'])]
        result['speedup_interval_scope']='One-frame quantization and conservative timer-collection ceilings; estimate uses unadjusted elapsed target times'
    result_path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k in ['format','speedup_estimate','speedup_interval']},indent=2))


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        print(f'm3_benchmark: {error}',file=sys.stderr);raise SystemExit(1)
