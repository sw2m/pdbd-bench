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
  harness/         the entrypoint's Python package
```

Runners here are written in Python 3 against the standard library only. bencher guarantees
`python3` in every guest (sw2m/bencher#17), so a runner written this way moves to another OS
family without a rewrite. Anything else a runner needs, its Salt state installs.

### `transport`

pdbd's link (`linkup`: userspace PPP over ppproto and a TUN) against kernel PPP (`pppd`) over the
same L1. A VM on `images:debian/12/cloud`: kernel PPP, TUN and network namespaces need a kernel
of its own.

Inside the guest, each pairing `<near>.<far>` builds its own topology: a socat PTY pair as the L1,
the far end in the root namespace, the near end in a `near` namespace on `10.0.0.1` ↔
`10.0.0.2`. Far starts first and near only once far's interface exists: with linkup near, a
ConfReq sent before the far tty opens is lost and never resent (pdbd#24). Each pairing runs
`repeat` times, and each repetition measures:

| Row | Tags | Samples |
| --- | --- | --- |
| `link` | `pairing` | verdict: `ok` when every repetition came up; `err` otherwise, and the pairing's other rows are from the repetitions that did |
| `bring-up` | `pairing` | ms from near start until both ends report IPCP Open (`local  IP address` from pppd, `phase: Open` from linkup), polled every 10 ms |
| `throughput` | `pairing`, `direction`: `forward`, `reverse`, `parallel` | iperf3 Mbit/s near → far, far → near (`-R`), and near → far over 4 connections (`-P 4`), `duration` s each |
| `rtt` | `pairing`, `load`: `idle`, `loaded` | every ping reply's ms: 20 idle, then during the forward run |
| `cpu` | `pairing` | ms of busy time on the run's own CPUs (bencher fences the benchmark onto them, so this includes kernel PPP and softirq work) per MB received over the three iperf3 runs |

Rows with pppd in their pairing carry its version as a `pppd` tag. `cpu` carries the pairing's
telemetry: each pairing is a reporter (`pppd.pppd`, `linkup.linkup`, `linkup.pppd`) covering its
socat, both L2 ends and both iperf3 ends.

| Param | Default | |
| --- | --- | --- |
| `pairings` | `["pppd.pppd", "linkup.linkup", "linkup.pppd"]` | pairings with linkup are skipped without a `linkup` artifact |
| `repeat` | `3` | repetitions per pairing |
| `duration` | `10` | seconds per iperf3 run |
| `baud` | `115200` | the L1's line speed, passed to both ends |
| `pins.pppd` | latest | a pppd version; unset, the latest `ppp-project/ppp` release is built (pppd floats) |

| Artifact | |
| --- | --- |
| `linkup` | pdbd's `linkup` example, built static (`x86_64-unknown-linux-musl`): the guest is not the build host |

pppd is built from ppp's own release tarball (`transport/pppd`, `harness.Build`) by the
runner's Salt state, so every run spends about a minute building it.

`ci/bench/` is this repo's own consumer of `transport`: `pppd.pppd` only (no `linkup` artifact),
short runs, and expectations that the link comes up and carries traffic. CI runs it through the
bencher action.

## Development

Open PRs as drafts; `draft-guard` re-drafts a PR opened ready. CI runs when a PR is marked ready,
or on demand with `workflow_dispatch`. `mergeable` is the one required status check on `main`.
