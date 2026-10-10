# Independent M2 review

Review date: October 10, 2026. Baseline: completed M2 delivery, SPEC.md revision 5;
native build tags `CFBED205` (128-byte cache) and `06A147B0` (64-byte cache).
The implementation was uncommitted. All 47 runtime source hashes were checked
against `m2-evidence/verification.json` before making an isolated review copy.

**Disposition: the original M2 delivery has one blocking cache cancellation
defect. The developer's correction passes the independent targeted reproduction;
M3 integration and expanded regression checks remain with the dev task.** The
original suite does not cover this cancellation order.

## P1: cancellation can resurrect a revoked dirty cache victim

Affected code: `native/cache.asm`, `cache_invalidate_victim` and both paths that
restore `cache_pending_old_flags` (`cache_service` and requester cancellation).

Reproduction on the native 6510 backend:

1. Process A owns a dirty cache line at physical REU address `$060000`, containing
   `$66`; physical REU still contains `$A5`.
2. Process B requests a line at `$070000`. CLOCK selects A's line, saves its old
   VALID/DIRTY flags and schedules the STASH/FETCH continuation for B.
3. Cancel A before STASH and advance its incarnation. The code correctly keeps
   only BUSY on the destination and changes the continuation to FETCH, but its
   rollback snapshot still contains A's old VALID/DIRTY flags.
4. Cancel B, or make B's incarnation stale and call `cache_service`. Either
   cancellation path restores the obsolete flags, resurrecting A's dirty data.
5. A later eviction selects that entry and writes the revoked `$66` bytes to
   `$060000`, overwriting physical memory that should still contain `$A5`.

This reproduced for both 64- and 128-byte cache lines, with both explicit B
cancellation and stale-generation cancellation. Each probe completed with state
bytes `01 02 04 03 00 01 05 55`; the observed physical byte was `$66` rather than
`$A5`. Cache source SHA-256:
`6e32186aa5c8410ff1b89ca5c40d8cd63d186e693a97d77dc6a40759dff9a7bb`.

The cleanup path must revoke the old victim's rollback validity as well as its
published flags. Neither cancellation path may restore a victim after its owner
has been invalidated. Preserve the different, valid case where cancelling only
B must retain a still-live A's dirty line. Add native regression tests for both
cancellation orders, both cache sizes, explicit/stale completion, and cancellation
before and after the write-back phase. Verify physical REU bytes, not only tags.

The [native probe](m2-review-evidence/cancel-chain.asm) and
[four observed results](m2-review-evidence/cancel-chain.json) preserve this
reproduction. Assemble with Kick Assembler variables `cacheLine=64|128` and
`stale=0|1`; preload a private 16 MiB REU filled with `$A5`, load the PRG and enter
at `$1200`. On completion `$0307=$55`, inspect `$0300..$0306` and physical REU
`$060000`. The probe deliberately tests the faulty baseline and does not assert
that its observed corruption is correct. Integrate expected-safe assertions into
the native regression suite when fixing the defect.

### Targeted correction verification

The developer added rollback validation against the victim's live incarnation,
revoked the saved flags when invalidating the victim, and removed DIRTY from the
rollback snapshot after a successful STASH. It also checks victim liveness before
a pending write-back. An independently frozen copy of that correction has cache
source SHA-256 `dd6e3283a424924036ddea8c06e0bc9a29e671e1d56bf82aa2cbb4e03ecc6444`.

The unchanged review probe now preserves physical `$A5` in all four cases;
state bytes are `01 02 04 00 00 02 09 55`. See
[post-fix observations](m2-review-evidence/cancel-chain-fixed.json). This closes
the specific reproduced corruption. These four probes do not replace the
developer's expanded lifecycle tests, revised bounds/maps or full regression
checks for the eventual M3 build. The 1,218-case rerun below tested the original
frozen M2 delivery, not a claim about every subsequent implementation change.

## M3 engineering priorities

- **Resident budget:** the delivered maps leave only 68/62 bytes after the
  planned 4 KiB numeric reserve. Separate production and extended diagnostic
  builds, account for all remaining modules and audit any init-only reuse.
  Do not count boot code as reclaimable until its runtime references are checked.
  Avoid an overlay framework as a speculative prerequisite.
- **Real scheduling:** replace host-driven command stepping with autonomous
  scheduling at consistent VM boundaries. Verify two non-yielding apps,
  remaining fuel across REU/video/internal-work waits, exactly-once syscall
  completion, cancellation/reuse and bounded native-job rotation. A single
  pending DMA continuation must not strand other WAIT_REU owners.
- **Useful non-display time:** the present admission window is PAL 280–299,
  only 20 of 312 raster lines. This is a safe diagnostic restriction, not a
  performance result. Broader admission needs refreshed bounds and raster/NMI
  tests; horizontal-margin execution remains disabled.
- **Real workload baseline:** follow `../specs/PERFORMANCE.md`. Start with an
  autonomous fixed-point Mandelbrot in VM assembly and a comparable native
  original-C64 implementation. Measure complete output and preserve correctness;
  do not derive speedup from M2's mailbox waits or aggregate scanout counter.

No second scheduler, new bytecode format or workload-specific native renderer
is needed to start this work. Reaching the speed goal is a measured optimization
track; M3 must not claim it solely because its scheduler passes.

## Verification record

The independent rerun passed Rust tests, formatting and Clippy, M1, deterministic
native builds and static bounds for both cache sizes, all ten M0 profiles,
the existing native cache lifecycle fixtures, and 66 margin lifecycle assertions.
The all-in-one command stopped at temporary-image creation because the local
disk filled; completed review-only emulator inputs were removed and the remaining
checks were resumed individually. No source or user artifact was removed.

Both complete differential runs passed: **609 cases and 1,594 logical actions
per cache size**, 1,218 cases in total, with active UPIC. Both reported zero missed
synchronizations, zero active-line DMA violations and successful real CIA2 NMI
recovery without changing guest state or cache contents. Rebuilt artifact hashes
match the original delivery for both variants. Observed maximum step/service
times were 65/141 PHI2 ticks (128-byte lines) and 66/77 (64-byte lines); these are
diagnostic timings, not workload throughput. The new four-case reproduction
above fails on the original delivery independently of that existing suite. The
targeted correction was checked separately as described above. Physical Ultimate timing and
optional margin activation remain unqualified.
