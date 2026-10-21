package main

import (
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"runtime"
	"runtime/debug"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

// see mux/README.md "Scenarios"
type Params struct {
	Window  int     `json:"window"`
	Budget  int     `json:"budget"`
	Chunk   int     `json:"chunk"`
	Bulk    int     `json:"bulk"`
	Flows   int     `json:"flows"`
	Message int     `json:"message"`
	Pings   int     `json:"pings"`
	Warm    int     `json:"warm"`
	Load    int     `json:"load"`
	Churn   int     `json:"churn"`
	Idle    int     `json:"idle"`
	Timeout float64 `json:"timeout"`
}

type Result struct {
	Values  map[string]float64 `json:"values"`
	Verdict string             `json:"verdict"`
}

type Flow = io.ReadWriteCloser

type Session interface {
	Open() (Flow, error)
	Accept() (Flow, error)
	Close() error
}

type Duo struct {
	open   func() (Flow, error)
	accept func() (Flow, error)
	close  func() error
}

func (d Duo) Open() (Flow, error)   { return d.open() }
func (d Duo) Accept() (Flow, error) { return d.accept() }
func (d Duo) Close() error          { return d.close() }

type Mux struct {
	Module string
	New    func(near, far net.Conn, p Params) (Session, error)
}

type bench struct {
	Session
	p    Params
	data []byte
}

// see mux/README.md "Statistics"
func Run(m Mux, scenario string, p Params) (Result, error) {
	if scenario == "isolation" { // see mux/README.md "Statistics"
		if _, err := once(m, "calm", p); err != nil {
			return Result{}, fmt.Errorf("priming: %w", err)
		}
	}
	if _, err := once(m, scenario, p); err != nil {
		return Result{}, fmt.Errorf("priming: %w", err)
	}
	var calm Result
	if scenario == "isolation" {
		var err error
		if calm, err = once(m, "calm", p); err != nil {
			return Result{}, fmt.Errorf("the calm baseline: %w", err)
		}
		if calm.Verdict != "ok" {
			return Result{}, errors.New("the calm baseline missed the deadline")
		}
		if err := os.WriteFile("/proc/self/clear_refs", []byte("5"), 0); err != nil {
			return Result{}, fmt.Errorf("resetting the peak RSS: %w", err)
		}
	}
	before, err := cpu()
	if err != nil {
		return Result{}, err
	}
	r, err := once(m, scenario, p)
	if err != nil {
		return Result{}, err
	}
	after, err := cpu()
	if err != nil {
		return Result{}, err
	}
	r.Values["cpu ms"] = float64(after-before) / 1e6
	if scenario == "isolation" && r.Verdict == "ok" {
		r.Values["calm MiB/s"] = calm.Values["MiB/s"]
		r.Values["ratio"] = r.Values["MiB/s"] / calm.Values["MiB/s"]
	}
	return r, nil
}

func cpu() (int64, error) {
	var u syscall.Rusage
	if err := syscall.Getrusage(syscall.RUSAGE_SELF, &u); err != nil {
		return 0, err
	}
	return u.Utime.Nano() + u.Stime.Nano(), nil
}

func once(m Mux, scenario string, p Params) (Result, error) {
	near, far, err := pair()
	if err != nil {
		return Result{}, err
	}
	s, err := m.New(near, far, p)
	if err != nil {
		return Result{}, err
	}
	defer s.Close()
	b := bench{s, p, make([]byte, p.Chunk)}
	for i := range b.data {
		b.data[i] = 0x5a
	}
	var r Result
	switch scenario {
	case "bulk":
		r, err = b.bulk()
	case "flows":
		r, err = b.flows()
	case "isolation":
		r, err = b.isolation(true)
	case "calm":
		r, err = b.isolation(false)
	case "pingpong":
		r, err = b.pingpong(0)
	case "loaded":
		r, err = b.pingpong(p.Load)
	case "churn":
		r, err = b.churn()
	case "idle":
		r, err = b.idle()
	default:
		return Result{}, fmt.Errorf("unsupported scenario %q", scenario)
	}
	if r.Verdict == "" {
		r.Verdict = "ok"
	}
	if r.Values == nil {
		r.Values = map[string]float64{}
	}
	return r, err
}

func pair() (net.Conn, net.Conn, error) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return nil, nil, err
	}
	defer l.Close()
	type accepted struct {
		c   net.Conn
		err error
	}
	ch := make(chan accepted, 1)
	go func() {
		c, err := l.Accept()
		ch <- accepted{c, err}
	}()
	near, err := net.Dial("tcp", l.Addr().String())
	if err != nil {
		return nil, nil, err
	}
	far := <-ch
	if far.err != nil {
		return nil, nil, far.err
	}
	for _, c := range []net.Conn{near, far.c} {
		if err := c.(*net.TCPConn).SetNoDelay(true); err != nil {
			return nil, nil, err
		}
	}
	return near, far.c, nil
}

func mib(bytes int, d time.Duration) float64 {
	return float64(bytes) / float64(1<<20) / d.Seconds()
}

