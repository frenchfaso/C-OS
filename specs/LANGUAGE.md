# C-Script: the C-OS userspace language

Specification 0.1, revision 4 — 10 October 2026. Normative companion to [SPEC.md](SPEC.md). Project name: **C-Script**; source extension `.cos`.

The goal is the simplicity of a small BASIC, with functions, local variables, blocks, and syntax familiar to JavaScript or Lua users. C-Script is compiled on the development computer directly into C-OS bytecode. Only the assembly VM runs on the C64: no parser, language interpreter, JIT, or additional dynamic runtime.

## 1 First-version scope

Included: variables with local type inference, 8/16/32-bit integers, float24 and float32, booleans, functions, conditionals, loops, linear byte arrays, text/buffer views, and SDK modules. The compiler is part of the MVP, although it follows the basic VM tests. [NUMERICS.md](NUMERICS.md) defines formats, rounding, conversions, backends, and numeric tests.

Excluded: dynamic objects, classes, metatables, closures, language coroutines, exceptions, eval, generics, float16, double, garbage collection, dynamic module loading, and on-device compilation. Do not promise source compatibility with JS, Lua, Python, or Ruby.

A loop without yield remains preemptible. The compiler must not rely on inserted cooperation points as the sole defense against CPU monopolization: the VM dispatcher consumes fuel for every executed opcode, including those inside generated libraries.

## 2 Language overview

```text
import ui
import system
import text

fn main() {
    let win, err = ui.open("Counter", 240, 152)
    if err != 0 { return }

    let count: long = 0
    let buffer = bytes(12)

    while true {
        let event, wait_error = ui.wait(win, 1)
        if wait_error == 0 && event.kind == ui.CLOSE_REQUEST {
            break
        }

        count = count + 1
        ui.fill(win, 8, 8, 120, 8, ui.WHITE)
        ui.text(win, 8, 8, text.decimal(buffer, count), ui.BLACK, ui.WHITE)
        ui.present(win)
    }

    ui.close(win)
}
```

This source is a normative example of the syntax and bindings to implement; it is not code that has already been compiled. Each loop iteration redraws a small area. `ui.wait` and `ui.present` can suspend this process without suspending the others. The buffer is allocated only once.

## 3 Lexical rules and blocks

- UTF-8 files; case-sensitive ASCII identifiers: letters, digits, and underscores, with no leading digit.
- `//` comments run to the end of the line. Nested comments are not required.
- Blocks use `{` and `}`; indentation is not significant.
- A newline terminates a simple statement, except inside `()`/`[]` or after an operator that requires an operand. A semicolon is an alternative explicit separator.
- Decimal and `0x` hexadecimal integers; underscores only between digits. Fractional literals such as `0.5`, `1.0`, and `1e-3`, at most 128 bytes per token; a decimal point, when present, requires digits on both sides. `1..10` remains an integer range.
- Double-quoted strings; escapes `\n`, `\r`, `\t`, `\"`, `\\`, `\xNN`.
- Non-ASCII text bytes must use explicit escapes in version 0.1. The UI displays only the glyphs specified in the main specification.
- Reserved words: `import`, `fn`, `let`, `const`, `if`, `else`, `while`, `for`, `in`, `break`, `continue`, `return`, `true`, `false`, and primitive type names.

Calls are expressions. A call used as a statement may discard its results; the compiler warns about ignored error results from I/O services. Acceptance-test sources must handle every error that could cause data loss.

## 4 Types and representation

