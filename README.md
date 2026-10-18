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
  harness/         the entrypoint's Python package
```

Runners here are written in Python 3 against the standard library only. bencher guarantees
`python3` in every guest (sw2m/bencher#17), so a runner written this way moves to another OS
family without a rewrite. Anything else a runner needs, its Salt state installs.

### Runners in this repo

| Runner | Measures |
| --- | --- |
| [`transport`](transport/README.md) | pdbd's userspace PPP (`linkup`) against kernel PPP (`pppd`) over one L1 |

Each runner documents its own rows, params and artifacts beside its code.

## Development

Open PRs as drafts; `draft-guard` re-drafts a PR opened ready. CI runs when a PR is marked ready,
or on demand with `workflow_dispatch`. `mergeable` is the one required status check on `main`.
