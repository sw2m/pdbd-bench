package main

import (
	"encoding/json"
	"fmt"
	"os"
	"runtime/debug"
)

var muxes = map[string]Mux{
	"hashicorp-yamux": hashicorp,
	"go-yamux":        goyamux,
	"smux":            smux,
	"x-http2":         http2,
	"mplex":           mplex,
}

func version(path string) string {
	if info, ok := debug.ReadBuildInfo(); ok {
		for _, d := range info.Deps {
			if d.Path == path {
				return d.Version
			}
		}
	}
	return ""
}

func main() {
	if len(os.Args) == 3 && os.Args[1] == "version" {
		m, ok := muxes[os.Args[2]]
		if !ok {
			fail("unknown impl %q", os.Args[2])
		}
		fmt.Println(version(m.Module))
		return
	}
	if len(os.Args) != 4 {
		fail("usage: peer <impl> <scenario> <params json> | peer version <impl>")
	}
	m, ok := muxes[os.Args[1]]
	if !ok {
		fail("unknown impl %q", os.Args[1])
	}
	var p Params
	if err := json.Unmarshal([]byte(os.Args[3]), &p); err != nil {
		fail("params: %v", err)
	}
	result, err := Run(m, os.Args[2], p)
	if err != nil {
		fail("%s %s: %v", os.Args[1], os.Args[2], err)
	}
	must(json.NewEncoder(os.Stdout).Encode(result))
}

func fail(format string, args ...any) {
	fmt.Fprintf(os.Stderr, "peer: "+format+"\n", args...)
	os.Exit(2)
}

func must(err error) {
	if err != nil {
		panic(err)
	}
}
