# Accepted isolated profiling evidence

`index.json` binds each unchanged copy to its original repository path, byte
length and SHA-256. It includes the six accepted 128-byte-cache profiling
groups, their reused ABI1/ABI2 baselines, raw counters, full logical outputs,
live scanout images, generated bounds and small assembled diagnostic programs.
The executed runner and generated probe/checker sources retain provenance.
Firmware, REU images, private USB copies, host executables and execution logs
are omitted.

These systematic samples measure inclusive diagnostic intervals. Nested
probes and IRQ time remain included; deliberately contracted admission windows
also affect paired elapsed differences. The diagnostics borrow future font
and numeric reserve, and do not establish normal production RAM fit or
physical Ultimate timing. See [measurement semantics](../../m3-perf-profile.md).

`profile-timer-final` qualifies modulo-16-bit intervals and register/flag
preservation. Its sampling phase is deliberately reset for forced probes:
512 samples from the 65,536-call loop plus two forced sampled calls give 514
measured callees across 65,539 calls. Its counters are qualification evidence,
and are not used to estimate workload helper costs.

The earlier live cascaded CIA2 A/B profiling trial was rejected because its
counters overflowed and some intervals had modulo-negative 65,536-PHI2
discontinuities. Its precise cause remains unestablished. The raw rejected
trial stays at `build/m3-perf/profile-core/runs/128/instrumented/`, including
`invalid-profile.json`; no measurement from it is copied here or accepted.
The separate stopped cascaded timer in the original native 1 MHz comparator
is a different measurement.

`profile-A/result.json` preserves the runner-provenance correction: its final
file digest had observed a later runner edit, and the actual earlier runner
was recovered byte-identically from a frozen source snapshot. The original
digest and provenance explanation remain in that unchanged receipt.
