# socat

pdbd's socat-style address dialect (crate `socat`, sw2m/pdbd#57) raced against the prior-art
parsers: each oracle is asked whether a string parses, and so is ours, across a corpus generated
from the oracles themselves. A container on `images:debian/12/cloud`: parsing needs no kernel of
its own. The entrypoint re-executes itself in an empty network namespace (`unshare --net`) before
anything parses, so no oracle can reach a network, and fails if the namespace has any link but
`lo`.

## Rows

| Row | Tags | Verdict |
| --- | --- | --- |
| `corpus` | `input`, `family` | `ok`: one per corpus entry; `family` is `<origin>:<kind>[:<family>]`, e.g. `socat:type:TCP`, `socat:option:SOCKET`, `websocat:overlay`, `hand:lexer` |
| `parse` | `impl` (`socat`, `websocat`, `oittaa`, `tocat`, `ours`), `input` | whether that parser accepts the input |
| `print` | `input`, `canonical` | `ok`: ours accepted the input and printed it as `canonical` |
| `alternative` | `input`, `form` | whether ours accepts `form`, the consumer's stand-in for an input it rejects |
| `oracle` | `impl`, `version`, `mode` (`floating` or `pinned`), and what identifies the build: `sha256` (socat's tarball, websocat's binary), `toolchain`, `source` (oittaa's module) | `ok`: the oracle that was raced |

`ours`, `print` and `alternative` rows need the `verdict` artifact; without it only the oracles are
raced.

## Corpus

Generated at run time, so a new oracle release brings its new forms with it. An entry is kept
once, under the first source that produced it.

| Source | Entries |
| --- | --- |
| socat `-hhh` | every address type and alias as a minimal form (`<host>` → `127.0.0.1`, `<port>` → `1`, `<filename>` → `f`, …); every option and alias, with a sample value by its `type=`, riding on the most preferred type whose `groups=` fit (`harness/corpus/source/help/help.py` ranks types pdbd's dialect parses first, so the option, not its host, decides the verdict); `fork`/`max-children` ride a LISTEN |
| oittaa/socat `-hhh` | its type list (aliases take their target's signature), and its options riding a host chosen by their help heading |
| oittaa/socat's tests | every string literal passed to `ParseChannel`/`ParseSpec` in `internal/parse/*_test.go`, found by `oittaa/main.go`'s `go/ast` walk |
| websocat `--help=full` and its `doc.md` | every address type and overlay, using a doc example where there is one; every doc alias; every doc example specifier |
| tocat | every scheme in `tocat-core`'s `match normalize(scheme)` table, with a sample body |
| the `hand` artifact | the consumer's own entries: one JSON string per line, `# <section>` lines naming the family `hand:<section>` |

## Oracles

None opens anything real: they run in the empty namespace, and socat, oittaa and websocat with
`PATH=/nonexistent` in a scratch directory.

- **socat** (built from upstream's latest release) and **oittaa/socat** (its CLI, `go install`ed
  at its latest version) run as `-d -d <input> /dev/null`. A syntax error (unknown address, wrong
  parameter count, unknown or inapplicable option, missing numeric value, `not allowed without`,
  …) is `err`; anything else, including a runtime failure or still running after 400 ms (a LISTEN
  in accept), is `ok`. oittaa mirrors socat's messages, so one classifier serves both.
- **websocat** (its latest release binary): `-t -E --dump-spec <input> -`. Exit 0 is `ok`. It
  resolves host names while building the spec, which in the empty namespace blocks, so one still
  running after 3 s has parsed it.
- **tocat**: `tocat/`, a tiny program over `tocat-core`'s latest release, asked
  `EndpointSpec::from_str` per input; a panic is `err`.
- **ours**: the consumer's own parser, the `verdict` artifact, asked the same way (below).

An oracle's verdict means it accepted the syntax, inferred from its errors; it never proves the
string would work. socat's lexer runs an unterminated quote into its next argument, so some of
socat's acceptances of malformed input are artefacts of that.

| Param | Default | |
| --- | --- | --- |
| `pins.socat` | latest | a release as upstream's tarballs name it: `1.8.1.3` |
| `pins.websocat` | latest | a release tag: `v1.14.1` |
| `pins.oittaa` | latest | a Go module version: `v1.0.3` |
| `pins.tocat` | latest | a `tocat-core` crate version: `0.3.0` |

Unset, an oracle's latest release is raced. `resolve` and `oracles` read the pins from
`params.json`, so no pin reaches a shell command line.

| Artifact | |
| --- | --- |
| `verdict` | ours: an executable for the guest that reads one JSON string per line on stdin and answers each with one JSON line: `{"ok": true, "canonical": "<print>"}` or `{"ok": false, ...}` (pdbd's `examples/verdict.rs`, built static) |
| `hand` | extra corpus entries (above) |
| `alternatives` | one JSON `[input, form]` pair per line: an input ours rejects and the form it accepts instead |

What this runner leaves to its consumer: which inputs have an alternative (the `alternatives`
artifact, decided by hand) and any coverage summary, which the consumer renders from the rows.

## Oracles track upstream

`resolve` picks every oracle's version (its pin, else its latest release) and the toolchain that
builds it: the latest stable Go for oittaa/socat, the latest stable Rust for `tocat/`. It prints
them as one JSON object, which bencher keys the image on and hands back as `resolved.json`:

```json
{"oittaa": {"go": "go1.27.3", "mode": "floating", "version": "v1.0.3"},
 "socat": {"mode": "floating", "version": "1.8.1.3"},
 "tocat": {"mode": "floating", "rust": "1.99.1", "version": "0.3.0"},
 "websocat": {"mode": "floating", "version": "v1.14.1"}}
```

`oracles`, called by the Salt state, installs exactly that (resolving the same way itself when
there is no `resolved.json`): socat from upstream's tarball, websocat's release binary and
`doc.md`, that Go and then oittaa/socat, that Rust (rustup) and then `tocat/`. A pin naming no
oracle fails `resolve`.

What stays floating inside a cached image:
- Debian's packages, including the C toolchain that builds socat;
- `tocat/`'s transitive crates, which have no lockfile;
- `rustup-init`, the latest installer, which installs the resolved Rust.

Once each build is verified, its build tree and toolchain are removed: all of Go but `bin/`,
which verifies oittaa's build info, and all of Rust and tocat's `target/`. A rebuild reinstalls
them. Every step verifies what it installed, and any failure
fails provisioning, and with it the bench: if an upstream changes how it ships, the run goes red
rather than racing something else. socat's downloads are plain http with no signature (its https
certificate is self-signed), so the tarball's sha256 is recorded on its `oracle` row; Go's and
rustup's archives are checked against the sha256 their upstreams publish. Every tarball is
extracted only after checking that no member or link lands outside its directory (Debian 12's
Python predates `tarfile`'s extraction filters). An installed oracle is verified against the
version it was asked for: socat's and websocat's own `--version`, oittaa's module version in
its Go build info, and the `tocat-core` version its harness was built against.

`ci/socat/` is this repo's own consumer of `socat`: no `verdict` artifact, two hand entries, and
rules that all four oracles accept `tcp:127.0.0.1:1` and reject an unknown type, so an oracle that
rejects everything, or accepts everything, fails CI here before it reaches pdbd. Each corpus
source raises when it parses nothing from its upstream, so a layout change fails the run too.
