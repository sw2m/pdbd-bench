use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::future::Future;
use std::io;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::mpsc;

// see mux/README.md "Scenarios"
#[derive(Deserialize, Clone, Copy, Default)]
#[serde(default)]
pub struct Params {
    pub window: u32,
    pub budget: usize,
    pub chunk: usize,
    pub bulk: usize,
    pub flows: usize,
    pub message: usize,
    pub pings: usize,
    pub warm: usize,
    pub load: usize,
    pub churn: usize,
    pub idle: usize,
    pub timeout: f64,
}

impl Params {
    pub fn limit(&self) -> usize {
        self.flows.max(self.load + 1).max(self.idle).max(self.churn) + 1
    }

    fn deadline(&self) -> Duration {
        Duration::from_secs_f64(self.timeout)
    }
}

#[derive(Serialize, Default)]
pub struct Outcome {
    pub values: BTreeMap<String, f64>,
    pub verdict: &'static str,
}

impl Outcome {
    fn of(values: &[(&str, f64)]) -> Self {
        let values = values.iter().map(|(k, v)| (k.to_string(), *v)).collect();
        Outcome { values, verdict: "ok" }
    }
}

pub trait Flow: AsyncRead + AsyncWrite + Unpin + Send + 'static {}

impl<T: AsyncRead + AsyncWrite + Unpin + Send + 'static> Flow for T {}

pub trait Opener: Send + Sync + 'static {
    type Flow: Flow;
    fn open(&self) -> impl Future<Output = io::Result<Self::Flow>> + Send;
}

pub trait Acceptor: Send + 'static {
    type Flow: Flow;
    fn accept(&mut self) -> impl Future<Output = io::Result<Self::Flow>> + Send;
}

pub async fn pair() -> io::Result<(TcpStream, TcpStream)> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let addr = listener.local_addr()?;
    let (near, far) = tokio::join!(TcpStream::connect(addr), listener.accept());
    let (near, (far, _)) = (near?, far?);
    near.set_nodelay(true)?;
    far.set_nodelay(true)?;
    Ok((near, far))
}

fn mib(bytes: usize, spent: Duration) -> f64 {
    bytes as f64 / (1 << 20) as f64 / spent.as_secs_f64()
}

async fn fill(flow: &mut impl Flow, data: &[u8], want: usize) -> io::Result<()> {
    let mut sent = 0;
    while sent < want {
        let n = data.len().min(want - sent);
        flow.write_all(&data[..n]).await?;
        sent += n;
    }
    flow.flush().await
}

async fn drain(flow: &mut impl Flow, chunk: usize, want: usize) -> io::Result<Instant> {
    let mut buf = vec![0; chunk];
    let mut got = 0;
    while got < want {
        match flow.read(&mut buf).await? {
            0 => return Err(io::Error::other(format!("EOF after {got} of {want} bytes"))),
            n => got += n,
        }
    }
    Ok(Instant::now())
}

fn jain(rates: &[f64]) -> (f64, f64) {
    let sum: f64 = rates.iter().sum();
    let squares: f64 = rates.iter().map(|r| r * r).sum();
    let mut sorted = rates.to_vec();
    sorted.sort_by(f64::total_cmp);
    (sum * sum / (rates.len() as f64 * squares), sorted[0] / sorted[sorted.len() / 2])
}

fn percentiles(mut trips: Vec<Duration>, prefix: &str) -> Vec<(String, f64)> {
    trips.sort();
    let at = |q: f64| trips[(q * (trips.len() - 1) as f64) as usize].as_secs_f64() * 1e6;
    let mut out = vec![(format!("{prefix}p50 µs"), at(0.50)), (format!("{prefix}p99 µs"), at(0.99))];
    if prefix.is_empty() {
        out.push(("p999 µs".into(), at(0.999)));
    }
    out
}

pub fn status(field: &str) -> io::Result<f64> {
    let raw = std::fs::read_to_string("/proc/self/status")?;
    raw.lines()
        .find_map(|l| l.strip_prefix(field)?.strip_prefix(':'))
        .and_then(|rest| rest.split_whitespace().next()?.parse::<f64>().ok())
        .map(|kb| kb * 1024.0)
        .ok_or_else(|| io::Error::other(format!("/proc/self/status has no {field}")))
}

pub struct Bench<O, A> {
    pub open: Arc<O>,
    pub accept: A,
    pub p: Params,
    pub data: Arc<Vec<u8>>,
}

