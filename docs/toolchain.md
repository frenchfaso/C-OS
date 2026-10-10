# M1 host VM and bytecode tools

The ABI 1 host tools implement all four-byte instructions in SPEC.md §8. The
single table in `src/isa.rs` supplies opcode numbers, mnemonic lookup, operand
forms, encoding, decoding, and disassembly. Rust runs on the development host;
this delivery does not contain the M2 native interpreter.

Use the Rust version in `rust-toolchain.toml` and the checked-in Cargo.lock:

```sh
cargo build --locked --release
cargo test --locked --workspace
cargo clippy --locked --all-targets -- -D warnings
python3 scripts/check_m1.py
```

`scripts/check_m1.py` checks the complete CLI pipeline, expected application
results, traces, and repeat-build byte identity.

After the first dependency fetch, append `--offline` to Cargo commands to check
that the existing lockfile and cache suffice. Only serde and serde_json are
runtime dependencies, for the normative host-only JSON object and manifest.

## Assemble, link, disassemble, execute

Run these commands from the repository root:

```sh
cargo run --locked --release --bin cosasm -- apps/linear.casm -o build/linear.cobj
cargo run --locked --release --bin cosasm -- apps/calls.casm -o build/calls.cobj
cargo run --locked --release --bin cosasm -- apps/spin.casm -o build/spin.cobj
cargo run --locked --release --bin cospack -- manifests/m1.json --out build/m1
cargo run --locked --release --bin cosdis -- build/linear.cobj
cargo run --locked --release --bin cosdis -- build/m1.manifest.json --app Linear
cargo run --locked --release --bin cosrun -- build/m1.manifest.json --app Linear --fuel 3 --trace build/linear.trace.jsonl
cargo run --locked --release --bin cosrun -- build/m1.manifest.json --app Calls --fuel 3
cargo run --locked --release --bin cosrun -- build/m1.manifest.json --app Spin --fuel 3 --slices 10
```

Linear resolves a pointer in initialized data, then stores and loads a word at
$04FFFF, crossing into $050000. It exits with R2=R3=$ABCD, eight retired opcodes,
and its original SP. Calls leaves R2=42, retires fourteen opcodes, and restores
SP across two nested calls and integer/pointer pushes. Spin contains no yield:
ten slices of three opcodes retire thirty instructions, leave R2=15, and stop
the host runner at its explicit slice limit (exit status 2). SliceLimit denotes
an intentionally bounded run, not a terminated guest or successful PROC_EXIT.

Object disassembly marks relocation placeholders. Linked disassembly shows the
actual physical addresses. The JSONL trace records architectural state at VM
boundaries; it can later be compared with M2. These host outcomes and model frame
counts are semantic results, not C64 timing measurements.

## Assembly source

The small `.casm` grammar is an implementation choice for M1; it does not change
the ISA or C-Script. Names are case-sensitive ASCII identifiers. Instructions
and registers are case-insensitive; directives are lowercase. `;` and `//`
start comments. Labels end with `:` and may precede an instruction. Operands use
commas. Numeric literals are decimal, `0x` hexadecimal, or `$` hexadecimal.
Expressions are one number, or a name optionally followed by one numeric `+`/`-` addend.
Constant definitions may refer forward to other constants; cycles are errors.

| Directive | Meaning |
|---|---|
| `.entry label` | Required aligned code entry label |
| `.code`, `.data`, `.bss` | Select the section; the initial section is code |
| `.const NAME = expression` | Integer constant; no label/physical pointer evaluation |
| `.byte values`, `.word values` | Unsigned initialized data, packed little endian |
| `.ptr values` | 24-bit values or ABS24 section references in initialized data |
| `.space size` | Zero initialized data or BSS length; unavailable in code |
| `.align power_of_two` | Data/BSS padding; unavailable in code |

Ordinary register operands follow the table in SPEC.md §8.3. Examples:

```text
LD16 R2, P1, 0
STP P2, P1, 3
PMAKE P0, R2, R3
PLI1 buffer+12
PLI P1, buffer+12
BEQ R0, R1, label
BEQ R0, R1, -2
SYSCALL $01
TRAP $1002
```

`PLI Pn, value` is an assembler alias for PLIn. A numeric branch operand is a
signed displacement in instructions; a label operand creates REL16_INSN.
LDI/ADDI accept −32768…65535 as raw 16-bit bits; memory offsets accept
0…65535, and shift counts 0…15. Useful diagnostics include file, line, and
column. Unknown syntax, nonexistent registers, unused operands, undefined
symbols, and malformed data are rejected.

