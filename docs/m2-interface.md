# Native M2 internal interface

Bytecode ABI/encoding remain unchanged. `native/m2_abi.inc` defines the compact
internal state/scratch interface. Active state is 96 bytes at $0002, copied into
four 128-byte PCBs at $0400. Raster scratch remains $C0 upward. M0's 80-byte report
is retained at $0300; cache continuations/counters use $0350–$03AF. Cache metadata
at $FD80 holds sixteen entries: tag, owner slot, flags and 16-bit incarnation.

`vm_step` attempts one opcode, returning its VM_OUTCOME. RUN means one completed
ordinary instruction; all other values are execution boundaries. `vm_run` loops
over RUN until a boundary. Both preserve remaining credit on WAIT_REU/WAIT_VIDEO.
The video admission hook runs before each attempt. `vm_save_context` and
`vm_load_context` copy the active state to/from VM_SLOT without cache flushes.

Cache calls use CACHE_ADDR (u24), CACHE_WIDTH (1..3), CACHE_WRITE (0/1), and
CACHE_VALUE (three-byte little-endian scalar). They may clobber A/X/Y and their
own scratch, but preserve architectural state and interpreter scratch.

- `cache_fetch_code`: copy the aligned instruction to VM_IR; carry means wait.
- `cache_prepare`: validate availability and pin all data lines; carry means wait.
- `cache_read_prepared` / `cache_write_prepared`: bounded scalar operation.
- `cache_unpin`: release temporary pins on every execution/wait/fault boundary.
- `cache_service`: at most one admitted DMA direction; dirty STASH and refill
  FETCH are separate service calls. Destination stays busy until completion.
- `cache_reset` / `cache_invalidate_owner`: initialize or cancel/invalidate an
  incarnation before slot reuse. Pending metadata records owner and incarnation.
- Coherent native read/write hooks flush only overlapping dirty lines before
  physical access, and invalidate/update affected lines after writes.

Only the centralized driver writes REU registers. The cache service uses the
boot's conservative DMA admission hook for every actual transaction. Tags/flags,
buffers and physical REU can be inspected separately, so logical memory checks
overlay dirty valid data without inserting diagnostic flushes.

The boot harness's mailbox/command protocol is diagnostic overhead in the future
desktop region. Commands run only at consistent interpreter boundaries. It is
not an M3 scheduler or an application API. Build maps must report it separately.
