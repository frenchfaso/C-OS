# Ultimate SDK and services for C-OS

Specification 0.1, revision 8 — October 10, 2026. Normative companion to [SPEC.md](SPEC.md) and [LANGUAGE.md](LANGUAGE.md). Current application ABI 2; SDK descriptors carrying an ABI field report 2. Revision 8 changes no service ID, descriptor layout or capability bit; M3-R budgets these services before feature expansion. Historical ABI 1 packs must be rebuilt, not silently relabeled.

Apps must be able to use video, files and directories, storage, the clock, SID and Ultimate Audio with a small number of calls. The APIs hide UCI, device addresses, DMA, synchronization and firmware differences. Every operation respects kernel isolation and scheduling; the device is never assigned to an app as a directly writable I/O range.

The following names, layouts and IDs are normative proposals for the C-OS implementation, **not** APIs already provided by the Ultimate firmware.

Ultimate service priorities:

| Delivery | API |
|---|---|
| MVP, M6a | Existing files + stat, directories, mkdir/rename/remove; storage discovery and RTC reads |
| MVP, M6b | SID and Ultimate Audio as already planned |
| After MVP, N1 | TCP/UDP clients, with bounded waits and socket isolation |
| After MVP, N2 | HTTP and JSON access delegated to the firmware, after backend testing |
| Later | Palette, disk images, SoftIEC and administrative tools |

Sections 1–9 define the MVP contract. Section 10 sets the scope of extensions: proposed signatures to qualify before assigning final opcodes/ABI definitions.

## 1 Common rules

1. Arguments and buffers are guest values; linear REU pointers are u24, lengths are u32. Apps have no 6510 pointers.
2. Handles identify a resource, its owner and its type. They are not hardware indices that can be used without validation.
3. A process may have only one blocking syscall in progress. The request retains a kernel continuation and suspends only that process.
4. No long busy waits, no native loops proportional to an unbounded size, and no firmware waits with the raster suspended.
5. A batch is validated before avoidable effects occur. Device operations may fail after partial effects: specify counts and error semantics.
6. Data read by drivers/hardware must include the latest VM writes; data written by a driver must be visible to subsequent LOADs. Use the kernel's single REU coherence protocol.
7. Kill/fault/exit release all resources. Cleanup that waits for a device lives in the kernel and does not resume terminated bytecode.
8. Optional UPIC margin execution follows SPEC §10.4 and is disabled until qualified. Only prepared CPU-local phases are eligible; UCI, REU DMA, device access, and miss-capable cache paths remain outside the active lines. This is not a new SDK entry point or permission to invoke a complete service from the raster IRQ. Completion, owner accounting, and fuel semantics remain unchanged.

Services return the status codes defined in SPEC.md. C-Script wrappers return `value, error` or just `error`. Success is `0`; a service that is present but not enabled returns ENODEV/ENOTSUP, without pretending to succeed.

IDs in this document are hexadecimal. All guest descriptors are packed and little endian; reserved fields must be zero. An unspecified output must not contain stale kernel registers/data.

## 2 C-Script SDK surface

### 2.1 System and UI

| Signature | Behavior |
|---|---|
| `system.exit(code: int)` | Terminates the process; does not return |
| `system.sleep(frames: word) -> word` | Waits in frames; zero yields the turn |
| `system.frame() -> dword` | Monotonic counter modulo 2^32 |
| `ui.open(title: str, width: word, height: word) -> (Window, word)` | Centered window, even X; outer dimensions |
| `ui.close(win: Window) -> word` | Closes the window |
| `ui.title(win: Window, title: str) -> word` | Changes the title, maximum 15 bytes |
| `ui.wait(win: Window, timeout: word) -> (Event, word)` | Event or EAGAIN; 0=poll, 65535=indefinite wait |
| `ui.input_state(win: Window) -> (InputState, word)` | Buttons, modifiers and pointer relative to the client area |
| `ui.clear(win: Window, color: byte) -> word` | Fills the client area |
| `ui.fill(win: Window, x: int, y: int, w: word, h: word, color: byte) -> word` | Clipped rectangle |
| `ui.frame(win: Window, x: int, y: int, w: word, h: word, color: byte) -> word` | One-pixel inner border |
| `ui.text(win: Window, x: int, y: int, value: str, fg: byte, bg: byte) -> word` | Opaque text, maximum 255 bytes per call |
| `ui.present(win: Window) -> word` | Waits for accepted work to be presented |

`ui.FOREVER=65535`. Colors: BLACK=0, WHITE=1, DARK_GRAY=11, GRAY=12, LIGHT_GRAY=15. Wrappers do not restrict client colors to these five; the shell must do so.

SDK constants are typed in the binding, rather than being inferred as plain `int`: colors, event types and Event flags are byte; FOREVER, file modes, capabilities and error codes are word; keycodes are int; button/modifier masks are word. Other record constants have the type of the corresponding field (for example, FileInfo.kind is byte and FileInfo.flags is word). Use distinct names in the ui module: `KEYCODE_LEFT` for the key, `BUTTON_LEFT` for the button, `MOD_SHIFT` for the modifier; all keys, buttons and modifiers listed below use the KEYCODE_, BUTTON_ and MOD_ prefixes, respectively. Event types retain names such as `ui.KEY_DOWN` and `ui.CLOSE_REQUEST`; `ui.REPEAT` is the byte flag. The compiler checks these signatures in the same way as function signatures.

`Event` exactly matches the record in SPEC.md: `kind: byte`, `flags: byte`, `window: Window`, `arg0: int`, `arg1: int`, `arg2: word`, `frame: dword`, `reserved: word`. Signed coordinates retain the same 16-byte layout. Event types: 1 POINTER_MOVE, 2 BUTTON_DOWN, 3 BUTTON_UP, 4 KEY_DOWN, 5 KEY_UP, 6 FOCUS, 7 BLUR, 8 CLOSE_REQUEST, 9 INPUT_RESET. The wrapper zeroes the record if the wait returns an error, without interpreting uninitialized fields.

For POINTER_MOVE/BUTTON: arg0=client x, arg1=client y, arg2=captured button mask after the transition, LEFT=1 and RIGHT=2; without capture, the mask is zero. BUTTON_DOWN in the client area starts capture for that window: subsequent movement and transitions reach it even outside the client area, with signed coordinates, until the last button is released, BLUR occurs, or the window is hidden or closed. For KEY: arg0=normalized code, arg1=ASCII for the current text or zero if the key produces no text, arg2=modifiers; SHIFT=1, CONTROL=2, COMMODORE=4. `flags` permits only bit0 REPEAT on KEY_DOWN; it is zero in all other cases. FOCUS/BLUR/CLOSE_REQUEST/INPUT_RESET have zero arguments. Global shell commands are consumed by the kernel and are not duplicated in the app's queue.