impl<O: Opener, A: Acceptor> Bench<O, A> {
    async fn opened(&mut self, n: usize) -> io::Result<(Vec<O::Flow>, Vec<A::Flow>)> {
        let accept = &mut self.accept;
        let open = &self.open;
        let ins = async {
            let mut ins = Vec::with_capacity(n);
            for _ in 0..n {
                let mut f = accept.accept().await?;
                let mut one = [0];
                f.read_exact(&mut one).await?;
                f.write_all(&one).await?;
                f.flush().await?;
                ins.push(f);
            }
            io::Result::Ok(ins)
        };
        let outs = async {
            let mut outs = Vec::with_capacity(n);
            for _ in 0..n {
                let mut f = open.open().await?;
                f.write_all(&[0x5a]).await?;
                f.flush().await?;
                outs.push(f);
            }
            io::Result::Ok(outs)
        };
        let (ins, outs) = tokio::join!(ins, outs);
        let (mut outs, ins) = (outs?, ins?);
        for f in outs.iter_mut() {
            let mut one = [0];
            f.read_exact(&mut one).await?;
        }
        Ok((outs, ins))
    }

    pub async fn bulk(&mut self) -> io::Result<Outcome> {
        let (mut outs, mut ins) = self.opened(1).await?;
        let (data, chunk, bulk) = (self.data.clone(), self.p.chunk, self.p.bulk);
        let start = Instant::now();
        let (end, sent) = tokio::join!(drain(&mut ins[0], chunk, bulk), fill(&mut outs[0], &data, bulk));
        sent?;
        Ok(Outcome::of(&[("MiB/s", mib(bulk, end? - start))]))
    }

    async fn spread(
        &self,
        outs: Vec<O::Flow>,
        ins: Vec<A::Flow>,
        share: usize,
    ) -> io::Result<Option<(Instant, Vec<Instant>)>> {
        let start = Instant::now();
        let mut readers = Vec::with_capacity(ins.len());
        for mut f in ins {
            let chunk = self.p.chunk;
            readers.push(tokio::spawn(async move { drain(&mut f, chunk, share).await.map(|e| (e, f)) }));
        }
        let mut writers = Vec::with_capacity(outs.len());
        for mut f in outs {
            let data = self.data.clone();
            writers.push(tokio::spawn(async move { fill(&mut f, &data, share).await.map(|_| f) }));
        }
        let all = async {
            let mut ends = Vec::with_capacity(readers.len());
            for r in readers {
                ends.push(r.await.map_err(io::Error::other)??.0);
            }
            for w in writers {
                w.await.map_err(io::Error::other)??;
            }
            io::Result::Ok(ends)
        };
        match tokio::time::timeout(self.p.deadline(), all).await {
            Ok(ends) => Ok(Some((start, ends?))),
            Err(_) => Ok(None),
        }
    }

    pub async fn flows(&mut self) -> io::Result<Outcome> {
        let n = self.p.flows;
        let share = self.p.bulk / n;
        let (outs, ins) = self.opened(n).await?;
        let Some((start, ends)) = self.spread(outs, ins, share).await? else {
            return Err(io::Error::other("flows missed the deadline"));
        };
        let last = *ends.iter().max().unwrap();
        let rates: Vec<f64> = ends.iter().map(|e| mib(share, *e - start)).collect();
        let (jain, slowest) = jain(&rates);
        Ok(Outcome::of(&[("MiB/s", mib(share * n, last - start)), ("jain", jain), ("slowest", slowest)]))
    }

    pub async fn isolation(&mut self, stalled: bool) -> io::Result<Outcome> {
        let begin = status("VmRSS")?;
        let n = self.p.flows;
        let share = self.p.bulk / n;
        let (mut outs, mut ins) = self.opened(n).await?;
        let mut quiet = outs.remove(0);
        let held = ins.remove(0);
        let data = self.data.clone();
        let blocked = tokio::spawn(async move {
            if stalled {
                let _ = fill(&mut quiet, &data, share).await; // see mux/README.md "Scenarios"
            }
            quiet
        });
        let outcome = match self.spread(outs, ins, share).await? {
            None => Outcome { values: BTreeMap::new(), verdict: "err" },
            Some((start, ends)) => {
                let last = *ends.iter().max().unwrap();
                let peak = status("VmHWM")?;
                Outcome::of(&[("MiB/s", mib(share * (n - 1), last - start)), ("peak B", peak - begin)])
            }
        };
        blocked.abort();
        drop(held);
        Ok(outcome)
    }

