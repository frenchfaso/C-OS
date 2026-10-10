"""Compare real target snapshots and logically visible write-back memory."""
import json

RUN, FUEL, WAIT_REU, YIELD, SYSCALL, FAULT, STOPPED, WAIT_VIDEO = range(8)


def integer(data, offset, length):
    return int.from_bytes(bytes(data[offset:offset+length]), "little")


def describe(state):
    return dict(r=[integer(state, i*2, 2) for i in range(8)],
                p=[integer(state, 16+i*3, 3) for i in range(4)],
                pc=integer(state, 28, 3), sp=integer(state, 31, 3), fuel=state[34],
                retired=integer(state, 35, 8), pid=integer(state,43,2),
                outcome=state[69], fault=state[70],
                address=integer(state,71,4) if state[75] else None,
                payload=integer(state,76,2), syscall=state[78],
                token=integer(state,79,8), pending=state[90], generation=integer(state,91,2))


def compare_state(expected, observed, *, name, wait=False, opcode=None, suspension=None,
                  instruction_pc=None):
    if len(expected) != 96 or len(observed) != 96:
        raise ValueError(f"{name}: incomplete native context snapshot")
    fields=list(range(69))+[91,92]
    if not wait:
        fields += [69,78,90]+list(range(79,90))
        if expected[69] == FAULT:
            fields += [70,75]
            if expected[75]: fields += list(range(71,75))
            if expected[70] == 9: fields += [76,77]
        if expected[69] == STOPPED: fields += [76,77]
    else:
        fields += [78,90]+list(range(79,90))
        if observed[69] not in [WAIT_REU, WAIT_VIDEO]:
            raise ValueError(f"{name}: expected an unchanged wait, observed {observed[69]}")
    mismatch=next((i for i in fields if expected[i] != observed[i]),None)
    if mismatch is not None:
        pc=integer(expected,28,3) if instruction_pc is None else instruction_pc
        raise ValueError(f"{name}: first divergent PC ${pc:06X}, opcode {opcode}, "
                         f"state byte {mismatch}; suspension={suspension}\n"
                         f"Expected: {json.dumps(describe(expected),sort_keys=True)}\n"
                         f"Observed: {json.dumps(describe(observed),sort_keys=True)}")


def metadata_entries(metadata):
    if len(metadata) != 112:
        raise ValueError("Incomplete native cache metadata snapshot")
    return [dict(index=i,tag=metadata[i]|(metadata[16+i]<<8)|(metadata[32+i]<<16),
                 owner=metadata[48+i],flags=metadata[64+i],
                 generation=metadata[80+i]|(metadata[96+i]<<8)) for i in range(16)]


def logical_bytes(address, physical, metadata, data_cache, line_size):
    """Overlay dirty cached bytes; preserve the distinct physical REU sample."""
    if line_size not in [64,128] or len(data_cache) != 8*line_size:
        raise ValueError("Invalid native data cache snapshot")
    result=bytearray(physical)
    covered=set()
    for entry in metadata_entries(metadata)[8:]:
        if entry['flags'] & 3 != 3:
            continue
        first=max(address,entry['tag'])
        last=min(address+len(result),entry['tag']+line_size)
        if first >= last:
            continue
        if any(a in covered for a in range(first,last)):
            raise ValueError("Multiple dirty lines claim the same physical REU bytes")
        covered.update(range(first,last))
        local=(entry['index']-8)*line_size+first-entry['tag']
        result[first-address:last-address]=bytes(data_cache[local:local+last-first])
    return bytes(result)


def compare_memory(watches, physical, metadata, data_cache, line_size, *, name, pc=None):
    """physical is a mapping from each watch address to its monitor-read bytes."""
    differences=0
    for watch in watches:
        address=watch['address']
        expected=bytes(watch['data'])
        raw=bytes(physical[address])
        if len(raw) != len(expected):
            raise ValueError(f"{name}: incomplete physical REU sample at ${address:06X}")
        visible=logical_bytes(address,raw,metadata,data_cache,line_size)
        if visible != expected:
            index=next(i for i,(a,b) in enumerate(zip(visible,expected)) if a != b)
            raise ValueError(f"{name}: divergent memory at ${address+index:06X}, PC={pc}; "
                             f"expected {expected[index]:02X}, observed logical {visible[index]:02X}, "
                             f"physical {raw[index]:02X}; metadata={metadata_entries(metadata)}")
        differences += sum(a != b for a,b in zip(raw,visible))
    return differences


def validate_wait(expected, snapshot, watches, physical, metadata, data_cache, line_size, **context):
    compare_state(expected,snapshot,wait=True,**context)
    return compare_memory(watches,physical,metadata,data_cache,line_size,
                          name=context['name'],pc=integer(expected,28,3))
