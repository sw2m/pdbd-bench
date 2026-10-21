# mux

pdbd's stream multiplexer (`crates/mux`, sw2m/pdbd#58) against the multiplexers people use, in
the languages they use them from. A container on `images:debian/12/cloud`: loopback TCP needs no
kernel of the runner's own.

Every impl is raced by a harness in its own language, and every harness speaks one protocol, so
the Python entrypoint drives them all the same way:

```
<harness> <impl> <scenario> <params json>    one measurement: prints {"values": {unit: value}, "verdict": "ok" | "err"}
<harness> version <impl>                     the version the harness was built against
```

Each measurement is a fresh process over a fresh loopback TCP pair (`127.0.0.1`, `TCP_NODELAY`),
both ends of the session in that one process.

## Rows

| Row | Tags | Samples |
| --- | --- | --- |
| `comparator` | `impl`, `package`, `version`, `mode` (`floating` or `pinned`), `toolchain`; for ours, `budget` | verdict `ok`: what was raced, built and verified |
| `bulk` | `impl` | `MiB/s`, `ms/MiB` (CPU) |
| `flows` | `impl`, `flows` (16, 256) | `MiB/s`, `jain`, `slowest`, `ms/MiB` |
| `isolation` | `impl`, `flows` (16) | `MiB/s` (stalled), `calm MiB/s`, `ratio`, `peak B` |
| `isolated` | `impl` | verdict: `ok` when every repetition's 15 other flows finished within `timeout` |
| `pingpong`, `loaded` | `impl` | `p50 µs`, `p99 µs`, `p999 µs` |
| `churn` | `impl` | `cycles/s`, `open p50 µs`, `open p99 µs` |
| `idle` | `impl` | `B/flow` |
| `udp` | `impl` (ours only), `datagram` (64, 512, 1400) | `datagrams/s` |

Each sample is one repetition's value, so bencher's `stats` give each unit's median and, with six
or more repetitions, its distribution-free 95% interval. No unit has a `.` in it, since an
expectation addresses one as `samples.<unit>.<stat>`.

## Params

| Param | Default | |
| --- | --- | --- |
| `repeat` | `7` | repetitions; see Statistics |
| `timeout` | `60` | s a scenario may take before it misses its deadline |
| `window` | `262144` | B, every impl's per-flow window; see Fairness |
| `budget` | `67108864` | B, the local receive bound, ours and the impls that have one |
| `chunk` | `65536` | B per write |
| `bulk` | `268435456` | B moved by `bulk`, and shared out by `flows` and `isolation` |
| `flows` | `[16, 256]` | flow counts for `flows` |
| `isolated` | `16` | flows in `isolation`; one of `flows`, the baseline it's read against |
| `message` | `64` | B per `pingpong`/`loaded` message |
| `pings` | `10000` | measured `pingpong` round trips; at least 1000, so a p99.9 has ten samples above it |
| `trips` | `2000` | measured `loaded` round trips, also at least 1000: a mux with head-of-line blocking takes milliseconds a trip under load, and `pings` of them would outrun `timeout` |
| `lead` | `100` | round trips before the measured ones |
| `busy` | `4` | flows running bulk traffic during `loaded` |
| `churn` | `1000` | open/close cycles |
| `idle` | `1000` | flows held by `idle` |
| `datagrams` | `200000` | datagrams per `udp` size |
| `sizes` | `[64, 512, 1400]` | datagram sizes for `udp` |
| `impls` | every impl | the impls to race |
| `scenarios` | every scenario | the scenarios to run |
| `pins.<comparator>` | latest | a comparator's version; unset, the latest release races (comparators float) |

| Artifact | |
| --- | --- |
| `muxbench` | pdbd's `crates/mux/examples/muxbench.rs`, built static: ours, as `core` (two `Multi`s fed into each other, no sockets) and `loopback` (a single-threaded busy-poll loop over the pair). Without it, only the comparators race |

