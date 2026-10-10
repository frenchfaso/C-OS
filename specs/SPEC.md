# C-OS Commodore OS
## Specification for the first implementation

Version 0.1, revision 6 — October 10, 2026. Target: C64 Ultimate, PAL, nominal 64 MHz turbo, 16 MiB REU, 320×200 UPIC video.

Initial numeric ABI version: 1, identical in the REU header, SYS_INFO, and SDK descriptors. Document versions and ABI versions use separate numbering.

C-OS is a small graphical operating system with a kernel and interpreter written in 6510 assembly. Applications execute bytecode and access the REU through linear 24-bit addresses. The kernel controls video, memory, input, and CPU time allocation; no application has to cooperate for the others to keep running.

The chosen UI is **C — Free NeXT desktop**: a simple desktop without a dock, taskbar, or permanent menu bar; square icons and widgets can be placed freely on a grid whose cells match the icon size. The shell uses only black, white, and the C64's three grays. The first implementation must prioritize simplicity, interaction latency, and code size.

This specification defines the behavior to implement. Values marked **initial** are parameters to measure and refine; they are not achieved performance figures. The chosen geometry, linear addressing, and application preemption are requirements. The internal RAM layout and cache sizes may be adjusted, provided the reason is documented and these requirements are preserved.

[C-Script: language and compiler](LANGUAGE.md), [SDK and Ultimate services](ULTIMATE-API.md), and [fractional numbers](NUMERICS.md) are also part of the specification. This document defines the VM, memory, scheduling, and shell; the companion documents define application source code, APIs, and the numeric profile. These are contracts to implement, not documentation of existing functionality.

For the development agent: start with section 22 and the milestone dependencies in §18. The tables in this document are normative for the ISA and core syscalls; ULTIMATE-API.md covers bindings, SDK records, events, and device services; NUMERICS.md covers numeric representation and semantics; LANGUAGE.md covers typing and the function ABI. Update cross-references together when changing a shared contract. This specification defines UI dimensions and behavior. Revision 5 adds preparation for optional native work in UPIC horizontal margins, disabled until timing qualification, without changing ABI 1, bytecode, or COS-NUM-1. See the [M2 implementation supplement](M2-UPIC-MARGINS.md).

Revision 6 adds the [real-workload performance contract](PERFORMANCE.md) and an autonomous workload baseline to M3. The goal is greater than 1× native original-C64 throughput, with 2× or better as the stretch goal; neither is an achieved result. ABI 1, bytecode, numeric semantics, and the default-disabled UPIC margin policy remain unchanged.

## 1 Decisions and scope

| Topic | Decision for version 0.1 |
|---|---|
| Name | C-OS, Commodore OS |
| Hardware | C64 Ultimate with 16 MiB REU and nominal 64 MHz turbo |
| Video | PAL; UPIC actually reduced to 320×200; 16 independent colors per pixel |
| Shell | Minimal NeXT style; desktop without permanent bars |
| Shell palette | C64 indices 0, 1, 11, 12, 15 |
| Desktop | 32×32 cells; each icon or widget occupies one whole cell |
| Runtime | Register VM implemented in NMOS 6502/6510 assembly |
| Application memory | Linear 24-bit REU addresses with bounds checking |
| Multitasking | One VM context per app; suspension enforced by the dispatcher |
| Fuel | Inexpensive counter per opcode; video deadlines handled separately |
| UPIC horizontal margins | Optional bounded native work after timing qualification; M2 prepares a disabled hook; VM and REU DMA remain outside active lines |
| Concurrent processes | Maximum 4 in the first version |
| Concurrent windows | Maximum 4, one per application |
| Initial language | C-Script, a small language compiled to bytecode on the development computer; assembler available for tests |
| Fractional numbers | Compact float24 and more precise float32; float aliases float32; COS-NUM-1 profile |
| Initial distribution | Bootstrap PRG and REU image generated together |
| Ultimate APIs | Files and directories, metadata, storage, and RTC through UCI; SID and Ultimate Audio through kernel services |
| Userspace video | Surfaces accessed through handles, native primitives, and blits from the app's pixel arrays; direct mapping deferred |
| Initial persistence | Documents and layout through the file service when storage is available |

The first MVP does not require POSIX, Linux, RISC-V emulation, binary compatibility with other VMs, Lua, WAMR, a JIT, garbage collection, networking, native USB HID, untrusted native processes, a filesystem written from scratch, or compilation on the C64. File I/O, directory/stat, mkdir/rename/file removal, storage discovery, RTC reads, SID, Ultimate Audio, and the C-Script compiler are in scope; device availability is reported to apps. Networking and HTTP have later milestones defined in the SDK document.

Do not port Freeview's event/update/render model or scheduler. C-OS applications have a normal entry point and a persistent context; they can run an event loop, wait for events, or compute.

## 2 Expected outcome of the first MVP

The system must boot to the desktop, allow icons to move between cells, and open at least two VM applications. An application in an infinite loop and an application continuously accessing the REU must coexist with usable input, windows, and desktop interaction.

The demonstration must include:

- a Note app in C-Script with an editable buffer and open/save operations through the file service;
- a Counter app that updates a limited area of its window;
- a Stress app alternating computation and accesses beyond the first 64 KiB;
- a native monitor showing processes, faults, memory, and diagnostic counters.

Also provide C-Script examples of file reads/writes, SID and PCM playback through Ultimate Audio, and drawing from a linear array. They do not all need to be resident processes at the same time: the pack contains at most four apps, and the bundler must be able to generate an alternative demo pack. Unavailable services return explicit errors; the desktop and apps without dependencies on that device continue running.

Include a directory-listing demo with stat for the selected entry and a shell panel to display/refresh detected storage. Verify boot without storage, selection between multiple C-OS roots, and a wall clock with uptime fallback. A simple list and the specified services are sufficient; a full file manager is not required.

Also include a small C-Script numeric panel: text input, float24/float32 selection, the four arithmetic operations, and a formatted result. A computation loop without yield in another app must coexist with the panel and desktop. The example demonstrates both types and error handling; performance comparisons belong in the separate benchmark.

A full file manager is not required for the MVP. Every active icon must open real functionality; avoid decorative buttons that do nothing.

The shell monitor may open a temporary panel handled like a compositor menu: it does not consume a fifth process or a fifth window surface. It must remain reachable when all four processes are busy and allow the active process to be identified and terminated.

## 3 Hardware and baseline facts

The REU is not RAM directly addressable by the 6510: the driver programs transfers between the REU and local RAM. The VM hides this distinction from apps through LOAD, STORE, and linear pointers. DMA registers remain exclusively under kernel control.

UPIC generates the image by writing the border color in sync with the raster. Reducing the width saves memory and work per line, but a loop that still waits through every line does not automatically return that time to the VM. The raster must be generated even when the desktop does not change.

