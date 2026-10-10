use cos_tools::{
    assembler,
    isa::{self, Opcode},
    object::{self, Object, RelocationKind, Section},
    pack::{self, AppInput, PackInput, StorageConfig},
};
use std::{
    fs,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};
struct Temp(PathBuf);
impl Temp {
    fn new() -> Self {
        static SERIAL: AtomicU64 = AtomicU64::new(0);
        let p = std::env::temp_dir().join(format!(
            "cos-toolchain-{}-{}",
            std::process::id(),
            SERIAL.fetch_add(1, Ordering::SeqCst)
        ));
        fs::create_dir_all(&p).unwrap();
        Self(p)
    }
}
impl Drop for Temp {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn input() -> PackInput {
    PackInput {
        format: "COSPACK1".into(),
        abi: 2,
        numeric_profile: "COS-NUM-1".into(),
        target: "c64u-pal-upic320".into(),
        storage: StorageConfig::Discover {
            directory: "cos".into(),
            marker: ".cos-volume".into(),
        },
        apps: vec![AppInput {
            id: 7,
            name: "Test".into(),
            object: "test.cobj".into(),
            arena_start: 0x40000,
            arena_size: 0x20000,
            stack_size: 128,
            heap_min: 128,
        }],
    }
}
fn terminal() -> Object {
    assembler::assemble(".entry start\nstart: SYSCALL 0\n", "test.casm").unwrap()
}
fn save(temp: &Temp, obj: &Object) {
    object::write_json(&temp.0.join("test.cobj"), obj).unwrap();
}
#[test]
fn independent_instruction_vectors() {
    // Bytes and operands are transcribed from SPEC 8.2/8.3, not emitted by an assembler.
    let vectors: [([u8; 4], Opcode, u8, u8, u32); 27] = [
        ([0x00, 0, 0, 0], Opcode::Nop, 0, 0, 0),
        ([0x01, 0x70, 0, 0], Opcode::Mov, 0, 7, 0),
        ([0x02, 7, 0x34, 0x12], Opcode::Ldi, 7, 0, 0x1234),
        ([0x08, 6, 15, 0], Opcode::Shl, 6, 0, 15),
        ([0x10, 0x37, 0x56, 0x12], Opcode::Ld8, 7, 3, 0x1256),
        ([0x11, 0x10, 0xff, 0xff], Opcode::Ld16, 0, 1, 65535),
        ([0x12, 0x21, 0, 0], Opcode::St8, 1, 2, 0),
        ([0x13, 0x07, 0x80, 0], Opcode::St16, 7, 0, 128),
        ([0x14, 0x32, 1, 0], Opcode::Ldp, 2, 3, 1),
        ([0x15, 0x12, 2, 0], Opcode::Stp, 2, 1, 2),
        ([0x16, 0x30, 0, 0], Opcode::Pmov, 0, 3, 0),
        ([0x17, 0x73, 0, 0], Opcode::Padd, 3, 7, 0),
        ([0x18, 0x21, 0, 0], Opcode::Psub, 1, 2, 0),
        ([0x19, 0x37, 0, 0], Opcode::Pgetlo, 7, 3, 0),
        ([0x1a, 0x26, 0, 0], Opcode::Pgethi, 6, 2, 0),
        ([0x1b, 3, 7, 6], Opcode::Pmake, 3, 7, 6),
        ([0x1c, 0x56, 0x34, 0x12], Opcode::Pli0, 0, 0, 0x123456),
        ([0x1d, 0xff, 0xff, 0xff], Opcode::Pli1, 1, 0, 0xffffff),
        ([0x20, 0, 0, 4], Opcode::Jmp, 0, 0, 0x40000),
        ([0x21, 0x80, 0, 4], Opcode::Call, 0, 0, 0x40080),
        ([0x23, 0x70, 0xff, 0xff], Opcode::Beq, 0, 7, 65535),
        ([0x2c, 0x32, 0, 0x80], Opcode::Pbgeu, 2, 3, 32768),
        ([0x30, 7, 0, 0], Opcode::Push16, 7, 0, 0),
        ([0x36, 0xff, 0, 0], Opcode::Syscall, 255, 0, 0),
        ([0x38, 0, 0x01, 0x10], Opcode::Trap, 0, 0, 0x1001),
        ([0x39, 0, 0, 0], Opcode::Mulu, 0, 0, 0),
        ([0x3a, 0, 0, 0], Opcode::Muls, 0, 0, 0),
    ];
    for (bytes, op, a, b, immediate) in vectors {
        let i = isa::decode(bytes).unwrap();
        assert_eq!((i.op, i.a, i.b, i.immediate), (op, a, b, immediate));
        assert_eq!(isa::encode(i).unwrap(), bytes);
    }
}
#[test]
fn complete_opcode_table_is_the_normative_table() {
    let expected = [
        0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e,
        0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1a, 0x1b, 0x1c, 0x1d, 0x1e,
        0x1f, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x29, 0x2a, 0x2b, 0x2c, 0x30,
        0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3a,
    ];
    assert_eq!(
        Opcode::ALL.iter().map(|op| *op as u8).collect::<Vec<_>>(),
        expected
    );
    for byte in 0..=255 {
        assert_eq!(Opcode::from_byte(byte).is_ok(), expected.contains(&byte));
    }
}
#[test]
fn malformed_operands_and_reserved_fields_are_rejected() {
    for bytes in [
        [0x0f, 0, 0, 0],
        [0x00, 1, 0, 0],
        [0x01, 0x80, 0, 0],
        [0x02, 0x10, 0, 0],
        [0x03, 0x08, 0, 0],
        [0x08, 0, 16, 0],
        [0x08, 0, 1, 1],
        [0x0c, 7, 1, 0],
        [0x10, 0x47, 0, 0],
        [0x14, 0x34, 0, 0],
        [0x16, 0, 1, 0],
        [0x17, 0x83, 0, 0],
        [0x19, 0x38, 0, 0],
        [0x1b, 4, 0, 0],
        [0x1b, 0, 8, 0],
        [0x1b, 0, 0, 8],
        [0x22, 0, 0, 1],
        [0x23, 0x80, 0, 0],
        [0x29, 0x04, 0, 0],
        [0x30, 0x10, 0, 0],
        [0x32, 4, 0, 0],
        [0x35, 0, 0, 1],
        [0x36, 0, 1, 0],
        [0x37, 1, 0, 0],
        [0x38, 1, 0, 0],
        [0x39, 1, 0, 0],
        [0x39, 0, 1, 0],
        [0x39, 0, 0, 1],
        [0x3a, 1, 0, 0],
        [0x3a, 0, 1, 0],
        [0x3a, 0, 0, 1],
    ] {
        assert!(isa::decode(bytes).is_err(), "accepted {bytes:02X?}");
    }
    let mut i = isa::decode([0x02, 0, 0, 0]).unwrap();
    i.immediate = 65536;
    assert!(isa::encode(i).is_err());
    i.immediate = 0;
    i.b = 1;
    assert!(isa::encode(i).is_err());
}
#[test]
fn assembly_relocations_have_independent_expected_linked_bytes() {
    let source = ".const LAST = NEXT+1\n.const NEXT = 41\n.entry start\nstart: LDI R2,LAST\nPLI P1,value\nBEQ R2,R3,done\nJMP start\ndone: SYSCALL 0\n.data\nvalue: .ptr start\n.word $abcd\n.bss\nscratch: .space 70000\n";
    let object = assembler::assemble(source, "test.casm").unwrap();
    assert_eq!(&object.code[..4], &[2, 2, 42, 0]);
    assert_eq!(object.relocations.len(), 4);
    let (app, code, data) = pack::link_object(&input().apps[0], &object, 128).unwrap();
    assert_eq!(app.data.start, 0x40080);
    assert_eq!(&code[4..8], &[0x1d, 0x80, 0, 4]);
    assert_eq!(&code[8..12], &[0x23, 0x32, 1, 0]);
    assert_eq!(&code[12..16], &[0x20, 0, 0, 4]);
    assert_eq!(&data, &[0, 0, 4, 0xcd, 0xab]);
    assert_eq!(app.bss.length, 70000);
    assert_eq!(app.source_map[0].address, 0x40000);
}
#[test]
fn assembler_errors_have_file_line_column() {
    let cases = [
        ".entry x\nx: MOV R8,R1",
        ".entry x\nx: LDI R0,65536",
        ".entry x\nx: SHL R0,16",
        ".entry x\nx: LD8 R0,P4,0",
        ".entry x\nx: NOP 1",
        ".entry x\nx: MULU R0,R1",
        ".entry x\nx: MULS 0",
        ".entry x\nx: JMP missing",
        ".entry x\nx: NOP\nx: SYSCALL 0",
        ".entry x\nx: BEQ R0,R1,32768",
        ".entry x\nx: .space 4",
        ".entry x\nx: NOP\n.data\n.word x",
        ".entry x\nx: SYSCALL 0\n.bss\n.align 3",
        ".entry x\nx: SYSCALL 0\n.data\n.byte -1",
    ];
    for source in cases {
        let e = assembler::assemble(source, "bad.casm").unwrap_err();
        assert!(e.starts_with("bad.casm:"), "{e}");
    }
    assert!(
        assembler::assemble(
            ".const A=B\n.const B=A\n.entry x\nx: SYSCALL 0",
            "cycle.casm"
        )
        .unwrap_err()
        .contains("cyclic")
    );
}

#[test]
fn repeated_numeric_signs_are_rejected_instead_of_silently_changed() {
    for number in ["--1", "++1", "+-1", "-+1"] {
        let source = format!(".entry start\nstart: LDI R0, {number}\nSYSCALL 0\n");
        let error = assembler::assemble(&source, "signs.casm").unwrap_err();
        assert!(error.contains("signs.casm:2:"));
    }
}
#[test]
fn static_control_flow_overflow_and_alignment_are_rejected() {
    for source in [
        ".entry x\nx: JMP $000000",
        ".entry x\nx: JMP x+1",
        ".entry x\nx: BEQ R0,R1,-2",
        ".entry x\nx: PLI0 x-1\nSYSCALL 0",
    ] {
        let object = assembler::assemble(source, "bad.casm").unwrap();
        assert!(pack::link_object(&input().apps[0], &object, 128).is_err());
    }
    let mut object = terminal();
    object.relocations.push(cos_tools::object::Relocation {
        kind: RelocationKind::Rel16Insn,
        section: Section::Code,
        offset: 0,
        target: object.entry.clone(),
        addend: 0,
    });
    assert!(object.validate().is_err());
}
#[test]
fn empty_pack_header_and_shared_reservation() {
    let temp = Temp::new();
    let mut config = input();
    config.apps.clear();
    let output = pack::pack(&temp.0, &config, 0x12345678).unwrap();
    assert_eq!(output.image.len(), 16 * 1024 * 1024);
    assert_eq!(
        &output.image[..16],
        b"COSREU01\x78\x56\x34\x12\x02\x00\x00\x00"
    );
    assert_eq!(output.manifest.system_reserve.last, 0x3ffff);
    assert!(output.map.contains("16515072"));
}
#[test]
fn arena_validation_rejects_overlaps_ids_alignment_and_profile() {
    let base = input();
    for field in 0..8 {
        let mut config = base.clone();
        match field {
            0 => config.apps[0].id = 0,
            1 => config.apps[0].arena_start = 0x3ff80,
            2 => config.apps[0].arena_start += 1,
            3 => config.apps[0].stack_size = 0,
            4 => config.apps[0].heap_min = 0,
            5 => config.apps[0].arena_size = 0x1000000,
            6 => config.numeric_profile = "OTHER".into(),
            _ => config.apps[0].name = "sixteen-byte-name".into(),
        };
        assert!(config.validate().is_err());
    }
    let mut duplicate = base.clone();
    duplicate.apps.push(duplicate.apps[0].clone());
    assert!(duplicate.validate().is_err());
    duplicate.apps[1].id = 8;
    assert!(duplicate.validate().is_err());
    let temp = Temp::new();
    save(&temp, &terminal());
    let mut top = base.clone();
    top.apps[0].arena_start = 0xfffc00;
    top.apps[0].arena_size = 1024;
    assert_eq!(
        pack::pack(&temp.0, &top, 1).unwrap().manifest.apps[0]
            .arena
            .last,
        0xffffff
    );
}
#[test]
fn seed_capacity_is_bounded_and_bss_does_not_consume_it() {
    let temp = Temp::new();
    let mut object = terminal();
    object.data = vec![0x5a; 65408];
    save(&temp, &object);
    let output = pack::pack(&temp.0, &input(), 1).unwrap();
    assert_eq!(output.manifest.apps[0].data_seed.start, 128);
    assert_eq!(output.image[65535], 0x5a);
    object.data.push(1);
    save(&temp, &object);
    assert!(
        pack::pack(&temp.0, &input(), 1)
            .unwrap_err()
            .contains("data seed")
    );
    object.data.clear();
    object.bss_size = 70000;
    save(&temp, &object);
    assert_eq!(
        pack::pack(&temp.0, &input(), 1).unwrap().manifest.apps[0]
            .data_seed
            .length,
        0
    );
}
#[test]
fn serialized_manifest_bounds_are_revalidated() {
    let temp = Temp::new();
    save(&temp, &terminal());
    let output = pack::pack(&temp.0, &input(), 1).unwrap();
    for field in 0..6 {
        let mut m = output.manifest.clone();
        match field {
            0 => m.apps[0].heap.first += 1,
            1 => m.apps[0].entry += 1,
            2 => m.apps[0].data.start += 128,
            3 => m.apps[0].data_seed.start = 0,
            4 => m.apps[0].stack.last -= 1,
            _ => m.system_reserve.last += 1,
        };
        assert!(m.validate().is_err());
    }
}
#[test]
fn objects_reject_unknown_json_fields_and_malformed_relocations() {
    let mut value = serde_json::to_value(terminal()).unwrap();
    value["not_supported"] = true.into();
    assert!(serde_json::from_value::<Object>(value).is_err());
    let mut object = terminal();
    object.abi = 1;
    assert!(object.validate().is_err());
}
#[test]
fn complete_assembly_samples_link_deterministically() {
    let temp = Temp::new();
    let mut config = input();
    config.apps.clear();
    for (n, name) in ["linear", "calls", "spin"].iter().enumerate() {
        let source = fs::read_to_string(format!("apps/{name}.casm")).unwrap();
        let object = assembler::assemble(&source, &format!("apps/{name}.casm")).unwrap();
        let filename = format!("{name}.cobj");
        object::write_json(&temp.0.join(&filename), &object).unwrap();
        config.apps.push(AppInput {
            id: n as u16 + 1,
            name: name.to_string(),
            object: filename,
            arena_start: 0x40000 + n as u32 * 0x20000,
            arena_size: 0x20000,
            stack_size: 1024,
            heap_min: 128,
        });
    }
    let first = pack::pack(&temp.0, &config, 1).unwrap();
    let second = pack::pack(&temp.0, &config, 1).unwrap();
    assert_eq!(first.image, second.image);
    assert_eq!(
        pack::build_tag(&temp.0, &config).unwrap(),
        pack::build_tag(&temp.0, &config).unwrap()
    );
}

#[test]
fn relative_relocation_range_and_addend_alignment_are_checked() {
    let mut object = terminal();
    object.code = vec![0; (32769 + 1) * 4];
    object.code[0..4].copy_from_slice(&[0x23, 0, 0, 0]);
    object.code[32769 * 4..].copy_from_slice(&[0x36, 0, 0, 0]);
    object.relocations.push(cos_tools::object::Relocation {
        kind: RelocationKind::Rel16Insn,
        section: Section::Code,
        offset: 0,
        target: cos_tools::object::SectionReference {
            section: Section::Code,
            offset: 32769 * 4,
        },
        addend: 0,
    });
    let mut app = input().apps.remove(0);
    app.arena_size = 0x40000;
    assert!(
        pack::link_object(&app, &object, 128)
            .unwrap_err()
            .contains("REL16_INSN")
    );
    object.relocations[0].target.offset = 4;
    object.relocations[0].addend = 1;
    assert!(pack::link_object(&app, &object, 128).is_err());
}

#[test]
fn direct_linker_rejects_invalid_layout_without_panicking() {
    for invalid in [0, 1, 128, u32::MAX] {
        let mut app = input().apps.remove(0);
        app.arena_size = invalid;
        assert!(pack::link_object(&app, &terminal(), 128).is_err());
    }
    assert!(pack::link_object(&input().apps[0], &terminal(), 0).is_err());
}