| Type | Representation | Use |
|---|---|---|
| `bool` | One byte, 0/1 only | Conditions |
| `byte` | u8 | Pixels, data, SID registers |
| `word` | u16 | Small counts, flags, error codes |
| `int` | i16 | Default integer, coordinates |
| `dword` | u32 | Sizes, large indices, file positions |
| `long` | i32 | Larger integer calculations |
| `float24` | 3 bytes, 16 significant bits | Compact fractional calculations and data, about 4–5 digits |
| `float32`, `float` | 4 bytes, 24 significant bits | Fractional calculations with about 6–7 digits; float is an alias |
| `bytes` | u24 pointer + u32 length, 7 bytes | Mutable byte view |
| `str` | u24 pointer + u32 length, 7 bytes | Read-only text view |
| `Window`, `File`, `Dir`, `SID`, `PCM` | u16 handles, distinct types | Kernel resources |
| SDK records | Fixed fields and declared layout | InputState 8 bytes; Event/DateTime/StorageInfo 16 bytes; FileInfo 32 bytes |

All multibyte fields in guest memory are little endian and packed; there is no implicit padding. A driver's hardware ABI may differ, and the kernel is responsible for conversion.

SDK records are values with readable fields, including nested fields such as `info.modified.year`; they cannot be modified by passing pointers to their internal fields. Multiple results such as `(FileInfo, bool, word)` reside in the caller's static result block and require no heap allocations. A directory entry's name is written into an app-supplied buffer and is not a temporary pointer inside FileInfo.

In Event, `arg0` and `arg1` have type `int`: negative client coordinates can be read directly, without a cast from word. `arg2` remains word. InputState and the `ui.input_state` binding are defined in the SDK; the record allows the state to be read again after INPUT_RESET without introducing handles or allocations.

Handles cannot be added or converted to pointers. Zero denotes an invalid handle in error outputs. Opaque types cannot be constructed from an integer in the language; the VM still checks ownership and validity for hand-written bytecode.

The language exposes no native pointers, register addresses, or `peek/poke`. Buffer views use the VM's linear 24-bit pointers. 32-bit lengths and indices prevent buffers from being truncated at 64 KiB.

### 4.1 Inference and conversions

`let x = 12` creates a mutable `int`. `let x: word = 12` specifies an explicit type. `const` requires an expression that can be evaluated at compile time and does not allow reassignment. A variable's type does not change after initialization; uninitialized variables are not allowed.

Inference proceeds from the bottom up through the expression tree. A **direct literal** is a numeric token, optionally enclosed only by parentheses and unary minus; its exact value includes the sign before range checking. Constant names, casts, and subexpressions with binary operators are already typed and are not direct literals. An outer context does not change the types of their parts.

A declaration, assignment, parameter, or expected result may supply a type for a direct literal; the same applies to a cast applied directly to the literal. An integer literal required as an integer must be representable. With no context, its type is `int` if possible, otherwise `long`, otherwise `dword`; a value that fits none of these types is an error. This correctly includes −32,768 and −2,147,483,648 and rejects negative values below the minimum long value. Fractional literals without a context are float32; a float24 context rounds them directly to that format according to NUMERICS.md §3. A fractional literal does not implicitly acquire an integer type.

For a binary operator, first type the operands that are not direct literals. If exactly one operand is a direct literal and the other is a typed number, try the other's type: an integer adopts it if representable; a float format accepts the numeric literal with its own rounding. Otherwise, the literal takes its type without context, and ordinary conversions are considered. If both are direct literals, both take their types without context. This rule also applies to for-loop bounds; shifts follow the separate rule below. The expected type outside the operator is not propagated into its operands.

Implicit conversions are allowed only when they preserve all values: byte→word/dword/int/long, word→dword/long, int→long; also byte/word/int→float24/float32 and float24→float32. The common type of two integers is the integer type with the smallest range that contains all values of both types. If none exists, the operation requires an explicit cast; do not choose a float as a fallback. The rule is the same for all five integer types: byte+byte produces byte, byte+int produces int, byte+word produces word, int+word produces long, word+dword produces dword; int+dword and long+dword are errors. Long/dword→float and float32→float24 require a cast.

The casts `byte(x)`, `word(x)`, `int(x)`, `dword(x)`, and `long(x)` are checked: an out-of-range constant is a compile-time error; an out-of-range runtime value causes a `RANGE` fault. When applied to a direct fractional literal, an integer cast first types the literal as float32, then performs the conversion; it neither interprets the decimal as an integer nor skips float32 rounding. To retain only the low bits, explicitly mask before casting. Handles and views do not support these casts.