The MVP keycode table is shared by the kernel and SDK; the manifest does not redefine it: `0x20…0x7E` for printable keys, with uppercase letters and the base symbol without Shift; `0x100` RETURN, `0x101` BACKSPACE, `0x102` INSERT, `0x103` LEFT, `0x104` RIGHT, `0x105` UP, `0x106` DOWN, `0x107` HOME, `0x108` CLEAR, `0x109` RUN_STOP; `0x110…0x117` for F1…F8 in order; `0x120` SHIFT, `0x121` CONTROL, `0x122` COMMODORE. The ASCII byte in arg1 reflects the actual text, including Shift and the keyboard mode. Physical function keys F1/F3/F5/F7 with Shift produce F2/F4/F6/F8, so Shift+F5 produces the F6 code; Shift+RIGHT and Shift+DOWN produce LEFT and UP. Shift+BACKSPACE produces INSERT and Shift+HOME produces CLEAR. Retain the code chosen at key-down until its corresponding key-up, even if Shift is released first. Other codes are ignored in the MVP; no hardware scancodes reach apps.

`ui.wait` passes Window in R1 to EVENT_WAIT: the kernel checks ownership and that the window is live before consuming an event or suspending the process. A closed handle returns EBADF even after a new window has been created. `ui.input_state` uses INPUT_STATE with R0=Window; the kernel returns R1=buttons, R2=modifiers, R3=client x, R4=client y. The wrapper constructs `InputState`, 8 packed bytes: `buttons: word` at 0, `modifiers: word` at 2, `x: int` at 4, `y: int` at 6; on error, the record is zero. Coordinates may lie outside the client area and are not clipped.

InputState represents the state deliverable to that window, rather than all physically pressed buttons: `buttons` is zero if the window does not own capture; `modifiers` is zero if it does not have focus. Coordinates always give the current position relative to the client area. Reading the state after BLUR therefore does not restore a press whose release would be delivered elsewhere.

INPUT_RESET or BLUR require the app to clear all keys it logically tracks as held; BLUR also clears buttons and client interactions. After INPUT_RESET the app can reread buttons, modifiers and the pointer with `ui.input_state`; 0.1 does not provide a key bitmap. This contract prevents a lost KEY_UP in a full queue from leaving a key stuck in the app. Pending flags, focus coalescing and delivery order follow SPEC.md §13.2.

The first primitives are immediate wrappers over GFX_SUBMIT. Wrappers, including video blits, zero each 16-byte record before filling the fields they use: stack temporaries are not implicitly zero. Batch access is `ui.submit(win: Window, commands: bytes, count: word) -> word`: it checks `1 <= count <= 16` and at least `16*count` bytes, using the format already defined. More convenient helpers for constructing batches can be added to the library after measuring simple apps. No retained widget tree is needed.

### 2.2 Video

| Signature | Behavior |
|---|---|
| `video.info() -> (VideoInfo, word)` | Resolution, source formats and capabilities |
| `video.client_size(win: Window) -> (word, word, word)` | Client width, height, error |
| `video.blit8(win: Window, x: int, y: int, pixels: bytes, w: word, h: word) -> word` | Linear INDEX8 source, stride=w |
| `video.blit4(win: Window, x: int, y: int, pixels: bytes, w: word, h: word) -> word` | Packed source, stride=ceil(w/2) |

The wrapper validates that the view contains at least the required bytes, then the kernel validates the guest range again. A blit does not modify the source buffer; its lifetime must cover the blocking call. Clipping and conversion are native and split into bounded chunks.

**There is no `video.framebuffer()` in 0.1.** A buffer created with `bytes()` belongs to the app and appears on screen only after a blit. The internal tiled/packed format and UPIC framebuffer are not visible. No VIC registers, raster routines, hardware sprites or UPIC addresses in the ABI.

A future extension may return `{ptr, width, height, stride, format}` for a logical framebuffer, with explicit acquisition, damage/presentation and release. It may be an app surface in REU; it must not promise aliasing with physical scanout. Do not reserve a mapping or impose coherence costs today for this possibility.

### 2.3 Files

| Signature | Behavior |
|---|---|
| `fs.open(path: str, mode: word) -> (File, word)` | File relative to the app's data directory |
| `fs.read(file: File, dst: bytes) -> (dword, word)` | Bytes read and status; zero with success = EOF or an empty request |
| `fs.write(file: File, src: bytes) -> (dword, word)` | Confirmed bytes written and status |
| `fs.seek(file: File, position: dword) -> word` | Absolute position in the range 0…size, including EOF |
| `fs.tell(file: File) -> (dword, word)` | Current logical position |
| `fs.size(file: File) -> (dword, word)` | File size |
| `fs.close(file: File) -> word` | Releases the handle; check for backend errors |
| `fs.stat(path: str) -> (FileInfo, word)` | Type, attributes and available metadata |
| `fs.opendir(path: str) -> (Dir, word)` | Creates a listing in REU; `"."` denotes the app's data root |
| `fs.next(dir: Dir, name: bytes) -> (FileInfo, bool, word)` | One entry; bool=false with error=0 indicates the end of the listing |
| `fs.closedir(dir: Dir) -> word` | Frees the listing and invalidates the handle |
| `fs.mkdir(path: str) -> word` | Creates a directory without automatically creating ancestors |
| `fs.rename(old_path: str, new_path: str) -> word` | Renames within the app's root; an existing destination = EEXIST |
| `fs.remove(path: str) -> word` | Deletes a single file; a directory returns EISDIR |

Initial modes: READ=1, READ_WRITE=2, CREATE_NEW=3, CREATE_TRUNCATE=4. These are C-OS enums, **not UCI flags to forward without translation**. READ/READ_WRITE require an existing file; CREATE_NEW fails if it exists; CREATE_TRUNCATE creates or truncates. READ permits only reading; READ_WRITE, CREATE_NEW and CREATE_TRUNCATE guarantee both reading and writing. If the profile does not support combined access when opening, FILE_OPEN returns ENOTSUP before creating or truncating: no implicit reduction in the permissions of the requested mode.

Each read/write may return a count smaller than requested. The first implementation transfers at most one data block, initially 128 bytes: the program or a bytecode helper repeats the call. Do not allocate a local buffer the size requested by the app. An empty request returns zero without dereferencing the pointer, but still checks the handle.

`fs.seek` does not extend the file: it accepts only positions between zero and the verified known size, inclusive; beyond EOF it returns ERANGE without changing the cursor or file. A write may extend the file sequentially. Before sending each individual block, compute `position + chunk_length` with carry checking: if it exceeds `$FFFFFFFF`, return ERANGE with a zero count and no effects from that block, without shortening the transfer to make it fit. Blocks completed by previous calls remain valid.

