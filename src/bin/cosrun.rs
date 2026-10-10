use cos_tools::{
    harness::{Harness, ServiceState},
    object::{read_json, write_atomic},
    pack::LinkedManifest,
    vm::{Bounds, Memory, Outcome, Vm},
};
use serde_json::json;
use std::{env, fs, path::PathBuf};

fn run() -> Result<bool, String> {
    let mut args = env::args().skip(1);
    let manifest_path = PathBuf::from(args.next().ok_or(
        "usage: cosrun MANIFEST --app NAME_OR_ID [--fuel 1..255] [--slices N] [--trace FILE]",
    )?);
    let mut selector = None;
    let mut fuel = 128u8;
    let mut slices = 1000u64;
    let mut trace_path = None;
    while let Some(arg) = args.next() {
        let value = args
            .next()
            .ok_or_else(|| format!("missing value for {arg}"))?;
        match arg.as_str() {
            "--app" => selector = Some(value),
            "--fuel" => {
                fuel = value.parse().map_err(|_| "fuel must be 1..255")?;
                if fuel == 0 {
                    return Err("fuel must be 1..255".into());
                }
            }
            "--slices" => {
                slices = value
                    .parse()
                    .map_err(|_| "slice limit must be a positive integer")?;
                if slices == 0 {
                    return Err("slice limit must be positive".into());
                }
            }
            "--trace" => trace_path = Some(PathBuf::from(value)),
            _ => return Err(format!("unknown option {arg}")),
        }
    }
    let selector = selector.ok_or("--app NAME_OR_ID is required")?;
    let manifest: LinkedManifest = read_json(&manifest_path)?;
    manifest.validate()?;
    let selected: Vec<_> = manifest
        .apps
        .iter()
        .filter(|app| app.name == selector || selector.parse::<u16>() == Ok(app.id))
        .collect();
    if selected.len() != 1 {
        return Err("app selector must identify exactly one manifest application".into());
    }
    let app = selected[0];
    let image_path = manifest_path
        .parent()
        .unwrap_or(std::path::Path::new("."))
        .join(&manifest.reu_image);
    let image = fs::read(&image_path).map_err(|e| format!("{}: {e}", image_path.display()))?;
    manifest.validate_image(&image)?;
    let mut memory = Memory::new();
    memory.write(0, &image)?;
    if app.data.length != 0 {
        let data = memory
            .read(app.data_seed.start, app.data_seed.length)?
            .to_vec();
        memory.write(app.data.start, &data)?;
    }
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
    vm.refuel(fuel);
    let mut kernel = Harness::new();
    kernel.quantum = fuel;
    let mut trace = Vec::new();
    let mut outcome = json!("SliceLimit");
    let mut success = false;
    for slice in 0..slices {
        let boundary = vm.run(&mut memory);
        if trace_path.is_some() {
            serde_json::to_writer(
                &mut trace,
                &json!({"slice":slice,"context":vm.state,"outcome":boundary}),
            )
            .map_err(|e| e.to_string())?;
            trace.push(b'\n');
        }
        match boundary {
            Outcome::FuelExhausted | Outcome::Yield => vm.refuel(fuel),
            Outcome::Syscall(call) => {
                let mut service = kernel.accept(&mut vm, &mut memory, &call)?;
                while service == ServiceState::Pending {
                    // Host model frames advance deterministically; these are not wall-clock measurements.
                    kernel.frame = kernel.frame.wrapping_add(1);
                    service = kernel.tick(&mut vm, &mut memory)?;
                    if trace_path.is_some() {
                        serde_json::to_writer(&mut trace, &json!({"slice":slice,"service":format!("{service:?}"),"context":vm.state})).map_err(|e|e.to_string())?;
                        trace.push(b'\n');
                    }
                }
                if matches!(service, ServiceState::WaitMemory { .. }) {
                    return Err("unexpected unavailable line in default host memory".into());
                }
                if service == ServiceState::Exited {
                    outcome =
                        serde_json::to_value(vm.run(&mut memory)).map_err(|e| e.to_string())?;
                    success = true;
                    break;
                }
            }
            Outcome::Fault(fault) => {
                if let Some(location) = app
                    .source_map
                    .iter()
                    .filter(|loc| loc.address <= fault.pc)
                    .max_by_key(|loc| loc.address)
                {
                    eprintln!(
                        "{}:{}:{}: PID {} at ${:06X}: {:?}",
                        location.file,
                        location.line,
                        location.column,
                        fault.pid,
                        fault.pc,
                        fault.cause
                    );
                }
                outcome = serde_json::to_value(Outcome::Fault(fault)).map_err(|e| e.to_string())?;
                break;
            }
            terminal @ Outcome::Stopped { .. } => {
                outcome = serde_json::to_value(terminal).map_err(|e| e.to_string())?;
                success = true;
                break;
            }
            Outcome::WaitMemory { .. } => {
                return Err("unexpected unavailable line in default host memory".into());
            }
        }
    }
    if let Some(path) = trace_path {
        write_atomic(&path, &trace)?;
    }
    println!("{}", serde_json::to_string_pretty(&json!({"app":app.name,"pid":app.id,"build_tag":manifest.build_tag,"outcome":outcome,
        "context":vm.state,"syscalls":kernel.calls,"native_chunks":kernel.chunks,"model_frames":kernel.frame})).map_err(|e|e.to_string())?);
    Ok(success)
}

fn main() {
    match run() {
        Ok(true) => (),
        Ok(false) => std::process::exit(2),
        Err(error) => {
            eprintln!("cosrun: {error}");
            std::process::exit(1);
        }
    }
}
