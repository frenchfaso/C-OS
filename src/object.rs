//! Host-only COSOBJ1 relocatable objects. No target JSON parser is required.
use crate::isa;
pub use crate::{ABI, NUMERIC_PROFILE};
use serde::{Deserialize, Serialize};
use std::{collections::BTreeMap, fs, path::Path};
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Section {
    Code,
    Data,
    Bss,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SectionReference {
    pub section: Section,
    pub offset: u32,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum RelocationKind {
    #[serde(rename = "ABS24")]
    Abs24,
    #[serde(rename = "REL16_INSN")]
    Rel16Insn,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Relocation {
    pub kind: RelocationKind,
    pub section: Section,
    pub offset: u32,
    pub target: SectionReference,
    pub addend: i64,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceLocation {
    pub address: u32,
    pub file: String,
    pub line: u32,
    pub column: u32,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Object {
    pub format: String,
    pub abi: u16,
    pub compiler_version: String,
    pub numeric_profile: String,
    pub code: Vec<u8>,
    pub data: Vec<u8>,
    pub bss_size: u32,
    pub symbols: BTreeMap<String, SectionReference>,
    pub entry: SectionReference,
    pub relocations: Vec<Relocation>,
    pub source_map: Vec<SourceLocation>,
}
impl Object {
    pub fn validate(&self) -> Result<(), String> {
        if self.format != "COSOBJ1" {
            return Err("expected COSOBJ1 object format".into());
        }
        if self.abi != ABI {
            return Err(format!("object requires ABI {ABI}, got ABI {}", self.abi));
        }
        if self.numeric_profile != NUMERIC_PROFILE {
            return Err(format!("object requires {NUMERIC_PROFILE}"));
        }
        if self.code.is_empty() || !self.code.len().is_multiple_of(4) {
            return Err("object code must be nonempty and a multiple of four bytes".into());
        }
        if self.code.len() > 0x1000000 || self.data.len() > 0x1000000 || self.bss_size > 0x1000000 {
            return Err("object section exceeds physical REU size".into());
        }
        for (n, bytes) in self.code.chunks_exact(4).enumerate() {
            isa::decode(bytes.try_into().unwrap())
                .map_err(|e| format!("object code +${:X}: {e}", n * 4))?;
        }
        if self.entry.section != Section::Code
            || !self.entry.offset.is_multiple_of(4)
            || self.entry.offset as usize >= self.code.len()
        {
            return Err("entry must refer to an aligned code instruction".into());
        }
        for (name, symbol) in &self.symbols {
            let length = self.section_len(symbol.section);
            if symbol.offset as usize > length {
                return Err(format!("symbol {name} is beyond its section"));
            }
        }
        let mut patches = Vec::new();
        for rel in &self.relocations {
            let count = match rel.kind {
                RelocationKind::Abs24 => 3,
                RelocationKind::Rel16Insn => 4,
            };
            if rel.section == Section::Bss
                || (rel.offset as usize)
                    .checked_add(count)
                    .is_none_or(|end| end > self.section_len(rel.section))
            {
                return Err("relocation patch is outside initialized section".into());
            }
            if rel.target.offset as usize > self.section_len(rel.target.section) {
                return Err("relocation target is outside its section".into());
            }
            if rel.kind == RelocationKind::Rel16Insn {
                if rel.section != Section::Code
                    || !rel.offset.is_multiple_of(4)
                    || rel.target.section != Section::Code
                    || !rel.target.offset.is_multiple_of(4)
                {
                    return Err("REL16_INSN requires aligned code source and target".into());
                }
                let op = isa::decode(
                    self.code[rel.offset as usize..rel.offset as usize + 4]
                        .try_into()
                        .unwrap(),
                )?
                .op;
                if !matches!(
                    op.form(),
                    isa::OperandForm::BranchR | isa::OperandForm::BranchP
                ) {
                    return Err("REL16_INSN must patch a relative branch".into());
                }
            } else if rel.section == Section::Code {
                if rel.offset % 4 != 1 {
                    return Err(
                        "code ABS24 must patch the operand of an absolute instruction".into(),
                    );
                }
                let op = isa::decode(
                    self.code[rel.offset as usize - 1..rel.offset as usize + 3]
                        .try_into()
                        .unwrap(),
                )?
                .op;
                if op.form() != isa::OperandForm::Absolute {
                    return Err("code ABS24 must patch an absolute instruction".into());
                }
            }
            let start = rel.offset as usize
                + if rel.kind == RelocationKind::Rel16Insn {
                    2
                } else {
                    0
                };
            let end = start
                + if rel.kind == RelocationKind::Rel16Insn {
                    2
                } else {
                    3
                };
            if patches
                .iter()
                .any(|&(s, a, b)| s == rel.section && a < end && start < b)
            {
                return Err("overlapping relocations".into());
            }
            patches.push((rel.section, start, end));
        }
        for loc in &self.source_map {
            if !loc.address.is_multiple_of(4)
                || loc.address as usize >= self.code.len()
                || loc.line == 0
                || loc.column == 0
            {
                return Err("invalid object source map location".into());
            }
        }
        Ok(())
    }
    pub fn section_len(&self, section: Section) -> usize {
        match section {
            Section::Code => self.code.len(),
            Section::Data => self.data.len(),
            Section::Bss => self.bss_size as usize,
        }
    }
}
pub fn read_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<T, String> {
    let contents = fs::read(path).map_err(|e| format!("{}: {e}", path.display()))?;
    serde_json::from_slice(&contents).map_err(|e| format!("{}: {e}", path.display()))
}
/// Write a complete file atomically; an error cannot publish a partial JSON artifact.
pub fn write_json<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    let mut bytes = serde_json::to_vec_pretty(value).map_err(|e| e.to_string())?;
    bytes.push(b'\n');
    write_atomic(path, &bytes)
}
pub fn write_atomic(path: &Path, bytes: &[u8]) -> Result<(), String> {
    if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let temp = path.with_extension(format!("{}.tmp", std::process::id()));
    fs::write(&temp, bytes).map_err(|e| format!("{}: {e}", temp.display()))?;
    fs::rename(&temp, path).map_err(|e| {
        let _ = fs::remove_file(&temp);
        format!("{}: {e}", path.display())
    })
}
