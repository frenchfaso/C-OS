# Fractional numbers in C-Script

Specification 0.1, revision 7 — October 10, 2026. Normative companion to [SPEC.md](SPEC.md) and [LANGUAGE.md](LANGUAGE.md). Application ABI 2; unchanged numeric profile: `COS-NUM-1`.

C-Script provides two fractional formats: **float24**, for compact data and calculations with a short significand, and **float32**, for greater precision. `float` is an alias for float32. The chosen type determines representation and rounding; the assembly backend must produce the same results as the host model. Any float24 speed advantage must be measured, including REU access and call overhead.

## 1 Selected formats

| Type | Bytes | Significant bits in normal numbers | Approximate decimal precision | Exactly representable consecutive integers |
|---|---:|---:|---|---|
| `float24` | 3 | 16 | About 4–5 significant digits | −65,536 through +65,536 |
| `float32`, alias `float` | 4 | 24 | About 6–7 significant digits | −16,777,216 through +16,777,216 |

Both use an 8-bit exponent with a bias of 127. The smallest positive normal number is 2^-126, approximately 1.17549435×10^-38. The maximum is `(2 − 2^-15) × 2^127` for float24 and `(2 − 2^-23) × 2^127` for float32. A shorter significand reduces precision while retaining the same normal exponent range.

Float32 uses the IEEE binary32 representation. Float24 is a C-OS format, not an IEEE standard: sign in bit 23, exponent in bits 22…15, fraction in bits 14…0. A normal value is `(-1)^sign × (1 + fraction/2^15) × 2^(exponent−127)`. All values are packed little endian.

Exact widening of a normal float24 to binary32 corresponds to shifting its bits eight positions to the left. Narrowing requires rounding, rather than simply discarding a byte. The three bytes of a float24 represent a number and have no relation to the VM's u24 pointers.

The profile supports zero and finite normal numbers. Its semantics are restricted; **this is not a claim of full IEEE 754 compliance**:

- Each operation rounds to the precision of its result type using round-to-nearest, ties-to-even, abbreviated RNE.
- The result is first rounded to the destination format; if it remains subnormal, it is converted to +0. A value that rounds to the smallest normal number must survive.
- Subnormal inputs and −0, including those supplied by hand-written bytecode, are interpreted as +0 on entry to numeric operations.
- Zero outputs always have all bits clear. Apps cannot change any global rounding modes or numeric flags.
- Inputs with exponent 255, including NaNs and infinities, are invalid. Overflow produces an error; division by zero produces an error. The language runtime maps errors to the faults defined below.

Byte, word, int, dword and long retain their integer arithmetic. Sizes, addresses, handles, indices, fuel and timers continue to use integers.

## 2 Float16 and fixed point

A third format, binary16, would use 2 bytes, 11 significant bits and about 3 significant digits, with a maximum of 65,504 and a smallest normal number of 2^-14. It remains a candidate for later: without subnormals, the lower limit is approximately 0.000061. Around 320, the spacing between representable values would be 0.25; float24 provides a spacing of 1/128 and float32 of 1/32,768. These are numeric spacings, not measurements of UI smoothness.

The first implementation includes float24 and float32. Avoid the cost of three backends until apps and measurements justify binary16. Mad-Pascal's half routines are a concrete reference for arithmetic with a reduced significand; the examined addition/multiplication code is not a directly reusable RNE backend. [f16 library](https://github.com/tebe6502/Mad-Pascal/blob/master/lib/f16.pas).

Fixed point, such as Q16.16, is an alternative for interpolation over a known range. It provides uniform spacing but not the wide dynamic range of floats. It may become a later library; do not add a third fractional type now and call it a float.

## 3 Syntax and conversions

```text
fn main() {
    let speed: float24 = 0.125
    let position: float24 = 12.5
    position = position + speed

    let measured: float32 = 1234.56789
    let mean = measured / 3.0
    let precise_position = float32(position)
    let compact_mean = float24(mean)
    let pixel = int(position) // truncate toward zero, with a range check
}
```

Fractional literals consist of digits, a decimal point and digits, optionally followed by `e`/`E`, an optional sign and a decimal exponent; `1e3` is also allowed. Valid examples: `0.5`, `1.0`, `1e-3`, `1.25E+2`. Require digits before and after the decimal point when it is present; `1..10` remains an integer range, without ambiguity with `1.`. Underscores are allowed only between digits.