Float-to-integer conversions truncate toward zero, then check the range; `int(-3.75)` is −3. The casts `float24(x)`, `float32(x)`, and `float(x)` apply RNE to the destination format. They do not retype the operands of an already typed expression. Full rules, including overflow and underflow, are in NUMERICS.md.

A float context does not transform an integer-only expression: `float24(1 / 2)` and `let x: float24 = 1 / 2` are zero. It can, however, determine the format of a direct literal, as in `let x: float24 = (-0.5)` or `let x: float24 = 2`. The following consequences are normative:

| Expression, with `a24: float24` | Type and behavior |
|---|---|
| `let x: float24 = 1.0 + 2.0` | Error: the sum is float32 and requires a narrowing cast |
| `float24(1.0 + 2.0)` | float32 sum, followed by RNE conversion to float24 |
| `a24 + (1.0 + 2.0)` | Inner sum is float32; outer result is float32 |
| `a24 + 1.0` | The direct literal takes type float24; float24 sum |
| `float24(1.0) + 2.0` | First operand is already float24; float24 sum |

### 4.2 Operators

Precedence order, from lowest to highest: `||`, `&&`, `|`, `^`, `&`, `== !=`, `< <= > >=`, `<< >>`, `+ -`, `* / %`, unary `! ~ -`, call/index/field. Binary operators are left-associative; assignment is a statement, not an expression. Do not include `++`, `--`, or compound assignments in the MVP.

`&&` and `||` evaluate from the left and stop as soon as the result is known. Conditions require `bool`; use `x != 0`, not implicit truthy/falsy conversions of strings or handles.

The operands of all expressions are evaluated from left to right, except for the short-circuit evaluation just described. For an indexed assignment, evaluate the view and index, check the bounds, then evaluate the value to write; each expression is evaluated exactly once.

| Operators | Allowed types and result |
|---|---|
| `+ - * /`, unary minus | Integers or floats; binary operations use the common type, unary operations use the operand's type |
| `%`, `&`, `|`, `^`, `~` | Integers only; common type for binary operators, operand's type for `~` |
| `<< >>` | Integer left operand; independent integer count; result has the left operand's type |
| `< <= > >=` | Only numbers convertible to a common type; bool result |
| `== !=` | Numbers with a common type, two bools, or two handles of the same nominal type; bool result |
| `!`, `&&`, `||` | bool only; bool result |

str/bytes views and records have neither implicit equality nor arithmetic operators. Handles do not support ordering comparisons or comparisons with integers. In numeric comparisons, the common type applies to the operands, while the result is always bool. Shifts do not promote the left operand to the count's type; check the count in its own type before narrowing it.

Integer arithmetic has fixed width, wrapping modulo 2^N for addition, subtraction, multiplication, and negation. Signed division truncates toward zero; the remainder has the dividend's sign. Division by zero causes a fault; MIN / -1 returns MIN for consistency with wrapping. Shifts accept only counts 0…N−1; otherwise, they fault. `>>` is arithmetic for signed types and logical for unsigned types.

The compiler lowers multiplication/division and 32-bit operations to VM sequences or small bytecode routines. These routines consume fuel; no software multiplication may become an unbounded native job. The 16-bit case uses R directly where possible.

This rule applies to integers. Float arithmetic uses NUM_OP, the bounded native service described in NUMERICS.md. Float24 and float32 support `+ - * /`, negation, and boolean comparisons; `%`, bitwise operators, and shifts remain integer-only. `1 / 2` is zero, `1.0 / 2.0` is 0.5. Mixed operations between the two float types produce float32; each operation rounds to its own result type. A literal with no fixed type next to a float24 operand adopts float24, avoiding unintended promotion.

Size, allocation, bounds, and address checks use wide arithmetic with overflow detection: they do **not** inherit the wrapping behavior of the app's numeric arithmetic.

