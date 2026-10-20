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
  resolve          prints the exact versions of what the runner installs, which bencher puts into the image key
  harness/         the entrypoint's Python package
  <other scripts>  helpers its Salt state calls (transport/pppd builds its comparator; socat/oracles installs its oracles)
```

Runners here are written in Python 3 against the standard library only. bencher guarantees
`python3` in every guest (sw2m/bencher#17), so a runner written this way moves to another OS
family without a rewrite. Anything else a runner needs, its Salt state installs.

A runner that installs something floating (a latest release) ships a `resolve`, so a consumer
can cache its provisioned image (`cache = "provisioned"` in `bench.toml`, bencher 0.3.0 or
later): bencher keys the image on what `resolve` printed, so a new upstream release misses the
cache instead of being masked by it, and the Salt state installs exactly that
(`$BENCHER_IN/resolved.json`). Under an older bencher, with no `resolved.json`, the runner
resolves at provisioning as before.

A runner whose `resolve` names a version must reject a pin it doesn't know, so a misspelled pin
fails at launch rather than quietly floating. And an empty `resolved.json` is an error, not the
older-bencher fallback.

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
