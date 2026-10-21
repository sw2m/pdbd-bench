package main

import (
	"io"
	"net"

	yamux "github.com/hashicorp/yamux"
)

var hashicorp = Mux{"github.com/hashicorp/yamux", func(near, far net.Conn, p Params) (Session, error) {
	cfg := yamux.DefaultConfig()
	cfg.MaxStreamWindowSize = uint32(p.Window)
	cfg.AcceptBacklog = limit(p) // see mux/README.md "Fairness"
	cfg.EnableKeepAlive = false
	cfg.LogOutput = io.Discard
	c, err := yamux.Client(near, cfg)
	if err != nil {
		return nil, err
	}
	s, err := yamux.Server(far, cfg)
	if err != nil {
		return nil, err
	}
	return Duo{
		open:   func() (Flow, error) { return c.OpenStream() },
		accept: func() (Flow, error) { return s.AcceptStream() },
		close:  func() error { c.Close(); return s.Close() },
	}, nil
}}