Directories and metadata are part of the MVP; a full file picker, directory deletion, native copies of entire trees and mounting come later. A `read_exact`/`write_all` library can be written in C-Script using slices and loops, so it remains subject to fuel.

`fs.next` requires a name buffer of at least 256 bytes, reused on every call. The wrapper checks the view's u32 length and passes capacity 256 to the syscall, even for larger views, without truncating the length to u16. It writes `info.name_len` bytes and an additional NUL; use `text.view(name, dword(info.name_len))` for the text. At the end of the listing it returns a zero record and leaves the buffer unchanged. An insufficient buffer returns ERANGE without advancing the cursor.

Names are returned in full up to 255 bytes; an entry that cannot be addressed through the 127-byte path API, or contains non-ASCII bytes, has the NAME_UNADDRESSABLE flag. The interface may display it but must not open it using a truncated name. Names longer than 255 bytes cause EOVERFLOW when opening the listing, without publishing an incomplete listing.

### 2.4 SID

| Signature | Behavior |
|---|---|
| `sid.count() -> word` | Configured and available logical SIDs |
| `sid.open(index: word) -> (SID, word)` | Exclusive lease of an entire SID |
| `sid.close(chip: SID) -> word` | Silences and releases the chip |
| `sid.write(chip: SID, reg: byte, value: byte) -> word` | Validated register write |
| `sid.write_batch(chip: SID, pairs: bytes) -> word` | Register/value pairs, from 1 to 25 |
| `sid.note(chip: SID, voice: byte, note: byte, wave: byte, volume: byte) -> word` | Simple helper, MIDI notes 0…95 and voice 0…2 |
| `sid.off(chip: SID, voice: byte) -> word` | Lowers the voice gate |

`sid.note` is a bytecode library with a PAL frequency table generated on the development computer, not a new native synthesizer. It configures frequency, initial pulse width $0800, AD=$09, SR=$F0, gate and global volume. Allowed wave values: TRIANGLE=$10, SAW=$20, PULSE=$40, NOISE=$80; volume 0…15. For combinations and custom ADSR, use write_batch.

The lease is per chip, because the filter and volume are shared by its three voices. Do not promise isolation by simply assigning different voices to different processes. SID model, base address and count depend on the hardware profile; do not hardcode the device's theoretical maximum count into the language.

### 2.5 Ultimate Audio

| Signature | Behavior |
|---|---|
| `audio.count() -> word` | PCM channels available in the profile |
| `audio.open() -> (PCM, word)` | First free channel |
| `audio.play(ch: PCM, sample: bytes, hz: word, volume: byte, pan: byte, loop: bool) -> word` | Starts signed 8-bit PCM, entire sample; optional loop |
| `audio.stop(ch: PCM) -> word` | Stops hardware reads and releases the restriction on the sample |
| `audio.volume(ch: PCM, value: byte) -> word` | Volume 0…63 |
| `audio.pan(ch: PCM, value: byte) -> word` | 0…255, initial center 128 |
| `audio.state(ch: PCM) -> (word, word)` | 0 stopped / 1 playing, error |
| `audio.close(ch: PCM) -> word` | Stops and releases the channel |

Signed 8-bit PCM is the C-OS logical format. The driver must qualify encoding, rate, looping and pan on the backend: any conversions must be documented, rather than leaving sample semantics ambiguous. In 0.1, do not include compressed decoders, software mixing or streaming with interrupt callbacks.

`hz` is initially 1,000…32,000; the driver returns ERANGE outside this range. The actual frequency depends on the hardware divisor and is reported in tests. The source format does not expose the divisor. Samples must be nonempty, entirely within the owner's arena and have length ≤$FFFFFF.

`loop=true` repeats the entire sample. Loops with A/B points, variable rate and double buffering are later extensions; keep the first API small.

### 2.6 Ultimate information

| Signature | Behavior |
|---|---|
| `ultimate.info() -> (UltimateInfo, word)` | Profile, ABI version, capabilities and device counts |
| `ultimate.has(capability: word) -> bool` | Profile capability, without a new destructive probe |

Numbered capabilities: FILE_IO=0, FILE_SEEK=1, SID=2, PCM8=3, VIDEO_BLIT8=4, RTC=5, FILE_META=6, DIRECTORY=7, FILE_MUTATE=8, STORAGE_ENUM=9. Reserved for extensions: TCP_CLIENT=10, UDP_CLIENT=11, HTTP=12, HTTP_JSON=13, HTTPS=14; they remain zero in the MVP. `has(n)` reads bit n of UltimateInfo; unknown indices are false. UltimateInfo is the sole ABI source of capabilities; SYS_INFO.R4 remains reserved and zero.

A capability indicates a service implemented and qualified on the profile; it does not guarantee that media is inserted or that data is fresh. APIs report availability and operational errors. RTC is implemented through the DOS command described below; the widget uses uptime when the time is unavailable. No general `ultimate.command(raw_bytes)` pass-through: future functions will have typed services with resource and duration checks.

### 2.7 Storage

| Signature | Behavior |
|---|---|
| `storage.scan() -> (word, dword, word)` | Media count, listing generation, error |
| `storage.info(index: word, generation: dword) -> (StorageInfo, word)` | Reads a listing entry; outdated generation = ESTALE |

Initial enumeration of at most five media devices. Do not return a partial count as if the listing were complete: exceeding the limit returns EOVERFLOW. Scans are explicit, at boot or on refresh requests; no scan on every frame. Concurrent requests may share an ongoing scan. A previous listing remains valid until the new one is fully published; a scan error does not publish a partial table.

StorageInfo describes the SD/USB/other type, unit, observed presence, selection for C-OS and read-only status if known. It does not promise capacity or free space when the backend does not provide them. The ID is a diagnostic identifier and does not grant access to a volume: normal `fs` APIs always operate within the root assigned to the app.

### 2.8 Clock

| Signature | Behavior |
|---|---|
| `clock.now() -> (DateTime, word)` | Latest recent RTC sample; EAGAIN if refresh is pending |

Civil date/time in a fixed record. The kernel updates a shared cache at most once every 50 frames, in a low-priority UCI job. App calls read the cache; they do not multiply firmware requests. A sample older than 100 frames is not presented as current: return EAGAIN and request a refresh. No device returns ENODEV; a malformed response returns EIO. On EAGAIN/error, the wrapper returns a zero record.

The record reports the frame when it was acquired and whether the UTC offset is known. Without time-zone information, zero in the offset does not mean UTC. `system.frame()` remains the monotonic reference for timeouts and scheduling even if the RTC changes. Setting the time and NTP synchronization are later administrative services.

## 3 ABI for additional services

R0 always holds the status on return. Unless explicitly stated otherwise, outputs are zeroed on error and the destination buffer is unchanged. Core syscalls remain defined in SPEC.md.

