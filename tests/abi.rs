//! Reject legacy ABI containers even when their header and manifest agree.
use cos_tools::{
    assembler, object,
    pack::{self, AppInput, PackInput, StorageConfig},
};
use std::{
    fs,
    path::PathBuf,
    process::Command,
    sync::atomic::{AtomicU64, Ordering},
};

struct Temp(PathBuf);
impl Temp {
    fn new() -> Self {
        static SERIAL: AtomicU64 = AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "cos-abi-{}-{}",
            std::process::id(),
            SERIAL.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&path).unwrap();
        Self(path)
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
            object: "app.cobj".into(),
            arena_start: 0x40000,
            arena_size: 0x20000,
            stack_size: 128,
            heap_min: 128,
        }],
    }
}
fn pack(temp: &Temp) -> pack::PackOutput {
    let object =
        assembler::assemble(".entry x\nx: MULU\nMULS\nSYSCALL 0\n", "multiply.casm").unwrap();
    assert_eq!(object.abi, 2);
    assert_eq!(object.code, [0x39, 0, 0, 0, 0x3a, 0, 0, 0, 0x36, 0, 0, 0]);
    object::write_json(&temp.0.join("app.cobj"), &object).unwrap();
    pack::pack(&temp.0, &input(), 0x87654321).unwrap()
}

#[test]
fn abi_two_is_consistent_in_objects_manifest_header_constants_and_map() {
    assert_eq!(cos_tools::ABI, 2);
    let temp = Temp::new();
    let output = pack(&temp);
    assert_eq!(output.manifest.abi, 2);
    assert_eq!(&output.image[..8], b"COSREU01");
    assert_eq!(&output.image[12..14], &[2, 0]);
    assert!(output.constants.contains(".const COS_ABI = 2\n"));
    assert!(output.map.contains("ABI 2; COS-NUM-1"));
    output.manifest.validate_image(&output.image).unwrap();
    let source = cos_tools::isa::disassemble(&output.image[0x40000..0x4000c], 0x40000).unwrap();
    assert!(source.contains("39 00 00 00  MULU"));
    assert!(source.contains("3A 00 00 00  MULS"));
}

#[test]
fn legacy_and_mixed_abis_are_rejected_before_linking() {
    let temp = Temp::new();
    let output = pack(&temp);
    let mut legacy = input();
    legacy.abi = 1;
    assert!(
        legacy
            .validate()
            .unwrap_err()
            .contains("requires ABI 2, got ABI 1")
    );
    let mut old_object = assembler::assemble(".entry x\nx: SYSCALL 0\n", "old.casm").unwrap();
    old_object.abi = 1;
    assert!(
        old_object
            .validate()
            .unwrap_err()
            .contains("requires ABI 2, got ABI 1")
    );
    object::write_json(&temp.0.join("old.cobj"), &old_object).unwrap();
    let mut mixed = input();
    let mut second = mixed.apps[0].clone();
    second.id = 8;
    second.name = "Old".into();
    second.object = "old.cobj".into();
    second.arena_start = 0x60000;
    mixed.apps.push(second);
    let error = pack::pack(&temp.0, &mixed, output.manifest.build_tag).unwrap_err();
    assert!(
        error.contains("old.cobj") && error.contains("requires ABI 2, got ABI 1"),
        "{error}"
    );
}

#[test]
fn matching_old_abi_and_mixed_headers_are_rejected_by_every_pack_reader() {
    let temp = Temp::new();
    let mut output = pack(&temp);
    output.manifest.reu_image = "paired.reu".into();
    // The old pair has identical magic, build tag, app count and numeric profile.
    // ABI compatibility must fail even though the pair agrees internally.
    output.manifest.abi = 1;
    output.image[12..14].copy_from_slice(&1_u16.to_le_bytes());
    let error = output.manifest.validate_image(&output.image).unwrap_err();
    assert!(error.contains("requires ABI 2, got ABI 1"), "{error}");
    fs::write(temp.0.join("paired.reu"), &output.image).unwrap();
    let manifest_path = temp.0.join("paired.json");
    object::write_json(&manifest_path, &output.manifest).unwrap();
    let manifest = manifest_path.to_str().unwrap();
    let result_path = temp.0.join("output.bin");
    let fixture_path = temp.0.join("fixtures.json");
    for (binary, arguments) in [
        (
            env!("CARGO_BIN_EXE_cosrun"),
            vec![manifest, "--app", "Test"],
        ),
        (
            env!("CARGO_BIN_EXE_cosdis"),
            vec![manifest, "--app", "Test"],
        ),
        (
            env!("CARGO_BIN_EXE_cosbench"),
            vec![
                manifest,
                "--app",
                "Test",
                "--bytes",
                "1",
                "--out",
                result_path.to_str().unwrap(),
            ],
        ),
        (
            env!("CARGO_BIN_EXE_cosfixtures"),
            vec![fixture_path.to_str().unwrap(), "--manifest", manifest],
        ),
    ] {
        let result = Command::new(binary).args(arguments).output().unwrap();
        assert!(!result.status.success(), "accepted ABI1: {binary}");
        let error = String::from_utf8(result.stderr).unwrap();
        assert!(
            error.contains("requires ABI 2, got ABI 1"),
            "{binary}: {error}"
        );
    }
    assert!(!result_path.exists());
    assert!(!fixture_path.exists());
    output.manifest.abi = 2;
    assert!(
        output
            .manifest
            .validate_image(&output.image)
            .unwrap_err()
            .contains("REU image requires ABI 2, got ABI 1")
    );
}

#[test]
fn common_image_validation_checks_the_complete_header_and_length() {
    let temp = Temp::new();
    let mut output = pack(&temp);
    for length in [0, 8, 15, 16, 0xffffff] {
        assert!(
            output
                .manifest
                .validate_image(&output.image[..length])
                .is_err()
        );
    }
    for address in [0, 8, 12, 14, 15] {
        output.image[address] ^= 1;
        assert!(
            output.manifest.validate_image(&output.image).is_err(),
            "header offset{address}"
        );
        output.image[address] ^= 1;
    }
    output.manifest.validate_image(&output.image).unwrap();
}
