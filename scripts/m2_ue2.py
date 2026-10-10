#!/usr/bin/env python3
"""Differentially execute native M2 on an explicitly supplied Ultimate backend.

The backend, firmware and ROMs remain external read-only developer inputs.
Mailbox commands run on the production C64 CPU with raster IRQs enabled.
"""
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
from m2 import initial_state
from m2_compare import compare_state, compare_memory, validate_wait, integer, metadata_entries

ROOT = Path(__file__).resolve().parents[1]
COUNTERS = dict(code_hits=33,data_hits=37,code_misses=41,data_misses=45,
                fetch_bytes=49,stash_bytes=53,evictions=57,dma_deferrals=61,
                stale_cancellations=65,native_reads=69,native_writes=73,dma_calls=77)


class Target:
    def __init__(self,args):
        self.args=args
        self.out=Path(args.out).resolve()
        self.out.mkdir(parents=True,exist_ok=True)
        (self.out/'result.json').unlink(missing_ok=True)
        self.spec=json.loads((Path(args.build)/'map.json').read_text())
        self.line=self.spec['cache_line_bytes']
        self.sequence=0
        self.log=(self.out/'protocol.log').open('w')
        self.trace=(self.out/'snapshots.jsonl').open('w')
        self.emulog=(self.out/'emulator.log').open('w')
        usb=self.out/'usb';usb.mkdir(exist_ok=True)
        self.linked=json.loads((Path(args.build)/'m2.manifest.json').read_text())
        self.image=(Path(args.build)/'m2.reu').read_bytes()
        private=bytearray(self.image)
        # Seed application BSS and initialized-data destinations with nonzero
        # bytes. The native loader must clear/copy them before any fixture.
        for app in self.linked['apps']:
            for key,value in [('bss',0xa5),('data',0xcc)]:
                region=app[key];first=region['start'];length=region['length']
                private[first:first+length]=bytes([value])*length
        (usb/'diagnostic.reu').write_bytes(private)
        self.private_image_sha256=hashlib.sha256(private).hexdigest()
        shutil.copyfile(args.flash,self.out/'isolated-flash.bin')
        settings=self.out/'settings.cfg'
        settings.write_text(Path(args.settings).read_text()+
                            '\n[C64 and Cartridge Settings]\nREU Preload=Enabled\nREU Preload Image=/Usb0/diagnostic.reu\n')
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
                    raise ValueError('Backend did not open its loopback control endpoint')
                time.sleep(.05)
        self.socket.settimeout(args.timeout)
        self.socket.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        self.stream=self.socket.makefile('rwb',buffering=0)
        self.command('wait 6000')
        self.command('expect-console "REU Load: Loaded" 30000')
        self.command('monitor c64 halt')
        prg=(Path(args.build)/'m2.prg').read_bytes()
        self.write(int.from_bytes(prg[:2],'little'),prg[2:])
        self.command('monitor g 1200')
        self.command('wait 1000')
        report=self.read(0x300,80)
        if report[:5]!=b'M0R1\x01':
            raise ValueError(f'Native boot/probe failed: {report.hex(" ")}')
        self.initial_report=report
        self.boot_validation=self.validate_boot()
        if not args.video:
            self.issue(13,arguments=[0])

    def validate_boot(self):
        verified=[]
        native=(Path(self.args.build)/'native.bin').read_bytes()
        if self.read(0x1800,len(native))!=native:
            raise ValueError('Boot resident bytes differ from the published native image')
        for slot,app in enumerate(self.linked['apps']):
            if self.read(0x400+slot*128,128)!=initial_state(app):
                raise ValueError(f"Boot context {slot} differs from static linked bounds/initial registers")
            first=app['code']['first'];length=app['code']['last']-first+1
            if self.read(first,length,True)!=self.image[first:first+length]:
                raise ValueError(f"Boot app{app['id']} code differs from its static pack")
            first=app['data']['start'];length=app['data']['length'];seed=app['data_seed']['start']
            if self.read(first,length,True)!=self.image[seed:seed+length]:
                raise ValueError(f"Boot app{app['id']} data did not restore its nonzero initialization seed")
            first=app['bss']['start'];length=app['bss']['length']
            for offset in range(0,length,4096):
                block=min(4096,length-offset)
                if self.read(first+offset,block,True)!=bytes(block):
                    raise ValueError(f"Boot app{app['id']} failed to zero previously nonzero BSS")
            verified.append(dict(slot=slot,pid=app['id'],code_bytes=app['code']['last']-app['code']['first']+1,
                                 data_restored_bytes=app['data']['length'],bss_cleared_bytes=length,
                                 context_128_bytes_match=True))
        return dict(native_resident_bytes_match=True,applications=verified,
                    nonzero_destination_sentinels_before_boot=True)

    def commands(self,commands):
        for line in commands:self.log.write('>>> '+line+'\n')
        self.stream.write(('\n'.join(commands)+'\n').encode())
        outputs=[]
        for command in commands:
            lines=[]
            while True:
                raw=self.stream.readline()
                if not raw:raise ValueError('Backend closed the control connection')
                text=raw.decode().rstrip('\r\n');self.log.write(text+'\n')
                if text=='ok':break
                if text.startswith('error line '):raise ValueError(f'{command}: {text}')
                lines.append(text)
            outputs.append('\n'.join(lines))
        return outputs

    def command(self,line):
        return self.commands([line])[0]

    @staticmethod
    def write_commands(address,data):
        data=bytes(data)
        return [f'monitor wr ram {address+offset:04x} {data[offset:offset+128].hex(" ")}'
                for offset in range(0,len(data),128)]

    def write(self,address,data):
        self.commands(self.write_commands(address,data))

    def read(self,address,length,physical=False):
        if not length:
            return b''
        if physical:
            start=0x1000000+address
            return memory(self.command(f'monitor fw-memory {start:08x} {start+length-1:08x}'),start,length,'FW')
        return memory(self.command(f'monitor m ram {address:04x} {address+length-1:04x}'),address,length)

    def issue(self,command,slot=0,arguments=(),completion=(),staging=None):
        if len(arguments)>96 or len(completion)>42:
            raise ValueError('Diagnostic packet exceeds its bounded mailbox')
        writes=[]
        if arguments:writes+=self.write_commands(0xfe20,arguments)
        if completion:writes+=self.write_commands(0xfe80,completion)
        if staging is not None:writes+=self.write_commands(0x1000,staging)
        writes+=self.write_commands(0xfe02,[command,0,slot])
        self.sequence=(self.sequence+1)&255
        writes+=self.write_commands(0xfe00,[self.sequence])
        self.commands(writes)
        for _ in range(500):
            _,dump=self.commands(['wait 1','monitor m ram fe00 fe0c'])
            header=memory(dump,0xfe00,13)
            if header[1]==self.sequence:
                return dict(command=command,result=header[3],header=list(header),
                            state=list(self.read(0xfee0,96)))
        raise ValueError(f'Native command {command} failed to acknowledge; last header {header.hex(" ")}')

    def capture(self,record,watches):
        commands=['monitor m ram fd80 fdef',f'monitor m ram 0c00 {0xc00+8*self.line-1:04x}',
                  f'monitor m ram 0800 {0x800+8*self.line-1:04x}','monitor m ram 0350 03af','monitor m ram 0062 0065']
        locations=[(0xfd80,112),(0xc00,8*self.line),(0x800,8*self.line),(0x350,96)]
        for watch in watches:
            start=0x1000000+watch['address'];length=len(watch['data'])
            commands.append(f'monitor fw-memory {start:08x} {start+length-1:08x}')
        output=self.commands(commands)
        for key,text,(address,length) in zip(['metadata','data_cache','code_cache','work'],output,locations):
            record[key]=list(memory(text,address,length))
        entries=metadata_entries(record['metadata'])
        busy=sum(bool(entry['flags']&4) for entry in entries)
        if busy>1 or bool(busy)!=bool(record['work'][0]):
            raise ValueError('Cache continuation/BUSY ownership invariant failed')
        for entry in entries:
            if entry['flags']&16:
                raise ValueError('Cache PIN leaked across an interpreter/service boundary')
            if entry['flags']&1 and (entry['tag']%self.line or entry['owner']>=4):
                raise ValueError('Cache live tag alignment/owner invariant failed')
            if entry['index']<8 and entry['flags']&2:
                raise ValueError('Immutable code cache line became dirty')
        record['instruction']=list(memory(output[4],0x62,4))
        record['physical']={watch['address']:list(memory(text,0x1000000+watch['address'],len(watch['data']),'FW')) for watch,text in zip(watches,output[5:])}
        return record

    def emit(self,record):
        self.trace.write(json.dumps(record,separators=(',',':'))+'\n')
        self.trace.flush()

    def close(self):
        if hasattr(self,'stream'):
            try:self.command('quit')
            except (OSError,ValueError):pass
        if hasattr(self,'process'):
            try:self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=10)
        for attribute in ['stream','socket','trace','log','emulog']:
            value=getattr(self,attribute,None)
            if value is not None:value.close()