func (b bench) fill(f Flow, want int) error {
	for sent := 0; sent < want; {
		n := min(len(b.data), want-sent)
		if _, err := f.Write(b.data[:n]); err != nil {
			return err
		}
		sent += n
	}
	return nil
}

func (b bench) drain(f Flow, want int) (time.Time, error) {
	buf := make([]byte, len(b.data))
	for got := 0; got < want; {
		n, err := f.Read(buf)
		got += n
		if err != nil && got < want {
			return time.Time{}, fmt.Errorf("read after %d of %d bytes: %w", got, want, err)
		}
	}
	return time.Now(), nil
}

// see mux/README.md "Scenarios"
func (b bench) opened(n int) ([]Flow, []Flow, error) {
	ins := make(chan Flow, n)
	failed := make(chan error, 1)
	go func() {
		echo := make([]byte, 1)
		for i := 0; i < n; i++ {
			f, err := b.Accept()
			if err == nil {
				_, err = io.ReadFull(f, echo)
			}
			if err == nil {
				_, err = f.Write(echo)
			}
			if err != nil {
				failed <- err
				return
			}
			ins <- f
		}
	}()
	outs := make([]Flow, n)
	for i := range outs {
		f, err := b.Open()
		if err != nil {
			return nil, nil, err
		}
		if _, err := f.Write(b.data[:1]); err != nil {
			return nil, nil, err
		}
		outs[i] = f
	}
	accepted := make([]Flow, n)
	for i := range accepted {
		select {
		case f := <-ins:
			accepted[i] = f
		case err := <-failed:
			return nil, nil, err
		}
	}
	one := make([]byte, 1)
	for _, f := range outs {
		if _, err := io.ReadFull(f, one); err != nil {
			return nil, nil, err
		}
	}
	return outs, accepted, nil
}

func (b bench) bulk() (Result, error) {
	outs, ins, err := b.opened(1)
	if err != nil {
		return Result{}, err
	}
	start := time.Now()
	done := make(chan error, 1)
	var end time.Time
	go func() {
		var err error
		end, err = b.drain(ins[0], b.p.Bulk)
		done <- err
	}()
	if err := b.fill(outs[0], b.p.Bulk); err != nil {
		return Result{}, err
	}
	if err := <-done; err != nil {
		return Result{}, err
	}
	return Result{Values: map[string]float64{"MiB/s": mib(b.p.Bulk, end.Sub(start))}}, nil
}

func (b bench) spread(outs, ins []Flow, share int, deadline time.Duration) ([]time.Time, time.Time, error) {
	start := time.Now()
	ends := make([]time.Time, len(ins))
	errs := make(chan error, 2*len(ins))
	var wg sync.WaitGroup
	for i := range ins {
		wg.Add(2)
		go func(i int) {
			defer wg.Done()
			var err error
			ends[i], err = b.drain(ins[i], share)
			if err != nil {
				errs <- err
			}
		}(i)
		go func(i int) {
			defer wg.Done()
			if err := b.fill(outs[i], share); err != nil {
				errs <- err
			}
		}(i)
	}
	finished := make(chan struct{})
	go func() { wg.Wait(); close(finished) }()
	select {
	case <-finished:
	case <-time.After(deadline):
		return nil, start, missed
	}
	select {
	case err := <-errs:
		return nil, start, err
	default:
	}
	return ends, start, nil
}

var missed = errors.New("deadline")

func fairness(rates []float64) (float64, float64) {
	sum, squares := 0.0, 0.0
	for _, r := range rates {
		sum += r
		squares += r * r
	}
	sorted := append([]float64(nil), rates...)
	sort.Float64s(sorted)
	jain := sum * sum / (float64(len(rates)) * squares)
	return jain, sorted[0] / sorted[len(sorted)/2]
}

func (b bench) flows() (Result, error) {
	n := b.p.Flows
	share := b.p.Bulk / n
	outs, ins, err := b.opened(n)
	if err != nil {
		return Result{}, err
	}
	ends, start, err := b.spread(outs, ins, share, time.Duration(b.p.Timeout*float64(time.Second)))
	if err != nil {
		return Result{}, err
	}
	last := start
	rates := make([]float64, n)
	for i, e := range ends {
		if e.After(last) {
			last = e
		}
		rates[i] = mib(share, e.Sub(start))
	}
	jain, slowest := fairness(rates)
	return Result{Values: map[string]float64{
		"MiB/s":   mib(share*n, last.Sub(start)),
		"jain":    jain,
		"slowest": slowest,
	}}, nil
}

func (b bench) isolation(stalled bool) (Result, error) {
	start, err := status("VmRSS")
	if err != nil {
		return Result{}, err
	}
	n := b.p.Flows
	share := b.p.Bulk / n
	outs, ins, err := b.opened(n)
	if err != nil {
		return Result{}, err
	}
	if stalled {
		go b.fill(outs[0], share) // see mux/README.md "Scenarios"
	}
	ends, began, err := b.spread(outs[1:], ins[1:], share, time.Duration(b.p.Timeout*float64(time.Second)))
	if errors.Is(err, missed) {
		return Result{Values: map[string]float64{}, Verdict: "err"}, nil
	}
	if err != nil {
		return Result{}, err
	}
	last := began
	for _, e := range ends {
		if e.After(last) {
			last = e
		}
	}
	peak, err := status("VmHWM")
	if err != nil {
		return Result{}, err
	}
	return Result{Values: map[string]float64{
		"MiB/s":  mib(share*(n-1), last.Sub(began)),
		"peak B": float64(peak - start),
	}}, nil
}

