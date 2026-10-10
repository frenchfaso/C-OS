# Native M2 cache

`native/cache.asm` is original NMOS 6510 code. The 128-byte build assembles to
1,804 bytes; the 64-byte variant to 1,810 bytes. Both use sixteen entries, 112
bytes of tag/owner/flags/incarnation metadata, 82 bytes of the 96-byte cache work
area, and 31 bytes of cache zero-page arguments/scratch. Cache buffer reservations
remain at $0800–$0BFF for code and $0C00–$0FFF for data. The 64-byte variant uses
512 bytes of each reservation; the 128-byte build uses 1,024 bytes of each.

Each of four process slots has two alternating read-only code lines. Eight
shared write-back data lines use CLOCK, with at most sixteen scan attempts. Tags
include a 16-bit process incarnation. Hits require a valid, nonbusy matching
tag, owner and incarnation. Scalar preflight pins at most two lines; execution
uses each line's actual buffer pointer, including noncontiguous replacements.
Every wait releases pins. Cache preparation changes no guest registers, memory,
stack or fuel.

A miss reserves one destination and records a continuation. Dirty STASH and
refill FETCH require separate service calls, each performing at most one DMA
direction. Old dirty bytes retain their old tag and owner through write-back;
the new tag becomes valid only after FETCH completes. Context switching does
not flush the cache. Slot reuse cancels that slot's requests and invalidates its
lines. Canceling a request that reserved another owner's dirty victim restores
that victim. An obsolete generation cannot publish a refill.

Trusted native scalar reads/writes inspect physical overlap across all live
cache owners. They write back only overlapping dirty lines before physical
DMA. Writes then invalidate affected code and data lines, preserving neighboring
dirty bytes. The continuation belongs to the requesting slot/incarnation while
each flushed line retains its own owner. Native hooks accept widths 1–3; the
caller remains responsible for guest arena/protection checks. Privileged code
patches invalidate their owners explicitly before writing.

The single runtime DMA driver validates the complete 24-bit REU range and local
$0800–$11FF range, accepts widths 1–128, initializes every REU field, and checks
video admission before and after masking IRQs. Width zero is a DMA no-op.
`cache_dma_error` at $03A1 distinguishes normal/deferred (0), invalid length (1),
REU end overflow (2), and invalid local range (3). The completion callback samples
the actual completion raster. Boot-only image loading runs before video.

## Independent cancellation check

Run from the repository using the external developer dependencies already used
for the M0 emulator check:

```sh
python3 tests/native/check_cache_cancel.py \
  --emulator /Users/frenchfaso/Documents/Code/C64/UE2-C64U-Emulator/target/release/ue2emu \
  --config /Users/frenchfaso/Documents/Code/C64/runtime/c64u.toml \
  --flash /Users/frenchfaso/Documents/Code/C64/runtime/flash.bin \
  --settings /Users/frenchfaso/Documents/Code/C64/runtime/ultimate.cfg \
  --kickassembler /Users/frenchfaso/Documents/Code/C64/toolchain/kickassembler/KickAss.jar \
  --java /Library/Java/JavaVirtualMachines/temurin-25.jdk/Contents/Home/bin/java
```

The checker assembles `tests/native/cache_cancel.asm`, copies flash/settings into
its build output, and preloads a private sentinel REU image. Both variants passed
eight dirty A lines, cancellation of B's ninth-line miss before DMA, reuse of B,
stale-generation refill cancellation, and cancellation/retry of a cross-owner
native read. A trusted code write also invalidates both private owners of the
same physical code line; the next code fetch observes the updated byte. Logical
A bytes remain $40–$47; physical data memory contains only $40
in the first byte and the sentinel everywhere else. The other seven lines remain
dirty, proving that no global flush was inserted.

| Line bytes | FETCH bytes | STASH bytes | DMA directions | Stale cancellations |
|---:|---:|---:|---:|---:|
| 128 | 1,409 | 129 | 14 | 1 |
| 64 | 705 | 65 | 14 | 1 |

Logs, control scripts, source/artifact hashes and `result.json` are saved under
`build/cache-cancel/{128,64}`. This fixture observes eight hardware stack bytes.
It disables video and qualifies cache semantics on the supplied emulator only;
the integrated interpreter/raster workload and physical Ultimate timing require
their separate checks. The work-area counters distinguish code/data hits and
miss attempts, FETCH/STASH bytes, victim reservations, DMA deferrals, stale
cancellations, native calls and actual DMA directions.

## Conditional admission bound

Reproduce the assembled control-flow bound for each completed build:

```sh
python3 scripts/m2_bounds.py --build build/m2/128 --out build/m2/128/bounds.json
python3 scripts/m2_bounds.py --build build/m2/64 --out build/m2/64/bounds.json
```

The analyzer verifies artifact hashes, explores both sides of every conditional
branch, expands every native call, and considers all 57 interpreter dispatch
table entries. It charges seven CPU cycles to every reachable official NMOS
instruction, including caller JSR and branch/page-cross costs. Loop limits reset
per subroutine invocation: eight data probes, sixteen CLOCK scans, sixteen unpin
entries, four code-copy bytes, three scalar bytes, fifteen shifts, and eight
retired/token carry bytes. Native invalidation scans sixteen entries. Unknown
instructions, indirect jumps and unannotated cycles reject the analysis.

The conversion assumes the fixed emulated turbo profile provides at least 48
normal-RAM CPU cycles per PHI2. It adds seven PHI2 ticks for each I/O bus access
and, for a DMA-capable call, another 511 ticks: the admission threshold for each
separately measured 128-byte FETCH/STASH direction. These are conditional model
allowances; startup calibration and observed maxima do not establish physical
memory, I/O or DMA stall bounds.

| Line bytes | One VM step, CPU cycles | One cache service, CPU cycles | Step PHI2 bound | Service PHI2 bound including DMA |
|---:|---:|---:|---:|---:|
| 128 | 21,581 | 1,988 | 464 | 665 |
| 64 | 21,875 | 2,030 | 470 | 666 |

Each native scalar call is bounded by 954 PHI2 ticks under the same assumptions.
The PAL admission window is lines 280–299. Even the latest start leaves at least
70 complete lines, or 4,410 PHI2 ticks, before IRQ58. The bounds cover one
`vm_step` attempt or one service/native call; `vm_run` rechecks admission before
every attempt. Diagnostic mailbox waits, timer instrumentation and IRQ execution
are separate. Physical Ultimate qualification remains pending.

Admission hooks return immediately with carry set while an NMI is pending.
The outer diagnostic command helpers and kernel command boundary perform
recovery before retrying admission. Recovery polls for the next PAL safe window;
under the accepted PAL profile with a continuously clocking VIC, this takes at
most one frame. That polling is outside the admitted step/service bounds above.
An external video-standard change and physical memory/I/O stalls remain
unqualified.

CIA timing samples use coherent high–low–high reads. The
[MOS Technology 6526 datasheet, November 1981](https://myoldcomputer.nl/Files/mos_6526_cia.pdf)
describes interval timer reads as live counter contents on printed page 6;
the read-latching described on page 7 belongs to TOD. A low/high timer pair can
tear at a low-byte rollover, so it cannot support precise duration claims. The
diagnostic VM timer records CPU/cache lookup time without actual DMA; the cache
service timer includes metadata, driver, one synchronous DMA direction and its
completion callback. M0's FETCH/STASH measurements remain separate observations.
