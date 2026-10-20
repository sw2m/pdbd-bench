# pdbd-bench

Benchmark fixtures for [pdbd](https://github.com/sw2m/pdbd): the runners
[bencher](https://github.com/sw2m/bencher) launches to measure pdbd against its comparators.

## Status

The maintainer doesn't like this repo and considers it, along with bencher and the way pdbd's
benchmarking CI looks as a whole, slop. It exists as a means to an end, benchmarking pdbd, not
as something they'd choose or recommend, and it gets only the care that end needs. Expect it to
be replaced rather than polished.

## Ownership

| Repo | Owns |
| --- | --- |
| **bencher** | the sandbox (Incus), the cloud layers, telemetry, statistics, `expect.tsv` evaluation, the report |
| **pdbd-bench** (this repo) | runners: the image a runner boots, the Salt states that provision it, and the entrypoint that measures |
| **pdbd** (consumer) | `bench.toml` (which runner, at which checkout of this repo, with which artifacts and params) and `expect.tsv` |

A consumer pins this repo by its own checkout of it (a CI checkout at a ref, a submodule, a
flake input), and bencher by the action ref or flake input it runs. Neither repo fetches the
other.

## Runners

Each runner is one directory, laid out by bencher's runner contract
([`runner.toml`, the entrypoint, the result](https://github.com/sw2m/bencher#runnertoml-fixture)):

```
<runner>/
  runner.toml      image, container or vm, declared reporters
  salt/runner.sls  what the runner needs installed, from bencher's pillar
  run              the entrypoint: reads $BENCHER_IN, prints the result JSON
  resolve          a helper for the consumer: prints the resolved.json naming the exact versions the runner installs
  harness/         the entrypoint's Python package
  <other scripts>  helpers its Salt state calls (transport/pppd builds its comparator; socat/oracles installs its oracles)
```

Runners here are written in Python 3 against the standard library only. bencher guarantees
`python3` in every guest (sw2m/bencher#17), so a runner written this way moves to another OS
family without a rewrite. Anything else a runner needs, its Salt state installs.

A runner that installs something floating (a latest release) reads its exact versions from the
consumer's `resolved.json` (`resolved = "resolved.json"` in `bench.toml`, bencher 0.4.0 or later),
which bencher hands it as `$BENCHER_IN/resolved.json` and keys a provisioned image on. The
consumer owns that file: committed and bumped, or generated before each run. The runner's
`resolve` is a helper for generating it on the consumer's side, with plain `python3` (3.11 or
later) and no sandbox:

```sh
python3 <checkout>/socat/resolve <bench dir> > <bench dir>/resolved.json
```

It reads the bench's `[params.pins]`, rejects a pin it doesn't know, and prints each pin, else the
latest release. With the file generated before every run, the key moves only when an upstream
release does. With it committed, it moves when the consumer bumps it.

The Salt state installs exactly what the file names, and validates it first: every name the
runner installs, exactly each one's fields, and agreement with the bench's pins as bencher staged
them. A pin overridden with `--set params.pins...` without regenerating the file fails rather
than racing something else.

The generated file is the consumer's, and this repo's own `ci/*/resolved.json` are git-ignored:
CI writes them before each run. Write them the same way before running `bencher lint` or
`bencher run` on a fresh checkout, since without them both fail the load:

```sh
python3 socat/resolve ci/socat > ci/socat/resolved.json
python3 transport/resolve ci/transport > ci/transport/resolved.json
``` With no file (an empty `resolved.json`), a run that
caches nothing (`cache = "base"`, or bencher before 0.3.0) resolves at provisioning time instead.
Priming a provisioned image fails, since it would cache whatever is latest that day under a key
that never moves. bencher 0.3.0 is not supported: it runs `resolve` itself, in the guest, without
the bench directory.

Since a provisioned image is exported, cached and imported on every run, a runner removes what
it downloaded only to build (its build trees, the Go and Rust toolchains, apt's downloaded
packages) once the build is verified. Debian's compilers and `-dev` packages stay.

What a key can't see: a version string re-published with new bits, a re-rolled tarball or a
moved tag, keeps its key. Each runner records what was raced (the sha256s on its rows), so the
change shows after the fact, not as a miss.

### Runners in this repo

| Runner | Measures |
| --- | --- |
| [`transport`](transport/README.md) | pdbd's userspace PPP (`linkup`) against kernel PPP (`pppd`) over one L1 |
| [`socat`](socat/README.md) | pdbd's socat-style address dialect against the prior-art parsers (socat, websocat, oittaa/socat, tocat), as per-input verdicts |

Each runner documents its own rows, params and artifacts beside its code.

## Development

Open PRs as drafts; `draft-guard` re-drafts a PR opened ready. CI runs when a PR is marked ready,
or on demand with `workflow_dispatch`. `mergeable` is the one required status check on `main`.
