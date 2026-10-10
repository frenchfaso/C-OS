//! Minimal static COSPACK1 linking into the shared 16 MiB physical REU.
use crate::{
    isa::{self, Opcode, OperandForm},
    object::*,
    vm::Range,
};
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::{Component, Path},
};
pub const REU_SIZE: u32 = 0x1000000;
pub const SYSTEM_RESERVE: u32 = 0x040000;
pub const SEED_LIMIT: u32 = 0x010000;
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "mode", rename_all = "lowercase", deny_unknown_fields)]
pub enum StorageConfig {
    Discover { directory: String, marker: String },
    Explicit { root: String },
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AppInput {
    pub id: u16,
    pub name: String,
    pub object: String,
    pub arena_start: u32,
    pub arena_size: u32,
    pub stack_size: u32,
    pub heap_min: u32,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PackInput {
    pub format: String,
    pub abi: u16,
    pub numeric_profile: String,
    pub target: String,
    pub storage: StorageConfig,
    pub apps: Vec<AppInput>,
}
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct SectionRange {
    pub start: u32,
    pub length: u32,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LinkedApp {
    pub id: u16,
    pub name: String,
    pub source: String,
    pub arena: Range,
    pub code: Range,
    pub data: SectionRange,
    pub bss: SectionRange,
    pub heap: Range,
    pub stack: Range,
    pub entry: u32,
    pub data_seed: SectionRange,
    pub symbols: BTreeMap<String, u32>,
    pub source_map: Vec<SourceLocation>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LinkedManifest {
    pub format: String,
    pub abi: u16,
    pub numeric_profile: String,
    pub target: String,
    pub build_tag: u32,
    pub reu_image: String,
    pub system_reserve: Range,
    pub storage: StorageConfig,
    pub apps: Vec<LinkedApp>,
}
#[derive(Debug)]
pub struct PackOutput {
    pub manifest: LinkedManifest,
    pub image: Vec<u8>,
    pub constants: String,
    pub map: String,
}
fn align(value: u32) -> Result<u32, String> {
    value
        .checked_add(127)
        .map(|n| n & !127)
        .ok_or_else(|| "section placement overflow".into())
}
fn aligned(value: u32, name: &str, nonempty: bool) -> Result<(), String> {
    if !value.is_multiple_of(128) || (nonempty && value < 128) {
        Err(format!(
            "{name} must be a multiple of 128{}",
            if nonempty { " and at least 128" } else { "" }
        ))
    } else {
        Ok(())
    }
}
fn path_in_root(root: &Path, input: &str) -> Result<std::path::PathBuf, String> {
    let relative = Path::new(input);
    if input.is_empty()
        || relative
            .components()
            .any(|c| !matches!(c, Component::Normal(_)))
    {
        return Err(format!(
            "host path '{input}' must be relative to the declared C-OS root without '.' or '..'"
        ));
    }
    let canonical_root = root.canonicalize().map_err(|e| e.to_string())?;
    let path = canonical_root
        .join(relative)
        .canonicalize()
        .map_err(|e| format!("{input}: {e}"))?;
    if !path.starts_with(&canonical_root) {
        return Err(format!("host path '{input}' escapes the declared root"));
    }
    Ok(path)
}
impl PackInput {
    pub fn validate(&self) -> Result<(), String> {
        if self.abi != ABI {
            return Err(format!("pack requires ABI {ABI}, got ABI {}", self.abi));
        }
        if self.format != "COSPACK1"
            || self.numeric_profile != NUMERIC_PROFILE
            || self.target != "c64u-pal-upic320"
        {
            return Err(format!(
                "pack requires COSPACK1, ABI {ABI}, {NUMERIC_PROFILE}, c64u-pal-upic320"
            ));
        }
        match &self.storage {
            StorageConfig::Discover { directory, marker } => {
                if directory != "cos" || marker != ".cos-volume" {
                    return Err(
                        "M1 discovery installation uses directory 'cos' and marker '.cos-volume'"
                            .into(),
                    );
                }
            }
            StorageConfig::Explicit { root } => {
                if !root.starts_with('/')
                    || !root.is_ascii()
                    || root.bytes().any(|c| c < 32 || c == 127 || c == b'\\')
                    || root.split('/').any(|c| c == ".." || c == ".")
                    || root.len() > 127
                {
                    return Err("explicit storage root must be an absolute ASCII path of at most 127 bytes without traversal".into());
                }
            }
        }
        if self.apps.len() > 4 {
            return Err("pack supports at most four applications".into());
        }
        let mut ids = BTreeSet::new();
        let mut ranges = Vec::new();
        for app in &self.apps {
            if app.id == 0 || !ids.insert(app.id) {
                return Err(format!(
                    "application ID {} must be distinct and nonzero",
                    app.id
                ));
            }
            if app.name.is_empty()
                || app.name.len() > 15
                || !app.name.bytes().all(|c| (32..=126).contains(&c))
            {
                return Err("application names must contain 1..15 printable ASCII bytes".into());
            }
            aligned(app.arena_start, "arena_start", false)?;
            aligned(app.arena_size, "arena_size", true)?;
            aligned(app.stack_size, "stack_size", true)?;
            aligned(app.heap_min, "heap_min", true)?;
            let end = (app.arena_start as u64) + (app.arena_size as u64);
            if app.arena_start < SYSTEM_RESERVE || end > REU_SIZE as u64 {
                return Err(format!(
                    "app {} arena exceeds allocatable shared REU $040000..$FFFFFF",
                    app.id
                ));
            }
            if app.stack_size >= app.arena_size {
                return Err(format!(
                    "app {} stack leaves no room for code and heap",
                    app.id
                ));
            }
            if ranges
                .iter()
                .any(|&(start, last)| start < end && (app.arena_start as u64) < last)
            {
                return Err("application arenas overlap (including cache-line ownership)".into());
            }
            ranges.push((app.arena_start as u64, end));
        }
        Ok(())
    }
}
fn address(reference: &SectionReference, app: &LinkedApp, addend: i64) -> Result<u32, String> {
    let start = match reference.section {
        Section::Code => app.code.first,
        Section::Data => app.data.start,
        Section::Bss => app.bss.start,
    };
    let target = (start as i64)
        .checked_add(reference.offset as i64)
        .and_then(|n| n.checked_add(addend))
        .ok_or("relocation arithmetic overflow")?;
    if target < app.arena.first as i64 || target > app.arena.last as i64 || target > 0xffffff {
        return Err(format!(
            "relocation address {target} is outside app {} arena",
            app.id
        ));
    }
    Ok(target as u32)
}
fn target_valid(target: i64, app: &LinkedApp) -> bool {
    target >= app.code.first as i64
        && target % 4 == 0
        && target
            .checked_add(3)
            .is_some_and(|end| end <= app.code.last as i64)
}
/// Link one checked object with no virtual base translation or dynamic linker.
pub fn link_object(
    input: &AppInput,
    object: &Object,
    seed: u32,
) -> Result<(LinkedApp, Vec<u8>, Vec<u8>), String> {
    object.validate()?;
    let single = PackInput {
        format: "COSPACK1".into(),
        abi: ABI,
        numeric_profile: NUMERIC_PROFILE.into(),
        target: "c64u-pal-upic320".into(),
        storage: StorageConfig::Discover {
            directory: "cos".into(),
            marker: ".cos-volume".into(),
        },
        apps: vec![input.clone()],
    };
    single.validate()?;
    if seed < 128
        || !seed.is_multiple_of(128)
        || seed
            .checked_add(object.data.len() as u32)
            .is_none_or(|end| end > SEED_LIMIT)
    {
        return Err("initialization seed exceeds or misaligns boot reserve".into());
    }
    let end = input
        .arena_start
        .checked_add(input.arena_size)
        .ok_or("arena arithmetic overflow")?;
    let code_end = input
        .arena_start
        .checked_add(object.code.len() as u32)
        .ok_or("code placement overflow")?;
    let data_start = align(code_end)?;
    let bss_start = align(
        data_start
            .checked_add(object.data.len() as u32)
            .ok_or("data placement overflow")?,
    )?;
    let heap_first = align(
        bss_start
            .checked_add(object.bss_size)
            .ok_or("BSS placement overflow")?,
    )?;
    let stack_first = end
        .checked_sub(input.stack_size)
        .ok_or("stack placement underflow")?;
    if stack_first < heap_first || stack_first - heap_first < input.heap_min {
        return Err(format!(
            "app {} code/data/BSS/stack leave less than heap_min {}",
            input.id, input.heap_min
        ));
    }
    let mut app = LinkedApp {
        id: input.id,
        name: input.name.clone(),
        source: input.object.clone(),
        arena: Range {
            first: input.arena_start,
            last: end - 1,
        },
        code: Range {
            first: input.arena_start,
            last: code_end - 1,
        },
        data: SectionRange {
            start: data_start,
            length: object.data.len() as u32,
        },
        bss: SectionRange {
            start: bss_start,
            length: object.bss_size,
        },
        heap: Range {
            first: heap_first,
            last: stack_first - 1,
        },
        stack: Range {
            first: stack_first,
            last: end - 1,
        },
        entry: 0,
        data_seed: SectionRange {
            start: seed,
            length: object.data.len() as u32,
        },
        symbols: BTreeMap::new(),
        source_map: object.source_map.clone(),
    };
    app.entry = address(&object.entry, &app, 0)?;
    for (name, symbol) in &object.symbols {
        app.symbols.insert(name.clone(), address(symbol, &app, 0)?);
    }
    for loc in &mut app.source_map {
        loc.address = loc
            .address
            .checked_add(input.arena_start)
            .ok_or("source map overflow")?;
    }
    let mut code = object.code.clone();
    let mut data = object.data.clone();
    for rel in &object.relocations {
        let target = address(&rel.target, &app, rel.addend)?;
        let buffer = match rel.section {
            Section::Code => &mut code,
            Section::Data => &mut data,
            Section::Bss => return Err("cannot relocate BSS".into()),
        };
        match rel.kind {
            RelocationKind::Abs24 => {
                buffer[rel.offset as usize..rel.offset as usize + 3]
                    .copy_from_slice(&target.to_le_bytes()[..3]);
            }
            RelocationKind::Rel16Insn => {
                let pc = input.arena_start + rel.offset;
                if !target_valid(target as i64, &app) {
                    return Err(
                        "relative branch relocation target must be an aligned code instruction"
                            .into(),
                    );
                }
                let bytes = (target as i64) - (pc as i64 + 4);
                if bytes % 4 != 0 {
                    return Err("relative branch displacement is not instruction-aligned".into());
                }
                let delta = bytes / 4;
                let delta = i16::try_from(delta)
                    .map_err(|_| "REL16_INSN displacement exceeds signed 16 bits")?;
                buffer[rel.offset as usize + 2..rel.offset as usize + 4]
                    .copy_from_slice(&delta.to_le_bytes());
            }
        }
    }
    for (n, bytes) in code.chunks_exact(4).enumerate() {
        let instruction = isa::decode(bytes.try_into().unwrap())?;
        let pc = app.code.first + n as u32 * 4;
        let target = match instruction.op {
            Opcode::Jmp | Opcode::Call => Some(instruction.immediate as i64),
            _ if matches!(
                instruction.op.form(),
                OperandForm::BranchR | OperandForm::BranchP
            ) =>
            {
                Some(pc as i64 + 4 + 4 * (instruction.immediate as u16 as i16 as i64))
            }
            _ => None,
        };
        if let Some(target) = target
            && !target_valid(target, &app)
        {
            return Err(format!(
                "app {} static control-flow target ${target:X} at ${pc:06X} is outside aligned code",
                app.id
            ));
        }
    }
    Ok((app, code, data))
}
pub fn pack(root: &Path, input: &PackInput, build_tag: u32) -> Result<PackOutput, String> {
    input.validate()?;
    let mut image = vec![0u8; REU_SIZE as usize];
    image[0..8].copy_from_slice(b"COSREU01");
    image[8..12].copy_from_slice(&build_tag.to_le_bytes());
    image[12..14].copy_from_slice(&ABI.to_le_bytes());
    image[14] = input.apps.len() as u8;
    let mut apps = Vec::new();
    let mut seed = 128u32;
    for app in &input.apps {
        let path = path_in_root(root, &app.object)?;
        let object: Object = read_json(&path)?;
        let seed_end = seed
            .checked_add(object.data.len() as u32)
            .ok_or("seed length overflow")?;
        if seed_end > SEED_LIMIT {
            return Err(format!(
                "app {} data seed ends at ${seed_end:06X}, exceeding initial reserve ${SEED_LIMIT:06X}; {} bytes available",
                app.id,
                SEED_LIMIT - seed
            ));
        }
        let (linked, code, data) =
            link_object(app, &object, seed).map_err(|e| format!("{}: {e}", app.object))?;
        image[linked.code.first as usize..linked.code.first as usize + code.len()]
            .copy_from_slice(&code);
        image[linked.data.start as usize..linked.data.start as usize + data.len()]
            .copy_from_slice(&data);
        image[seed as usize..seed_end as usize].copy_from_slice(&data);
        seed = align(seed_end)?;
        apps.push(linked);
    }
    let manifest = LinkedManifest {
        format: "COSPACK1".into(),
        abi: ABI,
        numeric_profile: NUMERIC_PROFILE.into(),
        target: input.target.clone(),
        build_tag,
        reu_image: String::new(),
        system_reserve: Range {
            first: 0,
            last: SYSTEM_RESERVE - 1,
        },
        storage: input.storage.clone(),
        apps,
    };
    let mut constants = format!(
        "// Generated C-OS static pack descriptors; inclusive bounds.\n.const COS_BUILD_TAG = ${build_tag:08x}\n.const COS_ABI = {ABI}\n.const COS_APP_COUNT = {}\n.const COS_SYSTEM_LAST = $03ffff\n",
        manifest.apps.len()
    );
    let mut map = format!(
        "C-OS M1 static REU map\nBuild tag: ${build_tag:08X}; ABI {ABI}; {NUMERIC_PROFILE}\nPhysical REU: 16777216 bytes shared\nSystem reservation: $000000..$03FFFF (262144 bytes)\nApplications: $040000..$FFFFFF (16515072 bytes total available)\nHeader: $000000..$00000F; seed area allocated through ${:06X}\nThis host-only M1 pack has no resident native kernel images or boot assets.\n",
        seed.saturating_sub(1)
    );
    for app in &manifest.apps {
        let prefix = format!("COS_APP_{}", app.id);
        constants.push_str(&format!(
            "\n.const {prefix}_PID = {}\n.const {prefix}_ENTRY = ${:06x}\n",
            app.id, app.entry
        ));
        for (name, range) in [
            ("ARENA", app.arena),
            ("CODE", app.code),
            ("HEAP", app.heap),
            ("STACK", app.stack),
        ] {
            constants.push_str(&format!(
                ".const {prefix}_{name}_FIRST = ${:06x}\n.const {prefix}_{name}_LAST = ${:06x}\n",
                range.first, range.last
            ));
            map.push_str(&format!(
                "App {} {} {name}: ${:06X}..${:06X} ({} bytes)\n",
                app.id,
                app.name,
                range.first,
                range.last,
                range.last - range.first + 1
            ));
        }
        for (name, range) in [
            ("DATA", app.data),
            ("BSS", app.bss),
            ("DATA_SEED", app.data_seed),
        ] {
            constants.push_str(&format!(
                ".const {prefix}_{name}_START = ${:06x}\n.const {prefix}_{name}_LENGTH = {}\n",
                range.start, range.length
            ));
            map.push_str(&format!(
                "App {} {name}: start=${:06X}, length={}\n",
                app.id, range.start, range.length
            ));
        }
        map.push_str(&format!(
            "App {} entry: ${:06X}; no compiler frames or SDK imports (hand assembly)\n",
            app.id, app.entry
        ));
    }
    manifest.validate()?;
    Ok(PackOutput {
        manifest,
        image,
        constants,
        map,
    })
}
/// Deterministic FNV-1a build identity over input and object bytes; not a signature.
pub fn build_tag(root: &Path, input: &PackInput) -> Result<u32, String> {
    let mut hash = 0x811c9dc5u32;
    let mut bytes = serde_json::to_vec(input).map_err(|e| e.to_string())?;
    for app in &input.apps {
        bytes.extend(std::fs::read(path_in_root(root, &app.object)?).map_err(|e| e.to_string())?);
    }
    for byte in bytes {
        hash = (hash ^ byte as u32).wrapping_mul(0x01000193);
    }
    Ok(hash)
}

impl LinkedManifest {
    /// Verify every container header field before any reader trusts image bytes.
    pub fn validate_image(&self, image: &[u8]) -> Result<(), String> {
        self.validate()?;
        if image.len() != REU_SIZE as usize {
            return Err("REU image must contain exactly 16777216 shared bytes".into());
        }
        let abi = u16::from_le_bytes(image[12..14].try_into().unwrap());
        if abi != ABI {
            return Err(format!("REU image requires ABI {ABI}, got ABI {abi}"));
        }
        if &image[..8] != b"COSREU01"
            || u32::from_le_bytes(image[8..12].try_into().unwrap()) != self.build_tag
            || usize::from(image[14]) != self.apps.len()
            || image[15] != 0
        {
            return Err(
                "REU header, build tag or application count does not match the manifest".into(),
            );
        }
        Ok(())
    }
    /// Validate a serialized map independently before a runner trusts its bounds.
    pub fn validate(&self) -> Result<(), String> {
        let inputs = PackInput {
            format: self.format.clone(),
            abi: self.abi,
            numeric_profile: self.numeric_profile.clone(),
            target: self.target.clone(),
            storage: self.storage.clone(),
            apps: self
                .apps
                .iter()
                .map(|app| AppInput {
                    id: app.id,
                    name: app.name.clone(),
                    object: app.source.clone(),
                    arena_start: app.arena.first,
                    arena_size: app
                        .arena
                        .last
                        .checked_sub(app.arena.first)
                        .and_then(|n| n.checked_add(1))
                        .unwrap_or(0),
                    stack_size: app
                        .stack
                        .last
                        .checked_sub(app.stack.first)
                        .and_then(|n| n.checked_add(1))
                        .unwrap_or(0),
                    heap_min: 128,
                })
                .collect(),
        };
        inputs.validate()?;
        if self.system_reserve.first != 0 || self.system_reserve.last != SYSTEM_RESERVE - 1 {
            return Err("linked manifest has an incompatible system reserve".into());
        }
        let mut seeds: Vec<(u32, u32)> = Vec::new();
        for app in &self.apps {
            for (name, range) in [("code", app.code), ("heap", app.heap), ("stack", app.stack)] {
                if range.first > range.last
                    || range.first < app.arena.first
                    || range.last > app.arena.last
                {
                    return Err(format!("app {} invalid {name} bounds", app.id));
                }
                aligned(range.first, name, false)?;
            }
            if app.code.first != app.arena.first
                || !(app.code.last - app.code.first + 1).is_multiple_of(4)
                || !target_valid(app.entry as i64, app)
            {
                return Err(format!("app {} invalid code or entry", app.id));
            }
            let data_start = align(app.code.last.checked_add(1).ok_or("code end overflow")?)?;
            let data_end = app
                .data
                .start
                .checked_add(app.data.length)
                .ok_or("data end overflow")?;
            let bss_start = align(data_end)?;
            let bss_end = app
                .bss
                .start
                .checked_add(app.bss.length)
                .ok_or("BSS end overflow")?;
            if app.data.start != data_start
                || app.bss.start != bss_start
                || app.heap.first != align(bss_end)?
                || app.heap.last.checked_add(1) != Some(app.stack.first)
                || app.stack.last != app.arena.last
                || app.heap.last - app.heap.first + 1 < 128
            {
                return Err(format!(
                    "app {} section placement or heap is inconsistent",
                    app.id
                ));
            }
            if app.data_seed.length != app.data.length
                || app.data_seed.start < 128
                || !app.data_seed.start.is_multiple_of(128)
            {
                return Err(format!("app {} invalid initialization seed", app.id));
            }
            let seed_end = app
                .data_seed
                .start
                .checked_add(app.data_seed.length)
                .ok_or("seed overflow")?;
            if seed_end > SEED_LIMIT {
                return Err(format!(
                    "app {} initialization seed exceeds boot reserve",
                    app.id
                ));
            }
            if app.data_seed.length > 0 {
                if seeds
                    .iter()
                    .any(|&(start, end)| start < seed_end && app.data_seed.start < end)
                {
                    return Err("overlapping initialization seeds".into());
                }
                seeds.push((app.data_seed.start, seed_end));
            }
            for address in app.symbols.values() {
                if *address < app.arena.first || *address > app.arena.last {
                    return Err("linked symbol outside arena".into());
                }
            }
            for loc in &app.source_map {
                if !target_valid(loc.address as i64, app) || loc.line == 0 || loc.column == 0 {
                    return Err("invalid linked source map".into());
                }
            }
        }
        Ok(())
    }
}
