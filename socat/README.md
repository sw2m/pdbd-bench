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

`ours`, `print` and `alternative` rows need the `ours` artifact; without it only the oracles are
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

None opens anything real: they run in the empty namespace, and socat and oittaa with
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
- **ours**: the `ours` artifact, asked the same way (below).

An oracle's verdict means it accepted the syntax, inferred from its errors; it never proves the
string would work. socat's lexer runs an unterminated quote into its next argument, so some of
socat's acceptances of malformed input are artefacts of that.

| Param | Default | |
| --- | --- | --- |
| `pins.socat`, `pins.websocat`, `pins.oittaa`, `pins.tocat` | latest | a version for that oracle; unset, the latest release is raced |

| Artifact | |
| --- | --- |
| `ours` | an executable for the guest that reads one JSON string per line on stdin and answers each with one JSON line: `{"ok": true, "canonical": "<print>"}` or `{"ok": false, ...}` (pdbd's `examples/verdict.rs`, built static) |
| `hand` | extra corpus entries (above) |
| `alternatives` | one JSON `[input, form]` pair per line: an input ours rejects and the form it accepts instead |

## Oracles track upstream

`oracles`, called by the Salt state, installs every oracle at its latest release (or its pin):
socat from upstream's tarball, websocat's release binary and `doc.md`, Go and then oittaa/socat,
Rust (rustup, stable) and then `tocat/`. Every step verifies what it installed, and any failure
fails provisioning, and with it the bench: if an upstream changes how it ships, the run goes red
rather than racing something else. socat's downloads are plain http with no signature (its https
certificate is self-signed), so the tarball's sha256 is recorded on its `oracle` row; Go's and
rustup's archives are checked against the sha256 their upstreams publish.

`ci/socat/` is this repo's own consumer of `socat`: no `ours` artifact, two hand entries, and
rules that each oracle accepts a plain TCP address and rejects an unknown type, so a broken
install or classifier fails CI here before it reaches pdbd.
