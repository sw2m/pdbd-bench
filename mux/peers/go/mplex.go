package main

import (
	"context"
	"net"

	gompx "github.com/libp2p/go-mplex"
)

var mplex = Mux{"github.com/libp2p/go-mplex", func(near, far net.Conn, p Params) (Session, error) {
	c, err := gompx.NewMultiplex(near, true, nil)
	if err != nil {
		return nil, err
	}
	s, err := gompx.NewMultiplex(far, false, nil)
	if err != nil {
		return nil, err
	}
	return Duo{
		open:   func() (Flow, error) { return c.NewStream(context.Background()) },
		accept: func() (Flow, error) { return s.Accept() },
		close:  func() error { c.Close(); return s.Close() },
	}, nil
}}
