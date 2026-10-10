use cos_tools::{
    assembler, isa,
    object::{self, Object},
    pack::LinkedManifest,
};
use std::{env, fs, path::Path};
fn run() -> Result<(), String> {
    let mut args = env::args().skip(1);
    let input = args
        .next()
        .ok_or("usage: cosdis OBJECT.cobj | MANIFEST.json --app NAME")?;
    let mut app = None;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--app" => app = Some(args.next().ok_or("--app requires a name or ID")?),
            _ => return Err(format!("unknown argument '{arg}'")),
        }
    }
    let path = Path::new(&input);
    if let Some(name) = app {
        let manifest: LinkedManifest = object::read_json(path)?;
        manifest.validate()?;
        let matches: Vec<_> = manifest
            .apps
            .iter()
            .filter(|a| a.name == name || a.id.to_string() == name)
            .collect();
        if matches.len() != 1 {
            return Err(format!(
                "app selector '{name}' must identify exactly one application"
            ));
        }
        let selected = matches[0];
        let image_path = path
            .parent()
            .unwrap_or(Path::new("."))
            .join(&manifest.reu_image);
        let image = fs::read(&image_path).map_err(|e| format!("{}: {e}", image_path.display()))?;
        manifest.validate_image(&image)?;
        print!(
            "{}",
            isa::disassemble(
                &image[selected.code.first as usize..=selected.code.last as usize],
                selected.code.first
            )?
        );
    } else {
        let object: Object = object::read_json(path)?;
        object.validate()?;
        print!("{}", assembler::listing(&object)?);
    }
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        eprintln!("cosdis: {e}");
        std::process::exit(2);
    }
}
