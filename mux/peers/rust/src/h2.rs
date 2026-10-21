use crate::scenario::{pair, Acceptor, Opener, Params};
use ::h2::{client, server, RecvStream, SendStream};
use bytes::{Buf, Bytes};
use std::io;
use std::pin::Pin;
use std::task::{ready, Context, Poll};
use tokio::io::{AsyncRead, AsyncWrite, ReadBuf};
use tokio::sync::{mpsc, Mutex};

const CONNECTION: u32 = 1 << 30; // see mux/README.md "Fairness"

pub struct Flow {
    send: SendStream<Bytes>,
    recv: RecvStream,
    held: Bytes,
}

impl AsyncRead for Flow {
    fn poll_read(mut self: Pin<&mut Self>, cx: &mut Context<'_>, buf: &mut ReadBuf<'_>) -> Poll<io::Result<()>> {
        while self.held.is_empty() {
            match ready!(self.recv.poll_data(cx)) {
                Some(Ok(b)) => self.held = b,
                Some(Err(e)) => return Poll::Ready(Err(io::Error::other(e))),
                None => return Poll::Ready(Ok(())),
            }
        }
        let n = self.held.len().min(buf.remaining());
        buf.put_slice(&self.held[..n]);
        self.held.advance(n);
        let _ = self.recv.flow_control().release_capacity(n);
        Poll::Ready(Ok(()))
    }
}

impl AsyncWrite for Flow {
    fn poll_write(mut self: Pin<&mut Self>, cx: &mut Context<'_>, buf: &[u8]) -> Poll<io::Result<usize>> {
        self.send.reserve_capacity(buf.len());
        let n = loop {
            match self.send.capacity() {
                0 => match ready!(self.send.poll_capacity(cx)) {
                    Some(Ok(_)) => continue,
                    Some(Err(e)) => return Poll::Ready(Err(io::Error::other(e))),
                    None => return Poll::Ready(Err(io::ErrorKind::BrokenPipe.into())),
                },
                n => break n.min(buf.len()),
            }
        };
        self.send.send_data(Bytes::copy_from_slice(&buf[..n]), false).map_err(io::Error::other)?;
        Poll::Ready(Ok(n))
    }

    fn poll_flush(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<io::Result<()>> {
        Poll::Ready(Ok(()))
    }

    fn poll_shutdown(mut self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<io::Result<()>> {
        let _ = self.send.send_data(Bytes::new(), true);
        Poll::Ready(Ok(()))
    }
}

pub struct Open(Mutex<client::SendRequest<Bytes>>);

pub struct Accept(mpsc::UnboundedReceiver<Flow>);

impl Opener for Open {
    type Flow = Flow;

    async fn open(&self) -> io::Result<Flow> {
        let ask = self.0.lock().await.clone();
        let mut ask = ask.ready().await.map_err(io::Error::other)?;
        let (answer, send) = ask.send_request(http::Request::new(()), false).map_err(io::Error::other)?;
        let recv = answer.await.map_err(io::Error::other)?.into_body();
        Ok(Flow { send, recv, held: Bytes::new() })
    }
}

impl Acceptor for Accept {
    type Flow = Flow;

    async fn accept(&mut self) -> io::Result<Flow> {
        self.0.recv().await.ok_or(io::ErrorKind::BrokenPipe.into())
    }
}

pub async fn session(p: Params) -> io::Result<(Open, Accept)> {
    let (near, far) = pair().await?;
    let (found, inbound) = mpsc::unbounded_channel();
    let limit = p.limit() as u32; // see mux/README.md "Fairness"
    tokio::spawn(async move {
        let Ok(mut conn) = server::Builder::new()
            .initial_window_size(p.window)
            .initial_connection_window_size(CONNECTION)
            .max_concurrent_streams(limit)
            .handshake::<_, Bytes>(far)
            .await
        else {
            return;
        };
        while let Some(Ok((request, mut respond))) = conn.accept().await {
            let Ok(send) = respond.send_response(http::Response::new(()), false) else {
                return;
            };
            let _ = found.send(Flow { send, recv: request.into_body(), held: Bytes::new() });
        }
    });
    let (ask, conn) = client::Builder::new()
        .initial_window_size(p.window)
        .initial_connection_window_size(CONNECTION)
        .max_concurrent_streams(limit)
        .handshake::<_, Bytes>(near)
        .await
        .map_err(io::Error::other)?;
    tokio::spawn(conn);
    Ok((Open(Mutex::new(ask)), Accept(inbound)))
}