Inference follows LANGUAGE.md §4.1 from the bottom up. A direct literal is a numeric token optionally enclosed only by parentheses and unary minus; constant names and compound expressions are already typed. Without context, a fractional literal has type float32. A declaration, assignment, parameter, expected result or cast applied directly to the literal may require float24. In an operator with one already typed float operand and one direct literal, the literal takes the other operand's format. If both are direct literals, they take their context-free types. An expected type outside the expression is not propagated into their binary operators.

Given `a24: float24`, the following examples are normative:

| Source | Semantics |
|---|---|
| `let x: float24 = (-0.5)` | Direct literal rounded to float24 |
| `let x: float24 = 1.0 + 2.0` | Error: float32 sum assigned to float24 without a cast |
| `float24(1.0 + 2.0)` | float32 sum, then RNE cast to float24 |
| `a24 + (1.0 + 2.0)` | Inner sum is float32 and outer result is float32 |
| `a24 + 1.0` | Literal and sum are float24 |
| `float24(1.0) + 2.0` | float24 sum because the first operand is already typed |

Integers without a decimal point/exponent retain the language's rules when no direct context requires a float. Do not change these types after constant folding.

Additional implicit conversions: byte/word/int to either float; float24 to float32. These are exact for all values of the source type. Long/dword to float require a cast because they may lose integer units. Float32 to float24 requires an RNE cast. A cast enclosing an already typed expression converts its result: `float24(a32 + b32)` performs the float32 addition first.

Context may determine a fractional literal's format or convert an isolated integer literal; it does not turn a compound expression containing only integers into floating-point arithmetic. `float24(1 / 2)` and `let x: float24 = 1 / 2` produce zero: integer division is performed first, then the result is converted. Write `1.0 / 2.0` for fractional division.

Mixed float24/float32 operations promote to float32. Do not implicitly narrow a float32 result when assigning it to float24. The permitted operators are `+ - * /`, unary minus and the six comparisons, which produce bool. `%`, bitwise operations and shifts remain integer operations. `1 / 2` retains integer division; `1.0 / 2.0` produces 0.5.

Float→integer truncates toward zero and checks the range of the truncated result before writing it; no wrapping or undefined host-compiler behavior is allowed. `int(-3.75)` is −3; `byte(-0.5)` is 0; `byte(-1.0)` is RANGE. Conversions to 8/16 bits first use the signed/unsigned 32-bit result, then apply the existing range check.

Casts between formats and constants are rounded directly to the required format. The host compiler must start from the token's exact decimal value, not from an already rounded double. Do not reassociate operations, fuse multiplication/addition or retain hidden precision beyond a source operation.

## 4 Minimal library

`math` is a static module. The following functions are overloads resolved at compile time for float24 and float32, without dynamic dispatch:

| Function | Result |
|---|---|
| `math.abs(x)` | Same type as x, absolute value |
| `math.min(a, b)`, `math.max(a, b)` | Common type after the ordinary conversions |
| `math.trunc(x)` | Same type, fractional part removed toward zero |
| `math.floor(x)`, `math.ceil(x)` | Same type, mathematical floor/ceiling |
| `text.real(dst: bytes, value: float24/float32, digits: byte) -> (str, word)` | Formatting with 1…9 significant digits, buffer ≥24 bytes |
| `text.parse_float(src: str) -> (float32, word)` | Parsing into the language's default format |
| `text.parse_float24(src: str) -> (float24, word)` | Parsing directly into the compact format |

The overload format comes from the numeric argument's type, not from the call's expected result type. Direct literals follow the ordinary rules; math.min/max select the common type as a binary operator does, including the rule for a direct literal next to a typed operand. The resulting type must be float24 or float32. If all arguments are integers, require an explicit cast: `math.abs(1)` is an error, `math.abs(1.0)` selects float32 and `math.min(a24, 1.0)` selects float24. Text.real applies the same rule to its value parameter. Do not introduce integer math overloads as an accidental consequence of implicit conversions.

Text.real rounds in decimal, ties-to-even, to the requested number of significant digits; it uses fixed notation if the decimal exponent after rounding is between −4 and digits−1 inclusive, otherwise scientific notation. It removes trailing fractional zeros and a decimal point left without fractional digits; zero becomes `0`. The separator is `.`, the exponent is `e` with a sign and at least two digits, and formatting is locale-independent. Output is length-delimited. Validate, in order, digits 1…9, dst capacity ≥24 and numeric validity: ERANGE for the first two errors, EDOM for a non-finite input. Subnormals and −0 follow the profile's canonicalization rules. On error, the result view is empty and dst remains unchanged. Nine digits allow float32 round-tripping and six allow float24 round-tripping; printed digits do not increase the value's precision.

