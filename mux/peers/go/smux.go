package main

import (
	"net"

	xtaci "github.com/xtaci/smux"
)

var smux = Mux{"github.com/xtaci/smux", func(near, far net.Conn, p Params) (Session, error) {
	cfg := xtaci.DefaultConfig()
	cfg.Version = 2 // per-stream windows; v1 has only the session bucket
	cfg.MaxStreamBuffer = p.Window
	cfg.MaxReceiveBuffer = p.Budget // see mux/README.md "Fairness"
	cfg.KeepAliveDisabled = true
	c, err := xtaci.Client(near, cfg)
	if err != nil {
		return nil, err
	}
	s, err := xtaci.Server(far, cfg)
	if err != nil {
		return nil, err
	}
	return Duo{
		open:   func() (Flow, error) { return c.OpenStream() },
		accept: func() (Flow, error) { return s.AcceptStream() },
		close:  func() error { c.Close(); return s.Close() },
	}, nil
}}
