use cos_tools::{assembler, object};
use std::{env, fs, path::PathBuf};
fn run() -> Result<(), String> {
    let mut args = env::args().skip(1);
    let input = args.next().ok_or("usage: cosasm SOURCE -o OBJECT.cobj")?;
    let mut output = None;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "-o" => output = Some(PathBuf::from(args.next().ok_or("-o requires a path")?)),
            _ => return Err(format!("unknown argument '{arg}'")),
        }
    }
    let output = output.ok_or("-o OBJECT.cobj is required")?;
    let source = fs::read_to_string(&input).map_err(|e| format!("{input}: {e}"))?;
    let assembled = assembler::assemble(&source, &input)?;
    let listing = assembler::listing(&assembled)?;
    object::write_json(&output, &assembled)?;
    object::write_atomic(&output.with_extension("lst"), listing.as_bytes())?;
    object::write_json(&output.with_extension("map.json"), &assembled.source_map)?;
    println!(
        "{}: code={} data={} BSS={} relocations={}",
        output.display(),
        assembled.code.len(),
        assembled.data.len(),
        assembled.bss_size,
        assembled.relocations.len()
    );
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        eprintln!("cosasm: {e}");
        std::process::exit(2);
    }
}
