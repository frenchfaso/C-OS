# Native M2 bounds and prepared-phase contract

These are conservative source bounds for the current NMOS code, not physical
timing qualification. The default renderer has margin work disabled. Changing
the call graph, interrupt handlers, cache loops or target profile requires a new
audit and fresh backend/hardware measurements.

## Hardware stack

The current operational kernel needs at most **14 bytes** of temporary hardware
stack without an interrupt. The deepest path is:

```text
m2_run_command --JSR--> vm_run --JSR--> vm_step --JSR--> vm_execute
    --JMP dispatch--> PUSH/CALL handler --JSR--> scalar store
    --JSR--> cache_prepared_byte_pointer --JSR--> cache_line_pointer
```

Six simultaneous JSR return addresses use 12 bytes. `cache_line_pointer` adds
two temporary PHA bytes. The indirect opcode dispatch is JMP, so it adds no
return address. The direct `vm_step` command has one fewer caller frame.

Other paths stay below this bound:

| Path | Maximum bytes without interrupts |
| --- | ---: |
| `vm_run` data-line selection, including request/counter helper | 12 |
| Native overlap search through `cache_entry_live` | 8 |
| Cache service or native DMA, including PHP and completion/raster helper | 9 |
| Context save/load while preserving the requested slot with PHA | 5 |
| Prepared-phase claim, including its PHP and validation calls | 7 |
| M2 boot data restoration, including the loader caller and transfer setup | 10 |

The default renderer IRQ adds eight bytes: three pushed by the CPU, three for
A/X/Y, and two for `JSR render_line`. One NMI adds four more: three CPU bytes and
the handler's one PHA. A conservative combined upper bound is therefore
**26 bytes** (14 + 8 + 4), even though DMA masks IRQ and the video admission
window prevents a normal opcode from reaching the display IRQ.

This bound assumes the current default-disabled margin hook, a nonrecursive
`vm_run`, no nested IRQ, at most one nonrecursive NMI, and no added external
KERNAL calls. Boot runs with IRQ disabled. The margin body has no callback or
recursive call. A future qualified margin body changes the IRQ bound. The
backend's observed high-water mark is reported separately from this static
upper bound.

Every success, fault and wait path returns through its complete JSR chain.
Virtual CALL/RET bytes are cached REU data; no virtual frame or interpreter
continuation remains on the hardware stack between commands or slice boundaries.

## Opcode admission

A single `vm_step` contains no REU DMA. Cold misses select a request and return;
the separate service entry performs the transfer. Its finite loops are bounded
by eight retirement-counter bytes, fifteen shift iterations, four instruction
bytes, eight data entries per line, sixteen CLOCK scans, three scalar bytes and
sixteen entries per unpin pass. At most two data lines are involved, and at most
three unpin passes occur in one attempt.

`scripts/m2_bounds.py` derives the reproducible bound from the current assembled
PRG, native image, dispatch table and symbols. It explores both branch outcomes,
charges every reachable official NMOS instruction seven CPU cycles, and applies
explicit backward-edge caps to the finite loops. Unknown instructions,
unrecognized cycles and recursive calls fail the analysis. Source loops and
their caps must be reviewed together when changed.

The conditional conversion uses a conservative 48 fast CPU cycles per PHI2,
plus seven additional PHI2 ticks per I/O bus access. A service call adds a
separate 511-tick DMA allowance; `vm_step` has none. This is a fixed emulated
turbo-profile model, not a claim that a manual48 profile passes boot or that
physical memory/I/O stalls have been qualified. The latest admitted start
leaves at least 4,410 ticks until IRQ58. Each build's generated bound report
contains instruction counts, I/O counts, converted bounds and artifact hashes;
the corresponding measured target maximum is reported separately.

Run `python3 scripts/m2_bounds.py --build build/m2/128` (and with `64`) after
assembly. Physical-device qualification remains necessary. This arithmetic
does not qualify another speed, renderer phase or hardware profile.

## Disabled optional phase

`native/margins.asm` reserves a single 32-byte record at $1080–$109F and a
16-byte private buffer at $10A0–$10AF. It uses no zero page. The ordinary
cache/native DMA staging occupies $1000–$107F; boot's BUFFER is $1100–$117F.
The margin region has no alias with live VM, cache or raster scratch.

The record carries one trusted routine identity, slot/PID/incarnation, a private
buffer address and exclusive ownership flag, a complete conservative cost cap,
declared A/flags clobbers, a continuation, inherited native entitlement, inputs,
result and exactly-once work/completion counts. There is one fixed CPU-local XOR
body; no indirect application callback, allocation, driver, DMA or wait exists.

The lifecycle is IDLE → DRAFT → READY → RUNNING → DONE → IDLE. The publisher fills
all fields and inputs before the final single-byte READY store. Claim masks IRQ
across validation and the RUNNING store, then restores flags before the private
body. Incomplete, cancelled, mismatched or already claimed records perform no
work. Slot reuse revokes the owner outside raster before the context is replaced.
Consumption and cancellation discard occur outside raster. Ordinary context
switches do not cancel or globally flush prepared work.

One successful phase consumes one unit of the inherited native entitlement.
It creates no queue, quantum or additional owner turn. The ordinary arbiter must
measure/charge the actual native cost and rotate the existing job when consuming
completion. `margin_actual_cost` is reserved and unmeasured in M2: its zero value
does not mean that the phase takes zero cycles. Full M3 fairness and accounting
remain future work.

The fixed ordinary-path claim/validation/body/publication is bounded by 512
NMOS cycles, including its caller and register-preservation allowance. Its
longest success path is below 300 cycles before that allowance; the bound does
not include a future timing-profile selector or establish a legal horizontal
slot. No profile is qualified and `margin_irq_hook` always returns idle. The
default renderer compiles no call at its prepared location after the final
pixel. Enabling useful raster work needs the complete activation gate in
[the supplement](../specs/M2-UPIC-MARGINS.md).

`tests/native/margins.asm` and `scripts/m2_margins.py` execute the ordinary-path
contract on the actual backend. The independent $A5 XOR $3C = $99 vector and
66 native assertions check partial publication, declarations, stale generations
and PIDs, owner cancellation, exclusivity, result consumption, entitlement,
register/IRQ-flag preservation and balanced hardware stack. This verifies
handoff semantics while raster activation stays disabled.
