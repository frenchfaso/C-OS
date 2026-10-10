//! C-OS ABI 2 host tools and reference execution model.
pub const ABI: u16 = 2;
pub const NUMERIC_PROFILE: &str = "COS-NUM-1";
pub mod assembler;
pub mod harness;
pub mod isa;
pub mod object;
pub mod pack;
pub mod vm;
