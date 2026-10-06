# Stability-test dead-man switch

`tools/deadman_watchdog.py` launches one workload under a Windows Job Object. The
controller must run `feed` periodically; the watchdog never feeds itself. Session
state always lands in `<repo root>/artifacts/sessions/`, regardless of where the
script itself is stored.

Default safety behavior:

- external heartbeat older than 90 seconds: kill the workload process tree;
- hard runtime deadline reached: kill the workload process tree;
- a new WHEA record appears: kill the workload process tree;
- when `--sensor-required` is used, missing/stale HWiNFO CSV data: kill the
  workload process tree;
- protected temperature threshold reached: kill the workload process tree;
- only `--shutdown-on-thermal` permits a thermal emergency to schedule a
  shutdown; ordinary disconnects never shut down the PC.

Session state and logs are written under `artifacts/sessions/<session>/`.
The token printed in `session.json` is required for feeding and orderly stop.

Before a real stress test, validate the dead-man path with a harmless long-lived
process and allow its heartbeat to expire. Do not use `--sensor-required` until
HWiNFO CSV logging has been started and the protected sensor columns have been
verified.