The parsers accept an optional leading sign, integer or fractional decimals and an optional exponent, without underscores, whitespace or trailing characters. The decimal point requires digits on both sides: `.5` and `1.` are invalid, `0.5` and `1.0` are valid. Length is 1 to 63 bytes; report EINVAL for syntax and ERANGE for length/overflow. Return zero on error, without partial parsing. RNE and underflow follow the requested format. Formatting and parsing must handle the type's full range.

Bound the cost even for enormous textual exponents. Accumulate them with saturation and classify the result before building powers of ten or starting scaling loops; work must not be proportional to the exponent's numeric value. After full syntax validation, zero with any exponent remains zero; obvious overflow of a nonzero value returns ERANGE, and obvious underflow returns +0. The host compiler applies the same rule, with a limit of 128 bytes per fractional numeric token, including underscores.

Text conversions initially use bytecode helpers with static workspace in the app's frame and fuel-metered loops. Avoid allocating on every conversion. Their REU bytes, stack, numeric calls and execution times are included in the report. The resident assembly core contains only arithmetic, comparisons and numeric conversions; later text acceleration requires the same timing qualification.

Sqrt, trigonometry, logarithms, exponentials and general powers are later extensions. A float type does not imply importing a complete math library into local RAM.

## 5 Numeric service ABI

Reserve hexadecimal syscall **30 NUM_OP**. This is a kernel service independent of Ultimate devices. Both formats are part of the MVP: they are not optional hardware capabilities.

- R1: operation in bits 7…0, format in bits 15…8; format 0=float32, 1=float24, other values invalid.
- R2/R3: operand A, low16/high16. R4/R5: operand B, low16/high16, zero for unary operations.
- Float24 occupies the low 24 bits; the high 8 bits must be zero. Integer32 inputs use all 32 bits. Do not validate an integer as a float representation.
- R0 on return: status. R2/R3: result low16/high16, cleared on error. The other R registers and all P registers are preserved.
- Binary operations compute A op B. FCMP returns −1/0/+1 in signed16 R2 and R3=0; wrappers generate bool values using integer comparisons.

| Op | Name | Meaning of the selected format |
|---|---|---|
| 00 | FADD | Both inputs and the result |
| 01 | FSUB | Both inputs and the result |
| 02 | FMUL | Both inputs and the result |
| 03 | FDIV | Both inputs and the result |
| 04 | FCMP | Both inputs |
| 05 | FROM_I32 | Result format; A is i32 |
| 06 | FROM_U32 | Result format; A is u32 |
| 07 | TO_I32 | Format of A; i32 result |
| 08 | TO_U32 | Format of A; u32 result |
| 09 | FTRUNC | Format of A and the result |
| 0A | FFLOOR | Format of A and the result |
| 0B | FCEIL | Format of A and the result |
| 0C | F24_TO_F32 | Requires format 0; A is float24, output float32 |
| 0D | F32_TO_F24 | Requires format 1; A is float32, output float24 |

For 0C/0D, validate A according to the input type specified in the table: the format in R1 describes the result. In particular, A's high byte in F32_TO_F24 may be nonzero. R4/R5 must be zero for all unary operations.

Invalid operation/format/fields: EINVAL. Non-finite representation: new status 22 EDOM. Zero denominator after normalization: new status 23 EDIVZERO. Overflow and out-of-range conversion: ERANGE. Validate operands first, then the denominator, then perform the calculation. Ordinary rounding and underflow to zero are not errors.

Operator/cast wrappers map EDOM to TRAP `$1006 NUMERIC_INVALID`, EDIVZERO to `$1003 DIVIDE_BY_ZERO`, arithmetic or float-narrowing ERANGE to `$1007 FLOAT_OVERFLOW`, and integer-cast ERANGE to `$1001 RANGE`. Compiler errors in constant expressions are diagnosed at build time. Parsers return their documented errors, allowing the app to correct its input.

Unary minus and abs may use bytecode operations on the bits of an already valid value, canonicalizing zero. No persistent F registers or new dispatcher opcodes are needed. A float32 value uses two R16 registers or four bytes in the frame; float24 uses three bytes in the frame and, when needed, two R16 registers with the high part cleared.

## 6 Backend scheduling and memory

NUM_OP uses the existing single native-job queue. SYSCALL costs one opcode and records one continuation; math chunks are charged to their owner's native time, rotating with other jobs. A math syscall that completes immediately or suspends for an internal phase does not replenish fuel. NUM_OP preserves the remaining fuel until the normal end of the quantum: it is CPU work, not a wait for an external device.