| ID | Service | Input | Output |
|---|---|---|---|
| 20 | FILE_OPEN | P0=path, R1=length 1…127, R2=mode | R1=File |
| 21 | FILE_CLOSE | R0=File | Status |
| 22 | FILE_READ | R0=File, P0=dst, R1/R2=u32 length | R1/R2=bytes read |
| 23 | FILE_WRITE | R0=File, P0=src, R1/R2=u32 length | R1/R2=confirmed bytes |
| 24 | FILE_SEEK | R0=File, R1/R2=u32 position | Status |
| 25 | FILE_TELL | R0=File | R1/R2=position |
| 26 | FILE_SIZE | R0=File | R1/R2=size |
| 27 | FILE_STAT | P0=path, R1=length, P1=destination FileInfo | Status |
| 28 | DIR_OPEN | P0=path, R1=length | R1=Dir |
| 29 | DIR_NEXT | R0=Dir, P0=name, R1=capacity ≥256, P1=destination FileInfo | R1=1 entry / 0 end of listing |
| 2A | DIR_CLOSE | R0=Dir | Status |
| 2B | FILE_MKDIR | P0=path, R1=length | Status |
| 2C | FILE_RENAME | P0=old path, R1=length, P1=new path, R2=length | Status |
| 2D | FILE_REMOVE | P0=path, R1=length | Status |
| 40 | SID_OPEN | R1=logical index | R1=SID |
| 41 | SID_CLOSE | R0=SID | Status |
| 42 | SID_WRITE_BATCH | R0=SID, P0=pairs, R1=pair count 1…25 | Status |
| 43 | SID_GATE_OFF | R0=SID, R1=voice 0…2 | Status |
| 50 | AUDIO_OPEN | — | R1=PCM |
| 51 | AUDIO_CLOSE | R0=PCM | Status |
| 52 | AUDIO_PLAY | R0=PCM, P0=AudioDesc | Status |
| 53 | AUDIO_STOP | R0=PCM | Status |
| 54 | AUDIO_VOLUME | R0=PCM, R1=volume | Status |
| 55 | AUDIO_PAN | R0=PCM, R1=pan | Status |
| 56 | AUDIO_STATE | R0=PCM | R1=0/1 |
| 60 | VIDEO_INFO | P0=destination VideoInfo, 16 bytes | Status |
| 61 | VIDEO_CLIENT_SIZE | R0=Window | R1=width, R2=height |
| 70 | ULTIMATE_INFO | P0=destination UltimateInfo, 16 bytes | Status |
| 71 | CLOCK_NOW | P0=destination DateTime, 16 bytes | Status |
| 72 | STORAGE_SCAN | — | R1=count, R2/R3=generation low16/high16 |
| 73 | STORAGE_INFO | R1=index, R2/R3=generation, P0=destination StorageInfo | Status |

Each u32 R1/R2 pair is low16/high16; STORAGE explicitly uses R2/R3. In addition to core syscalls, ID 30 NUM_OP is defined in [NUMERICS.md](NUMERICS.md); it does not use UCI and is not a hardware capability. IDs not defined by any companion document or the core specification return ENOSYS; 80–8F are reserved for future networking and 90–9F for future HTTP, with no handlers in the MVP.

AudioDesc, 16 bytes: u24 sample pointer at 0; flags at 3 (bit0 loop); u32 length at 4; u16 hz at 8; u8 volume at 10; u8 pan at 11; four zero bytes at 12. Requirements and checks apply to the entire source, not just the first cache block.

VideoInfo, 16 bytes: u16 ABI at 0; u16 width/height at 2/4; u16 formats at 6 (bit0 BLIT4, bit1 BLIT8); u16 color count at 8 (=16); u16 flags at 10 (bit0 direct mapping, always zero in 0.1); four zero bytes at 12. No UPIC address or format.

UltimateInfo, 16 bytes: u16 ABI at 0; u32 capability bits at 2; u8 sid_count at 6; u8 pcm_count at 7; u16 timing_profile_id at 8; u16 hardware_profile_id at 10; u16 firmware_profile_id at 12; two zero bytes at 14. Profile IDs are manifest/report keys, not arbitrary interpretations of the firmware version string.

Handles of every type: a monotonic u16 counter per process incarnation, shared across Window/File/Dir/SID/PCM; the shell has its own counter. Zero is invalid and no ID is reused within the same incarnation. Every lookup uses the calling process's identity, incarnation, ID, type and live state: the same numeric value in two apps does not identify the same resource. Kernel records always check owner and type, even for handwritten bytecode.

Each incarnation therefore permits at most 65,535 handle creations. Once exhausted, its new opens return ENOSPC without consuming IDs belonging to other apps or the shell; resources already open continue to work. The app's counter restarts only after termination, complete cleanup and a fresh start with its context and initialized data restored. Continuations from the old incarnation must not deliver results to the new one. The shell's counter lasts for the system session; its exhaustion also fails without wrapping.

### 3.1 File, directory, storage and time records

DateTime, 16 bytes:

| Offset | Field |
|---|---|
| 0 | `year`, u16, 1…9999 |
| 2 | `month`, u8, 1…12 |
| 3 | `day`, u8, valid for the month/year |
| 4 | `hour`, u8, 0…23 |
| 5 | `minute`, u8, 0…59 |
| 6 | `second`, u8, 0…59 |
| 7 | `flags`, u8: bit0 VALID, bit1 OFFSET_KNOWN |
| 8 | `utc_offset_minutes`, i16; zero if unknown |
| 10 | Two reserved zero bytes |
| 12 | `sampled_frame`, u32; zero when the record represents a file timestamp |

FileInfo, 32 bytes: `kind` u8 at 0 (0 unknown, 1 file, 2 directory, 3 other); `attributes` u8 at 1 (READ_ONLY=1, HIDDEN=2, SYSTEM=4, ARCHIVE=8); `valid` u16 at 2 (SIZE=1, MODIFIED=2); `size` u32 at 4; `modified` DateTime at 8; `name_len` u16 at 24; `flags` u16 at 26 (NAME_UNADDRESSABLE=1); four zero bytes at 28. Fields without validity bits are zero and must not be interpreted as actual measurements. For `stat`, name_len is the length of the final component, zero for the root `"."`.

`fs.FILE=1`, `fs.DIRECTORY=2`, `fs.SIZE_VALID=1`, `fs.MODIFIED_VALID=2` and `fs.NAME_UNADDRESSABLE=1` are SDK constants. A directory listing does not automatically run stat on every entry: it normally contains type, attributes and name; size/date may remain unknown. Request stat when needed, for example on the selected entry.

