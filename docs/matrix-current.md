# Current matrix dimensions

Live packaging / installed-runner cell counts derived from
`portable_resume.registry` (`enabled_source_keys` × `enabled_destination_keys`).
This page is **structure only** — it does not claim host UI activation, visual
picker smoke, marketplace reinstall, or dual-OS release evidence.

See also: [`host-support.md`](host-support.md), [`install-hosts.md`](install-hosts.md),
[`STATUS.md`](STATUS.md).

<!-- generated:matrix-summary:begin (run scripts/render_docs.py --write) -->
This repository ships **17** enabled source Skills to **18** destination hosts (registry-derived; currently **17×18=306** cells).
<!-- generated:matrix-summary:end (run scripts/render_docs.py --write) -->

<!-- generated:matrix-counts-table:begin (run scripts/render_docs.py --write) -->
<!-- portable-resume-matrix: sources=17 destinations=18 cells=306 -->

| Field | Count |
|---|---:|
| sources | 17 |
| destinations | 18 |
| cells | 306 |

Product check: `17 × 18 = 306` (must equal `len(rectangular_cells(...))`).
<!-- generated:matrix-counts-table:end (run scripts/render_docs.py --write) -->

Historical published products (for example `0.3.4` **9×9=81**) belong in
changelog / evidence archives and must not replace the live counts above.

Matrix inclusion does not imply every provider tier is readable in every live
state. In particular, #263 Phase 1 keeps the OpenCode cell enabled through
qualified file-store/export fallback while oversized live-WAL SQLite remains
fail-closed as `E_SQLITE_LIVE_WAL`; a live COW backend is not implemented or
claimed.
