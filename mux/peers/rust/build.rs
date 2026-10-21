// see mux/README.md "Build"
use std::fs;

fn main() {
    println!("cargo:rerun-if-changed=Cargo.lock");
    let lock = fs::read_to_string("Cargo.lock").unwrap_or_default();
    for name in ["yamux", "async_smux", "h2"] {
        let version = lock
            .split("[[package]]")
            .find(|p| p.lines().any(|l| l.trim() == format!("name = \"{name}\"")))
            .and_then(|p| p.lines().find_map(|l| l.trim().strip_prefix("version = \"")))
            .map(|v| v.trim_end_matches('"').to_string())
            .unwrap_or_default();
        println!("cargo:rustc-env=VERSION_{}={version}", name.to_uppercase());
    }
}