References for hardware constraints: [Ultimate turbo documentation](https://1541u-documentation.readthedocs.io/en/latest/config/turbo_mode.html), [UPIC manual](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/docs/UPIC_MANUAL.md), [Ultimate Audio interface](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/include/ultimate_audio_lib.h). The SDK document covers details to verify for files, SID, and audio.

| Item | Rule |
|---|---|
| Turbo | Verify actual speed at boot; do not rely solely on the value of $D031 |
| Startup | Wait until turbo is actually available after reset |
| PAL | First target; NTSC excluded from the initial profile |
| DMA | Synchronous and not interruptible by the CPU; measure duration and setup cost |
| Arbitration | Do not assume DMA becomes 64 times faster because of turbo |
| Firmware | Record model, version, settings, and timing profile with the results |
| Emulation | Useful for regressions and diagnostics; does not replace timing qualification on the device |
| NMI and firmware menu | Disturbances outside normal scheduling; provide display recovery and document their effects |

For the REU, start with immediate FETCH/STASH, incrementing addresses, REU interrupts disabled, and autoload disabled. Every transaction must explicitly initialize the required registers. A zero-length software request is a no-op: do not pass zero to the length registers, where it can mean 65,536 bytes.

## 4 Architecture

```text
Bytecode applications
    registers, linear addresses, syscalls
                    |
Assembly VM + fuel + access checks
                    |
Kernel: scheduler, caches, event queues, and bounded jobs
             /                     \
Window manager and drawing     REU driver
             \                     /
          Local RAM and framebuffer
                    |
          Highest-priority UPIC scanout
```

The kernel and shell are trusted native code. An application cannot call 6510 addresses, modify vectors, touch zero page or the hardware stack, change turbo settings, program the REU/VIC/CIA, or access the physical framebuffer.

C-Script compiles directly for this VM; it does not add a second interpreter. The kernel also owns UCI, SID, and Ultimate Audio. APIs may suspend the calling app while the kernel serves other work. UPIC details are part of neither the language nor the video ABI.

The VM does not emulate a whole machine: no chipset, hardware MMU, guest timers, or privileged instructions. Its state consists of registers, PC, a virtual stack, and process metadata.

## 5 Local RAM and framebuffer

### 5.1 Budget

| Resolution | Packed 4 bpp pixels | Reservation with 256-byte columns |
|---|---:|---:|
| 384×200 | 38,400 bytes | 49,152 bytes |
| 360×200 | 36,000 bytes | 46,080 bytes |
| 320×200 | 32,000 bytes | 40,960 bytes |

C-OS starts with 256-byte columns: predictable indexed reads, with no page crossing for Y between 0 and 199. The 56 undisplayed bytes in each column remain unused in the MVP.

Of the local 64 KiB, 40 KiB hold the framebuffer and 4 KiB are the visible I/O window. This leaves **20 KiB directly usable** for code, stacks, caches, and data while keeping I/O visible. The 24 KiB “outside the framebuffer” are not all normally accessible RAM.

### 5.2 Initial map

BASIC/KERNAL ROMs are banked out and I/O remains visible during normal operation, with the 6510 port configured consistently with $01=$35.

| Inclusive range | Bytes | Initial use |
|---|---:|---|
| $0000–$0001 | 2 | 6510 port registers |
| $0002–$007F | 126 | Active VM registers and dispatcher scratch |
| $0080–$00BF | 64 | Kernel and driver scratch |
| $00C0–$00FF | 64 | Scratch reserved for raster and interrupts |
| $0100–$01FF | 256 | Hardware stack, kernel only |
| $0200–$02FF | 256 | High-nibble extraction table |
| $0300–$03FF | 256 | Global state and compact window descriptors |
| $0400–$05FF | 512 | Four 128-byte PCBs |
| $0600–$07FF | 512 | Four event queues, each with 8 records of 16 bytes |
| $0800–$0BFF | 1,024 | Code cache: two 128-byte lines per process |
| $0C00–$0FFF | 1,024 | Shared data cache: eight 128-byte lines |
| $1000–$11FF | 512 | DMA and graphics job staging buffers |
| $1200–$3FFF | 11,776 | Resident kernel, VM, shell, and driver code |
| $4000–$CFFF | 36,864 | First 144 packed framebuffer columns |
| $D000–$DFFF | 4,096 | I/O; do not use as ordinary RAM |
| $E000–$EFFF | 4,096 | Last 16 packed framebuffer columns |
| $F000–$F9FF | 2,560 | UPIC renderer, preparation, and synchronization |
| $FA00–$FCFF | 768 | Resident font, 96 glyphs of 8 bytes |
| $FD00–$FD7F | 128 | Cursor save-under |
| $FD80–$FDFF | 128 | Cache metadata |
| $FE00–$FFF9 | 506 | Desktop state, dirty list, titles, and diagnostics |
| $FFFA–$FFFF | 6 | NMI, RESET, and IRQ vectors |

This is a design budget to compare with the first map file, not a measurement of the finished kernel. If a section does not fit, the build must fail: no silent overlaps, temporary I/O banking during raster output, or implicit removal of memory from the VM.

Structures have fixed limits. Generate a report with each section's actual size, maximum hardware stack usage, and remaining headroom. Do not add a UI framework before this report exists.

The budget also includes the drivers added in the SDK document: do not assume extra space beyond this map. Keep cold metadata, filenames, and bytecode libraries in the REU; only the necessary dispatcher, drivers, and continuations should be resident. The complete kernel's size is a risk to check early. If it does not fit, reduce duplication and move unprivileged logic into bytecode, or propose a measured revision of the map; do not silently remove required services.

The float24/float32 numeric core and its scratch space must fit within the same budget. NUMERICS.md sets an initial target to qualify of 4 KiB total for the core, numeric conversions, and bridge; text converters start as bytecode in the apps' REU arenas. Do not add 4 KiB to the map as though it were free memory outside the limit.

### 5.3 Framebuffer access

For x from 0 to 319 and y from 0 to 199:

```text
c = x >> 1
base(c) = $4000 + 256*c                  if c < 144
base(c) = $E000 + 256*(c-144)            otherwise
address = base(c) + y
even x: low nibble; odd x: high nibble
```

Primitives must preserve the adjacent pixel's nibble. The geometry and columns must actually be reduced to 320: a 320-wide viewport inside a 384-wide renderer does not satisfy this requirement.

## 6 Linear REU memory and isolation

### 6.1 Chosen model

The numeric address space is $000000–$FFFFFF. A pointer contains exactly three bytes, little endian.

In the MVP, **the application's address equals the REU offset**. Do not introduce a virtual page table or add a process base on every access. The loader assigns a contiguous arena to each application; the assembler/linker on the development computer resolves references against the assigned base.

This provides linear addressing and a simple ownership check. It does not provide separate private address spaces all based at zero, or overcommit. The 16 MiB are the total shared physical memory, not 16 MiB dedicated to each app.

An array may cross $xxFFFF without bank-switch instructions. LOAD/STORE, copies, stack, code, and APIs accept the same pointers.

### 6.2 System reservation

| Inclusive REU range | Size | Initial purpose |
|---|---:|---|
| $000000–$00FFFF | 64 KiB | Header, kernel images, app initialization seeds, and boot assets |
| $010000–$017FFF | 32 KiB | Client surface for window 1 |
| $018000–$01FFFF | 32 KiB | Client surface for window 2 |
| $020000–$027FFF | 32 KiB | Client surface for window 3 |
| $028000–$02FFFF | 32 KiB | Client surface for window 4 |
| $030000–$033FFF | 16 KiB | Directory snapshot 1 |
| $034000–$037FFF | 16 KiB | Directory snapshot 2 |
| $038000–$03FFFF | 32 KiB | Shell assets, configuration, cold metadata, and system reserve |
| $040000–$FFFFFF | 15.75 MiB | Application arenas |

The initial system reservation is therefore 256 KiB. Show it in reports; do not describe 15.75 MiB free as 16 MiB actually allocatable by apps. The boundary may be revised after measurement while retaining the linear 24-bit space.

Directory snapshots reuse 32 KiB of the original reservation; they do not increase the 6510 resident RAM limit. The build report must demonstrate that shell assets and metadata fit in the remaining 32 KiB. Snapshot slots and memory become available again after closedir, kill, or a failed opendir.

### 6.3 Process arena

Each arena contains immutable code, initialized data/BSS, a heap, and a separate virtual stack. Arena start and size, section starts, and stack size are multiples of 128 bytes; code is also aligned to four bytes. Heap and stack each contain at least 128 bytes. The manifest declares every bound. Two arenas must never share a physical cache line.

Initialized data and BSS may be empty: describe them with a start and length, where zero length authorizes no access or copy. The regions with inclusive bounds listed below are always nonempty. Alignment padding is not executable code and is not part of the data length to restore.

The kernel stores **inclusive 24-bit bounds**: arena_first/last, code_first/last, heap_first/last, stack_first/last. This avoids representing $1000000 in a 24-bit pointer.

For an access of N bytes where N>0:

1. Compute last = address + N - 1 with overflow detection.
2. Check address >= arena_first and last <= arena_last.
3. For a write, check that the range does not intersect code or an audio sample currently protected by the kernel.
4. For fetch/branch/return, check that the target is aligned to four and that all four instruction bytes are within code.

Do not discard carry beyond 24 bits. The kernel may address its own reservation, but the app cannot, including through a syscall.

An out-of-arena pointer may be constructed or stored as a value; dereferencing it is prohibited. This keeps comparisons and arithmetic simple without weakening memory access protection.

### 6.4 Heap and lifecycle

No GC in the MVP. Initially provide a userspace library with a bump allocator and reset the heap arena when the app restarts; general malloc/free may come later.

When the same app restarts, restore initialized data, clear BSS and context, and recreate its stack and resources. Heap contents are not guaranteed to be zero. MVP arenas are assigned statically and are not reassigned to another app during the session.

Before any future reassignment to another app, clear the region. When terminating a process, cancel pending jobs and invalidate every cache line and handle it owns before reusing the slot.

Before reusing memory being read by audio hardware, stop the channels and release the associated constraints. An already submitted UCI operation may require draining/abort and must not be attributed to a new process occupying the same slot. Termination has a kernel cleanup continuation separate from the now-stopped VM context.

## 7 Caches and REU transactions

### 7.1 Initial caches

- Code: two 128-byte lines per process, read-only; alternating replacement or one-bit LRU.
- Data: eight 128-byte lines total, write-back; simple CLOCK replacement.
- Tags: REU block address and valid/dirty/busy state; dirty data remains associated with its owner.
- A REU page here means only a cache block, not a window visible to the app.

Sizes are build parameters to compare against at least one variant with 64-byte lines. Do not introduce complex associative caches without measuring a real problem.

### 7.2 Misses and resumption

A cache miss puts the process in WAIT_REU and returns control to the kernel. The kernel performs write-back/refill in bounded transactions when the video schedule permits.

The destination line remains busy and unavailable until the transfer completes. Only then publish the valid tag and wake the process.

Before modifying registers, stack, or memory, an opcode must have checked all bounds and made every required line available. A 16- or 24-bit LOAD/STORE may cross two lines: pin both during the short execution phase.

If a line is missing, resume from the same PC without having changed visible state. This prevents partial STOREs, duplicate PUSHes, double syscalls, and repeated fuel consumption for the same attempt.

### 7.3 Coherence between the VM and native services

Full flushes are not needed at every context switch. However, drivers and native services cannot read a stale REU copy of data still dirty in the cache.

All native accesses to application memory must either:

- use the same coherent access layer as the VM; or
- write back the affected dirty lines before a DMA read, and invalidate/update lines affected by a DMA write.

The second approach must be centralized in the driver rather than duplicated in each syscall. Surface buffers belong to the kernel and use staging separate from the apps' data cache.

### 7.4 DMA driver

A single arbiter owns the REU registers. Every request declares direction, REU address, local address, length, owner, and continuation.

The driver:

- never transfers into I/O, code, zero page, or the hardware stack on behalf of an app;
- prevents wrap of the 16-bit local address and 24-bit REU address;
- splits transfers according to the time budget, not just the register limit;
- treats FETCH and STASH as distinct synchronous operations with their own costs;
- never starts DMA unless it can finish before the video guard time.

Conservative initial value: transactions of up to 128 bytes during normal service. The hardware profile may reduce or increase this based on measurements. A maximum length does not replace checking the available time.

## 8 VM and bytecode

### 8.1 Architectural state

| State | Size | Use |
|---|---:|---|
| R0–R7 | 8 × 16 bits | Integers, counters, handles, and arguments |
| P0–P3 | 4 × 24 bits | Linear pointers |
| PC | 24 bits | Address of the current opcode |
| SP | 24 bits | Next free byte in the descending virtual stack |
| Fuel | 8 bits | Instructions still allowed in the current slice |
| PCB | Separate metadata | Bounds, state, waits, events, jobs, and diagnostics |

The active process's R and P registers reside in zero page; they are copied to the PCB at a process switch. Apps cannot access this zero page directly.

The VM has no persistent arithmetic flags: branches compare registers. Integers are little endian; signed 16-bit values use two's complement. Integer ADD/SUB wrap modulo 65,536; pointer arithmetic instead checks for 24-bit overflow.

### 8.2 Initial encoding

Every instruction occupies **four bytes**: opcode, b1, b2, b3. PC and control-flow destinations are aligned to four.

This is an initial choice for simple decoding, fetching, and validation. It uses more code space than variable-length bytecode but avoids length decoding and destination bitmaps. Explicitly measure code traffic through the REU; do not claim this is the fastest format without comparison.

Operand rules:

- rr: b1 low nibble = destination/lhs; high nibble = source/rhs; valid R indices 0–7.
- pp: the same layout for P, with valid indices 0–3.
- rp: low nibble = R; high nibble = P.
- pr: low nibble = P; high nibble = R.
- u16/i16: b2 low, b3 high.
- u24: b1 low, b2 middle, b3 high.
- A single R/P register occupies all of b1 as an unsigned index unless the table explicitly specifies another position; R>7 or P>3 indices are invalid. In nibble formats, validate both indices separately.
- Unused fields must be zero; reserved encodings cause a fault.

For relative branches: target = PC + 4 + 4 × sign_extend(i16). Compute this with a sufficiently wide intermediate; it must not wrap at 24 bits.

When an instruction continues, validate the actual next PC selected before applying effects; a branch not taken uses PC+4. CALL also validates PC+4 as the future return address before pushing it. JMP/RET and termination do not require a valid fall-through. For a syscall that may return, the resumption PC must be valid before accepting the job. The compiler closes every path with RET, EXIT, or TRAP and leaves no implicit execution beyond the code.

### 8.3 Initial instruction set

All valid opcodes cost one fuel unit in version 0.1. Native operations are accounted for separately.

| Hex | Instruction | Operands | Semantics |
|---|---|---|---|
| 00 | NOP | zero | No effect |
| 01 | MOV | rr | Rdst = Rsrc |
| 02 | LDI | Rdst, u16 | Load a 16-bit constant |
| 03 | ADD | rr | Rdst += Rsrc |
| 04 | SUB | rr | Rdst -= Rsrc |
| 05 | AND | rr | Bitwise AND |
| 06 | OR | rr | Bitwise OR |
| 07 | XOR | rr | Bitwise XOR |
| 08 | SHL | Rdst, b2=count | Left shift, count 0–15 |
| 09 | SHR | Rdst, b2=count | Logical right shift, count 0–15 |
| 0A | SAR | Rdst, b2=count | Arithmetic right shift, count 0–15 |
| 0B | ADDI | Rdst, u16 | Immediate addition modulo 65,536 |
| 0C | TRUNC8 | Rdst | Clear the high 8 bits |
| 0D | SEXT8 | Rdst | Sign-extend the low 8 bits |
| 0E | NOT | Rdst | 16-bit complement |
| 10 | LD8 | rp, u16 | R = zero_extend(mem[P+u16]) |
| 11 | LD16 | rp, u16 | R = little-endian read of two bytes |
| 12 | ST8 | rp, u16 | Write the low 8 bits of R |
| 13 | ST16 | rp, u16 | Write two bytes of R |
| 14 | LDP | pp, u16 | Pdst = three bytes from [Psrc+u16] |
| 15 | STP | pp, u16 | Write the P selected by the low nibble to [P selected by the high nibble + u16] |
| 16 | PMOV | pp | Pdst = Psrc |
| 17 | PADD | pr | Pdst += unsigned(Rsrc), with checked overflow |
| 18 | PSUB | pr | Pdst -= unsigned(Rsrc), with checked underflow |
| 19 | PGETLO | rp | R = low 16 bits of P |
| 1A | PGETHI | rp | R = high 8 bits of P, zero-extended |
| 1B | PMAKE | b1=Pdst, b2=Rlo, b3=Rhi | P = Rlo + (Rhi << 16); Rhi must be <=255 |
| 1C–1F | PLI0–PLI3 | u24 | Load an immediate pointer into the P selected by the opcode |
| 20 | JMP | u24 | Jump to an absolute address |
| 21 | CALL | u24 | Save PC+4 on the stack and jump |
| 22 | RET | zero | Retrieve and validate the return PC |
| 23 | BEQ | rr, i16 | Branch if the two R registers are equal |
| 24 | BNE | rr, i16 | Branch if different |
| 25 | BLTU | rr, i16 | Branch if lhs < rhs unsigned |
| 26 | BGEU | rr, i16 | Branch if lhs >= rhs unsigned |
| 27 | BLTS | rr, i16 | Branch if lhs < rhs signed |
| 28 | BGES | rr, i16 | Branch if lhs >= rhs signed |
| 29 | PBEQ | pp, i16 | 24-bit equality comparison |
| 2A | PBNE | pp, i16 | 24-bit inequality comparison |
| 2B | PBLTU | pp, i16 | Unsigned pointer comparison |
| 2C | PBGEU | pp, i16 | Unsigned pointer comparison |
| 30 | PUSH16 | Rsrc | Push two bytes |
| 31 | POP16 | Rdst | Pop two bytes |
| 32 | PUSHP | Psrc | Push three bytes |
| 33 | POPP | Pdst | Pop three bytes |
| 34 | GETSP | Pdst | Copy SP |
| 35 | SETSP | Psrc | Set SP within stack bounds |
| 36 | SYSCALL | b1=id | Invoke a kernel service |
| 37 | YIELD | zero | Voluntarily end the slice |
| 38 | TRAP | b1=0, u16 | Explicit application fault |

Multiplication, division, and 32-bit integer operations start as bytecode libraries. Do not add an opcode with arbitrarily long work to accelerate them. Floats use the NUM_OP service with bounded and accounted native work, as specified in NUMERICS.md; the ISA does not gain F registers or monolithic floating-point opcodes.

### 8.4 Stack and calls

Descending stack in the REU. Initial SP = stack_last. For a PUSH of N bytes:

```text
check SP-(N-1) >= stack_first
write the little-endian value to [SP-(N-1), SP]
SP = SP-N
```

For a POP of N bytes, check SP+N <= stack_last, read [SP+1, SP+N], and increment SP by N. When the stack is full, SP = stack_first-1; when empty, SP = stack_last. Application arenas begin well above zero, so both are representable in 24 bits.

CALL uses a three-byte PUSH; RET validates the target before changing PC or SP. GETSP/SETSP support software frames and locals; SETSP accepts only [stack_first-1, stack_last].

The ISA does not automatically save any register other than the PC for CALL. The C-Script ABI adds preservation of P2 through the prologue/epilogue, as defined in LANGUAGE.md. No virtual-stack byte remains on the hardware stack between slices or waits.

### 8.5 Faults

An invalid opcode, misaligned PC, illegal access, pointer overflow, stack overflow/underflow, or TRAP terminates only the responsible process.

Record PID, instruction PC, cause, and affected address. Cancel its waits, invalidate its handles, and remove its window through the normal compositor. The monitor must remain usable.

## 9 Fuel and scheduler

### 9.1 Preemption rule

Initial quantum: **128 retired opcodes**. The dispatcher has a mandatory check that an app cannot skip. Compiler-inserted yields are unnecessary, and there are no debug hooks.

Logical sequence:

```text
if fuel == 0: return FUEL_EXHAUSTED to the kernel
fetch and decode
check bounds, resources, and cache lines
if I/O is needed: return WAIT without architectural effects
decrement fuel exactly once
execute a bounded phase and complete the instruction
publish the next PC or the syscall's wait state
```

The kernel may also interrupt the slice for a video deadline or a priority event. If suspension is purely for timing, preserve the remaining fuel. A miss does not consume fuel again on retry.

SYSCALL advances PC exactly once when the kernel accepts the job and stores a continuation. On resumption, deliver the result; do not execute the invocation again.

### 9.2 Process states

STOPPED, RUNNABLE, WAIT_REU, WAIT_JOB, WAIT_EVENT, SLEEPING, FAULTED.

Do not leave a WAIT process in runnable lists. I/O completion, an event, or sleep expiry returns it to RUNNABLE. Each app has at most one pending blocking syscall/job.

### 9.3 Initial policy

Round-robin among RUNNABLE processes, with equal quanta and no dynamic priorities. Waking a process inserts it at the tail and does not give it a shortcut to run repeatedly ahead of others.

Assign a new full quantum on exhaustion or after an actual wait for an event, positive sleep, or external I/O. Cache misses and suspensions for internal CPU work do not refill the budget: this also applies to MEM_COPY/FILL, drawing, presentation, and surface creation.

NUM_OP is CPU work: its continuations preserve remaining fuel even across multiple service windows. Waiting in the numeric queue is not a new activation from external I/O. Phase costs are recorded in the owner's native budget, with normal job rotation.

YIELD and SLEEP(0) surrender the remaining fuel and place the app at the tail; its next turn starts with the normal quantum. A poll that immediately returns EAGAIN is not a real wait and does not refill fuel. Shortening a slice for the raster deadline limits the opcodes executable now, without discarding or increasing the turn's remaining credit.

The native job queue is also served in rotation, **one bounded chunk per owner at a time**. A large copy or huge fill cannot monopolize service. Record retired opcodes, DMA bytes, and native time per process separately.

When both queues have work that can be admitted before the raster deadline, alternate a VM slice and a native queue chunk; preserve the turn across service windows. If a queue is empty or its next chunk does not fit in the remaining time, serve the other without losing the turn owed. The shell participates as an owner of ordinary jobs, including composition: two separate round-robin queues are insufficient if one is always served before the other.

Qualified margin work (§10.4) executes a prepared phase of an ordinary native job. Charge its actual work to the same owner and service entitlement; it does not create a second queue, a new quantum, or extra turns for that owner. Preparation and subsequent rotation remain with the ordinary arbiter outside the active interval. Preserve any VM/native turn already owed; a temporary absence of a legal VM window does not authorize an unbounded batch of native phases. M2 defines the handoff and accounting contract; the complete fairness policy remains M3.

NUM_OP, copies, fills, and drawing pass through this arbitration even when a single chunk is sufficient: a fast path must not execute a series of native jobs within one VM slice and bypass rotation. Metadata queries with a small, fixed cost may complete in the syscall handler, with that cost included in the opcode's bound.

Input, cursor, and shell interaction take precedence over ordinary work but are also bounded. Coalesce pointer movement and update slow widgets only when they change. Do not immediately add DWRR, basic-block scheduling, or complex adaptive estimates.

### 9.4 Fuel and real time

An opcode does not have a constant duration. Fuel limits VM monopolization; the video schedule limits when work may start.

Before a slice, the kernel may reduce its quantum based on available time and the worst measured cost of opcodes without misses. Slow paths return to the kernel before starting DMA or other lengthy work.

Maintain a conservative estimate of the maximum cost of each native chunk and a guard time before video. If a chunk does not fit, defer it to the next usable period. Do not use average DMA time as a safe upper bound.

## 10 Video schedule and interrupts

### 10.1 First implementation

The UPIC raster has absolute priority. During the 200 displayed lines, do not execute the VM or start REU DMA. Most work takes place before and after this interval.

Moving from 384 to 320 pixels does not shorten the 200 lines. Horizontal margins remain waits in the default build: the MVP must already demonstrate responsiveness with this simple configuration.

M2 prepares the small optional execution hook and internal handoff described in §10.4, without enabling work in the margins. Only after timing qualification may parts of those waits be replaced by native work of known duration. Activation is optional and is not a condition for completing M2 or the baseline MVP. Running general bytecode in the horizontal margins is outside the MVP; the prohibition on REU DMA throughout the 200 active lines remains in force even when native margin work is enabled.

### 10.2 Renderer

Use the corrected UPIC 1.3 pixel cadence as a reference: the 320-pixel variant has 160 pairs, 20 immediate loads to prepare, and 2,520 cycles in the pixel stream alone. Preparation, synchronization, and completion add further costs.

Do not indiscriminately copy delays from the 384 variant or those calibrated in the emulator. Verify pixels at all four edges, alignment, and the absence of skipped lines on the chosen profile. [UPIC timing description](https://github.com/xahmol/mandelbrot-upic/blob/main/docs/UPIC_VIEWER.md).

The IRQ must preserve A/X/Y and every shared resource it uses; raster scratch must be separate from VM scratch. The interpreter and kernel must use only supported NMOS 6502/6510 instructions.

### 10.3 Deadlines

Arm the IRQ early enough before the first active line to synchronize phase. An initial guard of two lines must be verified, not assumed sufficient in advance.

The fundamental rule is: no DMA may still be active when the raster needs to synchronize. SEI does not solve this; DMA can hold the CPU beyond the deadline.

The IRQ also interrupts native code in progress. However, VM process switching occurs only at a consistent interpreter boundary, not in the middle of a handler.

Disable unnecessary CIA sources. An external NMI may disturb timing: the handler must preserve state, request recovery/emergency handling if necessary, and resynchronize on the next frame. Do not promise disturbance-free output while the firmware menu is opened or an external NMI is generated.

### 10.4 Optional native work in horizontal margins

**Default: disabled.** Provide a build-time switch whose normal setting excludes margin execution. The disabled renderer must preserve its pixel cadence, horizontal phase, geometry, and synchronization behavior; any dormant-hook overhead must be accounted for and requalified rather than silently inserted into a timed path. M2 need not enable the switch to pass. Its preparation adds no opcode, syscall, or userspace callback.

Start with one optional hook **after the final pixel and before synchronization for the next line**. Replacing part of the delay before the pixel stream is a separate optimization with separate qualification. The CPU cycles left after subtracting the pixel stream are not an admission budget: preparation, turbo changes, synchronization, control flow, and guards also consume time. Do not reserve a fixed numerical budget based only on the nominal 64 MHz setting or an average measurement.

**Eligible work and timing**

- A phase is a small trusted kernel routine with a bounded instruction path, already resident code, and operands/results in reserved local RAM. It may advance a native job but is not a general syscall handler. The first trial operates only on private scratch.
- No VM execution, REU DMA, cache miss/refill/write-back, UCI service, device-register access, allocation, waiting, or generic scheduler/driver callback is allowed inside a phase. Resolve validation, data availability, and any coherence work before publishing it. The renderer's own timed hardware accesses remain unchanged.
- Its qualified maximum includes admission/selection overhead, dispatch, register and status preservation, checks, the body, state publication, return, and any padding. Include branch/page-crossing costs and relevant stalls for the actual profile. Start only if that complete bound plus the qualified guard fits before the next required raster synchronization or pixel write; otherwise leave the work pending and use the ordinary path later.
- For a future hook before the pixel stream, all admitted and empty paths must preserve the required pixel start phase, using qualified padding or equivalent synchronization. A merely finite or usually short routine is insufficient.
- Return with the renderer's required registers, arithmetic status, stack balance, scratch, and patched operands intact. Save continuation state explicitly; no native call frame may remain on the hardware stack between slots or turns.

**Preparation, ownership, and reentrancy**

Outside the active interval, prepare a compact record identifying the kernel routine, owner and incarnation, local state/buffer ownership, maximum slot cost, and declared clobbers. Its byte layout is internal, not a new app ABI. A single prepared record is sufficient initially; do not preallocate a queue for every scanline or build a second scheduler.

Publish readiness only after the record is complete, through a final atomic state transition or an equivalent documented protocol. The IRQ must skip absent, partially prepared, stale, cancelled, or currently executing work rather than wait for it. Claim each prepared phase once; publish progress/completion once; consume that result and advance ordinary queue state outside the raster. Slot reuse must not attribute an old result to a new process incarnation.

An IRQ may interrupt ordinary kernel code using shared state. The hook must not re-enter that code or reuse its live scratch, locks, or half-updated structures. Keep margin scratch explicitly reserved and separate from VM/raster scratch and from any suspended kernel routine; either transfer exclusive ownership of a job before arming it or skip it while the ordinary path owns it. Include the ownership transition and scratch cost in the RAM map and timing bound.

Initial phases use private local buffers. Later framebuffer work requires an explicit raster-aware access rule: do not modify the current source row from operand preparation through its final pixel, because some values are prepatched while others are read during emission. No phase may alter the active pixel stream or turbo/video configuration. Any future use of already resident cache buffers must also prove pinning and coherence without calling a miss-capable cache path inside the slot.

**Qualification and fallback**

Record the artifact hashes, exact routine and complete path bound, slot position, guard, machine/backend, firmware/FPGA, turbo, PAL/output configuration, and measurement method. A change affecting timing invalidates the corresponding qualification. Observed maxima alone do not prove the worst-case bound. Emulation may enable an explicit experimental build only after its timing paths have been checked; this does not enable the feature on physical hardware. A hardware profile requires its own qualification, including the acceptance checks in §17.7.

No matching qualified profile, no ready phase, or insufficient remaining time means no margin work. The ordinary implementation outside the display interval must remain functional. Record admission/defer counts, completed work, timing failures, and per-owner native cost. After a detected overrun, missed synchronization, NMI recovery, or profile mismatch, stop admitting further phases and return to the baseline until the recovery/qualification conditions are restored. These diagnostics cannot undo an overrun already incurred and do not replace the pre-execution bound.

Activation must demonstrate useful work after all overhead, unchanged expected pixel output/phase, and no regression in isolation or ordinary queue progress. It is acceptable to leave the feature disabled if the measured benefit or RAM cost does not justify it.

## 11 Chosen UI and desktop grid

### 11.1 Approved visual direction

Chosen direction: **Free NeXT desktop**, with a minimal desktop and objects movable on the grid.

The desktop has a uniform background, a few square icons, and small widgets. It reserves no space for a taskbar, dock, global menu bar, or permanent panels. Windows may overlap icons; a “Show Desktop” command provides access to them.

Fonts, icons, positions, and colors must follow the renderer's actual grid and the metrics defined here, especially movement in whole cells. Project presentation images will use screenshots of the implementation when available.

### 11.2 Palette

| Name | C64 index | Use |
|---|---:|---|
| Black | 0 | Text, outlines, selection, active title bar |
| White | 1 | Text on black, fields, border highlights |
| Dark gray | 11 | Hard shadows and secondary outlines |
| Medium gray | 12 | Desktop background and inactive states |
| Light gray | 15 | Icon, button, and panel surfaces |

Every shell pixel, including cursor, icons, widgets, menus, and system windows, must use these five indices. Applications may use other colors **inside their own client area**.

No gradients, transparency, antialiasing, soft shadows, interlacing, or temporal dithering. A binary spatial pattern is allowed only when needed to distinguish selection/focus. Do not use arbitrary XOR on indices because it could generate colors outside the palette.

Do not fix device RGB values to those of generated PNGs: the normative references are the C64 indices, their roles, and contrast. The current hardware palette may affect the resulting RGB colors.

### 11.3 Cells the same size as icons

**A cell measures 32×32 pixels, exactly matching the entire icon or widget square. There is no 8×8 snapping on the desktop.**

At 320×200:

- 10 columns, col = 0…9;
- 6 rows, row = 0…5;
- grid origin: x=0, y=4;
- square position: x=32×col, y=4+32×row;
- 4-pixel margins above and below;
- each object occupies one cell; desktop objects cannot overlap.

Movement is like moving a piece between squares on a checkerboard: the object moves from one cell to another. There is no restriction to diagonal moves or adjacent cells: the mouse may reach any free cell.

The 32×32 square includes the border, icon, and short label. The main graphic must stay simple; labels should normally fit within four characters using the 6×8 font. Use short names or recognizable icons without shrinking text below a readable size.

Adjacent objects occupy contiguous cells. If visual separation is needed, provide it inside the square rather than changing the grid spacing.

### 11.4 Dragging

1. Press on an icon: select it and record the source cell.
2. After a small initial pointer threshold, enter dragging mode; cancel any pending double click.
3. Compute the candidate cell from the square's position, preserving the initial grab offset. Round to the nearest cell and clamp col/row to the valid range.
4. Show the preview **already snapped to the cell**; avoid allowing the final icon to wander through invalid positions.
5. On release in a free cell, update the record and invalidate only the necessary areas.
6. If another object occupies the cell, leave the object in its original position. No swapping, reordering, or automatic movement of other objects.
7. RUN/STOP cancels dragging. The source cell is a valid cancellation target without side effects.

Dragging is handled by the kernel and must work even if a VM app is stuck. Icons and widgets follow exactly the same rules.

On the desktop, F5 selects the next object and F6 (physical Shift+F5) the previous one, in row/column order with wraparound; when entering the desktop without a selection, choose the first object. RETURN opens the selected object. C=+M enters “Move” mode: cursor keys move the candidate cell, RETURN confirms, and RUN/STOP cancels. The same occupancy and bounds rules as for the mouse apply. Bindings are driver/shell constants; a shortcut editor is not required for the MVP.

A single click selects; a double click opens/restores an app or activates a widget. Initial double-click threshold: 12 PAL frames, to refine through usability testing. Distance and dragging take precedence over opening.

### 11.5 Objects and layout

Initial capacity: 12 desktop objects, despite the grid having 60 cells. Initial objects are one launcher for each of the 0–4 apps actually present in the pack, plus two widgets: clock/uptime and system monitor.

Each record contains at least a stable ID, type, associated app/widget, column, row, and flags. Position does not depend on list order or window positions.

Suggested initial layout: apps in cells (0,0), (1,0), (0,1), (1,1); widgets in cells (9,0), (9,1). Users may change it freely.

During a session, the layout remains in memory. Save it through the file service after an initial idle period of 50 frames since the last move, not at every drag step. The versioned format contains IDs and coordinates, separate from shell code. Validate sizes, duplicates, and collisions; an invalid file leaves a valid default layout active. Unavailable storage or a write error must not block the desktop; report them in the monitor and retain the session state. The SDK document defines the format and recovery.

MVP widgets are native and perform bounded work. The clock uses the shared RTC cache, refreshed by the driver at low priority; if the sample is unavailable or stale, it clearly displays uptime rather than presenting it as wall-clock time. App time queries do not each generate a UCI request. The monitor refreshes at most a few times per second. Extensible userspace widgets come later.

### 11.6 Font and controls

Initial font: monospaced 6×8, with a glyph area up to 5×7 plus spacing. Store 8 bytes per glyph, 96 glyphs. Printable ASCII text in the MVP; unsupported characters become a replacement glyph.

Initial metrics:

| Element | Logical size |
|---|---|
| Desktop icon/widget | 32×32, one cell |
| Font | 6×8 |
| Window border | 2 pixels |
| Title bar | 12 pixels, inside the borders |
| Standard button | 14 pixels high |
| Menu item | 12 pixels high |
| Cursor | Maximum 12×16 pixels |
| Minimum window | 128×80 |
| Typical window | 240×152 |
| Maximum window | 320×200 |

The active title bar is black with white text. Light surfaces and crisp one/two-pixel borders evoke NeXT without reproducing its original dimensions. Buttons, selections, and focus must be readable using only the five tones.

Text, a button, checkbox, simple list, and single-line text field are sufficient for the MVP. Client control behavior may live in the small userspace library; the shell handles its own menus and controls natively. Do not introduce a generic widget tree, layout engine, or dynamic skins.

## 12 Windows and composition

### 12.1 Window manager

Maximum four windows, one per app, with explicit Z order, focus, movement, closing, and hiding. Menus are contextual or local to a window.

Do not apply the desktop grid to windows. Even X origins and integer Y origins may be used to simplify the first blitter; movement must remain understandable and consistent.

The first version may use dimensions fixed by the app at creation. Interactive resizing and maximization with reflow come later and are not prerequisites for multitasking.

Use an outline or limited preview while moving; recompose contents on confirmation. Avoid copying the entire REU surface on every mouse movement.

F1 toggles “Show Desktop” and restoration of the previous arrangement; F3 brings the next window to the front. Do not change app execution merely because windows are hidden.

The launcher for an already active app restores/brings forward its window; it does not start duplicates in the MVP. If the process is alive but has closed its window, it opens the native monitor with that process selected, allowing termination. A small indicator inside the icon shows the active state without additional colors.

### 12.2 Client surfaces

Every window has a kernel-private surface in the REU. The app can draw on it through syscalls but has no writable pointer to the surface.

**Direct userspace framebuffer mapping is deferred.** For custom drawing, an app may allocate a linear INDEX8 pixel array in its arena and submit it with BLIT8. This array is a source: modifying it does not automatically update the screen. The kernel performs conversion, clipping, and composition; page columns, nibbles, and UPIC timing remain private. A future extension must preserve this separation.

Initial internal format: 8×8 tiles, 4 bpp, 32 bytes per tile; tiles arranged in row order. Within a tile, use four packed columns of eight bytes, with even pixels in the low nibble:

```text
tile_x = x >> 3; tile_y = y >> 3
tile_cols = ceil(client_width / 8)
tile_offset = (tile_y * tile_cols + tile_x) * 32
byte_offset = ((x & 7) >> 1) * 8 + (y & 7)
```

These tiles are only the graphics storage format: **they do not change the desktop's 32×32 cells**.

With a 320×200 window and the borders/title bar defined above, the maximum client area is 316×184: 40×23 tiles, 29,440 bytes. It fits in a 32 KiB slot.

On opening, initialize the entire used portion of the surface before exposing it; until then the shell may show the chrome and a uniform client area. Creation is bounded work, not one long DMA transfer.

### 12.3 Dirty regions

Use a single local framebuffer. Do not create a second local framebuffer or recopy the entire screen every frame.

Keep up to 16 dirty rectangles. Merge overlapping ones; if capacity is exceeded, switch to **progressive, bounded** full recomposition rather than a monolithic job.

For each dirty area:

1. Reconstruct the background, icons/widgets, and windows according to current Z order.
2. Draw chrome with native local primitives.
3. Read only the required visible client portions.
4. Clip against the screen, client, and windows in front.
5. Update the framebuffer in bounded chunks during the permitted time.

A window's contents can be restored even when the app is stuck because its surface belongs to the kernel. A covered window continues updating its own surface without forcing the compositor to draw it.

Do not promise atomic presentation of an entire frame without double buffering. Large updates may appear progressively; small UI operations must take precedence and have bounded latency.

### 12.4 Cursor

Use a software cursor in the shell palette with a small local save-under. Before drawing an intersecting area, restore the background; after updates, save the new background and redraw the cursor.

The save-under must account for pixel-pair alignment: a 12-pixel width at an odd X may occupy 7 bytes per row. The 128-byte reservation covers 7×16=112 bytes.

Do not automatically use VIC sprites for the cursor: first verify compatibility with UPIC border mode. The first backend uses only the software framebuffer.

## 13 Input and events

### 13.1 Initial backends

The C64 keyboard must be fully usable from the first MVP. The initial pointer comes from a joystick in port 2 or a mouse backend available and verified on the Ultimate; do not depend on a new USB stack.

The driver exposes normalized, device-independent events. A future 1351/mouse backend must be addable without changing the VM or window manager.

Initial shortcuts:

| Command | Action |
|---|---|
| F1 | Show desktop / restore windows |
| F3 | Next window |
| F5 / F6 (physical Shift+F5) | Next / previous desktop object or client control |
| RETURN | Activate the selected control |
| RUN/STOP | Cancel menu, dragging, or movement mode |
| C=+M on the desktop | Move the selected object by cells |
| C=+RUN/STOP | Force termination of the active app through the shell |

Do not base navigation on a physical Tab key absent from the standard keyboard. Combinations must be verified on the actual driver.

The shell consumes F1, F3, and its own combinations before generating app events. It also handles navigation on the desktop and in native panels; within a client window, F5/F6, RETURN, and RUN/STOP are ordinary events interpreted by the controls library. Keycodes, ASCII, modifiers, and flags are fixed in SDK §2.1, without a per-app table in the manifest.

### 13.2 Queues

Each app has a queue of eight 16-byte events:

| Offset | Field |
|---|---|
| 0 | type, u8 |
| 1 | flags, u8 |
| 2 | window handle, u16 |
| 4 | arg0, i16 |
| 6 | arg1, i16 |
| 8 | arg2, u16 |
| 10 | source frame, u32 |
| 14 | reserved, two zero bytes |

Initial types: POINTER_MOVE, BUTTON_DOWN, BUTTON_UP, KEY_DOWN, KEY_UP, FOCUS, BLUR, CLOSE_REQUEST, and INPUT_RESET. Pointer coordinates are relative to the client; keys have a normalized code and optional ASCII value.

Coalesce POINTER_MOVE. If a transition cannot be queued, discard input events that are no longer consistent and mark INPUT_RESET in a pending flag outside the ring. Upon delivery, the app clears its held-key state and reads buttons/modifiers/pointer through INPUT_STATE; no pressed-key bitmap is promised. The next KEY_DOWN recreates state for that key. Deliver the flag before new input events so overflow cannot lose it.

Critical notifications have pending flags separate from the ring: CLOSE_REQUEST persists until delivery, and the final focus state remains pending for notification. Repeated changes before reading may coalesce into the last FOCUS/BLUR; they do not require a second queue. Delivery order: CLOSE_REQUEST, focus change, INPUT_RESET, ordinary ring. On every loss of focus, invalidate the old destination's input events and capture, and mark INPUT_RESET even if a later FOCUS absorbs the pending BLUR. BLUR also clears the app's logical key/button state. A new window starts with a clean queue and flags.

Keyboard input goes to the active window after global shell commands. Desktop and window dragging use pointer capture in the kernel and do not depend on app queues. A BUTTON_DOWN within a client gives it implicit capture until the final BUTTON_UP, BLUR, hiding, or closing. During capture, send movement/release outside the client too, using signed coordinates; without capture, pointer events go only to the visible client under the pointer. Clicking a client first gives it focus.

## 14 Syscall ABI

### 14.1 Conventions

SYSCALL uses the ID in b1. Arguments are in R/P, with no native pointers. R0 returns status; other registers remain unchanged except for explicit outputs.

Statuses: 0 OK, 1 EINVAL, 2 ERANGE, 3 ENOMEM, 4 EAGAIN, 5 EBADF, 6 ENOSYS, 7 ECANCELLED, 8 EIO, 9 EBUSY, 10 ENODEV, 11 ENOTSUP, 12 ETIMEDOUT, 13 ENOENT, 14 EEXIST, 15 EACCES, 16 ENOSPC, 17 EOVERFLOW, 18 ENOTDIR, 19 EISDIR, 20 ESTALE, 21 EROFS, 22 EDOM, 23 EDIVZERO. ENOSYS indicates an unknown ID; ENOTSUP indicates a known operation unsupported by the profile. EOVERFLOW includes listings exceeding declared limits; ESTALE identifies references to an outdated generation. EDOM/EDIVZERO are the numeric errors described in NUMERICS.md.

Syscall argument errors return a status without avoidable partial changes. Illegal accesses by VM instructions instead cause a process fault. Validate every range, including those inside descriptors or command arrays.

Blocking syscalls leave the process in WAIT_JOB/WAIT_EVENT/SLEEPING; the CPU continues with other processes. “Blocking for the app” does not mean “blocking for the system”.

### 14.2 Initial services

| ID | Name | Input | Output/behavior |
|---|---|---|---|
| 00 | PROC_EXIT | R0=exit code | Terminate; does not return |
| 01 | SYS_INFO | — | R1=ABI, R2=320, R3=200, R4=0 reserved; capabilities in UltimateInfo |
| 02 | GET_FRAME | — | R1=low16, R2=high16 of the frame counter |
| 03 | SLEEP | R0=frame count | 0 is equivalent to YIELD; otherwise wait |
| 04 | EVENT_WAIT | P0=destination record, R0=timeout, R1=Window | 0 polls; $FFFF waits indefinitely; otherwise frames |
| 05 | WIN_CREATE | P0=descriptor | R1=handle; one window per app |
| 06 | WIN_CLOSE | R0=handle | Close the window, not necessarily the process |
| 07 | WIN_TITLE | R0=handle, P0=text, R1=length | Maximum 15 characters |
| 08 | GFX_SUBMIT | R0=handle, P0=commands, R1=count | 1–16 commands; returns when the surface is updated |
| 09 | GFX_PRESENT | R0=handle | Wait for presentation of work already accepted |
| 0A | MEM_FILL | P0=dst, R1=byte, R2/R3=length | Fill in bounded chunks |
| 0B | MEM_COPY | P0=dst, P1=src, R2/R3=length | memmove semantics, including overlap |
| 0C | MEM_INFO | — | P0/P1=heap first/last, P2/P3=stack first/last |
| 0D | INPUT_STATE | R0=Window | R1=buttons, R2=modifiers, R3=x, R4=y signed client coordinates; InputState binding in the SDK |

32-bit length = R2 + (R3 << 16), to be validated against actual address space; do not truncate it to 16/24 bits before checking. Zero-length MEM_FILL/MEM_COPY do not access their pointers.

EVENT_WAIT validates R1 ownership and liveness before reading the queue or suspending the process; an expired handle returns EBADF even if another window of the same process now exists. It returns EAGAIN if the timeout expires; in that case it leaves the record unchanged. It writes the record only after validating and making all its bytes available. INPUT_STATE validates the same handle without consuming events; coordinates may be outside the client. R1 is zero without that window's capture, and R2 is zero without focus: do not recreate presses whose release would not be delivered. For core syscalls, declared scalar outputs are zero on error; buffers remain unchanged except for execution errors after validation of progressive jobs. No chunk executes on an argument error.

GET_FRAME is a monotonic counter modulo 2^32, incremented every PAL video period even without desktop recomposition. Timeouts and uptime use unsigned differences of the counter, independent of the RTC or wall clock; no finite MVP timeout approaches 2^31 frames.

Window handle: a nonzero 16-bit identifier checked against the owning process and a live window. It uses the monotonic counter per process incarnation defined in ULTIMATE-API.md §3: no reuse while that app is alive; exhaustion = ENOSPC confined to the owner. Restart the counter only after complete cleanup and a fresh app initialization.

### 14.3 Window creation

WIN_CREATE descriptor, 16 bytes:

| Offset | Field |
|---|---|
| 0 | x, u16 |
| 2 | y, u16 |
| 4 | outer width, u16 |
| 6 | outer height, u16 |
| 8 | title pointer, u24 |
| 11 | title length, u8, maximum 15 |
| 12 | flags, zero for the MVP |
| 13 | reserved, three zero bytes |

Dimensions and position must fit within the screen and meet the minimum sizes. X must be even in the initial backend. Invalid input returns EINVAL/ERANGE; do not silently correct a malformed structure.

### 14.4 Graphics commands

16-byte record:

| Offset | Field |
|---|---|
| 0 | operation, u8 |
| 1 | flags, u8 |
| 2 | x, i16, client coordinates |
| 4 | y, i16 |
| 6 | w or text length, u16 |
| 8 | h, u16 |
| 10 | foreground color, u8, 0–15 |
| 11 | background color, u8, 0–15 |
| 12 | source pointer, u24 |
| 15 | reserved, zero |

Operations: 1 CLEAR, 2 FILL_RECT, 3 FRAME_RECT, 4 TEXT, 5 BLIT4, 6 BLIT8.

- CLEAR uses the foreground color for the entire client.
- FILL_RECT fills the clipped rectangle.
- FRAME_RECT draws a one-pixel inner border of the original rectangle and then clips it; it does not create new borders along the client boundary.
- TEXT uses w as the number of ASCII bytes, maximum 255; h=0. Flag bit 0 indicates a transparent background; otherwise it uses the background color. No unbounded search for a terminator.
- BLIT4 reads a row-major source, stride ceil(w/2), two pixels per byte, first pixel in the low nibble. Validate the entire source range with wide arithmetic. No scaling or alpha in the MVP.
- BLIT8 reads a row-major source, stride=w, one byte per pixel. The low four bits select index 0–15; the high four bits are ignored. Validating the batch does not require scanning every pixel. Buffer checking uses w×h with 32-bit arithmetic and validates the entire range before effects.

Other flags and unused fields must be zero: CLEAR uses only foreground; FILL_RECT/FRAME_RECT use x/y/w/h and foreground; TEXT uses x/y/w, both colors, and source; BLIT4/8 use x/y/w/h and source. Zero rectangle dimensions or zero-length text are no-ops; colors and format must still be validated. Do not dereference the source of empty commands. Clipping a nonempty command does not remove the requirement to validate its entire declared source range.

Validate the batch before effects. The app is suspended during the job, so commands and sources remain stable. Process bounded tiles/portions with explicit continuations.

GFX_SUBMIT updates the surface and marks damage; it does not guarantee that everything is already on the display. GFX_PRESENT waits for currently visible portions to be composed and scanned out. If the window is entirely hidden, it may complete once the surface is updated. Later restoration uses that surface.

A compositor continuation cannot reuse outdated geometry or Z order. Maintain a scene generation for move/focus/show/hide/close and a content revision per window. Before publishing a prepared chunk, check both: if they changed, discard stale staging and recompose from the current scene. Clear damage only for the revision actually composed. GFX_PRESENT waits for at least the requested revision without clearing damage added in the meantime.

### 14.5 Extended services

The [SDK and Ultimate services](ULTIMATE-API.md) document reserves IDs 20–2F for files/directories, 40–4F for SID, 50–5F for Ultimate Audio, 60–6F for video, and 70–7F for Ultimate information, storage, and RTC. 80–8F and 90–9F are reserved for future networking and HTTP and return ENOSYS in the MVP. All IDs are hexadecimal. Apply the same isolation, fuel, continuation, and argument-checking rules; no API executes a native pointer supplied by the app.

ID **30 NUM_OP** is defined in [NUMERICS.md](NUMERICS.md): selector in R1, scalar operands in R2/R3 and R4/R5, result in R2/R3, status in R0. It is a kernel numeric service with no dependency on UCI or Ultimate hardware capabilities. 31–3F remain ENOSYS.

## 15 Boot and development tools

### 15.1 Bootstrap

Produce a small PRG and a 16,777,216-byte REU image. The PRG starts at the conventional address $0801 and loads resident segments from the REU into explicitly permitted destinations.

The REU pack must already be loaded when the PRG starts: the delivery includes a verified loading procedure for the emulator and the Ultimate menu. A pack loader using the new OS's file service is not required for the first bootstrap; that service exists only after the kernel has started.

Do not create a flat PRG that is naively loaded across $D000–$DFFF while I/O is active. The bootstrap must not overwrite itself while copying segments; RAM in its own area may become cache only after the final jump to the kernel.

Procedure:

1. Disable unnecessary interrupts and establish a known 6510 environment, including CLD.
2. Verify the REU pack header/build.
3. Verify REU presence and size with a test that saves and restores affected bytes; an aliasing test must distinguish at least the smaller supported sizes.
4. Verify PAL and actual speed; wait for any slow phase after reset to end.
5. Load only authorized resident segments and initialize vectors, RAM, and framebuffer.
6. Initialize caches, processes, input, surfaces, and desktop; prepare incremental storage-discovery and RTC requests, which continue after the display starts in service windows outside the 200 active lines.
7. Start the raster and kernel loop.

An insufficient configuration produces readable diagnostics; do not try to run the 64 MHz renderer at a lower speed while pretending compatibility.

### 15.2 MVP pack

16-byte REU header at $000000:

| Offset | Field |
|---|---|
| 0 | Eight ASCII bytes: COSREU01 |
| 8 | build_tag, u32 little endian |
| 12 | ABI version, u16 |
| 14 | app count, u8, 0–4 |
| 15 | reserved, zero |

The same build_tag is compiled into the bootstrap. It detects a PRG paired with the wrong pack; it is not a security signature.

In the MVP, the bundler generates descriptors and addresses as assembly constants in addition to a readable JSON manifest. No dynamic linker or general executable format is needed on the C64.

For each app, declare a stable ID, name, source, arena, code/data/BSS/heap/stack sections, entry point, and initialization seed. Distinct IDs in 1…65535, ASCII names of 1…15 bytes; the PID exposed to the VM is the app's stable ID, not its PCB slot index. Code length is positive and a multiple of four. Arenas do not overlap; the build validates all bounds, §6.3 alignments, and static branch addresses. heap_min and stack_size are multiples of 128 and at least 128; a pack with no apps is also valid.

The bundler input manifest may remain small. Example pack with a single app, using decimal numbers to avoid nonstandard JSON:

```json
{
  "format": "COSPACK1",
  "abi": 1,
  "numeric_profile": "COS-NUM-1",
  "target": "c64u-pal-upic320",
  "storage": { "mode": "discover", "directory": "cos", "marker": ".cos-volume" },
  "apps": [
    {
      "id": 1,
      "name": "Note",
      "object": "build/note.cobj",
      "arena_start": 262144,
      "arena_size": 1048576,
      "stack_size": 16384,
      "heap_min": 131072
    }
  ]
}
```

Discover mode searches detected media for the prepared data tree, as specified in ULTIMATE-API.md §5.4. Alternatively, `"storage": {"mode": "explicit", "root": "/usb0/cos"}` is allowed for a known configuration; that path is not guaranteed on every device. The bundler rejects ambiguous configurations and also produces the `COSDATA1\n` marker and the `cos/.system`, `cos/apps/<id>` tree to install. A missing root does not prevent booting in RAM; the shell handles selection among multiple candidates after the desktop starts.

Host paths are relative to the C-OS root declared to the bundler. Code/data/BSS are placed in order with 128-byte alignment; the stack sits at the top of the arena; the remaining space goes to the heap, at least heap_min. The report shows all actual ranges and the data seed. The entry comes from the exported `_cos_start` symbol for C-Script apps, or from the entry declared in the assembler object.

On app entry: PC=entry, SP=stack_last, R0=PID, R1=ABI version, other R registers=0; P0=heap_first, P1=heap_last, P2=data start, P3=stack_last. If initialized data is empty, P2 is zero; BSS and runtime data addresses come from the linker. The linker and startup library must use this same convention.

### 15.3 Toolchain

Native assembly: Kick Assembler, consistent with the workspace. **Rust is the recommended choice for the compiler and host tooling**: VM assembler/disassembler, bundler, reference VM, and runner. Start with a small Cargo workspace and share ISA definitions, formats, and diagnostics between commands; do not introduce many crates or frameworks before they are needed. Prefer the standard library and a few justified dependencies, with Cargo.lock and a documented toolchain for reproducible builds. Rust runs on the development computer; the target kernel and interpreter remain in 6510 assembly.

Existing auxiliary scripts and independent oracles, such as exact rational calculations for numeric tests, may use Python where useful. Do not maintain two compilers or two equivalent packaging pipelines. The Cargo/CLI commands proposed in LANGUAGE.md replace the earlier direction to build the entire toolchain in Python.

Provide:

- a two-pass bytecode assembler, labels, constants, and listings;
- the C-Script compiler described in LANGUAGE.md, typed SDK bindings, and source examples;
- a disassembler showing addresses, opcodes, and operands;
- a PRG/REU bundler, manifest, and map files;
- a host reference interpreter for the ISA;
- an emulator test runner and counter capture;
- a minimal userspace library for calls, heap allocation, and basic controls.

Verify the ISA, memory, and scheduler with small assembler programs, then complete C-Script within the same MVP release. There is no need to port a C or Lua compiler. The format remains experimental until the fundamental tests are complete; any changes must update the compiler, assembler, runtime, ABI, and tests together.

## 16 Diagnostics and performance

Minimum counters, readable without altering the app's normal execution flow:

- frames produced and missed synchronizations;
- missed deadlines and deferred DMA transfers;
- retired opcodes and context switches per process;
- code/data cache misses, write-backs, and bytes transferred;
- maximum duration of a native chunk and maximum DMA transfer;
- maximum hardware stack depth;
- event queue overflows/coalescing;
- recomposed rectangles/tiles and graphics backlog;
- frames when input is received, its effect is applied, and it first becomes visible;
- UCI requests, timeouts, I/O bytes, active audio channels, and protected samples;
- duration of directory/storage scans, snapshot usage, storage generations, and RTC cache age.
- NUM_OP calls and native execution time per process, format, and operation; in diagnostic builds, counts per function/helper and the cost of text conversions.

When margin execution is built, additionally record admitted/deferred phases, useful work completed, complete slot cost, timing failures/fallbacks, and cost per owner. Extended slot traces belong in diagnostic builds and their timing/RAM overhead must be reported. These are internal diagnostics, not new SYS_INFO fields or a userspace ABI change.

Extended counters and tracing may be enabled in diagnostic builds. The normal build must not log a line for every opcode.

Measure the interpreter, cache misses/cache access, DMA, drawing, composition, raster waits, and interaction latency separately. Do not report the number of partial updates as full-frame FPS.

Initial targets to verify:

| Scenario | Target |
|---|---|
| Idle desktop | No repeated full recomposition; regular scanout |
| Shell input with two stress-test apps | Visible latency p95 within 2 frames, p99 within 3 frames |
| Pointer movement | Updates when input is available; no dependence on app yields |
| App in an infinite loop | Other apps and the shell continue making progress |
| Large MEM_COPY/FILL | Progressive service without monopolizing a frame or queue |
| Video stability | Zero missed deadlines during 10 minutes of the qualified acceptance workload |
| Startup/window opening | Measure and report; distinguish ready chrome from a ready client surface |

On PAL, two/three frames are approximately 40/60 ms. These are acceptance targets to measure, not results already achieved or guarantees for every conceivable workload.

If latency exceeds the targets, profile before adding complexity. Prioritize eliminating unnecessary work, improving locality, reducing overly fine-grained syscalls, and tuning native chunks. The disabled margin hook is prepared in M2, but enabling it still requires the measured benefit and timing qualification of §10.4; a new dispatcher policy is not a prerequisite.

Application throughput is measured on complete, equivalent workloads, following [PERFORMANCE.md](PERFORMANCE.md): Mandelbrot first, then a small ray tracer and a simple 3D rasterizer as their dependencies become available. Target greater than 1× an original PAL C64 running native 6510 code, with 2× or better as the stretch goal. Keep UPIC active in the primary C-OS measurement. Report each workload separately, validate its output, and include cache, scheduling, and native-service costs. Opcode rates and clock ratios are diagnostic evidence, not substitutes for these results. M3 establishes the first honest baseline; missing the throughput goal does not justify weakening isolation, preemption, output quality, or video timing.

## 17 Acceptance tests

### 17.1 Memory and ISA

- Aligned and unaligned 8-, 16-, and 24-bit reads/writes.
- Cache-line crossings and the $xxFFFF/$yy0000 boundary.
- LD8 at the last valid REU byte; rejection of a multibyte access extending past $FFFFFF.
- Protection of the kernel reserve, other arenas, and code.
- Pointer overflow/underflow, with no silent wrapping.
- Taken/not-taken branches, signed/unsigned comparisons, PC outside code or unaligned.
- Nested calls and saving the 24-bit PC.
- Full/empty stack and out-of-bounds SETSP.
- STORE/PUSH/CALL with misses: exactly one effect and one accounting entry.
- Malformed opcodes and reserved fields: fault confined to the app.
- Manifests with empty data/BSS sections; rejection of misaligned arenas, duplicate IDs, and empty heaps/stacks; a pack with zero apps can boot.

### 17.2 Fuel and resumption

With a small test quantum, for example three instructions, compare host and 6510 states after each slice. Count retired instructions, not fetch attempts.

Run loops with no syscalls and no yields; verify preemption and progress of other processes. Repeat with continuous misses, dirty evictions, event waits, and long native copies.

A process must not receive free quanta for cache misses or native CPU jobs. A suspended syscall must not execute twice. Verify simultaneous progress of an always-full VM queue and an always-full native queue, including across raster deadlines. Loading the next process's registers must be independent of the state left by the previous process.

### 17.3 REU and coherence

Verify zero length, forward/backward overlap, final bytes, job cancellation, write-back followed by a native read, a native write followed by a VM LOAD, and process-slot reuse.

Compare checksums and expected contents. A test that checks only the registers written to the DMA controller does not demonstrate the correctness of returned data.

Also verify VM and native writes to protected audio samples, visibility of the latest STOREs before PLAY, and cessation of hardware reads before releasing/reusing the sample.

### 17.4 UI

- Actual 320×200 raster with every edge pixel present.
- Shell pixels limited to indices 0, 1, 11, 12, 15.
- 32×32 cell: all 60 positions valid, correct margins.
- Moving apps and widgets between cells, including nonadjacent cells.
- Occupied cells, drops outside the area, cancellation, keyboard operation, and fast dragging.
- No intermediate desktop positions in 8-pixel steps.
- Focus, Z order, “Show desktop,” restoration, and closing.
- Restoring a window whose app is unresponsive.
- Cursor at edges, odd X coordinates, and redrawn regions, with no trails.
- Event overflow without logically stuck buttons/keys.
- Rapid focus loss/regain, reset outside the ring, pointer release outside the client area, and expired handles without consuming events from the new window.
- Desktop fully usable by keyboard, with 0–4 launchers; selection of a live process with no window through the monitor.
- Surface memory and clipping with negative coordinates and partially visible rectangles.
- Graphics batches with nonzero unused fields rejected with EINVAL before any effect; clipped FRAME_RECT with no artificial borders.
- INPUT_STATE after BLUR during a press does not reactivate buttons in the old window; release outside the client area and subsequent focus remain consistent.

Check the palette using framebuffer indices; photographs and screenshots document the visual result.

### 17.5 Integrated workload

For at least ten minutes:

1. App A in an infinite arithmetic loop.
2. App B reading/writing beyond 64 KiB with repeated misses.
3. App C updating small rectangles.
4. Continuous shell input: pointer movement, icon moves, focus changes, and window interaction.
5. Fault injection and forced termination of an app.
6. Checks of frames, latency, memory, process progress, and data correctness.

Retain the configuration, artifact hashes, manifest, map, numeric outputs, and captures. Report emulator and physical-device results separately.

### 17.6 Language and SDK

Pass the tests described in the companion documents: compilable C-Script examples, indices beyond 64 KiB, 16/32-bit integer and float24/float32 arithmetic, type and bounds errors; two apps using different files without interfering with each other; directory/stat and mutations within the root; absent/disconnected storage and obsolete generations; valid/expired RTC cache with monotonic scheduling; UCI timeouts without blocking the raster; SID/PCM cleanup on termination; BLIT8 consistent with the source array. Repeat the integrated workload with file reads/writes, directory scans, float calculations without yield, and PCM playback in progress.

### 17.7 Optional UPIC margin execution

For M2 preparation, verify that the default-disabled build retains the baseline renderer timing/geometry and VM/cache behavior. Document hook location, scratch/ownership contract, default switch, code/RAM costs, and qualification steps. Tests of the internal handoff must cover incomplete/stale records, exclusive ownership, and exactly-once completion without requiring active video execution. These preparation checks do not constitute timing qualification or require the M3 scheduler.

Before enabling a profile:

1. Exercise the complete empty/admitted/deferred paths and every relevant branch of each eligible routine, including address-dependent timing. Prove the complete bound fits the slot and guard; insufficient budget must cause no phase effects.
2. Compare all expected 320×200 pixels, four edges, horizontal phase, and line continuity with the baseline, first with private-scratch work after the final pixel. Test any later pre-pixel slot separately, including padding on empty paths.
3. Interrupt ordinary VM and kernel execution at ownership/publication boundaries. Verify scratch/register/stack preservation, no reentrant job, stale incarnation rejection, cancellation, and exactly-once publication/consumption. No active-line DMA, UCI/device access, cache miss path, or VM execution is allowed.
4. Compare outputs with the same job executed outside the display. Preserve fuel, owner accounting, bounded preparation, and the existing VM/native turn; verify progress of other eligible owners when the full scheduler is present.
5. Measure useful work after overhead and cumulative RAM cost; retain raw timings and profile/artifact identifiers. Run at least ten minutes with the admitted workload and zero missed synchronizations/deadlines, then test bounded NMI/menu disturbance, fallback, and recovery separately. Disturbance-free output during NMI/menu use is not required.

Report emulation and physical-device qualification separately. An unavailable device keeps hardware activation pending, not M2 preparation blocked. Leave ordinary builds disabled unless their exact profile and enabled routines satisfy the gate.

## 18 Implementation sequence

| Phase | Deliverable | Completion criterion |
|---|---|---|
| M0 Hardware and budget | Turbo/REU probes, 320 renderer, map file, DMA measurements, and initial resident-memory budget | Geometry verified on the available backend; explicit timing; measured sizes distinguished from estimated reserves |
| M1 Host VM | ISA, assembler, disassembler, reference VM | Semantic tests and generation of minimal apps |
| M2 6510 VM | Dispatcher, pointers, cache, stack, and disabled UPIC margin hook/contract | State comparison with the reference at boundaries and on misses; cumulative budget updated before expanding the SDK/UI; default renderer unchanged; margin activation not required |
| M3 Scheduler | Fuel, PCBs, waits, bounded REU jobs, and autonomous workload measurement | Two loops without yield coexist with the raster; fairness and cancellation verified; a real workload has a validated output and native-C64 timing baseline |
| M4a C-Script | Host compiler, minimum library, calling ABI, and source map | Language examples and tests run on the VM; loops without yield remain preemptible |
| M4b Fractional numbers | Float24/float32, NUM_OP, numeric/text conversions, and host model | Bit-exact corpus, scratch isolation, budget, and timing verified for both formats |
| M5 Graphics and input | Primitives, surfaces, BLIT8, compositor, cursor, and events | Clipping, coherence, restoration, and input verified |
| M6a Storage and time | Incremental UCI, files/directories/stat, mutations, storage discovery, RTC, and bindings | I/O concurrency, snapshots, disconnection, timeouts, and clock cache verified |
| M6b Ultimate audio | SID, PCM, and C-Script bindings | Leases, sample coherence, and cleanup verified; complete RAM/REU budget updated |
| M7 Desktop and apps | Style C, 32×32 grid, persistence, and C-Script examples | Complete interaction under concurrent load |
| M8 MVP qualification | Stress tests, profiles, and reproducible documentation | Acceptance criteria measured, remaining limitations stated |

The numbering identifies deliverables; it does not impose an artificial chain: M1 may proceed while M0 is being qualified; M2 integrates the host model and hardware constraints, then M3 verifies scheduling. After M3, M4a and the M5/M6a/M6b services may advance using small assembler test programs; M4a progressively adds bindings. M4b uses M4a/M3 but **does not block M5 or an initial desktop demo**. M7 gradually integrates these branches; M8 requires every deliverable, including both float types and the planned services. Avoid permissive stubs that make a missing service appear complete.

The [M2 UPIC supplement](M2-UPIC-MARGINS.md) narrows margin work to preparation of the disabled hook, handoff, and scratch contract. M3 owns integration with ordinary native-job fairness and accounting. Experimental or supported activation is a separate qualification under §§10.4 and 17.7, may follow when evidence is available, and is not required by M8. Do not split every service or numeric routine merely to fill horizontal margins.

The resident-memory budget is a continuous gate, not a check to defer until M6b. Starting in M0/M2, report assembled code, tables, ZP, stack/scratch, caches, and reserves for modules still to be implemented separately; include an assembled numeric candidate as soon as one is available. The 4 KiB target for both float types is part of the existing native budget, not additional memory. An estimate does not prove everything will fit: every milestone updates the map and reports any overrun immediately. Before expanding the UI, resolve measured overruns by reducing code or revising the layout with justification; overlays, new schedulers, and alternative formats are not prerequisites to build in advance.

Extensions N1 (TCP/UDP) and N2 (HTTP/JSON) follow M8. Both reuse the UCI engine; HTTP delegated to the firmware does not first require a userspace HTTP stack over TCP. Their gates and preliminary contracts are in the SDK companion document §10.

Advance through executable results. Do not first build a large SDK or a complete desktop on top of an unverified VM.

If a physical C64 Ultimate is unavailable, complete the checks that can be emulated and deliver a precise hardware procedure. The final status must distinguish “MVP verified in emulation” from “timing qualified on hardware”; do not wait indefinitely for a device or invent qualification results.

## 19 Parameters to determine through measurement

| Parameter | Initial value | Reason to change it |
|---|---|---|
| VM quantum | 128 opcodes | Switch overhead or latency |
| Cache line | 128 bytes | DMA setup/locality tradeoff |
| Code cache | 2 lines per process | Misses and code traffic |
| Data cache | 8 global lines | Thrashing between heap and stack |
| Ordinary DMA | Up to 128 bytes | Measured timing limits |
| Guard time | At least the qualified margin, initial trial of 2 lines | Actual worst case and renderer phase |
| UPIC margin work | Disabled; first candidate slot after the final pixel | Complete timing bound, profile qualification, useful work, and RAM cost; no assumed cycle allowance |
| Dirty list | 16 rectangles | Available RAM and overflow frequency |
| Event queue | 8 events per app | Overflow and service cost |
| Directory snapshots | 2 × 16 KiB REU, at most 256 entries each | Name lengths, directory limits, and REU reserve |
| Storage list | At most 5 devices | Qualified hardware profiles |
| RTC cache | Refresh every 50 frames, expires after 100 | UCI load and quality of available data |
| Numeric core | Target ≤4 KiB resident for both formats, bridge, and numeric casts | Actual size, ZP/scratch, REU costs, and float24/float32 benefits |
| Native resident-memory area | Proposed map | Size of the code actually assembled |

The following are not parameters to change to conceal a problem: shell palette, whole-cell grid, isolation between apps, addresses beyond 64 KiB, mandatory preemption, and the kernel's exclusive ownership of video/REU.

## 20 Later developments

After the MVP:

- window resizing and more controls;
- mapping a linear logical framebuffer into userspace, with acquire/present/release and explicit coherence;
- C-Script extensions only when required by real apps;
- possible float16, fixed point, and advanced mathematical functions, with measurements and explicit contracts;
- package loader, dynamic arena allocation, and more installed apps;
- userspace widgets subject to the same limits as apps;
- broader use of qualified horizontal-margin phases beyond the optional hook in §10.4;
- a more compact bytecode format, superinstructions, or block-level fuel, only if profiling justifies them;
- a possible more compact framebuffer, without losing timing control;
- N1: TCP/UDP clients with timeouts, handles, and verification of latency imposed on other UCI services;
- N2: HTTP/JSON in the firmware, with handle management and separate HTTPS verification;
- dedicated fullscreen mode, palettes, advanced audio streaming, file picker, and disk-image/SoftIEC management.

These extensions must not become prerequisites for the first version.

## 21 Reference projects

The projects studied are sources of ideas, not mandatory dependencies:

| Project | Idea to examine |
|---|---|
| [Acheron](https://www.white-flame.com/acheron/) | Virtual registers, small dispatcher, trap points |
| [BBC VM and compiler](https://github.com/TheEnbyperor/bbc-c) | Host toolchain and VM on a 6502 with extended memory |
| [semu-c64](https://github.com/onnokort/semu-c64) | REU access and emulated CPU state; avoid the cost of a whole RISC-V machine for our ABI |
| [Hopper](https://github.com/sillycowvalley/Hopper) | Runtime/language separation and bytecode organization; check for 65C02 dependencies |
| [ChibiVM](https://www.chibiakumas.com/chibivm/) | Instructions and interpreter portability |
| [6o6](https://github.com/classilla/6o6) | Separation of virtual execution and memory backend |
| [PLASMA](https://github.com/dschmenk/PLASMA) | Environment and compilation for 6502 machines |
| [EightBall](https://github.com/bobbimanners/EightBall) | Compact language and VM on the C64 |
| [SWEET16 for C64](https://github.com/Silverune/Sweet16) | Minimal size and virtual register arithmetic |
| [Original QuakeC](https://github.com/id-Software/Quake-Tools/tree/master/qcc) | Operator/type table, shared compiler/runtime contract, and profiling; analysis in NUMERICS.md |
| [XC-BASIC](https://github.com/neilsf/xc-basic3) and [LLVM-MOS](https://github.com/llvm-mos/llvm-mos/tree/main/compiler-rt/lib/builtins/mos) | Software floats and coexistence with integer types; candidate comparison in NUMERICS.md |

Lua and WAMR are not runtimes for the first MVP. C-Script compiles to C-OS; changing an existing interpreter's allocator is not enough to make REU memory linear.

References in the original C64 workspace, outside this repository:

- Reference UPIC renderer: `poc/upic384.asm`.
- UPIC 1.3 experiment at 360 pixels with work in the margins: `experiments/mupic/research/fp-raster-work/player_360_dict13.asm`.
- Assembly wrapper: `tools/assemble.py`.
- Emulated renderer palette: `UE2-C64U-WebRust/vendor/trx64-core/src/render.rs`.

These local references document the preliminary work; they are not dependencies available in a C-OS clone. The public references above allow the backends to be studied without the original workspace.

The local reference renderer declares a GPL-3.0-only license. Before integrating external source code, record its provenance, revision, and license, retaining its notices. Icons and fonts for the build must have defined sources and provenance.

## 22 Handoff instructions for the dev agent

Implement C-OS following M0–M8 in the **C-OS repository root**. Specifications are collected in `specs/`: use this document together with LANGUAGE.md, ULTIMATE-API.md, and NUMERICS.md; the approved UI is C, with 32×32 cells matching the icons. Build commands and artifact paths are relative to the repository root.

The structure can start small: native sources, host tools, apps, tests, and build output. Do not generate scaffolding or interfaces for extensions that the MVP does not need.

Use existing projects as references, and keep C-OS sources, builds, and launchers in its own repository. Development scripts must not replace launchers or modify configurations of other projects in the workspace.

Deliver at every milestone:

1. A bootable artifact or reproducible host test.
2. The exact command to build and run it.
3. A memory map and actual sizes.
4. Relevant test results and required measurements.
5. Justified deviations from the initial parameters and remaining limitations.

The first technical delivery must verify the 320×200 renderer, resident RAM, and DMA duration before committing to an extensive graphics implementation. The recommended host tooling language is Rust, as described in §15.3 and LANGUAGE.md; it can progress while hardware qualification is pending.

For M2, also follow [the UPIC margin preparation supplement](M2-UPIC-MARGINS.md). Keep its optional execution disabled until the complete profile-specific timing gate passes; completing this preparation does not authorize VM or DMA activity during the display interval.

The final MVP includes the bootstrap PRG, REU pack, manifest and map file, sources, C-Script compiler, Ultimate SDK, bytecode toolchain, reference VM, demo apps, tests, and qualification report. The normal build must not download arbitrary dependencies or depend on paths to temporary artifacts.

Do not declare multitasking complete if apps must yield; do not claim linear memory if the app must select a bank; do not claim a responsive UI using only a static screen.