## 5 Variables and control flow

Block lexical scope, with no mutable global variables in 0.1. Global constants are allowed. A duplicate declaration in the same scope is an error; warn about shadowing to prevent simple mistakes.

```text
const LIMIT = 100

fn sum_to(limit: int) -> int {
    let result = 0
    for i in 0..limit {
        result = result + i
    }
    return result
}
```

`for name in start..end` excludes `end`, evaluates the bounds once, and advances by one. The iteration variable is local and cannot be assigned within the body. Bounds have the same integer type after conversion; `end <= start` gives zero iterations. The loop termination check precedes any increment that could overflow. Use `while` for other step sizes.

`break` and `continue` apply to the innermost loop. `if/else if/else` and `while` require blocks. There is no `goto` in the source language.

## 6 Functions and results

Parameters are always typed; an omitted result means no result. Examples: `fn twice(x: int) -> int`, `fn divide(a: int, b: int) -> (int, word)`.

The number and types of results are static. `return a, b` and `let value, err = call()` do not create a tuple object on the heap. Use `_` to explicitly discard a result. A single value cannot implicitly receive the first element of a multiple result.

Arguments are evaluated from left to right before the call. Parameters are passed by value; passing a view copies its seven bytes, not the buffer. Results must be defined on every path through a function that returns values. Forward calls are resolved at compile time.

Recursion and nested calls are allowed with explicit signatures and a bounded app stack; stack overflow is a process fault. There is no implicit recursion in the kernel and no promise of tail-call optimization. Each app has exactly one `fn main()` with no arguments or results in the entry module declared to the compiler; its return terminates the process with code zero. Imported library modules do not declare main or introduce other entry points.

### 6.1 C-Script calling ABI

This is a compiler convention over the VM's CALL/RET, distinct from syscalls:

1. The caller prepares packed arguments and space for results in its own frame on the guest stack.
2. P0 points to the argument block, P1 to the result block; zero if the respective block is empty. P2 holds the caller's frame pointer.
3. CALL saves the return PC according to the ISA. The prologue saves the old P2 with PUSHP, reserves a statically sized frame with bounds checking, and sets P2 to its first byte.
4. The pointers to the argument/result blocks are saved in the frame before P0/P1 are reused. The caller's frames remain live throughout the call.
5. The callee writes results into the prepared block. The epilogue releases its own frame, restores P2, and uses RET. SP returns to exactly its value before CALL.

R0–R7 and P0/P1/P3 are caller-saved. P2 is preserved by the C-Script convention, not by CALL itself. Live values must be saved in frames; do not rely on registers that a callee happens to leave unchanged.

Initial compilation limits: frame ≤4,096 bytes, argument block ≤255 bytes, results ≤64 bytes. Large records and arrays are passed through views. The compiler reports each frame's size; the manifest assigns a separate stack, initially 16 KiB per app, included in the arena budget.

Syscalls preserve registers according to SPEC.md; SDK wrappers translate results and status into the language contract. Every wrapper preserves P2 according to the C-Script ABI even when a syscall, such as MEM_INFO, uses it for an output: save the frame pointer before invocation, copy the outputs, and restore it before returning. Bytecode helpers follow the C-Script ABI, with no app-specific assembly entry points.

The compiler generates `_cos_start`: it saves the initial bounds in private app runtime data, initializes the allocator, prepares P0/P1/P2 for a call with no arguments, calls `main`, and finally invokes PROC_EXIT(0). Do not call `main` directly using the kernel entry convention, which assigns different meanings to P0…P3. Runtime data does not introduce mutable global variables into the source language.

## 7 Linear buffers and memory

```text
fn main() {
    let data = bytes(200000)
    data[70000] = 42
    data[199999] = data[70000]

    for i in 0..data.len {
        data[i] = byte(i & 15)
    }
}
```