`muxbench` speaks the harness protocol above, with `core` and `loopback` as its impls, and runs
every scenario including `udp`. Its `loopback` driver is a lower bound for pdbd's own event loop
(#59), which the report says.

## Scenarios

Every flow is primed before any clock starts: the opener sends one byte, the acceptor echoes it,
and the opener reads it back. A round trip, not one byte one way: a yamux stream stays unacknowledged
until the accepting side sends on it, and yamux implementations stop opening at 256 unacknowledged
streams (rust-yamux's `MAX_ACK_BACKLOG`), which a one-way byte never clears.

- **`bulk`**: one flow carries `bulk` bytes one way.
- **`flows`**: N flows are opened, accepted and primed, then each writes `bulk / N` concurrently.
  `jain` is Jain's fairness index over per-flow throughputs (a flow's bytes over its own finish
  time), bounded by 1/N and 1; `slowest` is the slowest flow's throughput over the median's.
- **`isolation`**: `isolated` flows, of which flow 0's reader takes only its priming byte. The
  measured run *stalls* it: flow 0's writer fills its window and blocks. A *calm* run in the same
  process, before it, leaves flow 0 silent instead. `MiB/s` is the other flows' aggregate when
  stalled, `ratio` is stalled over calm (1.0 is full isolation), and `peak B` is the process's
  peak RSS growth over the stalled run (`VmHWM` after `clear_refs`, less `VmRSS` before). A stall
  that keeps the other flows from finishing within `timeout` is the `isolated` verdict `err`,
  which is a result, not a runner failure.
- **`pingpong`**: `lead` then `pings` round trips of a `message`-byte message on one flow over an
  idle tunnel; percentiles of the measured ones.
- **`loaded`**: `lead` then `trips` round trips, while `busy` other flows run bulk traffic.
- **`churn`**: `churn` cycles of open, accept, one byte each way, and close both ways. `open`
  latency is from the open call to the far side's accept.
- **`idle`**: `idle` flows opened (priming touches each one both ways) and held. `B/flow` is the process's
  RSS growth over the same process before opening, divided by `idle`, after each runtime returns
  freed memory to the OS: Go `FreeOSMemory`, glibc `malloc_trim` (Rust, C), a compacting .NET
  collection, Node's `gc()` twice, and the JVM collecting under `-XX:+UseSerialGC` with heap free
  ratios of 0 (G1 doesn't return heap on demand; only `idle` runs that way). A runtime's
  allocator counters differ from runtime to runtime and stay out of the comparison.
- **`udp`**: ours only, since the others are stream-only: one UDP flow carries `datagrams`
  datagrams of each size.

`bulk` and `flows` also report `ms/MiB`: the harness process's user + system CPU time over the
measured run, read from the runtime's microsecond process clock (`getrusage`, Go's `Getrusage`,
Node's `cpuUsage`, through the JVM's Foreign Function API), per MiB moved. bencher's telemetry
samples a reporter at an interval, so it can miss or part-count a sub-second scenario.

## Comparators

| `impl` | Project | Runtime |
| --- | --- | --- |
| `core`, `loopback` | ours (`muxbench`) | Rust |
| `yamux` | libp2p/rust-yamux | Rust |
| `async-smux` | `async_smux` | Rust |
| `h2` | `h2` | Rust |
| `hashicorp-yamux` | hashicorp/yamux | Go |
| `go-yamux` | libp2p/go-yamux | Go |
| `smux` | xtaci/smux, v2 | Go |
| `x-http2` | `golang.org/x/net/http2` | Go |
| `mplex` | libp2p/go-mplex | Go |
| `nerdbank` | Nerdbank.Streams `MultiplexingStream`, protocol v3 | C# |
| `nghttp2-core`, `nghttp2-loopback` | nghttp2, through `nghttp2_session_mem_recv2`/`mem_send2` | C |
| `libp2p-yamux` | `@libp2p/yamux` | Node |
| `netty-http2` | netty `Http2FrameCodec` + `Http2MultiplexHandler` | JVM |

A library raced more than one way is one comparator with several impls (`modes`): nghttp2, like
ours, races sans-IO core to core as well as over loopback, which is the only fair company for
ours' `core`. `mplex` has no per-flow flow control: it races `flows` and `isolation` only, as the
control that shows what a missing window costs, not as a competitor.

An HTTP/2 flow is one POST: the request body carries near → far, the response body far → near.
Opening one sends headers, which `churn` pays for; the report says so.

Not compared, since they aren't a mux over a given byte stream: quinn and quic-go (QUIC owns its
UDP transport), russh (SSH adds mandatory crypto) and muxado. pdbd's `crates/mux/CLAUDE.md` cites
them for design.