The first implementation choice is an indivisible routine, allowed only after qualifying its maximum cost including the bridge and verifying that it fits in the available window, including guard time. If it does not fit now but fits in the next available window, defer the entire operation. Introduce internal continuations only for operations whose maximum cost does not fit in the qualified service window: in that case, split them into explicit phases, such as alignment, multiplication/division iterations and rounding. No native frame remains on the hardware stack between turns. An algorithm with a finite iteration count is not automatically short enough for the raster.

Operands, format, partial accumulator, carry/sticky bits and phase cursor belong to the process's job. The kernel may use shared ZP scratch only while executing a chunk; save everything that remains live before serving another owner. Do not overlap an external library's FAC/ARG or temporary registers with VM registers or UPIC scratch.

Qualification for an ordinary service window does not qualify a routine for a UPIC horizontal margin. Optional margin execution follows SPEC §10.4: only a separately bounded phase with already resident operands and exclusively owned local scratch may run there, with no REU/cache service or re-entry of an interrupted math routine. Preserve the same job, result semantics, owner accounting, and remaining fuel; retire the syscall only once. Do not split an otherwise suitable indivisible backend merely to populate margins. Numeric implementation remains M4b, and neither its completion nor M2 preparation requires margin activation. COS-NUM-1 is unchanged.

The cost includes the bridge, checks, spills/reloads, context saving and REU access. Kill cancels the job and releases scratch without publishing a result to a terminated process. Each app has at most one pending blocking job, as with the other services.

Initial target to qualify: the resident core for both formats, numeric conversions and bridge must fit within **4 KiB total**, included in the 20 KiB local budget. This size has not yet been demonstrated. Report ZP, scratch RAM, job contexts in REU and text helpers separately. If the core exceeds the target, share paths and move noncritical helpers into bytecode; do not remove a format or change precision without explicitly updating the specification.

Float24 must have a genuine 16-bit significand path: a 16×16 product and division at the required precision, with guard and sticky bits. Share unpacking, signs, exponents, errors and scheduling where useful; compare specialization with a parameterized core. Compiling every float24 operation as float32 followed by compression does not meet the acceleration objective and may introduce double rounding.

## 7 Sources and backend selection