This program must work without bank switching and with indices beyond 65,535. `.len` is always `dword`, even for a small buffer. Indexing accepts nonnegative integers; before adding to the pointer, it checks `index < len`. Negative signed indices cause a `BOUNDS` fault.

`bytes(n)` uses the app's bump allocator and returns a zeroed buffer. Zeroing uses MEM_FILL in bounded chunks. There must be no observable difference between diagnostic and normal builds; raw uninitialized heap memory remains a VM detail. Zero length is allowed and must cause no REU access.

An allocation beyond the heap or an overflow causes an `OUT_OF_MEMORY` fault. Arenas do not grow automatically. There is no `free`: allocate working buffers at startup and reuse them. The compiler warns about allocations inside loops as a potential issue, without forbidding them. The monitor shows the heap high-water mark.

The allocator also tracks remaining bytes with a 32-bit value. When it consumes the last byte at $FFFFFF, it marks the heap as exhausted without needing to represent $1000000 in a pointer. The empty case may use the canonical view `{ptr=0, len=0}`; none of its operations dereference zero.

`data.slice(start, length)` creates a view without copying or allocating. It checks `start <= data.len` and `length <= data.len - start` using wide arithmetic; an empty slice does not require representing the pointer one byte past $FFFFFF. Do not expose an operation that converts the view into an arbitrary integer/pointer.

Buffers are byte arrays in 0.1. Generic arrays and user-defined structures may come later; the SDK's fixed records are sufficient for events. Do not introduce dynamic containers for every file or video access.

## 8 Text

`str` is a read-only view, not a reference-counted object. String literals reside in the app's static data. Version 0.1 includes no concatenation operator, even for constant strings; text is assembled explicitly in a reusable buffer using text.copy and slices, then exposed with text.view.

`text.view(buffer, length)` produces a view of the buffer's first bytes, with bounds checking; if the buffer changes, the text observed through the view changes. Its lifetime does not exceed that of the process. It must not return references to stack temporaries.

A str exposes `.len: dword`, indexed reads `value[index] -> byte`, and `value.slice(start, length) -> str`. Indices, bounds, wide arithmetic, and empty slices follow the same rules as bytes; negative signed indices cause BOUNDS. None of these operations allocate or require new syscalls. Assignment to a str index is a compile-time error, even when the view was created from a mutable buffer.

Minimum helpers:

| Function | Contract |
|---|---|
| `text.view(src: bytes, length: dword) -> str` | Checked view, no copy |
| `text.decimal(dst: bytes, value: long) -> str` | Signed decimal, dst ≥12 bytes; BOUNDS before writing if too small |
| `text.decimal(dst: bytes, value: dword) -> str` | Full unsigned decimal 0…4,294,967,295, dst ≥12 bytes; same BOUNDS check |
| `text.copy(dst: bytes, src: str) -> dword` | Copies all bytes, bounds fault if they do not fit; returns length |
| `text.real(dst: bytes, value: float24/float32, digits: byte) -> (str, word)` | 1…9 significant digits; dst ≥24 bytes; static overload, no allocation |
| `text.parse_float(src: str) -> (float32, word)` | Checked conversion from ASCII, at most 63 bytes |
| `text.parse_float24(src: str) -> (float24, word)` | Direct conversion to the compact format |

The two text.decimal overloads are resolved at compile time: byte/word/dword use the unsigned one, int/long the signed one; a direct literal with no other type is first typed using the ordinary rules. No integer→float conversion is used to format integers. They do not allocate or write a NUL, and return a view of only the bytes produced; zero is `0`, with no `+` sign or leading zero. Capacity is checked before any change to dst.

Strings are length-delimited, not NUL-terminated. The file driver validates paths and converts them to the firmware's format. UI text must respect the service's maximum length; the library may split it into segments only while preserving clipping and coordinates. Version 0.1 promises neither text layout nor full Unicode.

The grammar, errors, choice between fixed/scientific notation, and numeric round-trip are defined in NUMERICS.md §4. Text converters are a bytecode library subject to fuel; their workspace must appear in the frame report.