StorageInfo, 16 bytes: `id` u16 at 0; `kind` u8 at 2 (1 SD, 2 USB, 3 other); `unit` u8 at 3; `flags` u16 at 4 (PRESENT=1, SELECTED=2, READ_ONLY=4, READY=8, READ_ONLY_KNOWN=16); two zero bytes at 6; `generation` u32 at 8; four zero bytes at 12. READY means the media was accessible during the scan, not that every future operation will succeed. IDs may be reused only with a new table generation.

Records returned by the wrapper are values copied into the caller's frame; they contain no pointers to kernel scratch space. DIR_NEXT validates all outputs, including the absence of overlap between the name and FileInfo, before copying and advancing. It also writes a zero FileInfo at the end of the listing. On error, memory outputs remain unchanged; the wrapper zeroes its own results, as with other syscalls.

## 4 Incremental UCI driver

UCI is a shared resource; the kernel owns the interface for the entire session. Existing libraries are protocol references, not code to import with their busy waits. Documentation describes FIFO, status/ack and DOS commands; some functions are marked untested. Verify the protocol and firmware at the revision used by the project. [UCI library manual](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/docs/UCILIB_MANUAL.md), [DOS interface](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/include/ultimate_dos_lib.h).

Minimal state machine:

```text
IDLE -> PREPARE -> SEND_CHUNK -> PUSH -> WAIT_RESPONSE
                                  -> DRAIN_DATA -> DRAIN_STATUS -> ACK
                                  -> COMPLETE / NEXT_STEP
any state -> TIMEOUT -> ABORT/DRAIN -> RECOVER or OFFLINE
```

Each visit performs at most a fixed number of FIFO accesses or a short poll, initially ≤32 bytes or a single status check. The actual limit must pass timing verification, rather than merely being a byte limit. PREPARE may require cache/DMA work and must be able to suspend without changing the registers of a transaction already in progress.

The arbiter serializes commands through the complete response, including status. No second process may consume data/status from the previous request. Do not perform read-modify-write on control registers that share an address with a read status register: use explicit command values.

Do not keep interrupts disabled while waiting for USB/SD/firmware. The raster retains priority; in v0.1, UCI service also runs outside the 200 active lines. The backend must verify that pauses between FIFO chunks are permitted.

Initial timeout: 250 PAL frames per command transaction, configurable per profile; use frame counter differences with correct wrap handling. The UI must remain responsive even if the app waits five seconds. A timeout does not authorize retrying a write: the external outcome may be uncertain.

Bounded recovery sends abort/drains according to the protocol. If it cannot reach a known state within a second configured limit, it marks the backend OFFLINE, fails pending requests and keeps the desktop/VM/video running. Do not perform a global Ultimate reset to recover a syscall.

Firmware commands that write directly into C64/REU RAM or load entire images are not the initial file service path. Before using them, demonstrate range control, coherence and acceptable timing interference. The baseline path uses FIFO and bounded kernel REU copies.

## 5 File handles, paths and concurrency

The reference DOS protocol exposes the currently open file and a current directory. Do not treat it as a table of independent file descriptors. C-OS logical files are virtualized over this state. [DOS operation declarations](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/include/ultimate_dos_lib.h).

Initial limits: four global userspace file handles, at most two per app, plus one handle reserved for the shell. Cold metadata and paths live in REU; keep only the active transaction context and necessary indices in local RAM. The kernel does not reserve 128 local bytes for each path.

For each handle, retain owner/generation, canonical path, mode, u32 position, state and known size. Before servicing a handle different from the physically open one:

1. Finish the previous transaction and close the physical file if necessary.
2. Select the correct directory/path without exposing a shared cwd to the app.
3. Reopen in a nondestructive mode: CREATE/TRUNCATE occur **only** on the first logical FILE_OPEN.
4. Restore the position with a verified seek.
5. Perform the single read/write, updating the position only from confirmed bytes.

Keeping the physical file open is a small optimization when ownership does not change. Use round-robin scheduling between complete block requests, without assigning the backend to an app for its handle's entire lifetime.

Seek and reopening without truncation are mandatory tests for the file milestone. If a firmware does not support them correctly, report the profile limitation: do not declare I/O concurrency complete or simulate independent handles over a single physical cursor.

Initial installation produces a data tree to copy to storage: `cos/apps/<id>` for each stable ID and `cos/.system` for the shell. The physical root is discovered or selected according to section 5.4; source code uses relative names such as `notes.txt`, not `/usb0/...`.

ASCII paths from 1 to 127 bytes, relative, without NUL, `..` components, backslashes or absolute prefixes; normalize separators and `.` before checking the root. A missing directory returns ENOENT. `"."` identifies the root for stat/opendir; root mutations are forbidden. Apps cannot change the global cwd. `mkdir` creates only the explicitly requested directory within this root.

The kernel serializes access to the same path: multiple readers are allowed; a writer excludes other handles to the same file while it remains open. Conflict = EBUSY. This protects C-OS apps from each other, not from changes made outside C-OS through the firmware menu or another computer.

READ may leave a valid prefix in the buffer and return `count>0` with an error; WRITE returns only bytes confirmed by the firmware. This is an explicit exception to the zero-output-on-error rule. A successful WRITE with `count>0` confirms exactly that prefix and advances by count; it does not promise to write the entire requested view. If the backend does not confirm the partial count after an error, the kernel must not infer it from the length sent: count remains zero for the uncertain block, even if the device may have written part of it. Timeout/reset or an error with indeterminate advancement invalidate the handle and require an explicit reopen. Do not automatically retry the uncertain portion; an error with a zero count does not prove that the file was left untouched.

FILE_CLOSE invalidates the handle even on a backend error. Success means that the close command completed, not a physical durability guarantee beyond those provided by the storage. Process termination must not send further app data after its kill; it completes only the necessary protocol and cleanup.

### 5.1 Desktop persistence

Two slots, `layout.0` and `layout.1`, in the `.system` directory. Each save writes the older slot, leaving the current valid one intact. It does not depend on atomic rename or new filesystem functions.

Format: 16-byte header and N records of 8 bytes, N≤12, exact total length `16+8*N`:

| Header offset | Field |
|---|---|
| 0 | Four ASCII bytes `COSL` |
| 4 | u16 version = 1 |
| 6 | N, u8 |
| 7 | Reserved, zero |
| 8 | u32 generation |
| 12 | u16 CRC16 |
| 14 | Two zero bytes |

Record: u16 object ID at 0; u8 type at 2 (1 launcher, 2 widget); u8 column at 3; u8 row at 4; u8 flags at 5 (initially zero); two zero bytes at 6. CRC16-CCITT-FALSE, polynomial $1021, init $FFFF, no reflection/final xor; computed over the whole file with the two CRC bytes treated as zero.

