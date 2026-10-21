use crate::scenario::{pair, Acceptor, Opener, Params};
use ::yamux::{Config, Connection, Mode, Stream};
use futures::future::poll_fn;
use std::collections::VecDeque;
use std::io;
use std::task::Poll;
use tokio::net::TcpStream;
use tokio::sync::{mpsc, oneshot};
use tokio_util::compat::{Compat, FuturesAsyncReadCompatExt, TokioAsyncReadCompatExt};

pub struct Open(mpsc::UnboundedSender<oneshot::Sender<Stream>>);

pub struct Accept(mpsc::UnboundedReceiver<Stream>);

impl Opener for Open {
    type Flow = Compat<Stream>;

    async fn open(&self) -> io::Result<Self::Flow> {
        let (tx, rx) = oneshot::channel();
        self.0.send(tx).map_err(|_| io::ErrorKind::BrokenPipe)?;
        Ok(rx.await.map_err(|_| io::ErrorKind::BrokenPipe)?.compat())
    }
}

impl Acceptor for Accept {
    type Flow = Compat<Stream>;

    async fn accept(&mut self) -> io::Result<Self::Flow> {
        Ok(self.0.recv().await.ok_or(io::ErrorKind::BrokenPipe)?.compat())
    }
}

async fn drive(
    mut conn: Connection<Compat<TcpStream>>,
    mut asks: mpsc::UnboundedReceiver<oneshot::Sender<Stream>>,
    found: mpsc::UnboundedSender<Stream>,
) {
    let mut waiting = VecDeque::new();
    poll_fn(|cx| {
        while let Poll::Ready(Some(ask)) = asks.poll_recv(cx) {
            waiting.push_back(ask);
        }
        while !waiting.is_empty() {
            match conn.poll_new_outbound(cx) {
                Poll::Ready(Ok(s)) => {
                    let ask: oneshot::Sender<Stream> = waiting.pop_front().unwrap();
                    let _ = ask.send(s);
                }
                Poll::Ready(Err(_)) => return Poll::Ready(()),
                Poll::Pending => break,
            }
        }
        loop {
            match conn.poll_next_inbound(cx) {
                Poll::Ready(Some(Ok(s))) => {
                    let _ = found.send(s);
                }
                Poll::Ready(_) => return Poll::Ready(()),
                Poll::Pending => return Poll::Pending,
            }
        }
    })
    .await
}

fn side(tcp: TcpStream, mode: Mode, p: &Params) -> (Open, Accept) {
    let mut cfg = Config::default();
    cfg.set_max_num_streams(p.limit()); // see mux/README.md "Fairness"
    // see mux/README.md "Fairness"
    cfg.set_max_connection_receive_window(Some(p.budget.max(256 * 1024 * p.limit())));
    let conn = Connection::new(tcp.compat(), cfg, mode);
    let (asks, rx) = mpsc::unbounded_channel();
    let (found, inbound) = mpsc::unbounded_channel();
    tokio::spawn(drive(conn, rx, found));
    (Open(asks), Accept(inbound))
}

pub async fn session(p: Params) -> io::Result<(Open, Accept)> {
    let (near, far) = pair().await?;
    let (open, _) = side(near, Mode::Client, &p);
    let (_, accept) = side(far, Mode::Server, &p);
    Ok((open, accept))
}
