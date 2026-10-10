//! The normative four-byte ISA from SPEC.md section 8.
use std::fmt;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OperandForm {
    Zero,
    Rr,
    Ri16,
    Shift,
    R,
    Rp16,
    Pp16,
    Pp,
    Pr,
    Rp,
    Make,
    Absolute,
    BranchR,
    BranchP,
    P,
    Service,
    Trap,
}
macro_rules! isa {
    ($( $op:ident = $value:expr, $name:literal, $form:ident; )*) => {
        #[derive(Clone, Copy, Debug, PartialEq, Eq)]
        #[repr(u8)]
        pub enum Opcode { $( $op = $value, )* }
        impl Opcode {
            pub const ALL: &'static [Self] = &[$( Self::$op, )*];
            pub fn from_byte(value:u8)->Result<Self,String> { match value { $( $value => Ok(Self::$op), )* _ => Err(format!("invalid opcode ${value:02X}")) } }
            pub fn mnemonic(self)-> &'static str { match self { $( Self::$op => $name, )* } }
            pub fn form(self)->OperandForm { match self { $( Self::$op => OperandForm::$form, )* } }
            pub fn parse(name:&str)->Option<Self> { Self::ALL.iter().copied().find(|op| op.mnemonic().eq_ignore_ascii_case(name)) }
        }
    }
}
isa! {
 Nop=0x00,"NOP",Zero; Mov=0x01,"MOV",Rr; Ldi=0x02,"LDI",Ri16;
 Add=0x03,"ADD",Rr; Sub=0x04,"SUB",Rr; And=0x05,"AND",Rr; Or=0x06,"OR",Rr; Xor=0x07,"XOR",Rr;
 Shl=0x08,"SHL",Shift; Shr=0x09,"SHR",Shift; Sar=0x0a,"SAR",Shift; Addi=0x0b,"ADDI",Ri16;
 Trunc8=0x0c,"TRUNC8",R; Sext8=0x0d,"SEXT8",R; Not=0x0e,"NOT",R;
 Ld8=0x10,"LD8",Rp16; Ld16=0x11,"LD16",Rp16; St8=0x12,"ST8",Rp16; St16=0x13,"ST16",Rp16;
 Ldp=0x14,"LDP",Pp16; Stp=0x15,"STP",Pp16; Pmov=0x16,"PMOV",Pp;
 Padd=0x17,"PADD",Pr; Psub=0x18,"PSUB",Pr; Pgetlo=0x19,"PGETLO",Rp; Pgethi=0x1a,"PGETHI",Rp;
 Pmake=0x1b,"PMAKE",Make; Pli0=0x1c,"PLI0",Absolute; Pli1=0x1d,"PLI1",Absolute; Pli2=0x1e,"PLI2",Absolute; Pli3=0x1f,"PLI3",Absolute;
 Jmp=0x20,"JMP",Absolute; Call=0x21,"CALL",Absolute; Ret=0x22,"RET",Zero;
 Beq=0x23,"BEQ",BranchR; Bne=0x24,"BNE",BranchR; Bltu=0x25,"BLTU",BranchR; Bgeu=0x26,"BGEU",BranchR;
 Blts=0x27,"BLTS",BranchR; Bges=0x28,"BGES",BranchR; Pbeq=0x29,"PBEQ",BranchP; Pbne=0x2a,"PBNE",BranchP; Pbltu=0x2b,"PBLTU",BranchP; Pbgeu=0x2c,"PBGEU",BranchP;
 Push16=0x30,"PUSH16",R; Pop16=0x31,"POP16",R; Pushp=0x32,"PUSHP",P; Popp=0x33,"POPP",P;
 Getsp=0x34,"GETSP",P; Setsp=0x35,"SETSP",P; Syscall=0x36,"SYSCALL",Service; Yield=0x37,"YIELD",Zero; Trap=0x38,"TRAP",Trap;
 Mulu=0x39,"MULU",Zero; Muls=0x3a,"MULS",Zero;
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Instruction {
    pub op: Opcode,
    pub a: u8,
    pub b: u8,
    pub immediate: u32,
}
fn reg(index: u8, max: u8, name: &str) -> Result<(), String> {
    if index > max {
        Err(format!("invalid {name} register index {index}"))
    } else {
        Ok(())
    }
}
fn zero(value: u32) -> Result<(), String> {
    if value != 0 {
        Err("reserved fields must be zero".into())
    } else {
        Ok(())
    }
}
/// Decode and validate every register, shift count, and reserved byte.
pub fn decode(bytes: [u8; 4]) -> Result<Instruction, String> {
    let [byte, x, y, z] = bytes;
    let op = Opcode::from_byte(byte)?;
    let mut i = Instruction {
        op,
        a: x & 15,
        b: x >> 4,
        immediate: u16::from_le_bytes([y, z]) as u32,
    };
    use OperandForm::*;
    match op.form() {
        Zero => {
            zero((x as u32) | (i.immediate << 8))?;
            i.a = 0;
            i.b = 0;
        }
        Rr => {
            reg(i.a, 7, "R")?;
            reg(i.b, 7, "R")?;
            zero(i.immediate)?;
        }
        Ri16 => {
            reg(x, 7, "R")?;
            i.a = x;
            i.b = 0;
        }
        Shift => {
            reg(x, 7, "R")?;
            if y > 15 {
                return Err("shift count must be 0..15".into());
            }
            zero(z as u32)?;
            i.a = x;
            i.b = 0;
            i.immediate = y as u32;
        }
        R => {
            reg(x, 7, "R")?;
            zero(i.immediate)?;
            i.a = x;
            i.b = 0;
        }
        Rp16 | Rp => {
            reg(i.a, 7, "R")?;
            reg(i.b, 3, "P")?;
            if op.form() == Rp {
                zero(i.immediate)?;
            }
        }
        Pp16 | Pp | BranchP => {
            reg(i.a, 3, "P")?;
            reg(i.b, 3, "P")?;
            if op.form() == Pp {
                zero(i.immediate)?;
            }
        }
        Pr => {
            reg(i.a, 3, "P")?;
            reg(i.b, 7, "R")?;
            zero(i.immediate)?;
        }
        Make => {
            reg(x, 3, "P")?;
            reg(y, 7, "R")?;
            reg(z, 7, "R")?;
            i.a = x;
            i.b = y;
            i.immediate = z as u32;
        }
        Absolute => {
            i.a = match op {
                Opcode::Pli0 => 0,
                Opcode::Pli1 => 1,
                Opcode::Pli2 => 2,
                Opcode::Pli3 => 3,
                _ => 0,
            };
            i.b = 0;
            i.immediate = (x as u32) | ((y as u32) << 8) | ((z as u32) << 16);
        }
        BranchR => {
            reg(i.a, 7, "R")?;
            reg(i.b, 7, "R")?;
        }
        P => {
            reg(x, 3, "P")?;
            zero(i.immediate)?;
            i.a = x;
            i.b = 0;
        }
        Service => {
            zero(i.immediate)?;
            i.a = x;
            i.b = 0;
        }
        Trap => {
            zero(x as u32)?;
            i.a = 0;
            i.b = 0;
        }
    }
    Ok(i)
}
/// Encode canonical architectural operands and reject truncation.
pub fn encode(i: Instruction) -> Result<[u8; 4], String> {
    use OperandForm::*;
    let mut bytes = [i.op as u8, 0, i.immediate as u8, (i.immediate >> 8) as u8];
    match i.op.form() {
        Zero => {
            zero(i.a as u32 | i.b as u32 | i.immediate)?;
        }
        Rr | Pp | Pr | Rp => {
            if i.a > 15 || i.b > 15 {
                return Err("register does not fit a nibble".into());
            }
            zero(i.immediate)?;
            bytes[1] = i.a | (i.b << 4);
        }
        Rp16 | Pp16 | BranchR | BranchP => {
            if i.a > 15 || i.b > 15 {
                return Err("register does not fit a nibble".into());
            }
            if i.immediate > 65535 {
                return Err("immediate does not fit 16 bits".into());
            }
            bytes[1] = i.a | (i.b << 4);
        }
        Ri16 => {
            zero(i.b as u32)?;
            if i.immediate > 65535 {
                return Err("immediate does not fit 16 bits".into());
            }
            bytes[1] = i.a;
        }
        Shift => {
            zero(i.b as u32)?;
            if i.immediate > 15 {
                return Err("shift count must be 0..15".into());
            }
            bytes[1] = i.a;
        }
        R | P | Service => {
            zero(i.b as u32 | i.immediate)?;
            bytes[1] = i.a;
        }
        Make => {
            if i.immediate > 7 {
                return Err("invalid R register for high pointer part".into());
            }
            bytes[1] = i.a;
            bytes[2] = i.b;
            bytes[3] = i.immediate as u8;
        }
        Absolute => {
            if i.immediate > 0xffffff {
                return Err("immediate does not fit 24 bits".into());
            }
            zero(i.b as u32)?;
            let expected = match i.op {
                Opcode::Pli0 => 0,
                Opcode::Pli1 => 1,
                Opcode::Pli2 => 2,
                Opcode::Pli3 => 3,
                _ => 0,
            };
            if i.a != expected {
                return Err("pointer register disagrees with PLI opcode".into());
            }
            bytes[1] = i.immediate as u8;
            bytes[2] = (i.immediate >> 8) as u8;
            bytes[3] = (i.immediate >> 16) as u8;
        }
        Trap => {
            zero(i.a as u32 | i.b as u32)?;
            if i.immediate > 65535 {
                return Err("TRAP payload does not fit 16 bits".into());
            }
        }
    }
    decode(bytes)?;
    Ok(bytes)
}
impl fmt::Display for Instruction {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        use OperandForm::*;
        write!(f, "{}", self.op.mnemonic())?;
        match self.op.form() {
            Zero => Ok(()),
            Rr => write!(f, " R{}, R{}", self.a, self.b),
            Ri16 => write!(f, " R{}, ${:04X}", self.a, self.immediate),
            Shift => write!(f, " R{}, {}", self.a, self.immediate),
            R => write!(f, " R{}", self.a),
            Rp16 => write!(f, " R{}, P{}, ${:04X}", self.a, self.b, self.immediate),
            Pp16 => write!(f, " P{}, P{}, ${:04X}", self.a, self.b, self.immediate),
            Pp => write!(f, " P{}, P{}", self.a, self.b),
            Pr => write!(f, " P{}, R{}", self.a, self.b),
            Rp => write!(f, " R{}, P{}", self.a, self.b),
            Make => write!(f, " P{}, R{}, R{}", self.a, self.b, self.immediate),
            Absolute => write!(f, " ${:06X}", self.immediate),
            BranchR => write!(
                f,
                " R{}, R{}, {}",
                self.a, self.b, self.immediate as u16 as i16
            ),
            BranchP => write!(
                f,
                " P{}, P{}, {}",
                self.a, self.b, self.immediate as u16 as i16
            ),
            P => write!(f, " P{}", self.a),
            Service => write!(f, " ${:02X}", self.a),
            Trap => write!(f, " ${:04X}", self.immediate),
        }
    }
}
pub fn disassemble(code: &[u8], base: u32) -> Result<String, String> {
    if !code.len().is_multiple_of(4) {
        return Err("code length must be a multiple of four".into());
    }
    let mut out = String::new();
    for (n, bytes) in code.chunks_exact(4).enumerate() {
        let address = (base as u64) + (n as u64) * 4;
        if address + 3 > 0xffffff {
            return Err("disassembly extends beyond 24 bits".into());
        }
        let i = decode(bytes.try_into().unwrap()).map_err(|e| format!("${address:06X}: {e}"))?;
        out.push_str(&format!(
            "{address:06X}  {:02X} {:02X} {:02X} {:02X}  {i}\n",
            bytes[0], bytes[1], bytes[2], bytes[3]
        ));
    }
    Ok(out)
}