At boot, select the most recent valid slot using a modulo 2^32 comparison with distance <2^31. On a tie, prefer slot 0; ambiguous cases or two invalid files use the default. Unknown IDs, duplicates, coordinates outside the grid or collisions make the slot invalid in 0.1.

After writing and closing, reread and validate before considering the save complete. If storage disappears, keep the layout in RAM and report the error. Debounce for 50 frames after the last movement; a new change during a save marks another save pending without altering the buffer already sent.

### 5.2 Directory listings in REU

The reference protocol returns a sequence of packets with attributes and a name. The kernel must complete or cancel this command before using UCI for other commands; leaving a directory open while waiting for the app's next call would block other services. [DOS implementation: directories and stat](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/include/ultimate_dos_lib.c).

DIR_OPEN gathers the listing into a private kernel snapshot in REU, using bounded chunks. Once the response and status have been consumed, it publishes the Dir handle and releases UCI. DIR_NEXT reads only the snapshot; an app that does not iterate over it does not retain the firmware channel.

Initial limits: two global snapshots, at most one per process, each 16 KiB, up to 256 entries and names of at most 255 bytes. The byte limit may be reached before the entry limit. The 32 KiB come from the existing system reserve, at the addresses listed in SPEC.md; they are not additional local RAM.

Simple internal format: compact header, then 32-byte FileInfo records followed by name_len name bytes and zero padding to an even offset. The cursor retains the offset and index of the next entry. No userspace pointer table, per-entry allocation or sorting in the driver. The snapshot is not mapped directly to the app.

DIR_OPEN publishes only complete listings. Empty directory = success and the first DIR_NEXT returns bool=false. Exceeding a limit = EOVERFLOW, zero handle, snapshot freed and command drained/canceled before another operation. Do not consume space intended for the second snapshot. If no slot is free, return ENOSPC; if the app already owns a Dir, return EBUSY.

Collection follows the UCI engine's timeout and abort rules. VM, input and video make progress during collection; other UCI commands wait for the transaction to finish. The directory limit is visible in diagnostics and in the demo's message. Increasing it is a parameter to measure, not a reason to silently return the first entries as a complete listing.

Skip synthetic `.` and `..` entries. Convert attributes into the SDK format; preserve the exact name. FileInfo.valid must not mark size or modified when the packet does not contain them. A separate stat converts the timestamp format returned by the firmware without inventing a time zone.

The listing is a snapshot of the scan: after rename/create/remove, the app reopens it to refresh it. An old snapshot may still contain names that no longer exist; this does not prevent mutations. Do not guarantee an atomic snapshot with respect to changes made outside the system. Detected media removal or a root change, however, invalidates handles tied to that storage session.

### 5.3 Small, bounded mutations

Mkdir, rename and remove are part of the first file service. Validate all paths and reserve the transaction before any effects. On media known to be read-only, return EROFS; do not attempt writes to discover its status during a scan.

- Mkdir creates a single directory with existing ancestors. Existing destination = EEXIST.
- Rename operates within the same root, without replacing an existing destination. Both names are validated before sending; the root, moving a directory inside itself and crossing media are forbidden.
- Remove deletes a single file. Directories return EISDIR; no recursive deletion or wildcard expansion.
- Open files involved in the operation, or open files under a directory being renamed, cause EBUSY. A listing snapshot is not an open file and does not prevent changes.
- The driver does not automatically retry a mutation after a timeout with an uncertain outcome. It returns the error and requires the calling logic to reread the state.

Path comparisons and locks must also respect the backend's case aliases. For ASCII names on FAT storage, two case variants must not bypass a file lease. Retain the original name for display and a canonical key for locks. The profile must verify rename semantics without overwrite, rather than infer them from the command name.

Saving through a temporary file may use these primitives, but the SDK does not promise atomic replacement or disk durability. The shell layout retains the two-slot format from section 5.1.

### 5.4 Storage discovery and lifecycle

Use enumeration of roots visible to the firmware to discover USB/SD, rather than assuming `/usb0/` exists. The existing reference performs this scan through directory operations; it is not a new hardware device. The C-OS driver must do so through the incremental UCI engine. [Media scan helper](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/include/ultimate_dos_lib.c).

The system scan filters the directory stream directly into the small media table. It retains at most five media root paths in REU, each in 128 bytes including the terminator; C-OS suffixes are constructed separately. It does not require a third 16 KiB buffer and must be able to proceed even when both app snapshots are occupied. Candidates or paths beyond the limits cause EOVERFLOW, without truncation or partial publication.

In the manifest's discover mode, look for the `cos` directory and the `.cos-volume` marker file, produced by the installation tools with the exact ASCII content `COSDATA1\n`. The scan is read-only. A single valid candidate becomes the system root; multiple candidates require a selection in the shell or an explicit path in the manifest. Without a selected root, the desktop runs in RAM and file APIs return ENODEV.

The marker identifies a prepared directory, not a unique physical medium. Volume selection and initial creation of the data tree belong to the shell/installation tools; `storage.scan` run by an app neither changes the active root nor writes to any volume.

Publish the listing with a u32 generation. If the observed data is identical, the generation may remain unchanged; if it changes, increment it and reject old index/generation pairs with ESTALE. Do not wrap the counter: on exhaustion, return EOVERFLOW. A new scan error does not mean that the old listing is an up-to-date snapshot.

Keep this generation separate from the media session used by file/Dir handles. A scan with no changes must not invalidate open files. Detected removal, a root change or recovery that loses file context ends the session: old handles return ESTALE while still identifiable as revoked, or EBADF after cleanup. New handles have new IDs.

After media loss, do not automatically select another candidate or resume pending writes on it. The shell may reconnect/select the volume; apps must explicitly reopen files and handle the errors already received. Do not promise instant detection of a physical change occurring entirely between two observations: qualify what the firmware can detect.

Before directory, stat or scan operations that change the firmware's cwd, preserve logical cursors and close/invalidate the physical file binding when necessary. An app's next operation must still reopen its own correct path and restore its own offset.

### 5.5 RTC reads

The backend uses DOS GET_TIME `$26`, on the DOS target; the reference library reads a `yyyy/mm/dd hh:mm:ss` string. Do not use the separate RTC opcode on the Control target, documented by the library as unimplemented. [Time implementation](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/include/ultimate_time_lib.c), [UCI command table](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/docs/UCILIB_MANUAL.md).

Validate length, digits, separators and calendar date before publishing DateTime. A malformed response does not replace a valid sample with partial values. Record the acquisition frame when the sample is complete; publish the cache as a whole.

Start a refresh at boot once UCI is available. During operation, keep at most one refresh pending and service the clock at low priority. Unsupported response = RTC capability disabled for the profile; temporary unavailability or stale data = operational error, without altering the monotonic counter. A valid read does not certify that the clock is synchronized or correctly set by the user.

