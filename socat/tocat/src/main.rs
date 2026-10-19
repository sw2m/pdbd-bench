// see socat/README.md "Oracles"
use std::io::{BufRead, Write};

fn main() {
    std::panic::set_hook(Box::new(|_| {}));
    let stdin = std::io::stdin();
    let mut out = std::io::BufWriter::new(std::io::stdout().lock());
    for line in stdin.lock().lines() {
        let line = line.expect("stdin");
        let input: String = serde_json::from_str(&line).expect("one JSON string per line");
        let ok = std::panic::catch_unwind(|| {
            input.parse::<tocat_core::endpoint::EndpointSpec>().is_ok()
        })
        .unwrap_or(false);
        writeln!(out, "{}", serde_json::json!({ "ok": ok })).expect("stdout");
    }
}
