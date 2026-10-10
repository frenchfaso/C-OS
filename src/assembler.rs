//! Two-pass bytecode assembler: labels remain section references until linking.
use crate::{
    isa::{self, Instruction, Opcode, OperandForm},
    object::*,
};
use std::collections::{BTreeMap, BTreeSet};
#[derive(Clone)]
struct Item {
    text: String,
    offset: u32,
    line: u32,
    column: u32,
}
#[derive(Debug)]
enum Expression {
    Number(i64),
    Name(String, i64),
}
fn identifier(s: &str) -> bool {
    let mut chars = s.bytes();
    chars
        .next()
        .is_some_and(|c| c.is_ascii_alphabetic() || c == b'_')
        && chars.all(|c| c.is_ascii_alphanumeric() || c == b'_')
}
fn number(s: &str) -> Option<i64> {
    let (sign, s) = if let Some(s) = s.strip_prefix('-') {
        (-1, s)
    } else if let Some(s) = s.strip_prefix('+') {
        (1, s)
    } else {
        (1, s)
    };
    if s.starts_with(['+', '-']) {
        return None;
    }
    let result = if let Some(s) = s
        .strip_prefix("0x")
        .or_else(|| s.strip_prefix("0X"))
        .or_else(|| s.strip_prefix('$'))
    {
        i64::from_str_radix(s, 16).ok()
    } else {
        s.parse::<i64>().ok()
    };
    result.and_then(|v| v.checked_mul(sign))
}
fn expression(s: &str) -> Result<Expression, String> {
    let compact: String = s.chars().filter(|c| !c.is_whitespace()).collect();
    if let Some(v) = number(&compact) {
        return Ok(Expression::Number(v));
    }
    let split = compact
        .char_indices()
        .skip(1)
        .find(|&(_, c)| c == '+' || c == '-');
    let (name, addend) = if let Some((n, _)) = split {
        (
            &compact[..n],
            number(&compact[n..]).ok_or_else(|| format!("expected numeric addend in '{s}'"))?,
        )
    } else {
        (compact.as_str(), 0)
    };
    if !identifier(name) {
        return Err(format!("invalid expression '{s}'"));
    }
    Ok(Expression::Name(name.to_owned(), addend))
}
fn constant(
    name: &str,
    defs: &BTreeMap<String, String>,
    cache: &mut BTreeMap<String, i64>,
    active: &mut BTreeSet<String>,
) -> Result<i64, String> {
    if let Some(v) = cache.get(name) {
        return Ok(*v);
    }
    if !active.insert(name.to_owned()) {
        return Err(format!("cyclic constant '{name}'"));
    }
    let expr = defs
        .get(name)
        .ok_or_else(|| format!("undefined constant '{name}'"))?;
    let value = match expression(expr)? {
        Expression::Number(v) => v,
        Expression::Name(other, add) => constant(&other, defs, cache, active)?
            .checked_add(add)
            .ok_or("constant overflow")?,
    };
    active.remove(name);
    cache.insert(name.to_owned(), value);
    Ok(value)
}
fn immediate(expr: &str, constants: &BTreeMap<String, i64>) -> Result<i64, String> {
    match expression(expr)? {
        Expression::Number(v) => Ok(v),
        Expression::Name(n, a) => constants
            .get(&n)
            .ok_or_else(|| format!("undefined constant '{n}'"))?
            .checked_add(a)
            .ok_or_else(|| "constant overflow".into()),
    }
}
fn ranged(value: i64, min: i64, max: i64, name: &str) -> Result<u32, String> {
    if value < min || value > max {
        Err(format!("{name} must be {min}..{max}, found {value}"))
    } else {
        Ok(value as u32)
    }
}
fn reg(s: &str, prefix: u8, max: u8) -> Result<u8, String> {
    let bytes = s.as_bytes();
    if bytes.len() != 2
        || bytes[0].to_ascii_uppercase() != prefix
        || !bytes[1].is_ascii_digit()
        || bytes[1] - b'0' > max
    {
        Err(format!(
            "expected {}0..{}{max}, found '{s}'",
            prefix as char, prefix as char
        ))
    } else {
        Ok(bytes[1] - b'0')
    }
}
fn tokens(text: &str) -> (&str, Vec<&str>) {
    let (head, tail) = text.split_once(char::is_whitespace).unwrap_or((text, ""));
    let args = if tail.trim().is_empty() {
        vec![]
    } else {
        tail.split(',').map(str::trim).collect()
    };
    (head, args)
}
fn count(args: &[&str], expected: usize) -> Result<(), String> {
    if args.len() != expected || args.iter().any(|s| s.is_empty()) {
        Err(format!(
            "expected {expected} operands, found {}",
            args.len()
        ))
    } else {
        Ok(())
    }
}
fn offset_mut(section: Section, sizes: &mut [u32; 3]) -> &mut u32 {
    &mut sizes[match section {
        Section::Code => 0,
        Section::Data => 1,
        Section::Bss => 2,
    }]
}
fn location(file: &str, line: u32, column: u32, error: impl std::fmt::Display) -> String {
    format!("{file}:{line}:{column}: {error}")
}
fn reference(
    expr: &str,
    constants: &BTreeMap<String, i64>,
    symbols: &BTreeMap<String, SectionReference>,
) -> Result<(Option<SectionReference>, i64), String> {
    match expression(expr)? {
        Expression::Number(v) => Ok((None, v)),
        Expression::Name(n, a) => {
            if let Some(v) = constants.get(&n) {
                Ok((None, v.checked_add(a).ok_or("constant overflow")?))
            } else {
                Ok((
                    Some(
                        symbols
                            .get(&n)
                            .ok_or_else(|| format!("undefined symbol '{n}'"))?
                            .clone(),
                    ),
                    a,
                ))
            }
        }
    }
}
/// Assemble without assigning a process's final physical addresses.
pub fn assemble(source: &str, file: &str) -> Result<Object, String> {
    let mut lines = Vec::new();
    let mut defs = BTreeMap::new();
    let mut entry_name = None;
    for (line, raw) in source.lines().enumerate() {
        let text = raw
            .split_once("//")
            .map_or(raw, |(s, _)| s)
            .split_once(';')
            .map_or_else(|| raw.split_once("//").map_or(raw, |(s, _)| s), |(s, _)| s);
        let text = text.trim();
        if text.is_empty() {
            continue;
        }
        let line = line as u32 + 1;
        let column = raw.find(text).unwrap_or(0) as u32 + 1;
        if let Some(rest) = text.strip_prefix(".const ") {
            let (name, value) = rest
                .split_once('=')
                .ok_or_else(|| location(file, line, column, "expected .const NAME = expression"))?;
            let name = name.trim();
            if !identifier(name)
                || defs
                    .insert(name.to_owned(), value.trim().to_owned())
                    .is_some()
            {
                return Err(location(
                    file,
                    line,
                    column,
                    "invalid or duplicate constant",
                ));
            }
        } else {
            lines.push((text.to_owned(), line, column));
        }
    }
    let mut constants = BTreeMap::new();
    for name in defs.keys() {
        constant(name, &defs, &mut constants, &mut BTreeSet::new())
            .map_err(|e| format!("{file}: constant {name}: {e}"))?;
    }
    let mut sizes = [0u32; 3];
    let mut section = Section::Code;
    let mut symbols = BTreeMap::new();
    let mut items = Vec::new();
    for (text, line, column) in lines {
        let result = (|| -> Result<(), String> {
            let mut text = text.as_str();
            if let Some((label, rest)) = text.split_once(':') {
                let label = label.trim();
                if !identifier(label)
                    || constants.contains_key(label)
                    || symbols
                        .insert(
                            label.to_owned(),
                            SectionReference {
                                section,
                                offset: *offset_mut(section, &mut sizes),
                            },
                        )
                        .is_some()
                {
                    return Err("invalid or duplicate label".into());
                }
                text = rest.trim();
                if text.is_empty() {
                    return Ok(());
                }
            }
            match text {
                ".code" => {
                    section = Section::Code;
                    return Ok(());
                }
                ".data" => {
                    section = Section::Data;
                    return Ok(());
                }
                ".bss" => {
                    section = Section::Bss;
                    return Ok(());
                }
                _ => (),
            }
            if let Some(rest) = text.strip_prefix(".entry ") {
                if entry_name.replace(rest.trim().to_owned()).is_some() {
                    return Err("duplicate .entry directive".into());
                }
                return Ok(());
            }
            let (head, args) = tokens(text);
            let offset = *offset_mut(section, &mut sizes);
            let length = match head {
                ".byte" | ".word" | ".ptr" => {
                    if section != Section::Data {
                        return Err(format!("{head} is valid only in .data"));
                    }
                    if args.is_empty() || args.iter().any(|s| s.is_empty()) {
                        return Err(format!("{head} needs at least one value"));
                    }
                    let width = if head == ".byte" {
                        1
                    } else if head == ".word" {
                        2
                    } else {
                        3
                    };
                    u32::try_from(args.len())
                        .map_err(|_| "too many values")?
                        .checked_mul(width)
                        .ok_or("section length overflow")?
                }
                ".space" => {
                    if section == Section::Code {
                        return Err(".space cannot create executable padding".into());
                    }
                    count(&args, 1)?;
                    ranged(immediate(args[0], &constants)?, 0, 0x1000000, "space size")?
                }
                ".align" => {
                    if section == Section::Code {
                        return Err(".align cannot create executable padding".into());
                    }
                    count(&args, 1)?;
                    let align = ranged(immediate(args[0], &constants)?, 1, 0x1000000, "alignment")?;
                    if !align.is_power_of_two() {
                        return Err("alignment must be a power of two".into());
                    }
                    (align - offset % align) % align
                }
                _ => {
                    if section != Section::Code {
                        return Err("instructions are valid only in .code".into());
                    }
                    if Opcode::parse(head).is_none() && !head.eq_ignore_ascii_case("PLI") {
                        return Err(format!("unknown instruction or directive '{head}'"));
                    }
                    4
                }
            };
            let end = offset
                .checked_add(length)
                .ok_or("section length overflow")?;
            if end > 0x1000000 {
                return Err("section exceeds physical REU size".into());
            }
            *offset_mut(section, &mut sizes) = end;
            items.push(Item {
                text: text.to_owned(),
                offset,
                line,
                column,
            });
            Ok(())
        })();
        result.map_err(|e| location(file, line, column, e))?;
    }
    let entry_name = entry_name.ok_or_else(|| format!("{file}: missing .entry directive"))?;
    let entry = symbols
        .get(&entry_name)
        .ok_or_else(|| format!("{file}: undefined entry '{entry_name}'"))?
        .clone();
    let mut object = Object {
        format: "COSOBJ1".into(),
        abi: ABI,
        compiler_version: format!("cosasm-{}", env!("CARGO_PKG_VERSION")),
        numeric_profile: NUMERIC_PROFILE.into(),
        code: vec![0; sizes[0] as usize],
        data: vec![0; sizes[1] as usize],
        bss_size: sizes[2],
        symbols,
        entry,
        relocations: vec![],
        source_map: vec![],
    };
    for item in items {
        let result = (|| -> Result<(), String> {
            let (head, args) = tokens(&item.text);
            if matches!(head, ".space" | ".align") {
                return Ok(());
            }
            if matches!(head, ".byte" | ".word" | ".ptr") {
                let width = if head == ".byte" {
                    1
                } else if head == ".word" {
                    2
                } else {
                    3
                };
                for (n, arg) in args.iter().enumerate() {
                    let offset = item.offset + n as u32 * width;
                    let (target, value) = reference(arg, &constants, &object.symbols)?;
                    let bits = if let Some(target) = target {
                        if width != 3 {
                            return Err("symbol addresses require .ptr (ABS24)".into());
                        }
                        object.relocations.push(Relocation {
                            kind: RelocationKind::Abs24,
                            section: Section::Data,
                            offset,
                            target,
                            addend: value,
                        });
                        0
                    } else {
                        ranged(value, 0, (1i64 << (width * 8)) - 1, "data value")?
                    };
                    for byte in 0..width {
                        object.data[(offset + byte) as usize] = (bits >> (byte * 8)) as u8;
                    }
                }
                return Ok(());
            }
            let (op, args) = if head.eq_ignore_ascii_case("PLI") {
                count(&args, 2)?;
                let p = reg(args[0], b'P', 3)?;
                (Opcode::from_byte(0x1c + p)?, vec![args[1]])
            } else {
                (Opcode::parse(head).ok_or("unknown opcode")?, args)
            };
            let mut i = Instruction {
                op,
                a: 0,
                b: 0,
                immediate: 0,
            };
            use OperandForm::*;
            match op.form() {
                Zero => count(&args, 0)?,
                Rr | Pp | Pr | Rp => {
                    count(&args, 2)?;
                    let (a, b) = match op.form() {
                        Rr => (b'R', b'R'),
                        Pp => (b'P', b'P'),
                        Pr => (b'P', b'R'),
                        _ => (b'R', b'P'),
                    };
                    i.a = reg(args[0], a, if a == b'R' { 7 } else { 3 })?;
                    i.b = reg(args[1], b, if b == b'R' { 7 } else { 3 })?;
                }
                Rp16 | Pp16 => {
                    count(&args, 3)?;
                    let prefix = if op.form() == Rp16 { b'R' } else { b'P' };
                    i.a = reg(args[0], prefix, if prefix == b'R' { 7 } else { 3 })?;
                    i.b = reg(args[1], b'P', 3)?;
                    i.immediate =
                        ranged(immediate(args[2], &constants)?, 0, 65535, "memory offset")?;
                }
                Ri16 | Shift => {
                    count(&args, 2)?;
                    i.a = reg(args[0], b'R', 7)?;
                    i.immediate = if op.form() == Shift {
                        ranged(immediate(args[1], &constants)?, 0, 15, "shift count")?
                    } else {
                        ranged(
                            immediate(args[1], &constants)?,
                            -32768,
                            65535,
                            "16-bit immediate",
                        )? & 65535
                    };
                }
                R | P => {
                    count(&args, 1)?;
                    let prefix = if op.form() == R { b'R' } else { b'P' };
                    i.a = reg(args[0], prefix, if prefix == b'R' { 7 } else { 3 })?;
                }
                Make => {
                    count(&args, 3)?;
                    i.a = reg(args[0], b'P', 3)?;
                    i.b = reg(args[1], b'R', 7)?;
                    i.immediate = reg(args[2], b'R', 7)? as u32;
                }
                Absolute => {
                    count(&args, 1)?;
                    i.a = match op {
                        Opcode::Pli0 => 0,
                        Opcode::Pli1 => 1,
                        Opcode::Pli2 => 2,
                        Opcode::Pli3 => 3,
                        _ => 0,
                    };
                    let (target, value) = reference(args[0], &constants, &object.symbols)?;
                    if let Some(target) = target {
                        object.relocations.push(Relocation {
                            kind: RelocationKind::Abs24,
                            section: Section::Code,
                            offset: item.offset + 1,
                            target,
                            addend: value,
                        });
                    } else {
                        i.immediate = ranged(value, 0, 0xffffff, "24-bit address")?;
                    }
                }
                BranchR | BranchP => {
                    count(&args, 3)?;
                    let prefix = if op.form() == BranchR { b'R' } else { b'P' };
                    let max = if prefix == b'R' { 7 } else { 3 };
                    i.a = reg(args[0], prefix, max)?;
                    i.b = reg(args[1], prefix, max)?;
                    let (target, value) = reference(args[2], &constants, &object.symbols)?;
                    if let Some(target) = target {
                        object.relocations.push(Relocation {
                            kind: RelocationKind::Rel16Insn,
                            section: Section::Code,
                            offset: item.offset,
                            target,
                            addend: value,
                        });
                    } else {
                        i.immediate =
                            ranged(value, -32768, 32767, "branch instruction displacement")?
                                & 65535;
                    }
                }
                Service => {
                    count(&args, 1)?;
                    i.a = ranged(immediate(args[0], &constants)?, 0, 255, "syscall ID")? as u8;
                }
                Trap => {
                    count(&args, 1)?;
                    i.immediate = ranged(immediate(args[0], &constants)?, 0, 65535, "TRAP code")?;
                }
            }
            let bytes = isa::encode(i)?;
            object.code[item.offset as usize..item.offset as usize + 4].copy_from_slice(&bytes);
            object.source_map.push(SourceLocation {
                address: item.offset,
                file: file.into(),
                line: item.line,
                column: item.column,
            });
            Ok(())
        })();
        result.map_err(|e| location(file, item.line, item.column, e))?;
    }
    object.validate().map_err(|e| format!("{file}: {e}"))?;
    Ok(object)
}
pub fn listing(object: &Object) -> Result<String, String> {
    let mut text = isa::disassemble(&object.code, 0)?;
    if !object.relocations.is_empty() {
        text.push_str("\nUnlinked relocations (displayed operand bytes are placeholders):\n");
        for rel in &object.relocations {
            text.push_str(&format!(
                "{:?}+${:X}: {:?} -> {:?}+${:X} {:+}\n",
                rel.section,
                rel.offset,
                rel.kind,
                rel.target.section,
                rel.target.offset,
                rel.addend
            ));
        }
    }
    Ok(text)
}
