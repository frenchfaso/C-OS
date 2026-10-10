//! Functional output and dynamic bytecode profile; no target timing claims.
use cos_tools::{
    harness::{Harness, ServiceState},
    object::{read_json, write_atomic},
    pack::LinkedManifest,
    vm::{Bounds, Memory, Outcome, Vm},
};
use serde_json::json;
use std::{collections::BTreeMap, env, fs, path::PathBuf};

fn run() -> Result<(), String> {
    let mut args = env::args().skip(1);
    let manifest_path = PathBuf::from(
        args.next()
            .ok_or("usage: cosbench MANIFEST --app NAME --bytes N --out FILE [--expected FILE]")?,
    );
    let mut selector = None;
    let mut output_path = None;
    let mut expected_path = None;
    let mut length = None;
    while let Some(flag) = args.next() {
        let value = args
            .next()
            .ok_or_else(|| format!("missing value for {flag}"))?;
        match flag.as_str() {
            "--app" => selector = Some(value),
            "--bytes" => length = Some(value.parse::<u32>().map_err(|_| "invalid output length")?),
            "--out" => output_path = Some(PathBuf::from(value)),
            "--expected" => expected_path = Some(PathBuf::from(value)),
            _ => return Err(format!("unknown option {flag}")),
        }
    }
    let manifest: LinkedManifest = read_json(&manifest_path)?;
    manifest.validate()?;
    let selector = selector.ok_or("--app is required")?;
    let app = manifest
        .apps
        .iter()
        .find(|app| app.name == selector)
        .ok_or("application not found")?;
    let length = length.ok_or("--bytes is required")?;
    let output_path = output_path.ok_or("--out is required")?;
    let image = fs::read(manifest_path.parent().unwrap().join(&manifest.reu_image))
        .map_err(|e| e.to_string())?;
    manifest.validate_image(&image)?;
    let mut memory = Memory::new();
    memory.write(0, &image)?;
    let seed = memory.read(app.data_seed.start, app.data.length)?.to_vec();
    memory.write(app.data.start, &seed)?;
    memory.write(app.bss.start, &vec![0; app.bss.length as usize])?;
    let mut vm = Vm::new(
        app.id,
        Bounds {
            arena: app.arena,
            code: app.code,
            heap: app.heap,
            stack: app.stack,
        },
        app.entry,
        (app.data.length != 0).then_some(app.data.start),
    )?;
    vm.check_access(app.heap.first, length, false)
        .map_err(|e| format!("output: {e:?}"))?;
    let mut harness = Harness::new();
    let mut histogram = BTreeMap::<u8, u64>::new();
    let mut library_retired = 0u64;
    let mut slices = 1u64;
    let mut attempts = 0u64;
    loop {
        attempts += 1;
        if attempts > 50_000_000 {
            return Err("functional attempt limit exceeded".into());
        }
        let pc = vm.state.pc;
        let retired = vm.state.retired;
        let opcode = memory.read(pc, 1)?[0];
        let result = vm.step_one(&mut memory);
        if vm.state.retired != retired {
            *histogram.entry(opcode).or_default() += 1;
            if app.symbols.get("mul_q8").is_some_and(|&start| {
                pc >= start
                    && pc <= app.code.last
                    && app.symbols.get("mul_q8_end").is_none_or(|&end| pc < end)
            }) {
                library_retired += 1;
            }
        }
        let Some(boundary) = result else { continue };
        match boundary {
            Outcome::FuelExhausted | Outcome::Yield => {
                vm.refuel(128);
                slices += 1;
            }
            Outcome::Syscall(call) => {
                let mut service = harness.accept(&mut vm, &mut memory, &call)?;
                while service == ServiceState::Pending {
                    harness.frame = harness.frame.wrapping_add(1);
                    service = harness.tick(&mut vm, &mut memory)?;
                }
                if service == ServiceState::Exited {
                    break;
                }
                if matches!(service, ServiceState::WaitMemory { .. }) {
                    return Err("unexpected unavailable host memory".into());
                }
            }
            Outcome::Stopped { code: 0 } => break,
            error => return Err(format!("benchmark failed at ${pc:06X}: {error:?}")),
        }
    }
    let output = memory.read(app.heap.first, length)?.to_vec();
    if let Some(path) = expected_path {
        let expected = fs::read(path).map_err(|e| e.to_string())?;
        if output != expected {
            let first = output.iter().zip(&expected).position(|(a, b)| a != b);
            return Err(format!(
                "independent output mismatch at {first:?}; sizes {}/{}",
                output.len(),
                expected.len()
            ));
        }
    }
    write_atomic(&output_path, &output)?;
    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "qualification":"Functional host output/profile only; not target throughput",
            "abi":cos_tools::ABI,
            "app":app.name,"pid":app.id,"output_address":app.heap.first,"output_bytes":length,
            "retired":vm.state.retired,"slices":slices,"arithmetic_library_retired":library_retired,
            "opcode_histogram":histogram,"syscalls":harness.calls,"native_chunks":harness.chunks,
            "multiply_unsigned_retired":histogram.get(&0x39).copied().unwrap_or(0),
            "multiply_signed_retired":histogram.get(&0x3a).copied().unwrap_or(0),
            "final_context":vm.state,
        }))
        .map_err(|e| e.to_string())?
    );
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("cosbench: {error}");
        std::process::exit(1);
    }
}