## 9 Modules and SDK

`import` enables a module resolved by the compiler and build manifest; it does not load files at runtime. Standard MVP modules: `system`, `ui`, `video`, `fs`, `storage`, `clock`, `sid`, `audio`, `ultimate`, `text`, `math`. Math contains abs/min/max/trunc/floor/ceil for both float types; trigonometry and transcendental functions come later. `net` and `http` belong to later milestones and produce an explicit import error in the MVP.

Normative signatures are in [ULTIMATE-API.md](ULTIMATE-API.md). App modules may import other project sources through static names; the bundler resolves an acyclic graph. `import util` makes the module's exported functions and constants available through qualified names, such as `util.helper(...)` and `util.LIMIT`. In 0.1, all functions and constants in a module are visible through this qualification; do not introduce export syntax or unqualified imports. Each module has its own namespace, and the app has only the entry point defined in §6. No code runs implicitly on import; no wildcards or searches in undeclared global directories.

Wrappers perform simple checks, prepare descriptors, and invoke syscalls. The kernel remains responsible for isolation even for bytecode not produced by the compiler. Do not rely on the type checker to protect REU memory, file handles, or devices.

### 9.1 I/O example

```text
import fs
import text
import system

fn main() {
    let data = bytes(32)
    let length = text.copy(data, "C-OS\n")
    let file, err = fs.open("hello.txt", fs.CREATE_TRUNCATE)
    if err != 0 { system.exit(int(err)) }

    let offset: dword = 0
    while offset < length {
        let count, write_error = fs.write(file, data.slice(offset, length - offset))
        offset = offset + count
        if write_error != 0 {
            fs.close(file)
            system.exit(int(write_error))
        }
        if count == 0 {
            fs.close(file)
            system.exit(8)
        }
    }

    let close_error = fs.close(file)
    if close_error != 0 { system.exit(int(close_error)) }
}
```

Opening with truncation is an explicit choice by the program. The driver must not truncate the file again when reopening the backend to interleave operations from multiple apps. The example handles partial results; `close` cannot guarantee survival of a sudden power loss if the firmware/storage provide no such guarantee.

### 9.2 Custom-pixel example

```text
import ui
import video

fn main() {
    let win, err = ui.open("Pixel", 160, 112)
    if err != 0 { return }
    let pixels = bytes(4096)

    for i in 0..pixels.len {
        pixels[i] = byte((i >> 2) & 15)
    }
    video.blit8(win, 8, 8, pixels, 64, 64)
    ui.present(win)

    while true {
        let event, wait_error = ui.wait(win, ui.FOREVER)
        if wait_error == 0 && event.kind == ui.CLOSE_REQUEST { break }
    }
    ui.close(win)
}
```

`pixels` is app memory, not a mapping of the surface or framebuffer. No UPIC details appear in the program.

### 9.3 Directory listing and clock

```text
import fs
import clock
import system
import text

fn main() {
    let name = bytes(256)
    let dir, open_error = fs.opendir(".")
    if open_error != 0 { system.exit(int(open_error)) }

    let count: word = 0
    while true {
        let info, found, read_error = fs.next(dir, name)
        if read_error != 0 {
            fs.closedir(dir)
            system.exit(int(read_error))
        }
        if !found { break }
        count = count + 1

        if info.kind == fs.FILE && (info.flags & fs.NAME_UNADDRESSABLE) == 0 {
            let filename = text.view(name, dword(info.name_len))
            let details, stat_error = fs.stat(filename)
            if stat_error == 0 && (details.valid & fs.SIZE_VALID) != 0 {
                // details.size is available, including for files larger than 64 KiB
            }
        }
    }
    let close_error = fs.closedir(dir)
    if close_error != 0 { system.exit(int(close_error)) }

    let now, time_error = clock.now()
    if time_error == 0 {
        let year = now.year
        // now.month/day/hour/minute/second are the observed civil date and time
    }
}
```