def counters(work):
    return {name:integer(work,offset,4) for name,offset in COUNTERS.items()}


def expected_instruction(case,watches,pc):
    for region in watches+case['patches']:
        offset=pc-region['address']
        if 0<=offset and offset+4<=len(region['data']):
            return bytes(region['data'][offset:offset+4]).hex(' ')
    return 'not fetched: PC has no complete fixture instruction'


def suspension_context(record):
    work=record['work']
    return dict(outcome=record['state'][69],phase=work[0],pending_entry=work[1],
                requester_slot=work[5],generation=integer(work,6,2),
                requested_tag=integer(work,2,3),native_active=work[21],
                actual_ir=bytes(record['instruction']).hex(' '))


def execute_case(target,case):
    # Independent fixtures abandon old process incarnations. Runtime switches
    # within a fixture retain all dirty lines; no test inserts a global flush.
    for slot in range(4):
        target.issue(7,slot)
        target.issue(8,slot)
    for context in case['contexts']:
        target.issue(1,context['slot'],context['initial'])
    active=case['contexts'][-1]['slot']
    states={c['slot']:c['initial'] for c in case['contexts']}
    for patch in case['patches']:
        data=patch['data'];address=patch['address']
        if not 0<=address<=address+len(data)<=0x1000000:
            raise ValueError(f"{case['name']}: fixture patch exceeds REU")
        for offset in range(0,len(data),128):
            chunk=data[offset:offset+128]
            args=list((address+offset).to_bytes(3,'little'))+[len(chunk)]
            for _ in range(500):
                result=target.issue(12,active,args,staging=chunk)
                if result['result']!=3:break
            if result['result']:
                raise ValueError(f"{case['name']}: native physical patch rejected {result['result']}")
    baseline=counters(target.read(0x350,96))
    watches=case.get('initial_watches',[])
    waits=services=dirty=0
    records=[]
    for index,action in enumerate(case['actions']):
        command=action['command'];requested=action['slot']
        # Completion packets deliberately may name a different owner; command5
        # must reject these without switching away from the current context.
        if command not in [5,7] and requested!=active:
            target.issue(7,requested);active=requested
        before=states[active]
        if command==7:active=requested
        label=f"{case['name']}/action{index}/cmd{command}"
        action_services=0
        instruction_pc=integer(before,28,3)
        opcode=expected_instruction(case,watches,instruction_pc)
        if command in [2,3] and (instruction_pc&3 or instruction_pc<integer(before,51,3) or instruction_pc+3>integer(before,54,3)):
            opcode='not fetched: invalid PC or incomplete code interval'
        for retry in range(1000):
            record=target.issue(command,requested,action.get('arguments') or (),action.get('completion') or ())
            waiting=(command in [2,3] and record['state'][69] in [2,7]) or (command in [9,10] and record['result']==3)
            current_watches=watches if waiting else action['watches']
            target.capture(record,current_watches)
            record.update(case=case['name'],action=index,retry=retry,slot=active,
                          instruction_pc=instruction_pc,expected_instruction=opcode,suspension=suspension_context(record))
            target.emit(record)
            if not waiting:break
            waits+=1
            if command in [2,3]:
                dirty+=validate_wait(before,record['state'],watches,record['physical'],record['metadata'],record['data_cache'],target.line,name=f'{label} opcode={opcode} suspension={record["suspension"]}',opcode=opcode,instruction_pc=instruction_pc,suspension=record['suspension'])
            else:
                compare_state(before,record['state'],name=label,opcode=opcode,instruction_pc=instruction_pc,suspension=record['suspension'])
                dirty+=compare_memory(watches,record['physical'],record['metadata'],record['data_cache'],target.line,name=f'{label} opcode={opcode} suspension={record["suspension"]}')
            # A cache service completes one real bounded direction. Dirty
            # STASH and subsequent refill FETCH are independently observable.
            while record['work'][0]:
                service=target.issue(4,active)
                target.capture(service,watches)
                service.update(case=case['name'],action=index,service=True,slot=active,
                               instruction_pc=instruction_pc,expected_instruction=opcode,suspension=suspension_context(service))
                target.emit(service);services+=1;action_services+=1
                if action_services>256:raise ValueError(label+': cache service watchdog expired')
                previous_dma=integer(record['work'],77,4)
                serviced_dma=integer(service['work'],77,4)
                if (serviced_dma-previous_dma)&0xffffffff>1:
                    raise ValueError(label+': cache service performed multiple DMA directions')
                compare_state(record['state'],service['state'],name=label+'/service',opcode=opcode,instruction_pc=instruction_pc,suspension=service['suspension'])
                dirty+=compare_memory(watches,service['physical'],service['metadata'],service['data_cache'],target.line,name=f'{label}/service opcode={opcode} suspension={service["suspension"]}')
                if service['result']==2:raise ValueError(label+': cache DMA validation error')
                record=service
        else:raise ValueError(label+': native operation made no progress')
        expected_result=action.get('expected_result') or 0
        if record['result']!=expected_result:
            raise ValueError(f'{label}: expected result{expected_result}, observed{record["result"]}')
        compare_state(action['expected_state'],record['state'],name=label,opcode=opcode,instruction_pc=instruction_pc if command in [2,3] else None,suspension=record['suspension'])
        dirty+=compare_memory(action['watches'],record['physical'],record['metadata'],record['data_cache'],target.line,name=f'{label} opcode={opcode} suspension={record["suspension"]}',pc=instruction_pc)
        if action.get('native_data') is not None:
            observed=target.read(0xfe24,len(action['native_data']))
            if observed!=bytes(action['native_data']):raise ValueError(label+': native coherent read mismatch')
        states[active]=action['expected_state'];watches=action['watches']
        records.append(dict(command=command,slot=active,state=record['state']))
    final=counters(target.read(0x350,96))
    return dict(name=case['name'],group=case['group'],actions=len(records),waits=waits,service_directions=services,
                dirty_physical_byte_differences_observed=dirty,counters={k:(final[k]-baseline[k])&0xffffffff for k in final},final_slot=active,final_state=records[-1]['state'] if records else states[active])