    pub async fn pingpong(&mut self, load: usize) -> io::Result<Outcome> {
        let (mut outs, mut ins) = self.opened(1 + load).await?;
        let stop = Arc::new(AtomicBool::new(false));
        let mut tasks = Vec::new();
        for (mut out, mut inbound) in outs.drain(1..).zip(ins.drain(1..)) {
            let (data, stop, chunk) = (self.data.clone(), stop.clone(), self.p.chunk);
            tasks.push(tokio::spawn(async move {
                let mut buf = vec![0; chunk];
                while inbound.read(&mut buf).await.map(|n| n > 0).unwrap_or(false) {}
            }));
            tasks.push(tokio::spawn(async move {
                while !stop.load(Ordering::Relaxed) {
                    if out.write_all(&data).await.is_err() {
                        break;
                    }
                }
            }));
        }
        let (mut near, mut far) = (outs.remove(0), ins.remove(0));
        let message = self.p.message;
        tasks.push(tokio::spawn(async move {
            let mut buf = vec![0; message];
            while far.read_exact(&mut buf).await.is_ok() {
                if far.write_all(&buf).await.is_err() || far.flush().await.is_err() {
                    break;
                }
            }
        }));
        let mut buf = vec![0; message];
        let mut trips = Vec::with_capacity(self.p.pings);
        for i in 0..self.p.warm + self.p.pings {
            let start = Instant::now();
            near.write_all(&self.data[..message]).await?;
            near.flush().await?;
            near.read_exact(&mut buf).await?;
            if i >= self.p.warm {
                trips.push(start.elapsed());
            }
        }
        stop.store(true, Ordering::Relaxed);
        for t in tasks {
            t.abort();
        }
        let values: Vec<(String, f64)> = percentiles(trips, "");
        Ok(Outcome { values: values.into_iter().collect(), verdict: "ok" })
    }

    pub async fn churn(&mut self) -> io::Result<Outcome> {
        let n = self.p.churn;
        let (accepted, mut arrivals) = mpsc::unbounded_channel();
        let accept = &mut self.accept;
        let server = async {
            for _ in 0..n {
                let mut f = accept.accept().await?;
                let _ = accepted.send(Instant::now());
                tokio::spawn(async move {
                    let mut one = [0];
                    if f.read_exact(&mut one).await.is_ok() && f.write_all(&one).await.is_ok() {
                        let _ = f.flush().await;
                        let _ = f.shutdown().await;
                        while f.read(&mut one).await.unwrap_or(0) > 0 {}
                    }
                });
            }
            io::Result::Ok(())
        };
        let open = &self.open;
        let client = async {
            let mut waits = Vec::with_capacity(n);
            let start = Instant::now();
            for _ in 0..n {
                let opened = Instant::now();
                let mut f = open.open().await?;
                f.write_all(&[0x5a]).await?;
                f.flush().await?;
                let at = arrivals.recv().await.ok_or_else(|| io::Error::other("acceptor gone"))?;
                waits.push(at.saturating_duration_since(opened));
                let mut one = [0];
                f.read_exact(&mut one).await?;
                f.shutdown().await?;
                while f.read(&mut one).await.unwrap_or(0) > 0 {}
            }
            io::Result::Ok((start.elapsed(), waits))
        };
        let (served, timed) = tokio::join!(server, client);
        served?;
        let (spent, waits) = timed?;
        let mut values: Vec<(String, f64)> = vec![("cycles/s".into(), n as f64 / spent.as_secs_f64())];
        values.extend(percentiles(waits, "open "));
        Ok(Outcome { values: values.into_iter().collect(), verdict: "ok" })
    }

    pub async fn idle(&mut self) -> io::Result<Outcome> {
        let before = rss()?;
        let n = self.p.idle;
        let (outs, ins) = self.opened(n).await?;
        tokio::time::sleep(Duration::from_millis(50)).await; // see mux/README.md "Scenarios"
        let after = rss()?;
        drop((outs, ins));
        Ok(Outcome::of(&[("B/flow", (after - before) / n as f64)]))
    }
}

fn rss() -> io::Result<f64> {
    unsafe { libc::malloc_trim(0) };
    status("VmRSS")
}