This is an example of bindings and error handling, to accompany the graphical demo required by SPEC.md. `name` is reused: a view of its contents changes on the next fs.next. If the app wants to retain a name, it copies it into its own buffer. Stat may fail if the file has changed since the snapshot, without invalidating the previously read entry.

`clock.now` may return EAGAIN while the kernel refreshes the cache. Always use system.frame/system.sleep for waits and intervals; a change in civil time must not change the behavior of app timers.

## 10 Essential grammar

The following EBNF summarizes the structure; precedence, newlines, and type rules are defined above. `sep` is a significant newline or `;`; separators after a block are optional.

```text
module     = { import_decl | const_decl | function | sep } ;
import_decl= "import", identifier, sep ;
function   = "fn", identifier, "(", [params], ")", ["->", results], block ;
params     = param, {",", param} ;
param      = identifier, ":", type ;
results    = type | "(", type, {",", type}, ")" ;
block      = "{", {statement | sep}, "}" ;
statement  = let_decl | const_decl | assign | call_stmt | if_stmt
           | while_stmt | for_stmt | return_stmt | "break" | "continue" ;
let_decl   = "let", binding, {",", binding}, "=", expression ;
binding    = identifier, [":", type] | "_" ;
const_decl = "const", identifier, [":", type], "=", expression ;
assign     = lvalue, "=", expression ;
if_stmt    = "if", expression, block, ["else", (block | if_stmt)] ;
while_stmt = "while", expression, block ;
for_stmt   = "for", identifier, "in", expression, "..", expression, block ;
return_stmt= "return", [expression, {",", expression}] ;
lvalue     = identifier | expression, "[", expression, "]" ;
```

Simple productions require a separator or the closing of the block. The complete grammar used by the tests must reject unsupported constructs rather than accepting and ignoring them.

## 11 Host compiler and formats

Recommended host implementation: **Rust**, for the compiler, assembler/disassembler, bundler, and reference VM. Start with a small Cargo workspace sharing type, ISA, and ABI definitions across tools; do not split it prematurely into many crates or impose a framework. Prefer the standard library where practical; a focused dependency for exact arithmetic or independent verification is preferable to approximate numeric results. Pipeline: lexer → parser → symbol and type resolution → simple IR → register allocation → bytecode/relocations → bundler.

A small recursive parser with explicit precedences is sufficient. Do not build a multi-backend framework. Initial optimizations are constant folding, temporary elimination, and keeping counters/local variables in R where possible. The simple case must not reread every variable from the REU stack on every opcode.

Borrow QuakeC's approach of a host-side table of operators, types, conversions, and lowering; resolve math/text overloads at compile time. A small shared schema generates ABI constants and signatures for the compiler, reference implementation, and kernel. Float constants are deduplicated by type and target bits; folding uses COS-NUM-1 after every operation, with no implicit host double arithmetic or float32→float24 double rounding.

For the float overloads of math and text.real, the format comes from the numeric argument's type, with direct literals that have no fixed format yet typed according to the ordinary rules. Math.min/max use the same common-type selection as a binary operator. The selected type must be float24 or float32: integer-only arguments require an explicit cast for these helpers, avoiding an ambiguous choice between two exact conversions. For example, `math.abs(1)` is an error, `math.abs(1.0)` returns float32, and `math.min(a24, 1.0)` returns float24. This rule concerns overload selection; a function with a single already-declared float parameter continues to accept exact implicit conversions.

The initial ISA has no frame-relative addressing: use P2 plus an offset for frame loads/stores. 32-bit integers use pairs of R16 registers or four bytes in spill storage. Syscall arguments are prepared only at the call, not kept globally in reserved registers.

Float24 occupies three packed bytes, float32 four; both may use temporary pairs of R16 registers. Do not reserve a persistent float register bank. Source code cannot reinterpret a float24 as a pointer merely because they have the same size.

Do not eliminate an infinite loop just because it produces no observable writes: its progress and fuel consumption have meaning in C-OS. Do not change wrapping, cast, or bounds results through aggressive optimization.