def run(args):
    fixture_bytes=Path(args.fixtures).read_bytes()
    fixture=json.loads(fixture_bytes)
    if fixture['format']!='COSM2FIXTURES1':raise ValueError('Unknown native fixture format')
    selected=[c for c in fixture['cases'] if not args.case or any(term in c['name'] for term in args.case)]
    selected=selected[:args.limit] if args.limit else selected
    if not selected:raise ValueError('No fixtures match the selected cases')
    target=Target.__new__(Target)
    try:
        target.__init__(args)
        results=[]
        for i,case in enumerate(selected):
            results.append(execute_case(target,case))
            if i==0 or (i+1)%25==0:print(f"Native{target.line}: {i+1}/{len(selected)} cases pass ({case['name']})",flush=True)
        # A real CIA2 one-shot edge invokes the installed NMI handler. Recover
        # separately from timed opcode/service maxima and compare the complete
        # guest architecture and logical/physical memory before and afterward.
        final_case=selected[-1];watches=final_case['actions'][-1]['watches']
        before=target.capture(dict(state=results[-1]['final_state']),watches)
        nmi_before=integer(target.read(0x300,80),20,2)
        recovery=target.issue(14,results[-1]['final_slot'])
        target.capture(recovery,watches);recovery['nmi_recovery_test']=True;target.emit(recovery)
        compare_state(before['state'],recovery['state'],name='CIA2 NMI recovery')
        compare_memory(watches,recovery['physical'],recovery['metadata'],recovery['data_cache'],target.line,name='CIA2 NMI recovery')
        if recovery['metadata']!=before['metadata'] or recovery['data_cache']!=before['data_cache'] or recovery['work']!=before['work']:
            raise ValueError('CIA2 NMI recovery modified cache continuation/buffers')
        target.command('wait 100')
        target.command(f"png {target.out/'scanout.png'}")
        geometry=scanout_geometry(target.out/'scanout.png') if args.video else None
        report=target.read(0x300,80);header=target.read(0xfe00,16)
        stack=target.read(0x100,256)
        touched=[i for i,value in enumerate(stack) if value!=0xa5]
        stack_depth=256-min(touched) if touched else 0
        status=target.command('monitor status')
        result=dict(format='COSM2UE2RESULT1',qualification='Functional emulation only; physical Ultimate timing pending',
                    cache_line_bytes=target.line,cases=len(results),actions=sum(c['actions'] for c in results),
                    waits=sum(c['waits'] for c in results),service_directions=sum(c['service_directions'] for c in results),
                    dirty_physical_byte_differences_observed=sum(c['dirty_physical_byte_differences_observed'] for c in results),
                    artifact_sha256=target.spec['artifact_sha256'],build_tag=target.spec['build_tag'],
                    fixtures_sha256=hashlib.sha256(fixture_bytes).hexdigest(),
                    boot_validation=target.boot_validation,executed_private_reu_sha256=target.private_image_sha256,
                    backend_executable_sha256=hashlib.sha256(Path(args.emulator).read_bytes()).hexdigest(),
                    config_sha256=hashlib.sha256(Path(args.config).read_bytes()).hexdigest(),
                    settings_sha256=hashlib.sha256(Path(args.settings).read_bytes()).hexdigest(),
                    report=list(report),scanouts=integer(report,16,2),missed_syncs=integer(report,18,2),
                    active_dma_violations=integer(report,26,2),observed_hardware_stack_bytes=max(report[28],stack_depth),
                    sampled_stack_bytes=report[28],stack_sentinel_touched_depth_lower_bound=stack_depth,
                    stack_page=list(stack),final_monitor_status=status,
                    vm_opcode_maximum_phi2_ticks=integer(header,9,2),cache_service_maximum_phi2_ticks=integer(header,11,2),
                    video_enabled=args.video,nmi_count=integer(report,20,2),nmi_recoveries=integer(header,13,2),
                    actual_cia2_nmi_preserved_state_and_caches=integer(report,20,2)>nmi_before and integer(header,13,2)>0,
                    scanout=geometry,case_results=results)
        if not result['actual_cia2_nmi_preserved_state_and_caches']:
            raise ValueError('CIA2 NMI injection/recovery was not observed')
        if result['active_dma_violations'] or result['missed_syncs']:
            raise ValueError('Runtime DMA/raster violation; inspect native snapshots and report')
        (target.out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print(f"Native{target.line}: all {len(results)} selected cases passed; output {target.out}",flush=True)
        return result
    finally:target.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for argument in ['emulator','config','flash','settings']:
        parser.add_argument('--'+argument,type=Path,required=True)
    parser.add_argument('--build',type=Path,default=ROOT/'build/m2/128')
    parser.add_argument('--out',type=Path,default=ROOT/'build/m2/ue2/128')
    parser.add_argument('--fixtures',type=Path,default=ROOT/'build/m2-fixtures.json')
    parser.add_argument('--limit',type=int,default=0)
    parser.add_argument('--case',action='append',help='Select fixture names containing this text; repeat to select several')
    parser.add_argument('--timeout',type=int,default=120)
    parser.add_argument('--video',action=argparse.BooleanOptionalAction,default=True)
    args=parser.parse_args()
    try:run(args)
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        print(f'm2_ue2: {error}',file=sys.stderr);return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
