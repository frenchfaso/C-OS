# M3 bootstrap and resident memory

The normal M3 build uses the fixed 20 KiB local-memory map from SPEC §5.2.
Boot-only code is outside the resident image. The VM, coherent cache driver,
scheduler and bounded jobs run autonomously at `$1200`; the host does not
dispatch their opcodes.

Build either cache variant with an explicit pack manifest:

```sh
cargo build --locked --release --bins --offline
mkdir -p build
target/release/cosasm apps/mandelbrot.casm -o build/mandelbrot.cobj
python3 scripts/m3.py --manifest manifests/m3.json --offline --cache-line 128 --out build/m3/128
python3 scripts/m3.py --manifest manifests/m3.json --offline --cache-line 64 --out build/m3/64
python3 -m unittest discover -s tests/native -p test_m3_artifacts.py -v
```

Java and the pinned Kick Assembler 5.25 jar are the same explicit dependencies
documented in [m0.md](m0.md). `JAVA` and `KICKASS_JAR`, or the corresponding
command options, select an installed developer toolchain. The normal clone
build uses `toolchain/KickAss.jar`; it does not search adjacent projects.
`--skip-host-build` requires the existing release Rust tools and every object
named by the manifest. The Rust `cospack` linker remains the sole app linker.
The manifest may contain zero through four apps; the paired REU header checks
the actual app count and build tag.

`m3.prg`, `m3.reu`, `m3.manifest.json`, `native.bin`, `renderer.prg`, `map.json`
and `map.txt` are produced together. Each map records the artifact hashes,
the composite build-input fingerprint, profiles, module boundaries and complete inclusive
RAM reservations. A native section exceeding its destination fails assembly.
A normal build also fails if the future 4 KiB numeric target cannot fit; its
map reports the shortfall explicitly.

## Bootstrap reuse and reference audit

The normal PRG starts at `$0801` and uses `SYS 2061` (`$080D`). Its entire code
must end before `$1200`. The hardware probes run with IRQs disabled, establish
PAL and the measured turbo profile, preserve the aliased REU probe bytes,
verify the pack and record the distinct FETCH/STASH bounds. Boot uses temporary
buffers at `$0600–$06FF` and `$0700–$07FF`, below the PRG and above the PCBs.
Those buffers remain in the future event-ring reservation; no additional RAM
is taken from another section.

The bootstrap fetches the four PCB records and initialization descriptors,
restores initialized data in chunks of at most 128 bytes, and clears BSS.
It then loads the independently assembled runtime into `$1200–$3FFF`, prepares
the framebuffer and nibble table, installs the renderer and vectors, and jumps
to the kernel. The resident destination cannot overwrite any live bootstrap
instruction or boot buffer. After the jump, the old PRG bytes may become cache
storage, as allowed by SPEC §15.1. This is one boot transition; there is no
runtime overlay loader.

| Code or storage | Last use | Normal runtime disposition |
| --- | --- | --- |
| PAL, speed, REU alias and pack checks | Before display setup | Bootstrap only |
| CIA measurement helpers and DMA test tables | Before resident start | Bootstrap only |
| Raw boot `transfer` | Renderer FETCH before final jump | Bootstrap only |
| Initialization loops | Before resident FETCH | Bootstrap only |
| Pattern generation, renderer load and vector setup | Before final jump | Bootstrap only |
| `$80–$90` boot DMA/timer scratch | Before final jump | Scheduler scratch after the jump |
| `$0600–$07FF` boot buffers | Initialization completes | Future event-ring storage |
| Raster admission, completion check and NMI recovery | Continuous operation | Resident native routines |
| App and job memory transfers | Continuous operation | Single coherent cache DMA driver |

The runtime assembles independently and imports neither `probe.asm` nor
`m3_boot.asm`. A symbolic call to a boot helper therefore cannot link into the
runtime accidentally. The normal scheduler does not invoke the boot timer or
raw DMA helpers. Its CIA accounting and `$80–$90` scratch belong to the active
kernel; cache arguments and scratch remain at `$91–$AF`, and raster scratch
remains separate at `$C0–$FF`.

## Normal and extended profiles

`scripts/m2.py` retains its extended diagnostic default: `SYS 4608`, native
destination `$1800`, the command mailbox and immutable acknowledgment snapshot,
full counters, and the tested margin lifecycle module. Its cumulative map
reports any numeric-target shortfall as diagnostic overhead, not production
headroom.

Normal M3 sets `M3_BUILD=1` and `EXTENDED_DIAGNOSTICS=0`. It omits the 728-byte
M2 command-harness section, extended cache counters and inline stack samples.
Compact code/data miss and write-back counters remain, along with per-owner
scheduler/native accounting and the actual-DMA serial used to charge bytes.
The three compact cache counters are 16-bit modulo counters; a snapshot does
not establish an exact lifetime count after a wrap.
The disabled margin record and private area still reserve 48 bytes at
`$1080–$10AF`; only compact initialization and idle helpers are resident.