The widget distinguishes civil time from uptime. Do not write to the RTC to obtain a reading or set the date from the build date.

## 6 SID driver

The logical SID table comes from the verified profile: I/O base, model/frequency and availability. Reject ranges that overlap REU, UCI, the sampler or other active devices. The absence of a readable chip cannot be diagnosed through a simple read-back of write-only registers.

Writes are allowed to registers $00…$18 of the selected SID, at most 25 pairs. The kernel maintains shadow control registers for gate-off and cleanup; do not read a write register to reconstruct its value.

Validate all pairs before the first write. The maximum duration of 25 writes must be measured; if the batch does not fit in the available time, defer it as a whole. Do not present the batch as atomic with respect to the analog circuitry: writes arrive in the specified order.

On open, establish a known silent state. On close/kill, lower the gates, zero the volume and release the lease in the first safe time window. An app owning the chip also controls its filter and volume; other apps receive EBUSY. No userspace callbacks from audio IRQs.

C-Script example:

```text
import sid
import system

fn main() {
    let chip, err = sid.open(0)
    if err != 0 { return }
    sid.note(chip, 0, 60, sid.TRIANGLE, 10)
    system.sleep(20)
    sid.off(chip, 0)
    sid.close(chip)
}
```

## 7 Ultimate Audio driver and REU samples

The reference interface describes seven channels, 8-bit samples, maximum volume 63 and registers for address, length and rate. The code converts REU offsets into SDRAM addresses and writes some fields in big endian order. These details stay in the driver, not in the guest ABI. [Audio header](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/include/ultimate_audio_lib.h), [audio implementation](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/include/ultimate_audio_lib.c).

The profile must specify format, signedness, loop/start/stop bits, write order and divisor for each register. The reference detection routine changes channel state: if used, run it at boot before assigning resources, never in response to `audio.count()` during playback. Do not copy contradictory comments about bits or endianness without verifying the code and output.

A local reference for signed PCM and divisors already exists in `tools/generate_e1m1_audio.py` in the original C64 workspace, outside this repository, with unsigned→signed conversion and handling of the final sample. Examine it without modifying it; document the formula actually qualified in the C-OS profile, because the references do not all use the same rate approximation. STOP/CLOSE/cleanup must also set the volume to zero, rather than mistaking the end of reads for guaranteed silence at the output. Explicitly test holding of the final sample and one-shot completion.

The kernel translates the guest offset into an allowed hardware address; it does not allow an app descriptor to select another SDRAM bank. PLAY must not make the device read kernel data or another app's data.

### 7.1 Ownership, coherence and protection

To avoid a second copy of every sample, PLAY reads the sample already in the app's REU directly. The region is **write-protected for the entire duration of playback**:

1. Validate the entire range and the channel lease. When replacing a sample, validate the new one before stopping the old one, where possible.
2. Complete write-back of the affected dirty lines; invalidate any write permissions stored in cache metadata.
3. Record the read-only restriction, then program the channel in a safe window. Publish PLAYING only after a successful start.
4. LOAD, blits and FILE_WRITE with the sample as source remain allowed. A VM STORE into the sample causes a `READ_ONLY` fault; MEM_FILL/MEM_COPY/FILE_READ with an overlapping destination return EBUSY before any effects.
5. STOP/CLOSE/kill stop the hardware before releasing the restriction. One-shot completion is detected through bounded polling; only then is the region unlocked.

Multiple channels may read overlapping ranges from the same process; a region stays protected while at least one channel uses it. At most seven restriction records, associated with channels, without a general allocator in the kernel.

The STORE path without active samples must remain cheap: a per-process flag skips the additional check when the restriction count is zero. With active audio, the check's worst-case cost must be included in opcode timing bounds; do not introduce a path that ignores the restriction on a cache hit.

End-of-sample detection must not rely solely on a `length/hz` estimate if hardware can slow down, stop or loop. Qualify the actual completion condition. If it is unreliable, retain the restriction until explicit STOP and report this profile limitation.

An app fault from writing to its own sample triggers normal cleanup and must not leave hardware reading memory that is then reused. No concurrently writable ring buffer in the first API.

### 7.2 Timing

The sampler reads memory independently of VM code: verify its interference with REU DMA and scanout, rather than inferring zero cost because it executes no opcodes. The initial profile may publish fewer than seven channels if that is the only qualified count; report the limit and measurement.

Disable unnecessary sampler IRQs. All register writes are short and outside the active raster in the first version. The driver performs a single native hz→divisor conversion per PLAY, with measured worst-case cost and bounded duration; AudioDesc carries only hz. The conversion is part of job preparation and is not repeated during playback.

Example: signed square wave, 64 samples repeated at 8 kHz:

```text
import audio
import system

fn main() {
    let channel, err = audio.open()
    if err != 0 { return }
    let sample = bytes(64)
    for i in 0..sample.len {
        if i < 32 { sample[i] = 48 }
        else { sample[i] = 208 } // byte representing -48 in signed PCM
    }
    let play_error = audio.play(channel, sample, 8000, 16, 128, true)
    if play_error == 0 { system.sleep(50) }
    audio.stop(channel)
    audio.close(channel)
}
```

The program does not modify `sample` during PLAY. Sound continues when the VM yields its turn, because playback is handled by hardware.

## 8 Size and minimal implementation

Use the 512-byte staging area already allocated in the map; UCI, graphics and DMA reserve it explicitly, without retaining pointers to staging that another job can overwrite during suspension. A suspended request retains in REU any data that cannot remain in the reserved staging area.

Cold file metadata, directory snapshots and the profile live in the REU system reserve. Active continuations, audio leases and essential small shadow state must fit within the measured RAM budget. Generate the report with all drivers enabled as well: a build with services excluded does not demonstrate that the complete system fits in 20 KiB. Report the two 16 KiB directory buffers, storage metadata and 16-byte RTC cache separately; the latter may reside in REU if the local budget requires it.

Reuse the bounded-job engine for pixel conversion, copies, files and flushes. Avoid a separate queue or scheduler for each library. Wrappers, text formatting, SID tables and file helpers can be bytecode in app arenas.

The first delivery may implement services in stages, but the MVP release must contain the required bindings and drivers. Absent hardware and hardware not yet implemented are two different conditions that must be made explicit in the report.

## 9 Mandatory tests

