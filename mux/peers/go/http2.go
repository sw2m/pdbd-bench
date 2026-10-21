package main

import (
	"io"
	"net"
	"net/http"

	xhttp2 "golang.org/x/net/http2"
)

type inbound struct {
	body io.ReadCloser
	w    http.ResponseWriter
	done chan struct{}
}

func (f *inbound) Read(p []byte) (int, error) { return f.body.Read(p) }

func (f *inbound) Write(p []byte) (int, error) {
	n, err := f.w.Write(p)
	f.w.(http.Flusher).Flush()
	return n, err
}

func (f *inbound) Close() error {
	select {
	case <-f.done:
	default:
		close(f.done)
	}
	return nil
}

type outbound struct {
	body *io.PipeWriter
	resp io.ReadCloser
}

func (f *outbound) Read(p []byte) (int, error)  { return f.resp.Read(p) }
func (f *outbound) Write(p []byte) (int, error) { return f.body.Write(p) }
func (f *outbound) Close() error                { return f.body.Close() }

var http2 = Mux{"golang.org/x/net", func(near, far net.Conn, p Params) (Session, error) {
	found := make(chan io.ReadWriteCloser, limit(p))
	srv := &xhttp2.Server{
		MaxConcurrentStreams:         uint32(limit(p)), // see mux/README.md "Fairness"
		MaxUploadBufferPerStream:     int32(p.Window),
		MaxUploadBufferPerConnection: 1 << 30, // see mux/README.md "Fairness"
	}
	go srv.ServeConn(far, &xhttp2.ServeConnOpts{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.(http.Flusher).Flush()
		f := &inbound{r.Body, w, make(chan struct{})}
		found <- f
		<-f.done
	})})
	cc, err := (&xhttp2.Transport{AllowHTTP: true}).NewClientConn(near)
	if err != nil {
		return nil, err
	}
	return Duo{
		open: func() (Flow, error) {
			pr, pw := io.Pipe()
			req, err := http.NewRequest(http.MethodPost, "http://peer/", pr)
			if err != nil {
				return nil, err
			}
			resp, err := cc.RoundTrip(req)
			if err != nil {
				return nil, err
			}
			return &outbound{pw, resp.Body}, nil
		},
		accept: func() (Flow, error) { return <-found, nil },
		close:  func() error { cc.Close(); return far.Close() },
	}, nil
}}
