use cos_tools::{
    object,
    pack::{self, PackInput},
};
use std::{
    env, fs,
    path::{Path, PathBuf},
};
fn run() -> Result<(), String> {
    let mut args = env::args().skip(1);
    let input = args
        .next()
        .ok_or("usage: cospack MANIFEST.json --out PREFIX [--root ROOT] [--build-tag U32]")?;
    let mut prefix = None;
    let mut root = PathBuf::from(".");
    let mut tag = None;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--out" => prefix = Some(PathBuf::from(args.next().ok_or("--out requires a prefix")?)),
            "--root" => root = PathBuf::from(args.next().ok_or("--root requires a path")?),
            "--build-tag" => {
                tag = Some(
                    args.next()
                        .ok_or("--build-tag requires decimal u32")?
                        .parse::<u32>()
                        .map_err(|e| e.to_string())?,
                )
            }
            _ => return Err(format!("unknown argument '{arg}'")),
        }
    }
    let prefix = prefix.ok_or("--out PREFIX is required")?;
    let config: PackInput = object::read_json(Path::new(&input))?;
    let tag = if let Some(tag) = tag {
        tag
    } else {
        pack::build_tag(&root, &config)?
    };
    let mut output = pack::pack(&root, &config, tag)?;
    let name = prefix
        .file_name()
        .ok_or("output prefix needs a filename")?
        .to_str()
        .ok_or("output prefix must be UTF-8")?;
    output.manifest.reu_image = format!("{name}.reu");
    let path = |suffix: &str| prefix.with_file_name(format!("{name}{suffix}"));
    object::write_atomic(&path(".reu"), &output.image)?;
    object::write_atomic(&path(".asm"), output.constants.as_bytes())?;
    object::write_atomic(&path(".map.txt"), output.map.as_bytes())?;
    let tree = path(".data").join("cos");
    fs::create_dir_all(tree.join(".system")).map_err(|e| e.to_string())?;
    for app in &config.apps {
        fs::create_dir_all(tree.join("apps").join(app.id.to_string()))
            .map_err(|e| e.to_string())?;
    }
    object::write_atomic(&tree.join(".cos-volume"), b"COSDATA1\n")?;
    object::write_json(&path(".manifest.json"), &output.manifest)?;
    println!(
        "{}: 16777216-byte shared REU image, {} apps, build tag ${tag:08X}",
        path(".reu").display(),
        config.apps.len()
    );
    println!("{}", output.map);
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        eprintln!("cospack: {e}");
        std::process::exit(2);
    }
}
