# Native host install / activation evidence policy (#123)

**Schema:** `portable-resume/native-evidence-v1`  
**Date:** 2026-08-02

## States (closed enum)

| State | Meaning |
|-------|---------|
| `not-run` | No exact-version native install/activation row for this host@version on this release |
| `stale` | Prior evidence exists but host CLI/package version or artifact identity drifted |
| `current` | Evidence recorded for the exact artifact identity + host version under test |
| `failed` | Attempted native install/activation and failed (must not be reported as pass) |

## Rules

1. Package contracts default `native_evidence_status=not-run` until a recorded row exists.
2. Installed-runner smoke (`scripts/smoke_installed_matrix.py`) proves **filesystem runner** packaging only — **never** host UI / marketplace picker / NL activation.
3. Host UI smoke rows live in `docs/host-ui-smoke.md` and remain **not-run** for v0.4-era hosts until filled.
4. Marketplace reinstall evidence is separate from direct Skill zip validation.
5. Automating evidence collection must write machine-readable JSON under `docs/evidence/` with:
   - `host`, `host_version`, `artifact_file`, `artifact_sha256`, `identity_sha256`
   - `state`, `recorded_at`, `operator` or `ci_run_url`
6. STATUS must not claim marketplace or visual picker success without `state=current` rows.

## Current tree honesty

As of this note, native activation / marketplace / visual pickers for post-v0.3.2 hosts remain **`not-run`**. Dual-OS **release claim** remains separate (CI runs dual OS; formal claim packet is plan 022).

## Windows mutating install (#125)

POSIX dirfd/lock path is fail-closed on `os.name == "nt"` with `E_INSTALL_UNSUPPORTED_PLATFORM` (Policy B). A full Windows implementation is **not** shipped; dual-OS **mutating install** claim stays incomplete until #125 lands on real Windows CI.
