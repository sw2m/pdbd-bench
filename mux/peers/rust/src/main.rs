mod h2;
mod qmux;
mod scenario;
mod smux;
mod yamux;

use scenario::{Acceptor, Bench, Opener, Outcome, Params};
use std::future::Future;
use std::io;
use std::process::exit;
use std::sync::Arc;

fn version(name: &str) -> Option<&'static str> {
    match name {
        "yamux" => Some(env!("VERSION_YAMUX")),
        "async-smux" => Some(env!("VERSION_ASYNC_SMUX")),
        "h2" => Some(env!("VERSION_H2")),
        "qmux" => Some(env!("VERSION_QMUX")),
        _ => None,
    }
}

fn cpu() -> f64 {
    let mut u: libc::rusage = unsafe { std::mem::zeroed() };
    unsafe { libc::getrusage(libc::RUSAGE_SELF, &mut u) };
    let ms = |t: libc::timeval| t.tv_sec as f64 * 1e3 + t.tv_usec as f64 / 1e3;
    ms(u.ru_utime) + ms(u.ru_stime)
}

async fn once<O, A, S>(session: &impl Fn(Params) -> S, scenario: &str, p: Params) -> io::Result<Outcome>
where
    O: Opener,
    A: Acceptor,
    S: Future<Output = io::Result<(O, A)>>,
{
    let (open, accept) = session(p).await?;
    let data = Arc::new(vec![0x5a; p.chunk]);
    let mut b = Bench { open: Arc::new(open), accept, p, data };
    match scenario {
        "bulk" => b.bulk().await,
        "flows" => b.flows().await,
        "isolation" => b.isolation(true).await,
        "calm" => b.isolation(false).await,
        "pingpong" => b.pingpong(0).await,
        "loaded" => b.pingpong(p.load).await,
        "churn" => b.churn().await,
        "idle" => b.idle().await,
        other => Err(io::Error::other(format!("unsupported scenario {other:?}"))),
    }
}

// see mux/README.md "Statistics"
async fn run<O, A, S>(session: impl Fn(Params) -> S, scenario: &str, p: Params) -> io::Result<Outcome>
where
    O: Opener,
    A: Acceptor,
    S: Future<Output = io::Result<(O, A)>>,
{
    if scenario == "isolation" {
        // see mux/README.md "Statistics"
        once(&session, "calm", p).await.map_err(|e| io::Error::other(format!("priming: {e}")))?;
    }
    once(&session, scenario, p).await.map_err(|e| io::Error::other(format!("priming: {e}")))?;
    let mut calm = None;
    if scenario == "isolation" {
        let baseline = once(&session, "calm", p).await.map_err(|e| io::Error::other(format!("the calm baseline: {e}")))?;
        if baseline.verdict != "ok" {
            return Err(io::Error::other("the calm baseline missed the deadline"));
        }
        calm = Some(baseline.values["MiB/s"]);
        std::fs::write("/proc/self/clear_refs", "5")?;
    }
    let before = cpu();
    let mut outcome = once(&session, scenario, p).await?;
    outcome.values.insert("cpu ms".into(), cpu() - before);
    if let (Some(calm), "ok") = (calm, outcome.verdict) {
        let stalled = outcome.values["MiB/s"];
        outcome.values.insert("calm MiB/s".into(), calm);
        outcome.values.insert("ratio".into(), stalled / calm);
    }
    Ok(outcome)
}

fn fail(message: String) -> ! {
    eprintln!("peer: {message}");
    exit(2)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() == 3 && args[1] == "version" {
        match version(&args[2]) {
            Some(v) => println!("{v}"),
            None => fail(format!("unknown impl {:?}", args[2])),
        }
        return;
    }
    if args.len() != 4 {
        fail("usage: peer <impl> <scenario> <params json> | peer version <impl>".into());
    }
    let (name, scenario) = (args[1].as_str(), args[2].as_str());
    let p: Params = serde_json::from_str(&args[3]).unwrap_or_else(|e| fail(format!("params: {e}")));
    let rt = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .unwrap_or_else(|e| fail(format!("runtime: {e}")));
    let outcome = rt.block_on(async {
        match name {
            "yamux" => run(yamux::session, scenario, p).await,
            "async-smux" => run(smux::session, scenario, p).await,
            "h2" => run(h2::session, scenario, p).await,
            "qmux" => run(qmux::session, scenario, p).await,
            other => fail(format!("unknown impl {other:?}")),
        }
    });
    match outcome {
        Ok(o) => println!("{}", serde_json::to_string(&o).unwrap()),
        Err(e) => fail(format!("{name} {scenario}: {e}")),
    }
    rt.shutdown_background();
}