1. Malformed values, handles, owners, lengths, descriptors and addresses; no writes outside the arena or unauthorized I/O.
2. VideoInfo without mapping; BLIT8 across 64 KiB, negative coordinates, cropping and odd X; comparison with expected pixels.
3. Two apps read and write distinct files with different cursors, alternating on every block; correct final checksums and sizes.
4. Reopening a CREATE_TRUNCATE file during switching without retruncation; conflict on the same path; read+write guaranteed by all three writable modes, or ENOTSUP before creating/truncating.
5. Partial reads/writes, EOF, exhausted space, removed storage, delayed response and timeout; no invented count for uncertain writes and no busy wait blocking the raster. Seek to EOF, beyond EOF and writes near the u32 limit, with ERANGE and no effects for the block that exceeds it.
6. Kill in every UCI state: no response delivered to another process or file, no retry of a write with an uncertain outcome.
7. Truncated layout file, incorrect CRC, duplicate IDs and collisions; recovery of the valid slot and use of defaults when necessary.
8. SID: contested lease, invalid batch without effects, gate-off/zero volume on kill, coherent shadow state.
9. PCM: data just written into cache, sample beyond 64 KiB, last valid address, attempted access beyond REU, unowned range, loop and one-shot.
10. CPU/native writes during audio pinning, overlap between channels and release only after the last stop; no altered samples or reads after arena reuse.
11. Verification of played audio: frequency/encoding, volume, pan and stop on the available backend; register logs alone do not prove sound output.
12. Combined VM/UI/UCI/PCM stress for ten minutes with a report of latency, deadlines, RAM usage, DMA traffic and app progress.
13. Empty directory, two simultaneous snapshots, byte/entry limits, a 255-byte name, an unaddressable name, a short name buffer and kill during collection; no partial handle and UCI available again.
14. Directory listing followed by file I/O at different positions: cwd and cursors must not contaminate each other. An unconsumed snapshot does not prevent other UCI operations.
15. Stat with known and unknown date/size; normalized attributes, valid timestamp and no invented time zone. A new scan after a change updates the listing.
16. Mkdir without ancestors, rename with an existing destination, locking even with different case, remove on a directory, attempts outside the root and mutation timeout without retry.
17. No storage, one candidate, multiple candidates, changed table, old generation, exceeded limits, a scan with both snapshots occupied, read-only media and disconnection during reads/writes; no automatic switch to another volume.
18. Valid RTC, absent RTC, malformed response, expired cache, backward change, crossing the system.frame wrap; all timeouts continue to use monotonic time.
19. Closed handle passed to wait/input_state after close/reopen; no event consumed from the new window. Input overflow, INPUT_RESET/BLUR, dragging outside the client area, Shift released before the key and global commands consumed by the shell; no key left stuck as held in the app.
20. Exhaustion of an app's 65,535 IDs without affecting new opens by other apps or the shell; cleanup and a new incarnation, with no inherited continuation or live handle.

Keep hardware source revisions, firmware version and settings alongside the results. Exposed capabilities must match what has been implemented and verified in the profile, not the firmware's maximum feature list.

## 10 Extensions after the MVP

This roadmap prepares later work without requiring new resident drivers in the first build. Signatures are proposals for C-Script; records, specific error codes and ID assignments will be frozen after backend testing. Importing `net` or `http` in the MVP must produce a clear compilation error, without stubs that pretend to succeed.

### 10.1 N1: TCP/UDP clients

First proposed APIs: `net.connect(host, port, timeout)`, `net.udp(host, port)`, `net.read(socket, dst, timeout)`, `net.write(socket, src, timeout)`, `net.close(socket)` and `net.info()`. Kernel Socket handles; two sockets per app and four globally as initial limits to measure. DNS/connect and transfers must have timeouts and cleanup paths; data is held in binary buffers with lengths, even when it contains NUL.

The firmware exposes TCP/UDP clients; legacy listener commands must not be considered available without checking the target firmware's dispatcher. [Network APIs and documented limits](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/docs/UCILIB_MANUAL.md#13-network-functions).

TCP returns partial counts, distinguishes timeout from EOF and preserves accepted bytes on partial errors. For UDP, define a separate datagram API if the firmware preserves boundaries and metadata: do not invent datagram semantics over a plain byte sequence. Qualify this point before freezing the signatures.

N1 gate: verify waits for DNS/connect/read, abort and recovery behavior, actual socket release on kill and interference with file I/O. A service that is asynchronous with respect to the VM may still occupy all of UCI for seconds: also measure the delay imposed on other requests, not just raster continuity.

Acceptance examples: a text client to a local server, binary transfer with NUL and timeout; a UDP NTP request as a later demo, without automatically writing to the RTC. TCP server services and global IP configuration remain separate.

### 10.2 N2: HTTP and JSON in firmware

The HTTP target in firmware v3.15a source handles headers, bodies, exchanges and JSON structures; the reference wrappers are marked as not yet tested on hardware. [HTTP firmware source](https://github.com/GideonZ/1541ultimate/blob/v3.15a/software/io/command_interface/http_target.cc), [wrapper status](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/include/ultimate_http_lib.h).

Initial proposed APIs: `http.get(url, timeout)`, `http.read(response, dst)`, `http.status(response)`, `http.close(response)`. Add headers and POST only after the binary GET path. For JSON responses: `http.json_int(response, path)` and `http.json_text(response, path, dst)`, with output in caller buffers, checked types and no implicit allocation per field.

This may reduce VM work by delegating parsing and HTTP handling to the firmware. It does not require C-Script to introduce dynamic objects. Proposed initial limits: one UCI exchange at a time, one live response per app, URL/header length and response size bounded by the kernel before and during transfer.

The kernel owns all firmware header/body handles, including temporary responses and error paths. A global call such as FREE_ALL must not be used to clean up a single app. Release only its handles; verify that timeout/abort do not leave unreachable objects in the firmware.

N2 gate: text/binary GET and JSON, malformed response, body beyond quota, disconnection, cleanup, latency of other UCI services and CPU/RAM measurements. The shared UCI backend is a dependency, not the prior implementation of N1 sockets: if qualified, HTTP may be developed without writing an HTTP stack over TCP in the VM.

HTTPS has a distinct capability. Enable it only after verifying actual support and TLS authentication, including the certificate chain and hostname; do not accept https URLs by downgrading them to http. Document redirects and firmware limits before exposing them as guaranteed behavior.

### 10.3 Other APIs and shell responsibilities

Programmable palette: useful especially with future fullscreen support. The kernel must save/restore the palette, protect the shell's five colors and manage global ownership before allowing apps to change it.

Disk image mount/unmount, drive information and SoftIEC: candidates for Commodore utilities, with drive leases and an explicit impact on files in use. The documented SoftIEC UCI path concerns the Ultimate's virtual drive; it is not equivalent to a driver for every physical IEC peripheral. [UCI functions and coverage](https://github.com/xahmol/ultimate-uci-oscar64/blob/main/docs/UCILIB_MANUAL.md).

Global configuration, IP/time changes, freeze, reboot and full REU loading/saving remain administrative shell services. Loading a REU while C-OS uses it also overwrites kernel backing, surfaces and processes: it requires a real exit/restore protocol, not a normal app syscall.
