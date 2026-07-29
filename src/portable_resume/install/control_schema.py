"""Closed, bounded validation for installer control documents (manifest + journal).

stdlib-only. Rejects duplicate keys, non-finite numbers, excess depth/size, and
unknown properties before transaction logic or recovery may act on the document.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Mapping

from .catalog import BUNDLE_VERSION, HOST_KEYS, MANIFEST_SCHEMA

# Conservative control-document limits (bytes / structure).
CONTROL_DOC_MAX_BYTES = 2 * 1024 * 1024
CONTROL_MAX_DEPTH = 8
CONTROL_MAX_MAP_ENTRIES = 8_192
CONTROL_MAX_LIST_ENTRIES = 8_192
CONTROL_MAX_STRING_CHARS = 8_192
CONTROL_MAX_CLAIMS = 64
CONTROL_MAX_FILES = 4_096
CONTROL_MAX_CLAIM_REFS = 64

JOURNAL_SCHEMA = "portable-resume/install-journal-v1"
JOURNAL_STATES = frozenset(
    {
        "staging",
        "committing",
        "orphaning",
        "publishing_manifest",
        "complete",
        "rollback",
    }
)
JOURNAL_PATH_STATES = frozenset(
    {"staged", "pending", "retained", "committed", "skipped", "removed"}
)
JOURNAL_ORPHAN_STATES = frozenset({"pending", "removed", "skipped"})

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SCOPES = frozenset({"project", "global"})
_ALLOWED_MODES = frozenset({0o644, 0o755, 420, 493})  # 420=0o644, 493=0o755 decimal forms
_MANIFEST_TOP = frozenset(
    {"schema_version", "bundle_version", "generation", "package_identity", "claims", "files"}
)
_CLAIM_KEYS = frozenset({"host", "scope", "root", "bundle_version"})
_FILE_ENTRY_KEYS = frozenset({"path", "sha256", "claims", "mode", "owner"})
_JOURNAL_TOP_REQUIRED = frozenset({"schema_version", "state", "generation", "claim", "stage_dir", "paths"})
_JOURNAL_TOP_OPTIONAL = frozenset(
    {
        "backup_root",
        "target_generation",
        "orphans",
        "operation",
    }
)
_JOURNAL_PATH_META_KEYS = frozenset(
    {
        "state",
        "existed",
        "rollback_backup",
        "original_sha256",
        "backup",
        "sha256",
    }
)
OWNER_MARKER = "portable-resume-owned"


class ControlSchemaError(ValueError):
    """Invalid installer control document (map to content-free diagnostics at call sites)."""


def _reject_const(name: str) -> None:
    raise ControlSchemaError(f"non-finite JSON constant: {name}")


def strict_json_loads(text: str | bytes, *, max_bytes: int = CONTROL_DOC_MAX_BYTES) -> Any:
    """Decode JSON with duplicate-key rejection and non-finite rejection."""

    if isinstance(text, bytes):
        if len(text) > max_bytes:
            raise ControlSchemaError("control document too large")
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ControlSchemaError("control document is not UTF-8") from error
    elif isinstance(text, str):
        if len(text.encode("utf-8")) > max_bytes:
            raise ControlSchemaError("control document too large")
    else:
        raise ControlSchemaError("control document must be str or bytes")

    def object_pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: set[str] = set()
        out: dict[str, Any] = {}
        if len(pairs) > CONTROL_MAX_MAP_ENTRIES:
            raise ControlSchemaError("map too large")
        for key, value in pairs:
            if not isinstance(key, str):
                raise ControlSchemaError("object keys must be strings")
            if key in seen:
                raise ControlSchemaError(f"duplicate object key: {key!r}")
            seen.add(key)
            out[key] = value
        return out

    try:
        data = json.loads(
            text,
            object_pairs_hook=object_pairs_hook,
            parse_constant=_reject_const,
        )
    except json.JSONDecodeError as error:
        raise ControlSchemaError("invalid JSON") from error
    _check_structure(data, depth=0)
    return data


def _check_structure(value: Any, *, depth: int) -> None:
    if depth > CONTROL_MAX_DEPTH:
        raise ControlSchemaError("document nesting too deep")
    if isinstance(value, dict):
        if len(value) > CONTROL_MAX_MAP_ENTRIES:
            raise ControlSchemaError("map too large")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > CONTROL_MAX_STRING_CHARS:
                raise ControlSchemaError("invalid map key")
            if any(ord(ch) < 0x20 for ch in key):
                raise ControlSchemaError("control characters in key")
            _check_structure(item, depth=depth + 1)
        return
    if isinstance(value, list):
        if len(value) > CONTROL_MAX_LIST_ENTRIES:
            raise ControlSchemaError("list too large")
        for item in value:
            _check_structure(item, depth=depth + 1)
        return
    if isinstance(value, str):
        if len(value) > CONTROL_MAX_STRING_CHARS:
            raise ControlSchemaError("string too long")
        if "\x00" in value:
            raise ControlSchemaError("NUL in string")
        return
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, int) and not isinstance(value, bool):
        # JSON integers only; reject bool (already handled).
        if value < -(2**63) or value > 2**63 - 1:
            raise ControlSchemaError("integer out of range")
        return
    if isinstance(value, float):
        raise ControlSchemaError("floating-point values are not allowed")
    raise ControlSchemaError(f"unsupported JSON type: {type(value).__name__}")


def _require_keys(data: Mapping[str, Any], required: frozenset[str], allowed: frozenset[str]) -> None:
    keys = frozenset(data)
    missing = required - keys
    if missing:
        raise ControlSchemaError(f"missing keys: {sorted(missing)}")
    extra = keys - allowed
    if extra:
        raise ControlSchemaError(f"unknown keys: {sorted(extra)}")


def _require_str(value: Any, *, name: str, max_chars: int = CONTROL_MAX_STRING_CHARS) -> str:
    if type(value) is not str:
        raise ControlSchemaError(f"{name} must be a string")
    if len(value) > max_chars or "\x00" in value:
        raise ControlSchemaError(f"invalid {name}")
    if any(ord(ch) < 0x20 for ch in value):
        raise ControlSchemaError(f"control characters in {name}")
    return value


def _require_int(value: Any, *, name: str, minimum: int = 0, maximum: int = 2**31 - 1) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise ControlSchemaError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise ControlSchemaError(f"{name} out of range")
    return value


def _require_hex64(value: Any, *, name: str) -> str:
    text = _require_str(value, name=name, max_chars=64)
    if _HEX64.fullmatch(text) is None:
        raise ControlSchemaError(f"invalid {name}")
    return text


def parse_manifest_document(text: str | bytes) -> dict[str, Any]:
    """Return a validated plain dict for install-manifest-v1 (not yet typed objects)."""

    data = strict_json_loads(text)
    if not isinstance(data, dict):
        raise ControlSchemaError("manifest root must be an object")
    _require_keys(data, _MANIFEST_TOP, _MANIFEST_TOP)

    schema_version = _require_str(data["schema_version"], name="schema_version", max_chars=128)
    if schema_version != MANIFEST_SCHEMA:
        raise ControlSchemaError("unsupported manifest schema_version")
    # Older product bundle versions must still load so plan_install / uninstall can
    # coordinate upgrades (verify_root enforces the *current* bundle separately).
    bundle_version = _require_str(data["bundle_version"], name="bundle_version", max_chars=64)
    if not bundle_version.strip():
        raise ControlSchemaError("empty bundle_version")
    generation = _require_int(data["generation"], name="generation", minimum=0, maximum=2**31 - 1)
    package_identity = _require_hex64(data["package_identity"], name="package_identity")

    claims_raw = data["claims"]
    if not isinstance(claims_raw, dict):
        raise ControlSchemaError("claims must be an object")
    if len(claims_raw) > CONTROL_MAX_CLAIMS:
        raise ControlSchemaError("too many claims")
    claims: dict[str, dict[str, str]] = {}
    for claim_id, meta in claims_raw.items():
        claim_id = _require_str(claim_id, name="claim id", max_chars=1024)
        if not isinstance(meta, dict):
            raise ControlSchemaError("claim entry must be an object")
        _require_keys(meta, _CLAIM_KEYS, _CLAIM_KEYS)
        host = _require_str(meta["host"], name="claim.host", max_chars=64)
        if host not in HOST_KEYS:
            raise ControlSchemaError("unknown claim host")
        scope = _require_str(meta["scope"], name="claim.scope", max_chars=32)
        if scope not in _SCOPES:
            raise ControlSchemaError("invalid claim scope")
        root = _require_str(meta["root"], name="claim.root", max_chars=CONTROL_MAX_STRING_CHARS)
        if not os.path.isabs(root):
            raise ControlSchemaError("claim.root must be absolute")
        claim_bundle = _require_str(meta["bundle_version"], name="claim.bundle_version", max_chars=64)
        if not claim_bundle.strip():
            raise ControlSchemaError("empty claim.bundle_version")
        # Claim id must recompute from host|scope|root (realpath spelling as stored).
        expected = f"{host}|{scope}|{root}"
        if claim_id != expected:
            raise ControlSchemaError("claim key inconsistent with host/scope/root")
        claims[claim_id] = {
            "host": host,
            "scope": scope,
            "root": root,
            "bundle_version": claim_bundle,
        }

    files_raw = data["files"]
    if not isinstance(files_raw, dict):
        raise ControlSchemaError("files must be an object")
    if len(files_raw) > CONTROL_MAX_FILES:
        raise ControlSchemaError("too many files")

    from .manifest import validate_rel_path

    files: dict[str, dict[str, Any]] = {}
    for path_key, entry in files_raw.items():
        path_key = _require_str(path_key, name="file path key", max_chars=1024)
        try:
            safe_key = validate_rel_path(path_key)
        except ValueError as error:
            raise ControlSchemaError("unsafe file path") from error
        if safe_key != path_key:
            raise ControlSchemaError("file path key not canonical")
        if not isinstance(entry, dict):
            raise ControlSchemaError("file entry must be an object")
        _require_keys(entry, _FILE_ENTRY_KEYS, _FILE_ENTRY_KEYS)
        nested_path = _require_str(entry["path"], name="file.path", max_chars=1024)
        try:
            nested_path = validate_rel_path(nested_path)
        except ValueError as error:
            raise ControlSchemaError("unsafe nested file path") from error
        if nested_path != safe_key:
            raise ControlSchemaError("file path mismatch")
        digest = _require_hex64(entry["sha256"], name="file.sha256")
        mode = _require_int(entry["mode"], name="file.mode", minimum=0, maximum=0o777)
        if mode not in _ALLOWED_MODES:
            raise ControlSchemaError("disallowed file mode")
        owner = _require_str(entry["owner"], name="file.owner", max_chars=64)
        if owner != OWNER_MARKER:
            raise ControlSchemaError("invalid owner marker")
        claim_list = entry["claims"]
        if not isinstance(claim_list, list) or not claim_list:
            raise ControlSchemaError("file claims must be a non-empty list")
        if len(claim_list) > CONTROL_MAX_CLAIM_REFS:
            raise ControlSchemaError("too many claim refs on file")
        refs: list[str] = []
        for item in claim_list:
            ref = _require_str(item, name="file.claim", max_chars=1024)
            if ref not in claims:
                raise ControlSchemaError("dangling file claim reference")
            if ref in refs:
                raise ControlSchemaError("duplicate file claim reference")
            refs.append(ref)
        files[safe_key] = {
            "path": safe_key,
            "sha256": digest,
            "claims": refs,
            "mode": mode,
            "owner": owner,
        }

    # Every claim must be referenced by at least one file when claims exist with files.
    # Empty files with empty claims is invalid for a published ownership document
    # except generation 0 empty templates — reject empty claims with empty files only
    # when generation > 0 and claims empty? Allow empty claims only if generation==0
    # and files empty (unused). Published installs always have claims.
    if generation > 0 and not claims:
        raise ControlSchemaError("generation > 0 requires claims")
    referenced = {ref for entry in files.values() for ref in entry["claims"]}
    if claims and not files:
        raise ControlSchemaError("claims without files")
    if set(claims) - referenced:
        raise ControlSchemaError("unreferenced claim")

    return {
        "schema_version": schema_version,
        "bundle_version": bundle_version,
        "generation": generation,
        "package_identity": package_identity,
        "claims": claims,
        "files": files,
    }


def parse_journal_document(text: str | bytes) -> dict[str, Any]:
    """Validate install-journal-v1 shape before recovery/mutation uses it."""

    data = strict_json_loads(text)
    if not isinstance(data, dict):
        raise ControlSchemaError("journal root must be an object")
    keys = frozenset(data)
    if not _JOURNAL_TOP_REQUIRED <= keys:
        raise ControlSchemaError("journal missing required keys")
    if keys - (_JOURNAL_TOP_REQUIRED | _JOURNAL_TOP_OPTIONAL):
        raise ControlSchemaError("journal has unknown keys")

    schema_version = _require_str(data["schema_version"], name="schema_version", max_chars=128)
    if schema_version != JOURNAL_SCHEMA:
        raise ControlSchemaError("unsupported journal schema_version")
    state = _require_str(data["state"], name="state", max_chars=64)
    if state not in JOURNAL_STATES:
        raise ControlSchemaError("unknown journal state")
    generation = _require_int(data["generation"], name="generation", minimum=0)
    claim = _require_str(data["claim"], name="claim", max_chars=1024)
    # Null stage_dir is allowed for published-generation recovery stubs that only
    # clear the journal; live staging journals always set a non-empty path.
    stage_raw = data["stage_dir"]
    if stage_raw is None:
        stage_dir = None
    else:
        stage_dir = _require_str(stage_raw, name="stage_dir", max_chars=CONTROL_MAX_STRING_CHARS)
        if not stage_dir:
            raise ControlSchemaError("stage_dir empty")

    backup_root = data.get("backup_root")
    if backup_root is not None:
        backup_root = _require_str(backup_root, name="backup_root", max_chars=CONTROL_MAX_STRING_CHARS)

    target_generation = data.get("target_generation")
    if target_generation is not None:
        target_generation = _require_int(target_generation, name="target_generation", minimum=0)

    operation = data.get("operation")
    if operation is not None:
        operation = _require_str(operation, name="operation", max_chars=32)
        if operation not in {"install", "uninstall"}:
            raise ControlSchemaError("unknown journal operation")

    paths_raw = data["paths"]
    if not isinstance(paths_raw, dict):
        raise ControlSchemaError("paths must be an object")
    if len(paths_raw) > CONTROL_MAX_FILES:
        raise ControlSchemaError("too many journal paths")

    from .manifest import validate_rel_path

    paths: dict[str, dict[str, Any]] = {}
    for rel, meta in paths_raw.items():
        rel = _require_str(rel, name="journal path", max_chars=1024)
        try:
            rel = validate_rel_path(rel)
        except ValueError as error:
            raise ControlSchemaError("unsafe journal path") from error
        if not isinstance(meta, dict):
            raise ControlSchemaError("path metadata must be an object")
        meta_keys = frozenset(meta)
        if not meta_keys <= _JOURNAL_PATH_META_KEYS:
            raise ControlSchemaError("unknown path metadata keys")
        if "state" not in meta:
            raise ControlSchemaError("path state required")
        path_state = _require_str(meta["state"], name="path.state", max_chars=32)
        if path_state not in JOURNAL_PATH_STATES:
            raise ControlSchemaError("unknown path state")
        cleaned: dict[str, Any] = {"state": path_state}
        if "existed" in meta:
            if type(meta["existed"]) is not bool:
                raise ControlSchemaError("path.existed must be bool")
            cleaned["existed"] = meta["existed"]
        if "sha256" in meta:
            cleaned["sha256"] = _require_hex64(meta["sha256"], name="path.sha256")
        if "original_sha256" in meta:
            cleaned["original_sha256"] = _require_hex64(meta["original_sha256"], name="original_sha256")
        if "rollback_backup" in meta:
            cleaned["rollback_backup"] = _require_str(
                meta["rollback_backup"], name="rollback_backup", max_chars=CONTROL_MAX_STRING_CHARS
            )
        if "backup" in meta:
            cleaned["backup"] = _require_str(meta["backup"], name="backup", max_chars=CONTROL_MAX_STRING_CHARS)
        paths[rel] = cleaned

    orphans: dict[str, dict[str, Any]] | None = None
    if "orphans" in data:
        orphans_raw = data["orphans"]
        if not isinstance(orphans_raw, dict):
            raise ControlSchemaError("orphans must be an object")
        orphans = {}
        for rel, meta in orphans_raw.items():
            rel = _require_str(rel, name="orphan path", max_chars=1024)
            try:
                rel = validate_rel_path(rel)
            except ValueError as error:
                raise ControlSchemaError("unsafe orphan path") from error
            if not isinstance(meta, dict):
                raise ControlSchemaError("orphan metadata must be an object")
            if frozenset(meta) - frozenset({"sha256", "state"}):
                raise ControlSchemaError("unknown orphan keys")
            if "sha256" not in meta or "state" not in meta:
                raise ControlSchemaError("orphan requires sha256 and state")
            o_state = _require_str(meta["state"], name="orphan.state", max_chars=32)
            if o_state not in JOURNAL_ORPHAN_STATES:
                raise ControlSchemaError("unknown orphan state")
            orphans[rel] = {
                "sha256": _require_hex64(meta["sha256"], name="orphan.sha256"),
                "state": o_state,
            }

    out: dict[str, Any] = {
        "schema_version": schema_version,
        "state": state,
        "generation": generation,
        "claim": claim,
        "stage_dir": stage_dir,
        "paths": paths,
    }
    if "backup_root" in data:
        out["backup_root"] = backup_root
    if target_generation is not None:
        out["target_generation"] = target_generation
    if operation is not None:
        out["operation"] = operation
    if orphans is not None:
        out["orphans"] = orphans
    return out
