package main

import (
	"context"
	"io"
	"net"

	yamux "github.com/libp2p/go-yamux/v5"
)

var goyamux = Mux{"github.com/libp2p/go-yamux/v5", func(near, far net.Conn, p Params) (Session, error) {
	cfg := yamux.DefaultConfig()
	cfg.InitialStreamWindowSize = uint32(p.Window)
	cfg.MaxStreamWindowSize = uint32(p.Window) // see mux/README.md "Fairness"
	cfg.MaxIncomingStreams = uint32(limit(p))  // see mux/README.md "Fairness"
	cfg.AcceptBacklog = limit(p)
	cfg.EnableKeepAlive = false
	cfg.LogOutput = io.Discard
	c, err := yamux.Client(near, cfg, nil)
	if err != nil {
		return nil, err
	}
	s, err := yamux.Server(far, cfg, nil)
	if err != nil {
		return nil, err
	}
	return Duo{
		open:   func() (Flow, error) { return c.OpenStream(context.Background()) },
		accept: func() (Flow, error) { return s.AcceptStream() },
		close:  func() error { c.Close(); return s.Close() },
	}, nil
}}
