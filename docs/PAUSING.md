# Pausing Docker experiments

New Docker runs on Linux hosts provide a host-owned clock for managed pauses. Use:

```sh
tlaps-bench pause-container CONTAINER_NAME
tlaps-bench resume-container CONTAINER_NAME
```

A quota guard can call these commands in place of `docker pause` and `docker
unpause`, checking the exit status before recording a successful transition.
Both commands are idempotent. The container name or ID is the same one accepted
by Docker. Preflight containers are deliberately not pausable through this API.

The runner's agent deadline and `agent_time_secs`, the grader envelope, and the
official checker's SANY/TLAPM envelope subtract recorded pauses. Ordinary idle
time, network/API waits, and solver execution still consume time. This is an
elapsed-time budget, not a CPU-time budget.

Docker agent results also record `agent_wall_time_secs` and
`agent_paused_time_secs`; the difference is the measured active process runtime.
On timeout, the existing `agent_time_secs` cap can additionally exclude shutdown
or output-draining overhead. Verification
reports retain `wall_secs` and add `active_secs` and `paused_secs`. Check-session
recovery charges the persisted active budget; old sessions without these fields
conservatively charge their entire recorded wall time. Self-check and formal
grading keep independent budgets and cache namespaces.

Each launch owns a durable ledger under `~/.tlaps-bench/runtime-clocks/`, outside
the agent's writable mounts. The directory is mounted read-only at
`/run/tlaps-bench-clock`. Its host path is recorded in the Docker label
`org.specula.tlaps-bench.active-clock`; an `active-clock.json` snapshot is copied
beside the launch's output after it exits. Retain the host ledger while retaining
or inspecting its container. The clock uses the Linux boot ID and monotonic time
and the host rejects a ledger from a previous host boot. The runner and Docker
container must share the Linux monotonic clock domain. An incompatible clock
epoch, or a host wall-clock adjustment over five seconds since clock creation,
fails closed rather than producing an untrustworthy budget measurement.

The controller freezes the container before writing the pause start, and durably
closes the interval before thawing it. Host clock readers share the controller's
lock so they cannot observe a half-published transition. Container readers check
for concurrent publication without holding that lock across a freeze.
Freeze-command transit before the recorded start and thaw-command transit after
the close are conservatively charged. If the controller crashes between Docker and ledger
updates, rerunning the command recovers the Docker state, but any unrecorded
interval stays charged and the command reports that fact. A checker hard crash
retains the existing write-ahead reservation of at most one heartbeat tick;
restart downtime is not a new examination. As before, incomplete measurements
after a hard crash should not be treated as complete wall/CPU telemetry.

Boundaries:

- This requires a new run and a checker image built from the updated source.
  Existing containers lack the clock mount; the control commands reject them.
  It does not retroactively repair previous experiment results.
- Docker launches from non-Linux hosts keep their existing wall-clock budgets
  and do not expose managed pause control.
- Plain `docker pause/unpause`, process signals, machine suspension, and an
  external guard that has not adopted these commands are not tracked. In
  particular, never thaw a managed pause directly: the ledger would remain
  paused. The controller detects that mismatch on its next invocation and
  rejects it; that run's accounting needs investigation.
- A backend that propagates an absolute deadline to its own child rejects
  managed pauses until that backend supports the active clock.
- Arbitrary shell `timeout`, CLI/tool timeouts, and TLAPM/solver internal tactic
  timers retain their own semantics. They can expire during a freeze even though
  the official checker envelope has time left. An experiment that requires those
  internal timers to be unaffected must pause between checks instead of freezing
  an active check. No proof-validation rule or timeout verdict is relaxed.