func percentiles(d []time.Duration) map[string]float64 {
	sort.Slice(d, func(i, j int) bool { return d[i] < d[j] })
	at := func(q float64) float64 {
		i := int(q * float64(len(d)-1))
		return float64(d[i].Nanoseconds()) / 1e3
	}
	return map[string]float64{"p50 µs": at(0.50), "p99 µs": at(0.99), "p999 µs": at(0.999)}
}

func (b bench) pingpong(load int) (Result, error) {
	outs, ins, err := b.opened(1 + load)
	if err != nil {
		return Result{}, err
	}
	stop := make(chan struct{})
	for i := 1; i <= load; i++ {
		go func(out, in Flow) {
			buf := make([]byte, len(b.data))
			go func() {
				for {
					if _, err := in.Read(buf); err != nil {
						return
					}
				}
			}()
			for {
				select {
				case <-stop:
					return
				default:
				}
				if _, err := out.Write(b.data); err != nil {
					return
				}
			}
		}(outs[i], ins[i])
	}
	go func() {
		buf := make([]byte, b.p.Message)
		for {
			if _, err := io.ReadFull(ins[0], buf); err != nil {
				return
			}
			if _, err := ins[0].Write(buf); err != nil {
				return
			}
		}
	}()
	buf := make([]byte, b.p.Message)
	trips := make([]time.Duration, 0, b.p.Pings)
	for i := 0; i < b.p.Warm+b.p.Pings; i++ {
		start := time.Now()
		if _, err := outs[0].Write(b.data[:b.p.Message]); err != nil {
			return Result{}, err
		}
		if _, err := io.ReadFull(outs[0], buf); err != nil {
			return Result{}, err
		}
		if i >= b.p.Warm {
			trips = append(trips, time.Since(start))
		}
	}
	close(stop)
	return Result{Values: percentiles(trips)}, nil
}

func (b bench) churn() (Result, error) {
	n := b.p.Churn
	accepted := make(chan time.Time, n)
	failed := make(chan error, 1)
	go func() {
		for i := 0; i < n; i++ {
			f, err := b.Accept()
			if err != nil {
				failed <- err
				return
			}
			accepted <- time.Now()
			go func() {
				echo := make([]byte, 1)
				if _, err := io.ReadFull(f, echo); err == nil {
					f.Write(echo)
				}
				f.Close()
			}()
		}
	}()
	waits := make([]time.Duration, 0, n)
	one := make([]byte, 1)
	start := time.Now()
	for i := 0; i < n; i++ {
		opened := time.Now()
		f, err := b.Open()
		if err != nil {
			return Result{}, err
		}
		if _, err := f.Write(b.data[:1]); err != nil {
			return Result{}, err
		}
		select {
		case at := <-accepted:
			waits = append(waits, at.Sub(opened))
		case err := <-failed:
			return Result{}, err
		}
		if _, err := io.ReadFull(f, one); err != nil {
			return Result{}, err
		}
		f.Close()
		io.Copy(io.Discard, f)
	}
	spent := time.Since(start)
	latency := percentiles(waits)
	return Result{Values: map[string]float64{
		"cycles/s":    float64(n) / spent.Seconds(),
		"open p50 µs": latency["p50 µs"],
		"open p99 µs": latency["p99 µs"],
	}}, nil
}

func status(field string) (int, error) {
	raw, err := os.ReadFile("/proc/self/status")
	if err != nil {
		return 0, err
	}
	for _, line := range strings.Split(string(raw), "\n") {
		if name, rest, ok := strings.Cut(line, ":"); ok && name == field {
			kb, err := strconv.Atoi(strings.Fields(rest)[0])
			return kb * 1024, err
		}
	}
	return 0, fmt.Errorf("/proc/self/status has no %s", field)
}

func rss() (int, error) {
	runtime.GC()
	debug.FreeOSMemory()
	raw, err := os.ReadFile("/proc/self/statm")
	if err != nil {
		return 0, err
	}
	pages, err := strconv.Atoi(strings.Fields(string(raw))[1])
	if err != nil {
		return 0, err
	}
	return pages * os.Getpagesize(), nil
}

func (b bench) idle() (Result, error) {
	before, err := rss()
	if err != nil {
		return Result{}, err
	}
	outs, ins, err := b.opened(b.p.Idle)
	if err != nil {
		return Result{}, err
	}
	time.Sleep(50 * time.Millisecond) // see mux/README.md "Scenarios"
	after, err := rss()
	if err != nil {
		return Result{}, err
	}
	runtime.KeepAlive(outs)
	runtime.KeepAlive(ins)
	return Result{Values: map[string]float64{"B/flow": float64(after-before) / float64(b.p.Idle)}}, nil
}