## COSOBJ1 and the static pack

The JSON object declares `format="COSOBJ1"`, ABI 1, the assembler version,
`numeric_profile="COS-NUM-1"`, code/data arrays, BSS length, section symbols,
entry, relocations, and code-relative source locations. Labels retain
`{section, offset}` during parsing; physical pointer values are assigned only
when linking to the manifest's arena. Unknown JSON fields are rejected.

ABS24 relocations identify the three operand bytes (or a `.ptr` data field).
REL16_INSN identifies the aligned four-byte branch instruction; its target is
another code section reference plus a byte addend. Linking checks patch/target
bounds, overlapping patches, 24-bit arithmetic, signed displacement range,
code alignment, and all static jump/call/branch targets. BSS contains no patch
bytes. Registers and reserved fields are validated independently of relocation.

`cospack` takes paths relative to `--root` (default: repository root). Absolute
paths, traversal, and symlinks escaping that root are rejected. The manifest
accepts zero through four apps with distinct stable IDs 1…65535 and names of
1…15 printable ASCII bytes. Arena ownership is physical and shared: all apps
live in the single $040000…$FFFFFF allocation area, following the 256 KiB system
reservation. Section starts, arena sizes, heaps, and stacks obey the alignment
and minimum-size rules. Alignment gaps are absent from executable code and
initialization lengths.

Code begins at arena_first. Data, BSS, and heap start on 128-byte boundaries in
that order; the stack occupies the top of the arena. Bounds are inclusive;
empty data/BSS retain an explicit start and length zero. The 16 MiB image
contains COSREU01, a reproducible build tag, ABI, app count, linked code, and
initialized data. The initialized-data restoration seeds occupy $000080 up to
$00FFFF; exceeding their capacity fails before publication. This pack contains
no resident kernel image or native bootstrap and must not be presented as a
bootable OS pack. The future native pack needs explicit sharing of that seed
area with kernel images and boot assets.

Generated files:

| Output | Contents |
|---|---|
| `build/*.cobj`, `*.lst`, `*.map.json` | Relocatable object, listing, and source locations |
| `build/m1.reu` | Exactly 16,777,216 shared physical REU bytes |
| `build/m1.manifest.json` | Linked bounds, entry, seeds, symbols, source map, build tag |
| `build/m1.asm` | Kick Assembler constants for static native descriptors |
| `build/m1.map.txt` | Actual code/data/BSS/heap/stack placement and sizes |
| `build/m1.data/cos/` | `.cos-volume` (`COSDATA1\n`), `.system/`, `apps/<id>/` |

The manifest is published after all companion writes succeed. Output files use
atomic rename individually; replacing a set in an interrupted build is not a
filesystem transaction. The runner rejects mismatched image/header/build tags
and validates linked bounds before accessing memory. The build tag is FNV-1a
over the normalized input and object bytes, including source-map filenames;
it is a pairing check, not a signature. Use relative source paths for builds
that reproduce across machines. An explicit decimal tag is available with
`--build-tag U32` for pairing with a native diagnostic program.

The initial discover installation uses `cos/.cos-volume`. Explicit storage
configuration declares a known absolute root; neither variant performs storage
I/O on the target at M1. An empty pack is reproducible with:

```sh
cargo run --locked --release --bin cospack -- manifests/empty.json --out build/empty
```

## Implemented and later deliverables

Implemented: shared full ISA; validating assembler/disassembler; section labels
and constants; ABS24/REL16_INSN; static pack construction and bounds validation;
independent expected encoding vectors; malformed input tests; arena/seed
capacity tests; minimal executable assembly programs; host reference VM and
its deterministic syscall harness.

The harness implements the core operations documented in `docs/host-vm.md`.
Other SDK operations return ENOTSUP when their ID is known and ENOSYS for an
unknown ID. No device capability is invented. Numeric profile/ABI declarations
preserve compatibility; they do not claim a float backend exists.

Deferred: native VM/cache/dispatcher (M2), target scheduler (M3), C-Script and
its frame reports/runtime library (M4a), float24/float32 numeric backends (M4b),
UI/storage/audio SDK services (M5/M6), native bootstrap/resident segment
packaging, and advanced bundling. Hand assembly reports section sizes and
assigned stack/heap, with no compiler frames or SDK imports. Existing maps and
boundary traces provide the immediate comparison interface for M2.
