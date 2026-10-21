use crate::scenario::{pair, Acceptor, Opener, Params};
use ::qmux::{transport, Config, RecvStream, SendStream, Session, Version};
use bytes::{Buf, Bytes};
use futures::future::BoxFuture;
use std::io;
use std::pin::Pin;
use std::task::{ready, Context, Poll};
use std::time::Duration;
use tokio::io::{AsyncRead, AsyncWrite, ReadBuf};
use tokio::net::TcpStream;
use tokio::sync::mpsc;
use web_transport_trait::{RecvStream as _, SendStream as _, Session as _};

const CONNECTION: u64 = 1 << 30; // see mux/README.md "Fairness"

type Step<S, T> = BoxFuture<'static, (S, Result<T, ::qmux::Error>)>;

pub struct Flow {
    send: Option<SendStream>,
    sending: Option<Step<SendStream, usize>>,
    recv: Option<RecvStream>,
    receiving: Option<Step<RecvStream, Option<Bytes>>>,
    held: Bytes,
}

impl Flow {
    fn new(send: SendStream, recv: RecvStream) -> Self {
        Flow { send: Some(send), sending: None, recv: Some(recv), receiving: None, held: Bytes::new() }
    }
}

impl AsyncRead for Flow {
    fn poll_read(self: Pin<&mut Self>, cx: &mut Context<'_>, buf: &mut ReadBuf<'_>) -> Poll<io::Result<()>> {
        let this = self.get_mut();
        while this.held.is_empty() {
            if this.receiving.is_none() {
                let Some(mut recv) = this.recv.take() else {
                    return Poll::Ready(Ok(()));
                };
                let max = buf.remaining();
                this.receiving = Some(Box::pin(async move {
                    let got = recv.read_chunk(max).await;
                    (recv, got)
                }));
            }
            let (recv, got) = ready!(this.receiving.as_mut().unwrap().as_mut().poll(cx));
            this.receiving = None;
            match got {
                Ok(Some(b)) => {
                    this.recv = Some(recv);
                    this.held = b;
                }
                Ok(None) => return Poll::Ready(Ok(())),
                Err(e) => return Poll::Ready(Err(io::Error::other(e))),
            }
        }
        let n = this.held.len().min(buf.remaining());
        buf.put_slice(&this.held[..n]);
        this.held.advance(n);
        Poll::Ready(Ok(()))
    }
}

impl Flow {
    fn settle(&mut self, cx: &mut Context<'_>) -> Poll<io::Result<usize>> {
        let (send, wrote) = ready!(self.sending.as_mut().unwrap().as_mut().poll(cx));
        self.sending = None;
        self.send = Some(send);
        Poll::Ready(wrote.map_err(io::Error::other))
    }
}

impl AsyncWrite for Flow {
    fn poll_write(self: Pin<&mut Self>, cx: &mut Context<'_>, buf: &[u8]) -> Poll<io::Result<usize>> {
        let this = self.get_mut();
        if this.sending.is_none() {
            let mut send = this.send.take().ok_or(io::ErrorKind::BrokenPipe)?;
            let data = Bytes::copy_from_slice(buf);
            this.sending = Some(Box::pin(async move {
                let wrote = send.write(&data).await;
                (send, wrote)
            }));
        }
        this.settle(cx)
    }

    fn poll_flush(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        let this = self.get_mut();
        if this.sending.is_some() {
            ready!(this.settle(cx))?;
        }
        Poll::Ready(Ok(()))
    }

    fn poll_shutdown(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        let this = self.get_mut();
        if this.sending.is_some() {
            ready!(this.settle(cx))?;
        }
        if let Some(send) = this.send.as_mut() {
            send.finish().map_err(io::Error::other)?;
        }
        Poll::Ready(Ok(()))
    }
}

pub struct Open(Session);

pub struct Accept(mpsc::UnboundedReceiver<Flow>);

impl Opener for Open {
    type Flow = Flow;

    async fn open(&self) -> io::Result<Flow> {
        let (send, recv) = self.0.open_bi().await.map_err(io::Error::other)?;
        Ok(Flow::new(send, recv))
    }
}

impl Acceptor for Accept {
    type Flow = Flow;

    async fn accept(&mut self) -> io::Result<Flow> {
        self.0.recv().await.ok_or(io::ErrorKind::BrokenPipe.into())
    }
}

fn config(p: &Params) -> Config {
    let mut c = Config::new(Version::QMux02);
    c.max_streams_bidi = p.limit() as u64; // see mux/README.md "Fairness"
    c.max_data = CONNECTION;
    c.max_stream_data_bidi_local = p.window.into();
    c.max_stream_data_bidi_remote = p.window.into();
    c.max_idle_timeout = 0; // see mux/README.md "Fairness"
    c.rtt_interval = Duration::ZERO; // see mux/README.md "Fairness"
    c
}

fn wire(tcp: TcpStream, c: &Config) -> transport::Stream<TcpStream> {
    transport::Stream::new(tcp, c.version, c.max_record_size)
}

pub async fn session(p: Params) -> io::Result<(Open, Accept)> {
    let (near, far) = pair().await?;
    let c = config(&p);
    let (near, far) = tokio::join!(Session::connect(wire(near, &c), c.clone()), Session::accept(wire(far, &c), c.clone()));
    let (near, far) = (near.map_err(io::Error::other)?, far.map_err(io::Error::other)?);
    let (found, inbound) = mpsc::unbounded_channel();
    tokio::spawn(async move {
        while let Ok((send, recv)) = far.accept_bi().await {
            if found.send(Flow::new(send, recv)).is_err() {
                return;
            }
        }
    });
    Ok((Open(near), Accept(inbound)))
}