### Fairness

- **Per-flow window**: `window` (256 KiB), wherever it's settable. Muxes that auto-tune a flow's
  window (go-yamux, `@libp2p/yamux`) have their maximum set to it too, so no impl grows past the
  shared window. rust-yamux auto-tunes with no per-stream maximum, bounded only by its connection
  receive window below; async_smux has no byte window to set.
- **Wire connection window** (HTTP/2): raised to 1 GiB, so it never binds. Every mux is compared
  on its per-flow mechanics, which is all ours has (sw2m/pdbd#58: no wire connection window).
- **Local receive bound**: `budget` (64 MiB) for ours and for the impls with one (smux's
  `MaxReceiveBuffer`, rust-yamux's connection receive window, which it insists be at least
  256 KiB a stream and so is raised to that where `budget` falls short).
- **Flow cap**: above the largest scenario's flow count, so a cap never binds.
- **Keepalives off**, so no ping is counted as traffic.
- **One allocator for native code**: glibc's malloc for every native harness (Rust, C, and ours,
  which the consumer links statically against glibc rather than musl). Runtimes with their own
  allocator (Go, .NET, Node, the JVM) keep it. musl's malloc made ours 14× slower on the same
  code (786 against 10 148 MiB/s core to core), because the mux allocates per frame.
- **Everything else** is the library's default.

Where a setting can't be made equal, the report reads with it in mind:

- `x/net/http2`'s client stream window is a fixed 4 MiB, so its far → near direction isn't at
  `window`. Only `pingpong`, `loaded`, `churn` and `idle` send anything far → near, and only a
  few bytes per message.
- Ours delivers each DATA frame as an owned `Vec`; the others hand out borrowed buffers.

### Known quirks

