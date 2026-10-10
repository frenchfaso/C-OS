//! Functional ABI 2 reference VM. Memory is one shared, physical 16 MiB REU.
use crate::isa::{Opcode, decode};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::sync::atomic::{AtomicU64, Ordering};

// Host-only ownership identity; absent from ISA state and comparison snapshots.
static NEXT_VM_IDENTITY: AtomicU64 = AtomicU64::new(1);

pub const REU_SIZE: usize = 0x1000000;
pub const APP_FIRST: u32 = 0x040000;
pub use crate::ABI;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Range {
    pub first: u32,
    pub last: u32,
}

impl Range {
    pub fn contains(self, address: u32, last: u32) -> bool {
        address >= self.first && last <= self.last
    }
    pub fn overlaps(self, other: Self) -> bool {
        self.first <= other.last && other.first <= self.last
    }
    pub fn len(self) -> u32 {
        self.last - self.first + 1
    }
    pub fn is_empty(self) -> bool {
        self.last < self.first
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Bounds {
    pub arena: Range,
    pub code: Range,
    pub heap: Range,
    pub stack: Range,
}

impl Bounds {
    pub fn validate(self) -> Result<(), String> {
        for (name, range) in [
            ("arena", self.arena),
            ("code", self.code),
            ("heap", self.heap),
            ("stack", self.stack),
        ] {
            if range.is_empty() || range.last >= REU_SIZE as u32 {
                return Err(format!("invalid {name} bounds"));
            }
            if range.first % 128 != 0 {
                return Err(format!("{name} start must be aligned to 128 bytes"));
            }
            if !self.arena.contains(range.first, range.last) {
                return Err(format!("{name} is outside the arena"));
            }
        }
        if self.arena.first < APP_FIRST || !self.arena.len().is_multiple_of(128) {
            return Err(
                "arena must exclude the 256 KiB system reservation and have an aligned size".into(),
            );
        }
        if !self.code.len().is_multiple_of(4) {
            return Err("code length must be a positive multiple of four".into());
        }
        if self.heap.len() < 128 || self.stack.len() < 128 || !self.stack.len().is_multiple_of(128)
        {
            return Err(
                "heap and stack need at least 128 bytes; stack size must be aligned".into(),
            );
        }
        if self.code.overlaps(self.heap)
            || self.code.overlaps(self.stack)
            || self.heap.overlaps(self.stack)
        {
            return Err("code, heap and stack must not overlap".into());
        }
        Ok(())
    }
}

pub struct Memory {
    bytes: Vec<u8>,
    unavailable: BTreeSet<u32>,
}

impl Default for Memory {
    fn default() -> Self {
        Self::new()
    }
}

impl Memory {
    pub fn new() -> Self {
        Self {
            bytes: vec![0; REU_SIZE],
            unavailable: BTreeSet::new(),
        }
    }
    pub fn read(&self, address: u32, length: u32) -> Result<&[u8], String> {
        let end = u64::from(address) + u64::from(length);
        if end > REU_SIZE as u64 {
            return Err("physical REU read exceeds 16 MiB".into());
        }
        Ok(&self.bytes[address as usize..end as usize])
    }
    pub fn write(&mut self, address: u32, bytes: &[u8]) -> Result<(), String> {
        let end = u64::from(address) + bytes.len() as u64;
        if end > REU_SIZE as u64 {
            return Err("physical REU write exceeds 16 MiB".into());
        }
        self.bytes[address as usize..end as usize].copy_from_slice(bytes);
        Ok(())
    }
    /// Withhold a cache line for deterministic M2 boundary comparisons.
    /// This models availability only, not a cache or DMA timing.
    pub fn hold_line(&mut self, address: u32) {
        self.unavailable.insert(address & !127);
    }
    pub fn release_line(&mut self, address: u32) {
        self.unavailable.remove(&(address & !127));
    }
    pub(crate) fn missing(&self, address: u32, length: u32) -> Option<u32> {
        if length == 0 {
            return None;
        }
        self.unavailable
            .range((address & !127)..=((address + length - 1) & !127))
            .next()
            .copied()
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Context {
    pub r: [u16; 8],
    pub p: [u32; 4],
    pub pc: u32,
    pub sp: u32,
    pub fuel: u8,
    pub retired: u64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum FaultCause {
    Decode(String),
    InvalidPc,
    AddressOverflow,
    OutOfArena,
    ReadOnly,
    StackOverflow,
    StackUnderflow,
    InvalidSp,
    Trap(u16),
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Fault {
    pub pid: u16,
    pub pc: u32,
    pub cause: FaultCause,
    pub address: Option<u32>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Syscall {
    pub token: u64,
    pub id: u8,
    pub pc: u32,
    pub resume_pc: Option<u32>,
    pub r: [u16; 8],
    pub p: [u32; 4],
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Outcome {
    FuelExhausted,
    Yield,
    Syscall(Syscall),
    WaitMemory { line: u32 },
    Fault(Fault),
    Stopped { code: u16 },
}

#[derive(Clone, Debug)]
pub struct ReturnValues {
    pub status: u16,
    pub r: [Option<u16>; 8],
    pub p: [Option<u32>; 4],
}

impl ReturnValues {
    pub fn status(status: u16) -> Self {
        Self {
            status,
            r: [None; 8],
            p: [None; 4],
        }
    }
}

pub struct Vm {
    pub state: Context,
    pub bounds: Bounds,
    pub pid: u16,
    pending: Option<Syscall>,
    terminal: Option<Outcome>,
    serial: u64,
    pub(crate) identity: u64,
}

impl Vm {
    pub fn new(
        pid: u16,
        bounds: Bounds,
        entry: u32,
        data_start: Option<u32>,
    ) -> Result<Self, String> {
        bounds.validate()?;
        if pid == 0 {
            return Err("PID must be nonzero".into());
        }
        if !entry.is_multiple_of(4) || entry > 0xfffffc || !bounds.code.contains(entry, entry + 3) {
            return Err("entry must select a complete aligned instruction in code".into());
        }
        if let Some(address) = data_start
            && (address % 128 != 0
                || !bounds.arena.contains(address, address)
                || bounds.code.contains(address, address)
                || bounds.heap.contains(address, address)
                || bounds.stack.contains(address, address))
        {
            return Err(
                "initialized data start must be aligned and outside code/heap/stack".into(),
            );
        }
        let mut r = [0; 8];
        r[0] = pid;
        r[1] = ABI;
        Ok(Self {
            state: Context {
                r,
                p: [
                    bounds.heap.first,
                    bounds.heap.last,
                    data_start.unwrap_or(0),
                    bounds.stack.last,
                ],
                pc: entry,
                sp: bounds.stack.last,
                fuel: 128,
                retired: 0,
            },
            bounds,
            pid,
            pending: None,
            terminal: None,
            serial: 0,
            identity: NEXT_VM_IDENTITY
                .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |id| id.checked_add(1))
                .map_err(|_| "host VM identity space exhausted")?,
        })
    }

    pub fn refuel(&mut self, fuel: u8) {
        self.state.fuel = fuel;
    }

    pub fn pending_syscall(&self) -> Option<&Syscall> {
        self.pending.as_ref()
    }

    pub fn complete_syscall(&mut self, token: u64, values: ReturnValues) -> Result<(), String> {
        let call = self.pending.as_ref().ok_or("no pending syscall")?;
        if call.token != token || call.resume_pc.is_none() {
            return Err("invalid syscall completion token or nonreturning call".into());
        }
        if values.r[0].is_some() {
            return Err("R0 is specified by status, not an output field".into());
        }
        if values.p.iter().flatten().any(|&p| p > 0xffffff) {
            return Err("syscall pointer output exceeds 24 bits".into());
        }
        self.state.r[0] = values.status;
        for i in 1..8 {
            if let Some(r) = values.r[i] {
                self.state.r[i] = r;
            }
        }
        for i in 0..4 {
            if let Some(p) = values.p[i] {
                self.state.p[i] = p;
            }
        }
        self.pending = None;
        Ok(())
    }

    pub fn exit_syscall(&mut self, token: u64, code: u16) -> Result<(), String> {
        let call = self.pending.as_ref().ok_or("no pending syscall")?;
        if call.token != token || call.id != 0 {
            return Err("invalid PROC_EXIT completion".into());
        }
        self.pending = None;
        self.terminal = Some(Outcome::Stopped { code });
        Ok(())
    }

    /// Checks a complete guest range before native service effects. Zero length does not dereference.
    pub fn check_access(&self, address: u32, length: u32, write: bool) -> Result<(), FaultCause> {
        if length == 0 {
            return Ok(());
        }
        let last = u64::from(address) + u64::from(length) - 1;
        if last > 0xffffff {
            return Err(FaultCause::AddressOverflow);
        }
        if !self.bounds.arena.contains(address, last as u32) {
            return Err(FaultCause::OutOfArena);
        }
        if write
            && self.bounds.code.overlaps(Range {
                first: address,
                last: last as u32,
            })
        {
            return Err(FaultCause::ReadOnly);
        }
        Ok(())
    }

    fn pc_valid(&self, pc: i64) -> Result<u32, (FaultCause, Option<u32>)> {
        if !(0..=0xffffff).contains(&pc) {
            return Err((FaultCause::AddressOverflow, u32::try_from(pc).ok()));
        }
        let pc = pc as u32;
        if !pc.is_multiple_of(4) || pc > 0xfffffc || !self.bounds.code.contains(pc, pc + 3) {
            return Err((FaultCause::InvalidPc, Some(pc)));
        }
        Ok(pc)
    }

    fn fail(&mut self, cause: FaultCause, address: Option<u32>) -> Outcome {
        let outcome = Outcome::Fault(Fault {
            pid: self.pid,
            pc: self.state.pc,
            cause,
            address,
        });
        self.terminal = Some(outcome.clone());
        outcome
    }

    pub fn run(&mut self, memory: &mut Memory) -> Outcome {
        if let Some(outcome) = &self.terminal {
            return outcome.clone();
        }
        if let Some(call) = &self.pending {
            return Outcome::Syscall(call.clone());
        }
        loop {
            if self.state.fuel == 0 {
                return Outcome::FuelExhausted;
            }
            match self.step(memory) {
                Ok(Some(outcome)) => return outcome,
                Ok(None) => (),
                Err((cause, address)) => return self.fail(cause, address),
            }
        }
    }

    /// Attempt one opcode for native differential snapshots. `None` means one
    /// ordinary opcode retired; boundaries preserve the same semantics as run.
    pub fn step_one(&mut self, memory: &mut Memory) -> Option<Outcome> {
        if let Some(outcome) = &self.terminal {
            return Some(outcome.clone());
        }
        if let Some(call) = &self.pending {
            return Some(Outcome::Syscall(call.clone()));
        }
        if self.state.fuel == 0 {
            return Some(Outcome::FuelExhausted);
        }
        match self.step(memory) {
            Ok(outcome) => outcome,
            Err((cause, address)) => Some(self.fail(cause, address)),
        }
    }

    fn step(&mut self, memory: &mut Memory) -> Result<Option<Outcome>, (FaultCause, Option<u32>)> {
        use Opcode::*;
        let pc = self.pc_valid(i64::from(self.state.pc))?;
        if let Some(line) = memory.missing(pc, 4) {
            return Ok(Some(Outcome::WaitMemory { line }));
        }
        let raw: [u8; 4] = memory.bytes[pc as usize..pc as usize + 4]
            .try_into()
            .unwrap();
        let ins = decode(raw).map_err(|e| (FaultCause::Decode(e), None))?;
        let a = usize::from(ins.a);
        let b = usize::from(ins.b);
        let imm = ins.immediate;
        let r = self.state.r;
        let p = self.state.p;
        let sp = self.state.sp;
        // Preflight all control flow, address calculations, access ranges and line availability.
        let mut next = i64::from(pc) + 4;
        let mut access: Option<(u32, u32, bool)> = None;
        let mut pointer_result = None;
        let mut pop_value = 0u32;
        match ins.op {
            Jmp | Call => {
                next = i64::from(imm);
                if ins.op == Call {
                    self.pc_valid(i64::from(pc) + 4)?;
                }
            }
            Beq | Bne | Bltu | Bgeu | Blts | Bges | Pbeq | Pbne | Pbltu | Pbgeu => {
                let take = match ins.op {
                    Beq => r[a] == r[b],
                    Bne => r[a] != r[b],
                    Bltu => r[a] < r[b],
                    Bgeu => r[a] >= r[b],
                    Blts => (r[a] as i16) < (r[b] as i16),
                    Bges => (r[a] as i16) >= (r[b] as i16),
                    Pbeq => p[a] == p[b],
                    Pbne => p[a] != p[b],
                    Pbltu => p[a] < p[b],
                    Pbgeu => p[a] >= p[b],
                    _ => unreachable!(),
                };
                if take {
                    next += 4 * i64::from(imm as u16 as i16);
                }
            }
            Ld8 | Ld16 | St8 | St16 | Ldp | Stp => {
                let address = u64::from(p[b]) + u64::from(imm);
                if address > 0xffffff {
                    return Err((FaultCause::AddressOverflow, u32::try_from(address).ok()));
                }
                let length = match ins.op {
                    Ld8 | St8 => 1,
                    Ld16 | St16 => 2,
                    _ => 3,
                };
                access = Some((address as u32, length, matches!(ins.op, St8 | St16 | Stp)));
            }
            Padd | Psub => {
                let value = if ins.op == Padd {
                    i64::from(p[a]) + i64::from(r[b])
                } else {
                    i64::from(p[a]) - i64::from(r[b])
                };
                if !(0..=0xffffff).contains(&value) {
                    return Err((FaultCause::AddressOverflow, u32::try_from(value).ok()));
                }
                pointer_result = Some(value as u32);
            }
            Pmake => {
                if r[imm as usize] > 255 {
                    return Err((FaultCause::AddressOverflow, None));
                }
                pointer_result = Some(u32::from(r[b]) | (u32::from(r[imm as usize]) << 16));
            }
            Setsp => {
                if p[a] < self.bounds.stack.first - 1 || p[a] > self.bounds.stack.last {
                    return Err((FaultCause::InvalidSp, Some(p[a])));
                }
            }
            _ => (),
        }
        if matches!(ins.op, Push16 | Pushp | Call | Pop16 | Popp | Ret) {
            if sp < self.bounds.stack.first - 1 || sp > self.bounds.stack.last {
                return Err((FaultCause::InvalidSp, Some(sp)));
            }
            let n = if matches!(ins.op, Push16 | Pop16) {
                2
            } else {
                3
            };
            if matches!(ins.op, Push16 | Pushp | Call) {
                if sp + 1 < self.bounds.stack.first + n {
                    return Err((FaultCause::StackOverflow, Some(sp)));
                }
                access = Some((sp - (n - 1), n, true));
            } else {
                if u64::from(sp) + u64::from(n) > u64::from(self.bounds.stack.last) {
                    return Err((FaultCause::StackUnderflow, Some(sp)));
                }
                access = Some((sp + 1, n, false));
            }
        }
        if let Some((address, length, write)) = access {
            self.check_access(address, length, write)
                .map_err(|cause| (cause, Some(address)))?;
        }
        // RET selects its PC only after the three return bytes are available.
        if ins.op != Ret && ins.op != Trap && !(ins.op == Syscall && ins.a == 0) {
            self.pc_valid(next)?;
        }
        if let Some((address, length, _)) = access {
            if let Some(line) = memory.missing(address, length) {
                return Ok(Some(Outcome::WaitMemory { line }));
            }
            if matches!(ins.op, Pop16 | Popp | Ret) {
                for i in 0..length {
                    pop_value |= u32::from(memory.bytes[(address + i) as usize]) << (8 * i);
                }
            }
        }
        if ins.op == Ret {
            next = i64::from(pop_value);
            self.pc_valid(next)?;
        }
        // The complete instruction is now admitted; every effect below occurs exactly once.
        self.state.fuel -= 1;
        self.state.retired += 1;
        let mut outcome = None;
        match ins.op {
            Nop => (),
            Mov => self.state.r[a] = r[b],
            Ldi => self.state.r[a] = imm as u16,
            Add => self.state.r[a] = r[a].wrapping_add(r[b]),
            Sub => self.state.r[a] = r[a].wrapping_sub(r[b]),
            And => self.state.r[a] = r[a] & r[b],
            Or => self.state.r[a] = r[a] | r[b],
            Xor => self.state.r[a] = r[a] ^ r[b],
            Shl => self.state.r[a] = r[a] << imm,
            Shr => self.state.r[a] = r[a] >> imm,
            Sar => self.state.r[a] = ((r[a] as i16) >> imm) as u16,
            Addi => self.state.r[a] = r[a].wrapping_add(imm as u16),
            Trunc8 => self.state.r[a] = r[a] & 255,
            Sext8 => self.state.r[a] = (r[a] as u8 as i8 as i16) as u16,
            Not => self.state.r[a] = !r[a],
            Mulu | Muls => {
                let product = if ins.op == Mulu {
                    u32::from(r[0]) * u32::from(r[1])
                } else {
                    (i32::from(r[0] as i16) * i32::from(r[1] as i16)) as u32
                };
                self.state.r[0] = product as u16;
                self.state.r[1] = (product >> 16) as u16;
            }
            Ld8 | Ld16 | Ldp => {
                let (address, length, _) = access.unwrap();
                let mut value = 0u32;
                for i in 0..length {
                    value |= u32::from(memory.bytes[(address + i) as usize]) << (8 * i);
                }
                if ins.op == Ldp {
                    self.state.p[a] = value;
                } else {
                    self.state.r[a] = value as u16;
                }
            }
            St8 | St16 | Stp | Push16 | Pushp | Call => {
                let (address, length, _) = access.unwrap();
                let value = match ins.op {
                    Stp | Pushp => p[a],
                    Call => pc + 4,
                    _ => u32::from(r[a]),
                };
                for i in 0..length {
                    memory.bytes[(address + i) as usize] = (value >> (8 * i)) as u8;
                }
                if matches!(ins.op, Push16 | Pushp | Call) {
                    self.state.sp = sp - length;
                }
            }
            Pmov => self.state.p[a] = p[b],
            Padd | Psub | Pmake => self.state.p[a] = pointer_result.unwrap(),
            Pgetlo => self.state.r[a] = p[b] as u16,
            Pgethi => self.state.r[a] = (p[b] >> 16) as u16,
            Pli0 | Pli1 | Pli2 | Pli3 => self.state.p[a] = imm,
            Pop16 => {
                self.state.r[a] = pop_value as u16;
                self.state.sp = sp + 2;
            }
            Popp => {
                self.state.p[a] = pop_value;
                self.state.sp = sp + 3;
            }
            Ret => self.state.sp = sp + 3,
            Getsp => self.state.p[a] = sp,
            Setsp => self.state.sp = p[a],
            Syscall => {
                self.serial += 1;
                let call = crate::vm::Syscall {
                    token: self.serial,
                    id: ins.a,
                    pc,
                    resume_pc: if ins.a == 0 { None } else { Some(next as u32) },
                    r,
                    p,
                };
                self.pending = Some(call.clone());
                outcome = Some(Outcome::Syscall(call));
            }
            Yield => {
                self.state.fuel = 0;
                outcome = Some(Outcome::Yield);
            }
            Trap => return Ok(Some(self.fail(FaultCause::Trap(imm as u16), None))),
            Jmp | Beq | Bne | Bltu | Bgeu | Blts | Bges | Pbeq | Pbne | Pbltu | Pbgeu => (),
        }
        if !(ins.op == Syscall && ins.a == 0) {
            self.state.pc = next as u32;
        }
        Ok(outcome)
    }
}
