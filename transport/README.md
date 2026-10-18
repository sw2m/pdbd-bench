# transport

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
| `pppd` | `version`, `mode` (`floating` or `pinned`), `toolchain` (the compiler that built it) | verdict `ok`: the comparator that was raced, built and verified; present whenever a pairing uses pppd |
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

## pppd tracks upstream

pppd is installed by Python, not by the distro's package manager, so that the comparator is
always the latest upstream release. Debian 12 packages pppd 2.4.9 and Debian 13 2.5.2, both
behind ppp-project's releases, and a benchmark that races a stale comparator says nothing about
the current one. `transport/pppd` (`harness.Build`) resolves the latest `ppp-project/ppp`
release, or `params.pins.pppd` when the consumer pins one, downloads ppp's own release tarball
(download.samba.org, which carries a built `configure` for every version), and builds it into
`/opt/pppd`. The runner's Salt state calls it during provisioning, so every run spends about a
minute building it.

Every failure on that path fails the run, so an upstream change to how ppp is released or
installed surfaces as a red bench instead of a quietly skipped comparator:

- resolving the release, downloading or unpacking the tarball, `configure`, `make` or
  `make install` failing fails the Salt state, and bencher reports a `provision` error;
- an install that succeeds but doesn't leave an executable `/opt/pppd/sbin/pppd` reporting the
  version that was built fails `Build`'s own check, and provisioning with it;
- the runner reads pppd's path from `Build` too, so the builder and the runner can't disagree
  about where pppd is.

In the measurement itself only one thing is an outcome rather than a failure: both ends running
but the link never coming up becomes the pairing's `link` verdict `err`, since that's what a
linkup regression (such as pdbd#24) looks like. Everything else exits the runner non-zero, and
bencher fails the run at `execute`:

- an end (pppd or linkup) or the socat bridge exiting before the link opens, with the end's exit
  status and the tail of its log, so a pppd that installed but won't start is a red bench, not
  a quiet `err`;
- the far end running but never creating its interface;
- iperf3 or ping failing, or output that doesn't parse.

`ci/bench/` is this repo's own consumer of `transport`: `pppd.pppd` only (no `linkup` artifact),
short runs, and expectations that the link comes up and carries traffic. CI runs it through the
bencher action.