Expected commands, with proposed names to implement:

```text
cargo build --release
cargo test --workspace
cargo run --release --bin cosc -- apps/counter/main.cos -o build/counter.cobj
cargo run --release --bin cosdis -- build/counter.cobj
cargo run --release --bin cospack -- manifests/desktop.json --out build/desktop
cargo run --release --bin cosrun -- build/desktop.manifest.json --app counter
```

These are delivery interfaces to implement, not commands that are already available. The Rust choice applies to host tooling; C-OS bytecode and the 6510 kernel retain their own contracts. Pin the toolchain and dependencies in build files to make outputs and tests reproducible.

The first `.cobj` format may be host-only JSON: `format="COSOBJ1"`, ABI/compiler version, byte arrays for `code` and `data`, `bss_size`, section symbols, entry point, and relocations. No JSON parsing on the C64.

Also include `numeric_profile="COS-NUM-1"`; the bundler checks that objects, constants, and kernel agree on the contract of both formats.

Minimum relocations: ABS24 with target section/offset and addend; REL16_INSN with aligned source and destination; section references for constants and views. Check for overflow, addresses outside the arena, and unaligned branches at link time. Do not assign final physical pointers during source parsing.

The bundler knows the arena bases and produces final code, initialized-data seeds, manifest, and symbols. If the seeds do not fit in the system's initial reserve, the build fails with a precise report: do not overwrite other pack data.

Required outputs: listing, address→file/line/column map, code/data/BSS size, each function's frame, assigned stack, available heap, included modules, and SDK imports. On a fault, host diagnostics translate PID/PC into function/line using the same build tag.

Language checking routines use TRAP with stable codes: $1001 RANGE, $1002 BOUNDS, $1003 DIVIDE_BY_ZERO, $1004 OUT_OF_MEMORY, $1005 SHIFT_RANGE, $1006 NUMERIC_INVALID, $1007 FLOAT_OVERFLOW. These are TRAP payloads, distinct from native VM fault causes and errors that syscalls can return. NUMERICS.md defines how numeric-service errors are translated.

## 12 Verification and completion

- Lexical and precedence tests, newlines, and parsing of the complete examples.
- Precise type errors with file/line/column; rejection of nonexistent handles, fields, and functions.
- Signed/unsigned arithmetic at the limits, casts, divisions, shifts, and evaluation order.
- Common integer type, operator matrix, and left→right order even with calls in operands; rejection of equality on views/records and comparisons between handles of different types.
- Float24/float32: literals, promotions, RNE, zero, overflow/underflow, conversions, text, and the bit-exact corpus from NUMERICS.md; no unintended double rounding.
- Normative examples of direct-literal context: parentheses/unary minus, explicit narrowing, and no propagation into subexpressions.
- Arrays >64 KiB, last valid byte, empty slices, negative indices, and overflow.
- str.len, indexed reads, and slices without allocation; writes rejected. Text.decimal at long/dword limits, short buffers with no writes, and unsigned values above 2^31−1.
- Nested/recursive calls, multiple results, and identical SP before/after the call.
- Exactly one main in the entry module, qualified imports, and P2 preservation in wrappers that use MEM_INFO.
- Zeroed allocation, isolated OOM, buffers reused without growth in an event loop.
- Reference VM/6510 VM comparison for generated bytecode, including cache misses and small quanta.
- Two C-Script apps looping without yield: both make progress, and input and raster remain serviced.
- Compilation and execution of UI, pixel, I/O, SID, and PCM examples.
- Dir/FileInfo/StorageInfo/DateTime/InputState bindings, multiple results without allocation, negative Event coordinates, nested fields, and name-buffer reuse; net/http imports rejected until the corresponding SDK profile is available.
- Reproducible builds with fixed inputs and versions; an error must not publish a partial artifact.

The language is complete for the MVP when the demo apps are written in C-Script and use the SDK, without relying on private native routines to bypass VM limitations.
