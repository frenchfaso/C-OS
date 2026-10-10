# M3 evidence

`verification.json` is the byte-identical complete final result from
`build/m3-results.json`. `inventory.json` binds every evidence file, the
executed collector, source/control inventory, external inputs and canonical
delivery artifact hashes. Large private firmware/REU copies remain build
outputs, not documentation assets.

- `map-*`, `manifest-*` and `reproducibility.json`: final normal packs,
  bootstrap/resident boundaries, future reservations and repeated build hashes.
- `cache-bounds-*`: current assembled control-flow bounds for both normal M3
  and extended M2 profiles, including their checker hashes and assumptions.
- `cache-rollback-*`, `cache-lifecycle-*`, `cache-verification.json`: physical
  REU regressions, normal/extended identity and the failing original-cache
  negative control.
- `scheduler-cancel-regression.json`: exact released-driver deadlock before
  the correction and 126 passing native assertions on each corrected profile.
- `native-contract-*`, `autonomous-*`: final native assertions, six concurrent
  packs, full guest/cache snapshots, actual loaded hashes, real CIA2 NMI and
  video checks.
- `benchmark-*`, `baseline-*`, `reference.*`, `host-profile.json`: complete
  image bytes, independent reference, target timing, live scanout, protocols
  and the functional opcode profile. Both images match all 192 bytes.
- `m0-m2-complete-check.log`: original successful cumulative M0–M2 execution,
  followed by interrupted partial M3 work before the final rebuild.
- `m3-complete-check.log`: final successful collector with the unchanged M2
  receipt explicitly revalidated, all M3/cache regressions and both benchmarks.

The 4 KiB numeric reservation fits in both normal packs. Other future modules
remain unsized. Mandelbrot speedups are 0.0152703× and 0.0145787×, below the
greater-than-1× goal. Static bounds are conditional on the recorded timing
model; observed native work intervals and stack lower bounds are separate.
Functional emulation does not qualify physical Ultimate raster/DMA behavior
or establish visible application frame rate.