| Reference | Findings and use in C-OS |
|---|---|
| [XC-BASIC 3](https://xc-basic.net/doku.php?id=v3:datatypes) | 4-byte floats, about 6–7 digits. Their use alongside integers is useful; DECIMAL denotes BCD integers 0…9999, not a fractional type. |
| [XC-BASIC math pack](https://github.com/neilsf/xc-basic3/blob/55014f0f6a2dfa2d40e377102f4da6b764a1e788/lib/math/_fplib.asm) | Selects BYTES_FP=4 and three significand bytes; uses global FAC/ARG and derives from the MS BASIC math pack. Its format differs from binary32 and rounding needs verification. A source of algorithms and conversions, not a library to link unchanged. |
| [LLVM-MOS add](https://github.com/llvm-mos/llvm-mos/blob/main/compiler-rt/lib/builtins/mos/addsf3.S), [mul](https://github.com/llvm-mos/llvm-mos/blob/main/compiler-rt/lib/builtins/mos/mulsf3.S), [div](https://github.com/llvm-mos/llvm-mos/blob/main/compiler-rt/lib/builtins/mos/divsf3.S) | 6502 assembly with RNE and special-value handling. The first candidate for float32 and a reference for deriving the shorter path; the original routines do not include C-OS fuel handling. |
| [Oscar64 runtime](https://github.com/drmortalwombat/oscar64/blob/main/include/crt.c) and [manual](https://github.com/drmortalwombat/oscar64/blob/main/oscar64.md) | Another 6502-oriented binary32 backend. The manual excludes NaNs; the examined shifts do not establish our RNE contract. Useful for comparing algorithms and sizes, not a replacement without testing. |
| [Woz and Rankin corrections](https://github.com/jefftranter/6502/blob/master/asm/wozfp/README.txt) | A compact historical 4-byte example with a two's-complement significand. Requires a different format; useful for study, not for silently changing the numeric ABI. |
| [Microsoft BASIC M6502](https://github.com/microsoft/BASIC-M6502) | A historical math pack with configurable precision; a possible alternative primary source. The entire interpreter's size does not measure the cost of floats alone. |
| [SoftFloat for 6502](https://github.com/rweather/berkeley-softfloat-3-6502) | A candidate host oracle for binary32. The C port does not demonstrate speed or size suitable for the C-OS kernel. |

Pin commits and record licenses in the report before integrating code. XC-BASIC is MIT at the repository level, but its math file carries a two-clause BSD notice: preserve the specific provenance. LLVM-MOS declares Apache-2.0 with the LLVM exception; Microsoft BASIC-M6502 is MIT; for Oscar64, examine the GPL and the terms of the files actually imported. Do not infer a license for historical Woz listings from public access alone.

This survey did not identify a ready-made NMOS backend that guarantees exactly the float24 format and profile defined here. Specialization and testing are part of the numeric milestone. No speed ratio between these candidates is assumed without comparable measurements.

## 8 Ideas adopted from QuakeC

QuakeC suggests a single host table of operators, types and lowering rules, constant deduplication by target representation and statically resolved builtins. Use a small, readable schema to generate IDs and signatures shared by the compiler/reference VM/kernel, including the numeric profile. Keep listings, function names and source maps outside the minimal build. [Original compiler](https://github.com/id-Software/Quake-Tools/blob/master/qcc/pr_comp.c), [shared contract generation](https://github.com/id-Software/Quake-Tools/blob/master/qcc/qcc.c).

The Quake VM counts statements, provides profiling and terminates execution after a runaway limit; that check does not suspend/resume a function. C-OS retains its own fuel and continuations. In diagnostic builds, count float-helper calls and costs, distinguishing opcodes from native time. [Original executor](https://github.com/id-Software/Quake/blob/master/WinQuake/pr_exec.c).

Retain explicit integers, four-byte bytecode and C-Script guest frames. The float/vector-centric model, eight-byte statements and locals saved by the Quake VM are not C-OS requirements. [Quake types and statements](https://github.com/id-Software/Quake/blob/master/WinQuake/pr_comp.h).

## 9 Required verification

The host model uses exact integers and ratios to produce operations in the selected format; it may use a verified binary32 oracle for independent comparison. Export a shared corpus of inputs, bit-pattern results and errors. The compiler, constant folder and 6510 backend must agree, including at the boundary between normal and subnormal numbers.

The Rust tooling recommended in LANGUAGE.md must implement these semantics without delegating folding to ordinary host f32/f64 arithmetic. An independent auxiliary oracle, such as Python with Fraction, may generate or verify the exact corpus. Sharing the corpus does not mean using the same implementation as its only test of itself; the choice of host libraries does not change COS-NUM-1.

Minimum coverage:

1. Little-endian encoding: zero, ±1, 0.5, maxima, smallest normal numbers, subnormal inputs, −0, NaN/Inf and nonzero high bits in float24 inputs.
2. The four operations, near-total cancellation, widely differing exponents, exact ties-to-even halfway cases, overflow and division by zero for both formats.
3. Integer32 boundaries, signed/unsigned conversions, truncation before the range check, promotions, narrowing casts and type errors.
4. A result just below the smallest normal number that rounds to the smallest normal number; a result that remains subnormal and becomes zero.
5. Constant folding identical to runtime, without reassociation or hidden precision; float24 literals converted directly from decimal.
   Also verify the context examples in §3: parentheses and unary minus preserve a direct literal, binary operators determine the type before outer context is applied, and folding does not remove narrowing errors.
6. A specific double-rounding test: in float24, `1.682830810546875 × 1.40277099609375` must produce `2.36065673828125`. Going through a rounded binary32 product first instead produces `2.360595703125`: that path must be rejected.
7. Invalid/over-limit parsing, a short dst, formatting at decimal boundaries, six/nine-digit round-trips and workspace without heap growth.
8. Two apps alternate formats with a small quantum and cache misses; results and scratch remain independent. Kill and suspension at every job phase.
9. Float loops without yield alongside input/UI, file I/O and PCM. Measure latency, raster deadlines and native time per process.

The benchmark reports +, −, ×, ÷, comparison, casts and text separately: linked core size, ZP, scratch, observed minimum/maximum cycles, qualified time bound, end-to-end cost with REU and throughput within the UPIC schedule. Report the float24/float32 difference on the same build. If float24 saves only memory, say so; a three-byte ABI alone does not prove a speed increase.

## 10 Deliverables

M4a produces the compiler and calling ABI already specified. M4b adds both floats, NUM_OP, text helpers and the host/6510 corpus before full qualification. The manifest and every host object declare `numeric_profile="COS-NUM-1"`; the bundler rejects incompatible combinations. Application ABI 2 adds bounded integer MULU/MULS but does not change this numeric profile, its service layout, float rounding or conversions. A later numeric backend may share a native multiplication algorithm only with its own complete timing/scratch proof; integer multiplication does not implement NUM_OP or replace its rounding rules. Future incompatible numeric changes require a new profile and corresponding verification.

Delivery includes pinned sources, licenses, reproducible tests and size/timing reports. Numeric support is complete when both formats work in C-Script apps and under concurrent load, with published limits.
