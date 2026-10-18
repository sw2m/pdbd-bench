# pdbd-bench

Benchmark fixtures for [pdbd](https://github.com/sw2m/pdbd): the runners
[bencher](https://github.com/sw2m/bencher) launches to measure pdbd against its comparators.

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
```

## Development

Open PRs as drafts; `draft-guard` re-drafts a PR opened ready. CI runs when a PR is marked ready,
or on demand with `workflow_dispatch`. `mergeable` is the one required status check on `main`.
