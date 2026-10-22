use crate::scenario::{pair, Acceptor, Opener, Params};
use ::async_smux::{MuxAcceptor, MuxBuilder, MuxConnector, MuxStream};
use std::io;
use std::num::NonZeroUsize;
use tokio::net::TcpStream;

pub struct Open(MuxConnector<TcpStream>);

pub struct Accept(MuxAcceptor<TcpStream>);

impl Opener for Open {
    type Flow = MuxStream<TcpStream>;

    async fn open(&self) -> io::Result<Self::Flow> {
        self.0.connect().map_err(io::Error::other)
    }
}

impl Acceptor for Accept {
    type Flow = MuxStream<TcpStream>;

    async fn accept(&mut self) -> io::Result<Self::Flow> {
        self.0.accept().await.ok_or(io::ErrorKind::BrokenPipe.into())
    }
}

pub async fn session(p: Params) -> io::Result<(Open, Accept)> {
    let (near, far) = pair().await?;
    let queue = NonZeroUsize::new(p.budget / p.chunk).unwrap(); // see mux/README.md "Fairness"
    let (connector, _, worker) = MuxBuilder::client().with_max_rx_queue(queue).with_connection(near).build();
    tokio::spawn(worker);
    let (_, acceptor, worker) = MuxBuilder::server().with_max_rx_queue(queue).with_connection(far).build();
    tokio::spawn(worker);
    Ok((Open(connector), Accept(acceptor)))
}