- **Nerdbank.Streams faults on abrupt channel disposal.** Disposing a channel right after its last
  write sometimes trips an internal assertion ("Sending ContentReadingCompleted frame for channel
  N (Local), which we've already sent termination for") and faults the whole
  `MultiplexingStream`, so every later `OfferChannelAsync` throws `ObjectDisposedException`
  (seen at `churn` rates with 2.14.405). The harness closes the way the API intends, which
  `churn` relies on: complete output, drain input to completion, then dispose.
- **`x/net/http2` holds about 540 KB per idle flow** (541 101 to 541 341 B, both ends, across
  four runs with x/net v0.58.0 and v0.61.0, where the next highest was go-yamux's ~2.2 KB). Not
  profiled; the per-stream server handler goroutine, parked until the flow closes, plus the
  request and response body buffers are the likely source.

Runtimes keep their own concurrency: Go goroutines, tokio's multi-threaded runtime, .NET's thread
pool, netty's event loops, Node's single event loop, and a single-threaded pump for nghttp2 and
ours. Each harness drives its library the way the library is meant to be driven:

- **netty** writes and drains on the stream's own event loop: a writer writes while the stream is
  writable and resumes on `channelWritabilityChanged`, a reader counts in `channelRead`, and an echo
  answers in `channelRead`. Only the measuring thread hands off to the event loop. Driving it from
  a blocking thread per flow instead lockstepped every 64 KiB write with a cross-thread wakeup
  (netty's default 64 KiB write-buffer high watermark) and cost it most of its throughput. The
  writer guards against re-entry, since a write can fire `channelWritabilityChanged` synchronously,
  and re-checks writability after flushing, so a wakeup the guard swallowed can't strand it.
- **Node** yields one turn of the event loop after each successful write: without it, concurrent
  writers spin in microtasks and starve the sockets' I/O.

## Statistics

- Every measurement is a fresh process, and before the measured run it primes: it runs the same
  scenario once on its own session, unmeasured, so JIT runtimes (.NET, Node, the JVM) are measured
  warm. `isolation` primes both variants, calm then stalled, then measures calm then stalled, so
  neither measured run is warmer than the other. Priming leaves garbage, which every harness
  collects before `idle`'s baseline.
- `repeat` repetitions; the default is 7, because bencher's distribution-free 95% interval of the
  median needs at least 6 samples (repo CI runs 2, for speed, and reports no intervals).
- Within a repetition every impl runs every scenario variant, and the impl order rotates by one
  each repetition, so drift (heat, a noisy host) spreads over every comparator instead of landing
  on one.
- The `ratio` is taken inside one process: stalled over calm, the two differing only by the stall.

## Build

The Salt state installs `build-essential` and calls `build`, which reads the consumer's
`resolved.json` (see the repo's README, "Runners"): each comparator's version and mode, and each
managed toolchain's version. `resolve` prints one: the bench's `params.pins`, else each
comparator's latest release, and each toolchain's latest:

| Runtime | Toolchain (latest) | Comparator versions from | Built as |
| --- | --- | --- | --- |
| Go | go.dev's latest stable | the Go module proxy | one `peer` binary; `go get` each module at its version |
| Rust | Rust's stable channel | crates.io (`max_stable_version`) | one `peer` binary; `cargo update --precise` each crate, `--locked` build |
| .NET | the newest `active` .NET channel's SDK | NuGet (newest stable) | self-contained `linux-x64` publish |
| Node | the newest LTS | the npm registry | `npm install --save-exact`, behind a launcher that runs `node --expose-gc` |
| JVM | Adoptium's newest LTS JDK | Maven Central metadata (netty 4.x `.Final`, never 5.0's alphas) | `javac` against netty's jars, behind a launcher |
| C | Debian's own `cc` (not floating) | the project's GitHub releases | nghttp2 built static from its release tarball, the harness linked against it |

Every download is checked before it's used: Go and Node tarballs against their sha256 lists,
the Rust installer against its `.sha256`, the .NET SDK against the release metadata's sha512, the
JDK against Adoptium's sha256, nghttp2 against its release's `checksums.txt`, and netty's jars
against Maven Central's `.sha1` (what Maven itself checks). The JVM harness needs no Maven: netty
is one group at one version, so `build` walks its POMs for every compile-scope `io.netty`
dependency and fetches exactly those.

After building, `build` runs every harness's `version <impl>` and fails unless it reports the
resolved version: one Go module's requirement can raise another's (MVS takes the highest), and
this catches it. Then it prunes what was only needed to build (the Go, Rust and .NET toolchains,
npm, the JDK's `jmods` and sources, nghttp2's install tree), keeping only what runs: the
binaries, Node, and the JDK.

What floats inside a cached image, unrecorded: `@libp2p/yamux`'s helpers (`@libp2p/utils`,
`@libp2p/logger`) and Debian's `cc`. What's recorded on the `comparator` row: every comparator's
version and the toolchain that built it.

Every failure on the build path fails provisioning, and every harness failure (a non-zero exit, a
measurement past its time limit, a verdict other than `ok` outside `isolation`) fails the run at
`execute`, so a comparator that stops building or running is a red bench, never a quietly missing
row.