`m3.py --extended-diagnostics` keeps autonomous scheduling and enables detailed
instrumentation. It does not restore per-opcode host control. `--margin-hook`
includes the full handoff module and emits its optional idle hook; qualification
still defaults to zero. Neither option grants permission for VM or REU DMA in
the 200 displayed lines. Diagnostic and experimental footprints are reported
separately from the normal build.

The normal renderer increments the scheduler's 32-bit frame counter at IRQ
entry, before its first-line synchronization. No frame callback runs inside the
pixel stream. The default M0 renderer stays byte-identical, and normal M3's
preparation and complete pixel path from `render_line` onward match M0.
After the initial complete-image measurement, normal M3 admission starts at
PAL line 260, immediately after the final displayed line 259, and ends at 299.
M0, M2 and diagnostic/experimental M3 keep lines 280–299. The latest-start guard
remains 4,410 PHI2 ticks; the conservative final-admitted-opcode and scheduler
tail bound of at most 3,742 ticks leaves 668 ticks under the emulation timing
model. Each earlier opcode checks admission again; this is not a whole-quantum
execution bound.
Physical Ultimate timing remains pending. NMI recovery executes only in the
outer kernel loop, preserves VM/cache continuations and fuel, disables margin
qualification and rearms the next normal raster deadline.

## RAM and future gates

Normal M3 keeps four 128-byte PCBs, with scheduler/job continuation metadata in
the previously unused final 32 bytes of each PCB. Scheduler globals occupy
`$FE00–$FE7F`; ordinary completion uses `$FE80–$FEA9`, and trusted replacement
reuses `$FE80–$FEDF` for a 96-byte fresh-context staging record. The map therefore
accounts for the larger 96-byte alias, or 224 bytes with the globals. Code and data
caches each use eight 64- or 128-byte lines within their original reservations.
Cache metadata uses 112 of its 128 reserved bytes. The compact cache work area
is measured from its assembly boundary; the larger 96-byte reservation remains
explicit.

The current generated map is authoritative for module sizes. The numeric
target is a future 4,096-byte allocation beginning immediately after the
assembled resident code, within `$1200–$3FFF`; it is not extra memory. The map
reports both this interval and the remaining resident headroom after it.
Event rings (512 bytes), font (768 bytes), cursor save-under (128 bytes), the
framebuffer, I/O hole and vectors retain their fixed reservations.

The normal Mandelbrot packs use these assembled footprints. Both variants
were rebuilt twice with identical hashes for all eight delivery artifacts;
the four artifact checks and the assembled control-flow bounds passed.

| Item | 128-byte lines | 64-byte lines |
| --- | ---: | ---: |
| Build tag | `$9184C26E` | `$4DE78353` |
| Bootstrap below `$1200`, reclaimed | 1,687 B | 1,687 B |
| Resident entry/video/NMI routines | 248 B | 248 B |
| Interpreter instructions | 2,474 B | 2,474 B |
| Interpreter tables | 171 B | 171 B |
| Coherent cache instructions | 1,702 B | 1,708 B |
| Disabled-margin initialization/helpers | 14 B | 14 B |
| Scheduler | 1,267 B | 1,267 B |
| Native jobs and fixed services | 1,395 B | 1,395 B |
| Total resident runtime | 7,271 B | 7,277 B |
| Renderer, including padding | 2,289 B | 2,289 B |
| Future numeric interval | `$2E67–$3E66` | `$2E6D–$3E6C` |
| Resident space after the numeric target | 409 B | 403 B |

Each cache uses 1,024 or 512 bytes for its eight lines. Both variants use
112 bytes of cache metadata, 40 bytes of cache work, 48 bytes of driver and
scheduler zero-page scratch, 126 bytes of active VM state/interpreter scratch,
512 bytes of PCB storage and 224 bytes of scheduler globals/aliased staging.
DMA staging uses 176 of its reserved 512 bytes, including the idle margin
record and private area. These runtime allocations and every fixed reservation
appear separately in `map.json` and `map.txt`; bootstrap bytes are excluded
from the final resident total.

Future shell, input, graphics, UCI, SID and audio code is still unsized. Fitting
the numeric target does not demonstrate that all those services fit. Their
measured implementation must use the remaining resident/preparation space or
justify a map revision before UI expansion; no future module is reported as
implemented merely because a reservation exists.

The conditional M3 hardware-stack bound is 18 normal bytes plus eight IRQ bytes
and one four-byte NMI, or 30 total, with no nested IRQ or recursive NMI and
margin execution disabled. Observed depth is a separate target measurement.
The M2 bound remains 14/26. Timing and stack observations from emulation remain
distinct from physical Ultimate qualification.
