# M2 supplement: prepare optional UPIC margin work

Specification 0.1, revision 5 — October 10, 2026. Implementation handoff for the existing M2 milestone. [SPEC.md](SPEC.md) §§9.3, 10.4, 17.7, and 18 are normative; this checklist does not replace the rest of M2 or change ABI 1/COS-NUM-1.

Historical version note: this M2 handoff targeted ABI 1. SPEC revision 7 later
introduces application ABI 2 for integer multiplication; the margin preparation,
default-disabled policy and qualification requirements below remain unchanged.

## Deliver in M2

- Prepare one optional native execution hook after the final pixel of a line, excluded from normal execution by a default-disabled build switch. Preserve baseline pixel cadence, geometry, phase, and synchronization when disabled.
- Define the smallest internal prepared-phase record: trusted kernel routine identity, owner/incarnation, local state and buffer ownership, complete maximum cost, and declared clobbers. A single record is sufficient; there is no new opcode or userspace API.
- Separate margin scratch from live VM, raster, and interrupted kernel scratch. Do not re-enter shared kernel routines from the IRQ.
- Define complete-before-ready publication, exclusive claim, incomplete/stale/cancelled record rejection, exactly-once completion, and consumption outside the raster. The full M3 scheduler and a per-line work queue are unnecessary.
- Account for code, local RAM, hardware stack, and diagnostic overhead in the cumulative map. Test the disabled baseline and internal ownership/handoff contract.

Activation is not an M2 completion criterion. A documented hook is not a timing qualification. Keep VM execution, REU DMA, UCI, and device operations outside all 200 active lines, including when qualified CPU-local work is eventually enabled.

## Later activation gate

1. Begin with private-scratch work after the final pixel. A hook before the pixel stream needs separate phase-preservation and padding qualification.
2. Bound the complete path, including selection, entry/exit, register/status preservation, checks, state publication, body, and padding. Admit it only when the bound plus guard fits before the next renderer deadline; otherwise defer without effects.
3. Prepare all operands and validate ownership outside the display interval. A phase cannot miss in the cache, request DMA, wait, allocate, access a device, or call a general scheduler/driver. Never overwrite a source row while the renderer is preparing or emitting it.
4. Preserve the ordinary job's continuation, fuel, owner cost, and native service entitlement. Subsequent queue rotation happens outside the raster; margin execution does not create a second scheduler or extra turns.
5. Run SPEC §17.7, recording exact artifacts, profile, full path bounds, useful work, RAM, image comparison, stability, and fallback. Experimental emulation results do not qualify physical hardware. A profile or timing-relevant change invalidates the corresponding qualification.

The normal outside-display path must always remain usable. Missing qualification, insufficient time, or unavailable work leaves the slot idle. Detected timing errors or recovery conditions stop further admission; an after-the-fact counter cannot prevent or undo an overrun.

## Scope and report

Do not fragment all native services, implement a float backend, or build a second scheduler to exploit every line. Complete the original VM/cache/stack and differential verification work of M2 first, with this small preparation included and execution disabled.

Report hook location and default switch, state/scratch ownership, handoff tests, measured code/RAM cost, disabled-baseline verification, and the still-pending activation evidence. Keep all repository content in English; discussion with the user may be in Italian.
