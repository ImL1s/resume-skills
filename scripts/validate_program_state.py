#!/usr/bin/env python3
"""Validate program-state closed schemas, replay helpers, and transition guards.

stdlib-only Wave 0 validator for all-open-issues-sequential-prs-20260728.
Without --state-root, runs synthetic self-checks. With --state-root, loads
state/pointer.json, state/manifest.json, receipts, dependency-events, and
evidence and validates closed schemas / chains / basic projection rules.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

PROGRAM_ID = "all-open-issues-sequential-prs-20260728"
SCHEMA_VERSION = 2
ISSUE_COUNT = 44
PAIR_COUNT = 212

ORDER_SOURCE_PATH = "plans/all-open-issues-sequential-prs/activation-order-20260728.json"
ORDER_SOURCE_SHA256 = (
    "c0d171be7406c7cae1475e40c51cbbc0ba4c913e4217507ce8decdecb806f36d"
)
# Frozen reviewed selection order (ledger_ordinal 1..44).
FROZEN_ISSUE_ORDER: list[int] = [
    12,
    13,
    62,
    68,
    61,
    17,
    63,
    35,
    28,
    26,
    29,
    10,
    16,
    36,
    38,
    69,
    67,
    66,
    65,
    48,
    47,
    46,
    45,
    44,
    43,
    42,
    41,
    40,
    39,
    37,
    34,
    33,
    32,
    30,
    27,
    25,
    24,
    23,
    22,
    19,
    18,
    15,
    8,
    7,
]
FROZEN_WAVE_BY_ISSUE: dict[int, int] = {
    **{n: 1 for n in (12, 13)},
    **{n: 2 for n in (62, 68, 61, 17, 63, 35, 28, 26, 29)},
    **{n: 3 for n in (10, 16, 36, 38)},
    **{
        n: 4
        for n in (
            69,
            67,
            66,
            65,
            48,
            47,
            46,
            45,
            44,
            43,
            42,
            41,
            40,
            39,
            37,
            34,
            33,
            32,
            30,
            27,
            25,
            24,
            23,
            22,
            19,
            18,
            15,
            8,
            7,
        )
    },
}
PAIRS_SOURCE_PATH = (
    "plans/all-open-issues-sequential-prs/activation-dependency-pairs-20260728.json"
)
PAIRS_SOURCE_SHA256 = (
    "341592eeb1b7bbacd3ff28c8db7073da1042c92cf75e1a474f512cc71268ec3f"
)
BASELINE_MANIFEST_SHA256 = (
    "72af3d77babab06250bb6682bf9c649e2021e68bc86db4cf9af690476fe6b303"
)
ACTIVATION_MAIN_SHA = "ef2a2f709290cb9e56c6c669bca03f15a12829a9"
ACTIVATION_SNAPSHOT_AT = "2026-07-28T01:23:52Z"

STATUS_ENUM = frozenset({"idle", "owned", "blocked", "complete"})
PHASE_ENUM = frozenset({"idle", "selected", "pr-open", "blocked", "complete"})
# Transition-from bootstrap uses uninitialized only on receipts, not pointer.
RECEIPT_STATUS_ENUM = STATUS_ENUM | frozenset({"uninitialized"})
RECEIPT_PHASE_ENUM = PHASE_ENUM | frozenset({"uninitialized"})

UUID_V4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
SEQUENCE_FILENAME_RE = re.compile(
    r"^(?P<seq>\d{20})-(?P<id>[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12})\.json$"
)

CLASSIFICATION_ENUM = frozenset(
    {
        "unknown",
        "none",
        "related-blocks-subject",
        "subject-blocks-related",
        "soft-ordering",
        "shared-root-cause",
    }
)
PROJECTION_STATUS_ENUM = frozenset(
    {"unresolved", "nonblocking", "blocking", "satisfied"}
)

ERROR_PROGRAM_COMPLETE = "E_PROGRAM_COMPLETE"
ERROR_ACCEPTANCE_INCOMPLETE = "E_ACCEPTANCE_INCOMPLETE"
ERROR_OWNER_MISMATCH = "E_OWNER_MISMATCH"
ERROR_EPOCH_MISMATCH = "E_EPOCH_MISMATCH"
ERROR_STATE_SCHEMA = "E_STATE_SCHEMA"
ERROR_STATE_ID = "E_STATE_ID"
ERROR_STATE_SEQUENCE = "E_STATE_SEQUENCE"
ERROR_STATE_HASH = "E_STATE_HASH"
ERROR_STATE_PATH = "E_STATE_PATH"
ERROR_STATE_CANONICAL = "E_STATE_CANONICAL"
ERROR_STATE_PROJECTION = "E_STATE_PROJECTION"


class ProgramStateError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Canonical JSON helpers
# ---------------------------------------------------------------------------


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                f"duplicate JSON key: {key!r}",
            )
        result[key] = value
    return result


def reject_nonfinite(token: str) -> Any:
    raise ProgramStateError(ERROR_STATE_SCHEMA, f"non-finite JSON number: {token}")


def strict_loads(text: str) -> Any:
    return json.loads(
        text,
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_nonfinite,
    )


def strict_load_path(path: Path) -> Any:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ProgramStateError(ERROR_STATE_CANONICAL, f"BOM forbidden: {path}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProgramStateError(
            ERROR_STATE_CANONICAL,
            f"invalid UTF-8: {path}: {exc}",
        ) from exc
    return strict_loads(text)


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def persisted_file_bytes(value: object) -> bytes:
    """Persisted state files are canonical JSON plus exactly one LF."""
    return canonical_bytes(value) + b"\n"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def self_hash(record: Mapping[str, Any], field_name: str) -> str:
    """SHA-256 of canonical object with only the named top-level self-hash omitted."""
    if field_name not in record:
        raise ProgramStateError(
            ERROR_STATE_HASH,
            f"missing self-hash field {field_name!r}",
        )
    without = {key: value for key, value in record.items() if key != field_name}
    return sha256_hex(canonical_bytes(without))


def verify_self_hash(record: Mapping[str, Any], field_name: str) -> str:
    expected = record[field_name]
    if not isinstance(expected, str) or SHA256_HEX_RE.fullmatch(expected) is None:
        raise ProgramStateError(
            ERROR_STATE_HASH,
            f"{field_name} must be 64-char lowercase hex",
        )
    computed = self_hash(record, field_name)
    if expected != computed:
        raise ProgramStateError(
            ERROR_STATE_HASH,
            f"{field_name} mismatch: got {expected}, expected {computed}",
        )
    return computed


def verify_persisted_bytes(path: Path, record: Mapping[str, Any]) -> None:
    on_disk = path.read_bytes()
    expected = persisted_file_bytes(record)
    if on_disk != expected:
        raise ProgramStateError(
            ERROR_STATE_CANONICAL,
            f"persisted bytes mismatch for {path}",
        )


# ---------------------------------------------------------------------------
# UUID / path helpers
# ---------------------------------------------------------------------------


def is_uuid_v4(value: object) -> bool:
    if not isinstance(value, str) or UUID_V4_RE.fullmatch(value) is None:
        return False
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return parsed.version == 4 and parsed.variant == uuid.RFC_4122


def require_uuid_v4(value: object, *, label: str) -> str:
    if not is_uuid_v4(value):
        raise ProgramStateError(
            ERROR_STATE_ID,
            f"{label} is not a lowercase RFC 4122 UUIDv4: {value!r}",
        )
    return str(value)


def format_sequence_prefix(sequence: int) -> str:
    if type(sequence) is not int or isinstance(sequence, bool) or sequence < 1:
        raise ProgramStateError(
            ERROR_STATE_SEQUENCE,
            f"sequence must be integer >= 1, got {sequence!r}",
        )
    return f"{sequence:020d}"


def parse_sequenced_filename(name: str) -> tuple[int, str]:
    match = SEQUENCE_FILENAME_RE.fullmatch(name)
    if match is None:
        raise ProgramStateError(
            ERROR_STATE_PATH,
            f"invalid sequenced filename: {name!r}",
        )
    seq = int(match.group("seq"))
    event_id = match.group("id")
    require_uuid_v4(event_id, label="filename id")
    if format_sequence_prefix(seq) != match.group("seq"):
        raise ProgramStateError(
            ERROR_STATE_SEQUENCE,
            f"sequence prefix not zero-padded 20 digits: {name!r}",
        )
    return seq, event_id


def validate_sequence_chain(sequences: Sequence[int], *, label: str) -> None:
    if not sequences:
        return
    if sequences[0] != 1:
        raise ProgramStateError(
            ERROR_STATE_SEQUENCE,
            f"{label} sequences must start at 1, got {sequences[0]}",
        )
    for index in range(1, len(sequences)):
        if sequences[index] != sequences[index - 1] + 1:
            raise ProgramStateError(
                ERROR_STATE_SEQUENCE,
                f"{label} sequence gap/duplicate at {sequences[index]} "
                f"(previous {sequences[index - 1]})",
            )


# ---------------------------------------------------------------------------
# Type / field helpers
# ---------------------------------------------------------------------------


def _is_int(value: object) -> bool:
    return type(value) is int and not isinstance(value, bool)


def _reject_floats(value: Any, *, path: str = "$") -> None:
    if isinstance(value, float):
        raise ProgramStateError(
            ERROR_STATE_SCHEMA,
            f"float forbidden at {path}: {value!r}",
        )
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_floats(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_floats(child, path=f"{path}[{index}]")


def require_object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProgramStateError(
            ERROR_STATE_SCHEMA,
            f"{label} must be a JSON object",
        )
    _reject_floats(value, path=label)
    return value


def require_keys_exact(obj: Mapping[str, Any], keys: Iterable[str], *, label: str) -> None:
    expected = set(keys)
    actual = set(obj)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        raise ProgramStateError(
            ERROR_STATE_SCHEMA,
            f"{label} field set mismatch; missing={missing} extra={extra}",
        )


def require_enum(value: object, allowed: frozenset[str], *, label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ProgramStateError(
            ERROR_STATE_SCHEMA,
            f"{label} must be one of {sorted(allowed)}, got {value!r}",
        )
    return value


def require_null_or_str(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProgramStateError(
            ERROR_STATE_SCHEMA,
            f"{label} must be string or null",
        )
    return value


def require_list(value: object, *, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ProgramStateError(ERROR_STATE_SCHEMA, f"{label} must be a list")
    return value


# ---------------------------------------------------------------------------
# Pointer schema
# ---------------------------------------------------------------------------

POINTER_FIELDS = (
    "schema_version",
    "program_id",
    "state_sequence",
    "epoch",
    "status",
    "phase",
    "owner_token",
    "owner_identity",
    "active_issue_number",
    "active_pr_ordinal",
    "active_branch",
    "active_authorization_id",
    "active_pr_number",
    "active_pr_node_id",
    "active_pr_url",
    "active_initial_head_sha",
    "completed_pr_receipt_sha256s",
    "blocked_reason",
    "blocked_from_status",
    "blocked_from_phase",
    "last_receipt_sequence",
    "last_receipt_sha256",
    "state_parent_oid",
    "updated_at",
    "pointer_sha256",
)


def validate_pointer(pointer: Any, *, verify_hash: bool = True) -> dict[str, Any]:
    obj = require_object(pointer, label="pointer")
    require_keys_exact(obj, POINTER_FIELDS, label="pointer")
    if obj["schema_version"] != SCHEMA_VERSION:
        raise ProgramStateError(ERROR_STATE_SCHEMA, "pointer.schema_version must be 2")
    if obj["program_id"] != PROGRAM_ID:
        raise ProgramStateError(ERROR_STATE_SCHEMA, "pointer.program_id mismatch")
    if not _is_int(obj["state_sequence"]) or obj["state_sequence"] < 1:
        raise ProgramStateError(ERROR_STATE_SEQUENCE, "pointer.state_sequence invalid")
    if not _is_int(obj["epoch"]) or obj["epoch"] < 0:
        raise ProgramStateError(ERROR_STATE_SCHEMA, "pointer.epoch invalid")
    status = require_enum(obj["status"], STATUS_ENUM, label="pointer.status")
    phase = require_enum(obj["phase"], PHASE_ENUM, label="pointer.phase")

    # Soft structural constraints by status (not every combination is legal).
    if status == "idle":
        if phase not in {"idle"}:
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                "idle pointer requires phase idle",
            )
        for key in (
            "owner_token",
            "owner_identity",
            "active_issue_number",
            "active_pr_ordinal",
            "active_branch",
            "active_authorization_id",
            "active_pr_number",
            "active_pr_node_id",
            "active_pr_url",
            "active_initial_head_sha",
            "blocked_reason",
            "blocked_from_status",
            "blocked_from_phase",
        ):
            if obj[key] is not None:
                raise ProgramStateError(
                    ERROR_STATE_SCHEMA,
                    f"idle pointer requires {key}=null",
                )
        if require_list(obj["completed_pr_receipt_sha256s"], label="completed_pr") != []:
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                "idle pointer requires empty completed_pr_receipt_sha256s",
            )
    elif status == "complete":
        if phase != "complete":
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                "complete pointer requires phase complete",
            )
        for key in (
            "owner_token",
            "owner_identity",
            "active_issue_number",
            "active_pr_ordinal",
            "active_branch",
            "active_authorization_id",
            "active_pr_number",
            "active_pr_node_id",
            "active_pr_url",
            "active_initial_head_sha",
            "blocked_reason",
            "blocked_from_status",
            "blocked_from_phase",
        ):
            if obj[key] is not None:
                raise ProgramStateError(
                    ERROR_STATE_SCHEMA,
                    f"complete pointer requires {key}=null",
                )
        if require_list(obj["completed_pr_receipt_sha256s"], label="completed_pr") != []:
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                "complete pointer requires empty completed_pr_receipt_sha256s",
            )
    elif status == "owned":
        if phase not in {"selected", "pr-open"}:
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                "owned pointer requires phase selected|pr-open",
            )
        if not isinstance(obj["owner_token"], str) or not obj["owner_token"]:
            raise ProgramStateError(ERROR_STATE_SCHEMA, "owned requires owner_token")
        if not isinstance(obj["owner_identity"], str) or not obj["owner_identity"]:
            raise ProgramStateError(ERROR_STATE_SCHEMA, "owned requires owner_identity")
        if not _is_int(obj["active_issue_number"]):
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                "owned requires active_issue_number int",
            )
        if not _is_int(obj["active_pr_ordinal"]) or obj["active_pr_ordinal"] < 1:
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                "owned requires active_pr_ordinal >= 1",
            )
        if not isinstance(obj["active_branch"], str) or not obj["active_branch"]:
            raise ProgramStateError(ERROR_STATE_SCHEMA, "owned requires active_branch")
        if phase == "selected":
            for key in (
                "active_authorization_id",
                "active_pr_number",
                "active_pr_node_id",
                "active_pr_url",
                "active_initial_head_sha",
            ):
                if obj[key] is not None:
                    raise ProgramStateError(
                        ERROR_STATE_SCHEMA,
                        f"owned/selected requires {key}=null",
                    )
        else:  # pr-open
            require_uuid_v4(obj["active_authorization_id"], label="active_authorization_id")
            if not _is_int(obj["active_pr_number"]):
                raise ProgramStateError(
                    ERROR_STATE_SCHEMA,
                    "owned/pr-open requires active_pr_number",
                )
            if not isinstance(obj["active_pr_node_id"], str) or not obj["active_pr_node_id"]:
                raise ProgramStateError(
                    ERROR_STATE_SCHEMA,
                    "owned/pr-open requires active_pr_node_id",
                )
            if not isinstance(obj["active_pr_url"], str) or not obj["active_pr_url"]:
                raise ProgramStateError(
                    ERROR_STATE_SCHEMA,
                    "owned/pr-open requires active_pr_url",
                )
            if not isinstance(obj["active_initial_head_sha"], str) or not obj[
                "active_initial_head_sha"
            ]:
                raise ProgramStateError(
                    ERROR_STATE_SCHEMA,
                    "owned/pr-open requires active_initial_head_sha",
                )
        for key in ("blocked_reason", "blocked_from_status", "blocked_from_phase"):
            if obj[key] is not None:
                raise ProgramStateError(
                    ERROR_STATE_SCHEMA,
                    f"owned pointer requires {key}=null",
                )
        require_list(obj["completed_pr_receipt_sha256s"], label="completed_pr")
    elif status == "blocked":
        if phase != "blocked":
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                "blocked pointer requires phase blocked",
            )
        if not isinstance(obj["blocked_reason"], str) or not obj["blocked_reason"]:
            raise ProgramStateError(ERROR_STATE_SCHEMA, "blocked requires blocked_reason")
        require_enum(
            obj["blocked_from_status"],
            STATUS_ENUM - {"blocked", "complete"},
            label="blocked_from_status",
        )
        require_enum(
            obj["blocked_from_phase"],
            PHASE_ENUM - {"blocked", "complete"},
            label="blocked_from_phase",
        )

    if not _is_int(obj["last_receipt_sequence"]) or obj["last_receipt_sequence"] < 1:
        raise ProgramStateError(
            ERROR_STATE_SEQUENCE,
            "pointer.last_receipt_sequence invalid",
        )
    if not isinstance(obj["last_receipt_sha256"], str):
        raise ProgramStateError(
            ERROR_STATE_SCHEMA,
            "pointer.last_receipt_sha256 must be string",
        )
    if obj["last_receipt_sha256"] and SHA256_HEX_RE.fullmatch(obj["last_receipt_sha256"]) is None:
        raise ProgramStateError(
            ERROR_STATE_HASH,
            "pointer.last_receipt_sha256 invalid hex",
        )
    if not isinstance(obj["state_parent_oid"], str):
        raise ProgramStateError(ERROR_STATE_SCHEMA, "state_parent_oid must be string")
    if not isinstance(obj["updated_at"], str):
        raise ProgramStateError(ERROR_STATE_SCHEMA, "updated_at must be string")

    if verify_hash:
        verify_self_hash(obj, "pointer_sha256")
    return obj


# ---------------------------------------------------------------------------
# Manifest activation block (Wave 0 constants)
# ---------------------------------------------------------------------------

MANIFEST_TOP_FIELDS = (
    "schema_version",
    "program_id",
    "activation",
    "state_sequence",
    "last_receipt_path",
    "last_receipt_sha256",
    "dependency_pair_source_path",
    "dependency_pair_source_sha256",
    "dependency_pair_count",
    "dependency_sequence",
    "last_dependency_event_path",
    "last_dependency_event_sha256",
    "pointer_path",
    "pointer_sha256",
    "previous_manifest_sha256",
    "expected_parent_state_oid",
    "resolved_issue_count",
    "resolved_issues",
    "dependency_projection",
    "unresolved_dependency_count",
    "terminal_lineage",
    "unresolved_lineage_count",
    "open_program_authorizations",
    "updated_at",
    "manifest_sha256",
)

ACTIVATION_FIELDS = (
    "snapshot_at",
    "main_sha",
    "issue_count",
    "issue_numbers",
    "issue_order",
    "issue_order_source_path",
    "issue_order_source_sha256",
    "baseline_manifest_sha256",
    "anchor_commit_oid",
    "anchor_tree_oid",
    "anchor_inventory_sha256",
    "anchor_evidence_ref",
)

ISSUE_ORDER_ENTRY_FIELDS = (
    "issue_number",
    "issue_node_id",
    "wave_number",
    "ledger_ordinal",
    "selection_wave_number",
)


def validate_activation_block(activation: Any, *, label: str = "activation") -> dict[str, Any]:
    obj = require_object(activation, label=label)
    require_keys_exact(obj, ACTIVATION_FIELDS, label=label)
    if obj.get("snapshot_at") != ACTIVATION_SNAPSHOT_AT:
        raise ProgramStateError(
            ERROR_STATE_SCHEMA,
            f"{label}.snapshot_at must equal {ACTIVATION_SNAPSHOT_AT}",
        )
    if obj.get("main_sha") != ACTIVATION_MAIN_SHA:
        raise ProgramStateError(
            ERROR_STATE_SCHEMA,
            f"{label}.main_sha must equal pinned activation main",
        )
    if obj.get("issue_count") != ISSUE_COUNT:
        raise ProgramStateError(
            ERROR_STATE_SCHEMA,
            f"{label}.issue_count must be {ISSUE_COUNT}",
        )
    if obj.get("issue_order_source_path") != ORDER_SOURCE_PATH:
        raise ProgramStateError(
            ERROR_STATE_SCHEMA,
            f"{label}.issue_order_source_path mismatch",
        )
    if obj.get("issue_order_source_sha256") != ORDER_SOURCE_SHA256:
        raise ProgramStateError(
            ERROR_STATE_SCHEMA,
            f"{label}.issue_order_source_sha256 mismatch",
        )
    if obj.get("baseline_manifest_sha256") != BASELINE_MANIFEST_SHA256:
        raise ProgramStateError(
            ERROR_STATE_SCHEMA,
            f"{label}.baseline_manifest_sha256 mismatch",
        )
    numbers = require_list(obj["issue_numbers"], label=f"{label}.issue_numbers")
    if len(numbers) != ISSUE_COUNT:
        raise ProgramStateError(
            ERROR_STATE_SCHEMA,
            f"{label}.issue_numbers length must be {ISSUE_COUNT}",
        )
    for value in numbers:
        if not _is_int(value):
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                f"{label}.issue_numbers must be integers",
            )
    if sorted(numbers) != sorted(set(numbers)):
        raise ProgramStateError(
            ERROR_STATE_SCHEMA,
            f"{label}.issue_numbers must be unique",
        )
    order = require_list(obj["issue_order"], label=f"{label}.issue_order")
    if len(order) != ISSUE_COUNT:
        raise ProgramStateError(
            ERROR_STATE_SCHEMA,
            f"{label}.issue_order length must be {ISSUE_COUNT}",
        )
    order_issue_numbers: list[int] = []
    for index, entry in enumerate(order):
        entry_obj = require_object(entry, label=f"{label}.issue_order[{index}]")
        require_keys_exact(
            entry_obj,
            ISSUE_ORDER_ENTRY_FIELDS,
            label=f"{label}.issue_order[{index}]",
        )
        if not _is_int(entry_obj["ledger_ordinal"]) or entry_obj["ledger_ordinal"] != index + 1:
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                f"{label}.issue_order[{index}].ledger_ordinal must be {index + 1}",
            )
        issue_number = entry_obj["issue_number"]
        if not _is_int(issue_number):
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                f"{label}.issue_order[{index}].issue_number must be int",
            )
        expected_issue = FROZEN_ISSUE_ORDER[index]
        if issue_number != expected_issue:
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                f"{label}.issue_order[{index}].issue_number must be "
                f"{expected_issue} (frozen order), got {issue_number}",
            )
        expected_wave = FROZEN_WAVE_BY_ISSUE[expected_issue]
        if entry_obj.get("wave_number") != expected_wave:
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                f"{label}.issue_order[{index}].wave_number must be {expected_wave}",
            )
        if entry_obj.get("selection_wave_number") != expected_wave:
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                f"{label}.issue_order[{index}].selection_wave_number must be "
                f"{expected_wave} (frozen wave until replay promotion)",
            )
        order_issue_numbers.append(issue_number)
    if sorted(order_issue_numbers) != sorted(numbers):
        raise ProgramStateError(
            ERROR_STATE_SCHEMA,
            f"{label}.issue_order issue set must equal {label}.issue_numbers",
        )
    if order_issue_numbers != FROZEN_ISSUE_ORDER:
        raise ProgramStateError(
            ERROR_STATE_SCHEMA,
            f"{label}.issue_order sequence must equal frozen selection order",
        )
    return obj


def validate_manifest_shape(
    manifest: Any,
    *,
    verify_hash: bool = True,
    require_pair_constants: bool = True,
) -> dict[str, Any]:
    obj = require_object(manifest, label="manifest")
    require_keys_exact(obj, MANIFEST_TOP_FIELDS, label="manifest")
    if obj["schema_version"] != SCHEMA_VERSION:
        raise ProgramStateError(ERROR_STATE_SCHEMA, "manifest.schema_version must be 2")
    if obj["program_id"] != PROGRAM_ID:
        raise ProgramStateError(ERROR_STATE_SCHEMA, "manifest.program_id mismatch")
    validate_activation_block(obj["activation"])
    if not _is_int(obj["state_sequence"]) or obj["state_sequence"] < 1:
        raise ProgramStateError(ERROR_STATE_SEQUENCE, "manifest.state_sequence invalid")
    if require_pair_constants:
        if obj.get("dependency_pair_source_path") != PAIRS_SOURCE_PATH:
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                "dependency_pair_source_path mismatch",
            )
        if obj.get("dependency_pair_source_sha256") != PAIRS_SOURCE_SHA256:
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                "dependency_pair_source_sha256 mismatch",
            )
        if obj.get("dependency_pair_count") != PAIR_COUNT:
            raise ProgramStateError(
                ERROR_STATE_PROJECTION,
                f"dependency_pair_count must be {PAIR_COUNT}",
            )
    if not _is_int(obj["dependency_sequence"]) or obj["dependency_sequence"] < 0:
        raise ProgramStateError(
            ERROR_STATE_SEQUENCE,
            "dependency_sequence invalid",
        )
    if obj.get("pointer_path") != "state/pointer.json":
        raise ProgramStateError(ERROR_STATE_PATH, "pointer_path must be state/pointer.json")
    require_list(obj["resolved_issues"], label="resolved_issues")
    require_list(obj["dependency_projection"], label="dependency_projection")
    require_list(obj["terminal_lineage"], label="terminal_lineage")
    require_list(obj["open_program_authorizations"], label="open_program_authorizations")
    if verify_hash:
        verify_self_hash(obj, "manifest_sha256")
    return obj


# ---------------------------------------------------------------------------
# Forbidden transitions (in-memory pure checks)
# ---------------------------------------------------------------------------


@dataclass
class PointerView:
    status: str
    phase: str
    epoch: int
    owner_token: str | None
    owner_identity: str | None
    active_issue_number: int | None
    active_pr_ordinal: int | None
    acceptance_complete: bool = False


@dataclass
class TransitionRequest:
    event_type: str
    to_status: str
    to_phase: str
    issue_number: int | None = None
    owner_token: str | None = None
    owner_identity: str | None = None
    epoch: int | None = None
    acceptance_complete: bool | None = None


def check_forbidden_transition(
    current: PointerView,
    request: TransitionRequest,
) -> None:
    """Raise ProgramStateError if the pure transition is forbidden."""
    if current.status == "complete":
        # Permanent sink: no acquisition / continuation / mutation.
        if request.event_type in {
            "issue-acquired",
            "pr-opened",
            "pr-checkpointed",
            "issue-released",
            "dependency-updated",
            "program-blocked",
            "program-resumed",
            "evidence-corrected",
            "program-completed",
        }:
            # Repeated completion is observational no-op for program-completed;
            # still reject acquisition and other mutations with E_PROGRAM_COMPLETE.
            if request.event_type == "program-completed":
                # observational no-op is allowed only when already complete; caller
                # treats it as non-writing. For guard table we reject state writes.
                raise ProgramStateError(
                    ERROR_PROGRAM_COMPLETE,
                    "program already complete; no state write",
                )
            raise ProgramStateError(
                ERROR_PROGRAM_COMPLETE,
                f"forbidden after complete: {request.event_type}",
            )

    # reject owned -> complete without going through idle
    if current.status == "owned" and request.to_status == "complete":
        raise ProgramStateError(
            ERROR_STATE_SCHEMA,
            "forbidden transition owned -> complete (must release to idle first)",
        )

    # reject acquisition when status is complete (also covered above)
    if request.event_type == "issue-acquired" and current.status != "idle":
        if current.status == "complete":
            raise ProgramStateError(
                ERROR_PROGRAM_COMPLETE,
                "cannot acquire issue when program is complete",
            )
        raise ProgramStateError(
            ERROR_STATE_SCHEMA,
            f"issue acquisition requires idle, got {current.status}",
        )

    # reject changing issue/owner/epoch during continuation
    if request.event_type in {"pr-opened", "pr-checkpointed"}:
        if current.status != "owned":
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                f"{request.event_type} requires owned status",
            )
        if (
            request.issue_number is not None
            and request.issue_number != current.active_issue_number
        ):
            raise ProgramStateError(
                ERROR_OWNER_MISMATCH,
                "continuation cannot change active issue",
            )
        if (
            request.owner_token is not None
            and request.owner_token != current.owner_token
        ):
            raise ProgramStateError(
                ERROR_OWNER_MISMATCH,
                "continuation cannot change owner_token",
            )
        if (
            request.owner_identity is not None
            and request.owner_identity != current.owner_identity
        ):
            raise ProgramStateError(
                ERROR_OWNER_MISMATCH,
                "continuation cannot change owner_identity",
            )
        if request.epoch is not None and request.epoch != current.epoch:
            raise ProgramStateError(
                ERROR_EPOCH_MISMATCH,
                "continuation cannot change epoch",
            )

    # reject release to idle with incomplete acceptance
    if request.event_type == "issue-released":
        complete = (
            request.acceptance_complete
            if request.acceptance_complete is not None
            else current.acceptance_complete
        )
        if not complete:
            raise ProgramStateError(
                ERROR_ACCEPTANCE_INCOMPLETE,
                "cannot release to idle while acceptance is incomplete",
            )
        if request.to_status != "idle":
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                "issue-released must target idle",
            )


# ---------------------------------------------------------------------------
# Dependency projection & selection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PairSpec:
    subject_issue_number: int
    related_issue_number: int
    related_is_baseline: bool
    dependency_id: str
    classification: str = "unknown"
    related_issue_node_id: str = ""
    current_event_sha256: str = ""
    effective_terminal_issues: frozenset[int] = field(default_factory=frozenset)


def project_dependency_status(
    classification: str,
    *,
    related_is_baseline: bool,
    subject: int,
    related: int,
    effective_terminal: frozenset[int],
    external_satisfied: bool = False,
) -> tuple[str | None, str | None, str]:
    if classification == "unknown":
        return None, None, "unresolved"
    if classification in {"none", "soft-ordering", "shared-root-cause"}:
        return None, None, "nonblocking"
    if classification == "related-blocks-subject":
        predecessor, successor = related, subject
        if related_is_baseline:
            status = "satisfied" if predecessor in effective_terminal else "blocking"
        else:
            status = "satisfied" if external_satisfied else "blocking"
        return predecessor, successor, status
    if classification == "subject-blocks-related":
        if not related_is_baseline:
            raise ProgramStateError(
                ERROR_STATE_PROJECTION,
                "subject-blocks-related requires related_is_baseline",
            )
        predecessor, successor = subject, related
        status = "satisfied" if predecessor in effective_terminal else "blocking"
        return predecessor, successor, status
    raise ProgramStateError(
        ERROR_STATE_SCHEMA,
        f"unknown classification: {classification}",
    )


def build_dependency_projection(
    pairs: Sequence[PairSpec],
    *,
    effective_terminal: frozenset[int] | None = None,
    external_satisfied_ids: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """One projection row per pair. Zero-outgoing issues get no sentinel rows."""
    terminal = effective_terminal or frozenset()
    external_ok = external_satisfied_ids or frozenset()
    rows: list[dict[str, Any]] = []
    for pair in pairs:
        pred, succ, status = project_dependency_status(
            pair.classification,
            related_is_baseline=pair.related_is_baseline,
            subject=pair.subject_issue_number,
            related=pair.related_issue_number,
            effective_terminal=terminal,
            external_satisfied=pair.dependency_id in external_ok,
        )
        rows.append(
            {
                "dependency_id": pair.dependency_id,
                "subject_issue_number": pair.subject_issue_number,
                "related_issue_number": pair.related_issue_number,
                "related_issue_node_id": pair.related_issue_node_id,
                "related_is_baseline": pair.related_is_baseline,
                "classification": pair.classification,
                "predecessor_issue_number": pred,
                "successor_issue_number": succ,
                "status": status,
                "current_event_sha256": pair.current_event_sha256,
            }
        )
    rows.sort(
        key=lambda row: (
            row["subject_issue_number"],
            row["related_issue_number"],
            row["dependency_id"],
        )
    )
    return rows


def issues_with_zero_outgoing_pairs(
    baseline_issues: Iterable[int],
    pairs: Sequence[PairSpec],
) -> list[int]:
    subjects = {pair.subject_issue_number for pair in pairs}
    return sorted(issue for issue in baseline_issues if issue not in subjects)


@dataclass(frozen=True)
class SelectionCandidate:
    issue_number: int
    selection_wave_number: int
    ledger_ordinal: int


def selection_key(candidate: SelectionCandidate) -> tuple[int, int, int]:
    return (
        candidate.selection_wave_number,
        candidate.ledger_ordinal,
        candidate.issue_number,
    )


def select_minimum_eligible(
    candidates: Sequence[SelectionCandidate],
) -> SelectionCandidate | None:
    if not candidates:
        return None
    return min(candidates, key=selection_key)


# ---------------------------------------------------------------------------
# Events list -> projection (for CLI / tests)
# ---------------------------------------------------------------------------


def projection_from_events(
    events: Sequence[Mapping[str, Any]],
    *,
    effective_terminal: frozenset[int] | None = None,
    external_satisfied_ids: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Build one-row-per-pair projection from an ordered event list (latest wins)."""
    latest: dict[tuple[int, int], PairSpec] = {}
    for event in events:
        subject = event["subject_issue_number"]
        related = event["related_issue_number"]
        key = (int(subject), int(related))
        classification = str(event.get("classification", "unknown"))
        if classification not in CLASSIFICATION_ENUM:
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                f"invalid classification {classification!r}",
            )
        dep_id = str(event["dependency_id"])
        require_uuid_v4(dep_id, label="dependency_id")
        latest[key] = PairSpec(
            subject_issue_number=key[0],
            related_issue_number=key[1],
            related_is_baseline=bool(event.get("related_is_baseline", False)),
            dependency_id=dep_id,
            classification=classification,
            related_issue_node_id=str(event.get("related_issue_node_id") or ""),
            current_event_sha256=str(event.get("event_sha256") or ""),
        )
    return build_dependency_projection(
        list(latest.values()),
        effective_terminal=effective_terminal,
        external_satisfied_ids=external_satisfied_ids,
    )


def _derive_terminal_issues_from_receipts(
    receipts: Sequence[tuple[Path, Mapping[str, Any]]],
) -> frozenset[int]:
    """Independently derive terminal issue numbers from validated receipt history."""
    terminal: set[int] = set()
    for _path, receipt in receipts:
        operation = str(receipt.get("operation") or receipt.get("event_type") or "")
        if operation not in {"issue-released", "program-completed"}:
            continue
        for key in (
            "issue_number",
            "active_issue_number",
            "released_issue_number",
        ):
            value = receipt.get(key)
            if _is_int(value):
                terminal.add(int(value))
        for item in receipt.get("resolved_issues") or []:
            if _is_int(item):
                terminal.add(int(item))
            elif isinstance(item, Mapping) and _is_int(item.get("issue_number")):
                terminal.add(int(item["issue_number"]))
    return frozenset(terminal)


def _derive_external_satisfied_ids(
    evidence: Sequence[tuple[Path, Mapping[str, Any]]],
) -> frozenset[str]:
    """Collect dependency IDs proven satisfied via typed external evidence."""
    satisfied: set[str] = set()
    for _path, record in evidence:
        evidence_type = str(
            record.get("evidence_type") or record.get("type") or ""
        )
        if evidence_type not in {
            "external-dependency-state",
            "external_dependency_satisfied",
        }:
            continue
        status = str(record.get("status") or record.get("state") or "").lower()
        if status not in {"satisfied", "complete", "terminal", "effective-terminal"}:
            continue
        dep_id = record.get("dependency_id")
        if isinstance(dep_id, str) and dep_id:
            require_uuid_v4(dep_id, label="dependency_id")
            satisfied.add(dep_id)
    return frozenset(satisfied)


def _load_frozen_pair_keys(repo_root: Path | None) -> set[tuple[int, int, bool]]:
    """Load frozen (subject, related, related_is_baseline) from tracked pairs."""
    candidates: list[Path] = []
    if repo_root is not None:
        candidates.append(repo_root / PAIRS_SOURCE_PATH)
    # Script lives in scripts/; repo root is parent.
    script_repo = Path(__file__).resolve().parents[1]
    candidates.append(script_repo / PAIRS_SOURCE_PATH)
    for path in candidates:
        if not path.is_file():
            continue
        raw = path.read_bytes()
        if sha256_hex(raw) != PAIRS_SOURCE_SHA256:
            raise ProgramStateError(
                ERROR_STATE_HASH,
                f"frozen pairs file hash mismatch at {path}",
            )
        payload = strict_loads(raw.decode("utf-8"))
        pairs = payload.get("pairs")
        if not isinstance(pairs, list):
            raise ProgramStateError(ERROR_STATE_SCHEMA, "frozen pairs.pairs must be list")
        keys: set[tuple[int, int, bool]] = set()
        for item in pairs:
            if not isinstance(item, Mapping):
                raise ProgramStateError(ERROR_STATE_SCHEMA, "frozen pair row must be object")
            keys.add(
                (
                    int(item["subject_issue_number"]),
                    int(item["related_issue_number"]),
                    bool(item["related_is_baseline"]),
                )
            )
        return keys
    raise ProgramStateError(
        ERROR_STATE_PATH,
        f"cannot locate frozen pairs file {PAIRS_SOURCE_PATH}",
    )


def _find_repo_root_near(start: Path) -> Path | None:
    current = start.resolve()
    for parent in [current, *current.parents]:
        if (parent / "plans" / "all-open-issues-sequential-prs").is_dir() and (
            parent / "scripts"
        ).is_dir():
            return parent
    return None


# ---------------------------------------------------------------------------
# State-root loader (basic Wave 0 coverage)
# ---------------------------------------------------------------------------


def _load_json_dir(directory: Path) -> list[tuple[Path, dict[str, Any]]]:
    if not directory.is_dir():
        return []
    items: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix != ".json":
            continue
        payload = require_object(strict_load_path(path), label=str(path))
        items.append((path, payload))
    return items


def validate_state_root(
    state_root: Path,
    *,
    require_pair_constants: bool = True,
) -> dict[str, Any]:
    if not state_root.is_dir():
        raise ProgramStateError(ERROR_STATE_PATH, f"state root missing: {state_root}")

    pointer_path = state_root / "pointer.json"
    manifest_path = state_root / "manifest.json"
    if not pointer_path.is_file() or not manifest_path.is_file():
        raise ProgramStateError(
            ERROR_STATE_PATH,
            "state root requires pointer.json and manifest.json",
        )

    pointer = validate_pointer(strict_load_path(pointer_path))
    verify_persisted_bytes(pointer_path, pointer)
    manifest = validate_manifest_shape(
        strict_load_path(manifest_path),
        require_pair_constants=require_pair_constants,
    )
    verify_persisted_bytes(manifest_path, manifest)

    if pointer["pointer_sha256"] != manifest["pointer_sha256"]:
        raise ProgramStateError(
            ERROR_STATE_HASH,
            "manifest.pointer_sha256 does not match pointer.pointer_sha256",
        )
    if pointer["state_sequence"] != manifest["state_sequence"]:
        raise ProgramStateError(
            ERROR_STATE_SEQUENCE,
            "pointer/manifest state_sequence mismatch",
        )

    activation_issue_numbers = {
        int(n) for n in manifest["activation"]["issue_numbers"] if _is_int(n)
    }
    if pointer["status"] == "owned":
        active = pointer.get("active_issue_number")
        if not _is_int(active) or int(active) not in activation_issue_numbers:
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                "owned pointer.active_issue_number must be in activation issue set",
            )

    receipts = _load_json_dir(state_root / "receipts")
    dep_events = _load_json_dir(state_root / "dependency-events")
    evidence = _load_json_dir(state_root / "evidence")

    claimed_receipt_seq = pointer.get("last_receipt_sequence")
    claimed_receipt_hash = pointer.get("last_receipt_sha256")
    manifest_receipt_path = manifest.get("last_receipt_path")
    manifest_receipt_hash = manifest.get("last_receipt_sha256")
    if claimed_receipt_seq is not None and (
        not _is_int(claimed_receipt_seq) or claimed_receipt_seq < 1
    ):
        raise ProgramStateError(
            ERROR_STATE_SEQUENCE,
            "pointer.last_receipt_sequence must be a positive integer when set",
        )
    if claimed_receipt_seq and not receipts:
        raise ProgramStateError(
            ERROR_STATE_PATH,
            "pointer claims last_receipt_sequence but receipts/ is empty or missing",
        )

    receipt_seqs: list[int] = []
    prev_hash: str | None = None
    last_receipt: dict[str, Any] | None = None
    last_receipt_path: Path | None = None
    for path, receipt in receipts:
        seq, op_id = parse_sequenced_filename(path.name)
        receipt_seqs.append(seq)
        if receipt.get("sequence") != seq:
            raise ProgramStateError(
                ERROR_STATE_SEQUENCE,
                f"receipt sequence field != filename for {path.name}",
            )
        if receipt.get("operation_id") != op_id:
            raise ProgramStateError(
                ERROR_STATE_ID,
                f"receipt operation_id != filename for {path.name}",
            )
        require_uuid_v4(receipt.get("receipt_id"), label="receipt_id")
        verify_self_hash(receipt, "receipt_sha256")
        verify_persisted_bytes(path, receipt)
        if seq == 1:
            if receipt.get("previous_receipt_sha256") is not None:
                raise ProgramStateError(
                    ERROR_STATE_HASH,
                    "bootstrap previous_receipt_sha256 must be null",
                )
        else:
            if receipt.get("previous_receipt_sha256") != prev_hash:
                raise ProgramStateError(
                    ERROR_STATE_HASH,
                    f"receipt chain break at sequence {seq}",
                )
        prev_hash = receipt["receipt_sha256"]
        last_receipt = receipt
        last_receipt_path = path
    validate_sequence_chain(receipt_seqs, label="receipt")

    if claimed_receipt_seq:
        if not receipt_seqs or receipt_seqs[-1] != claimed_receipt_seq:
            raise ProgramStateError(
                ERROR_STATE_SEQUENCE,
                "receipt chain tip sequence != pointer.last_receipt_sequence",
            )
        assert last_receipt is not None and last_receipt_path is not None
        tip_hash = last_receipt["receipt_sha256"]
        if not isinstance(claimed_receipt_hash, str) or not SHA256_HEX_RE.fullmatch(
            claimed_receipt_hash
        ):
            raise ProgramStateError(
                ERROR_STATE_HASH,
                "pointer.last_receipt_sha256 must be nonempty sha256 when sequence is set",
            )
        if tip_hash != claimed_receipt_hash:
            raise ProgramStateError(
                ERROR_STATE_HASH,
                "receipt chain tip hash != pointer.last_receipt_sha256",
            )
        if not isinstance(manifest_receipt_hash, str) or not SHA256_HEX_RE.fullmatch(
            manifest_receipt_hash
        ):
            raise ProgramStateError(
                ERROR_STATE_HASH,
                "manifest.last_receipt_sha256 must be nonempty sha256 when sequence is set",
            )
        if tip_hash != manifest_receipt_hash:
            raise ProgramStateError(
                ERROR_STATE_HASH,
                "receipt chain tip hash != manifest.last_receipt_sha256",
            )
        if not isinstance(manifest_receipt_path, str) or not manifest_receipt_path:
            raise ProgramStateError(
                ERROR_STATE_PATH,
                "manifest.last_receipt_path must be set when receipt sequence is set",
            )
        expected_rel = f"state/receipts/{last_receipt_path.name}"
        if manifest_receipt_path != expected_rel:
            raise ProgramStateError(
                ERROR_STATE_PATH,
                "manifest.last_receipt_path must equal "
                f"{expected_rel!r}, got {manifest_receipt_path!r}",
            )
    elif receipts:
        raise ProgramStateError(
            ERROR_STATE_SEQUENCE,
            "receipts present but pointer.last_receipt_sequence is unset/zero",
        )

    dep_seqs: list[int] = []
    prev_dep: str | None = None
    last_dep: dict[str, Any] | None = None
    last_dep_path: Path | None = None
    for path, event in dep_events:
        seq, event_id = parse_sequenced_filename(path.name)
        dep_seqs.append(seq)
        if event.get("dependency_sequence") != seq:
            raise ProgramStateError(
                ERROR_STATE_SEQUENCE,
                f"dependency_sequence != filename for {path.name}",
            )
        if event.get("event_id") != event_id:
            raise ProgramStateError(
                ERROR_STATE_ID,
                f"event_id != filename for {path.name}",
            )
        require_uuid_v4(event.get("dependency_id"), label="dependency_id")
        verify_self_hash(event, "event_sha256")
        verify_persisted_bytes(path, event)
        if seq == 1:
            if event.get("previous_dependency_event_sha256") is not None:
                raise ProgramStateError(
                    ERROR_STATE_HASH,
                    "first dependency previous hash must be null",
                )
        else:
            if event.get("previous_dependency_event_sha256") != prev_dep:
                raise ProgramStateError(
                    ERROR_STATE_HASH,
                    f"dependency chain break at sequence {seq}",
                )
        prev_dep = event["event_sha256"]
        last_dep = event
        last_dep_path = path
    validate_sequence_chain(dep_seqs, label="dependency")

    claimed_dep_seq = manifest.get("dependency_sequence")
    claimed_dep_path = manifest.get("last_dependency_event_path")
    claimed_dep_hash = manifest.get("last_dependency_event_sha256")
    if dep_events:
        if not _is_int(claimed_dep_seq) or claimed_dep_seq != dep_seqs[-1]:
            raise ProgramStateError(
                ERROR_STATE_SEQUENCE,
                "manifest.dependency_sequence must equal dependency event chain tip",
            )
        assert last_dep is not None and last_dep_path is not None
        if not isinstance(claimed_dep_hash, str) or not SHA256_HEX_RE.fullmatch(
            claimed_dep_hash
        ):
            raise ProgramStateError(
                ERROR_STATE_HASH,
                "manifest.last_dependency_event_sha256 must be nonempty sha256 "
                "when dependency events exist",
            )
        if last_dep["event_sha256"] != claimed_dep_hash:
            raise ProgramStateError(
                ERROR_STATE_HASH,
                "dependency chain tip hash != manifest.last_dependency_event_sha256",
            )
        expected_dep_rel = f"state/dependency-events/{last_dep_path.name}"
        if claimed_dep_path != expected_dep_rel:
            raise ProgramStateError(
                ERROR_STATE_PATH,
                "manifest.last_dependency_event_path must equal "
                f"{expected_dep_rel!r}, got {claimed_dep_path!r}",
            )
    else:
        # Manifest advertising the frozen pair source/count cannot be validated
        # as bootstrap-idle with zero dependency events — every frozen pair must
        # exist as an initial event (no sentinel, but also no empty set).
        if (
            manifest.get("dependency_pair_source_sha256") == PAIRS_SOURCE_SHA256
            or manifest.get("dependency_pair_count") == PAIR_COUNT
        ):
            raise ProgramStateError(
                ERROR_STATE_PROJECTION,
                "frozen pair source/count requires dependency-events to be present "
                f"(expected {PAIR_COUNT} initial events)",
            )
        if claimed_dep_seq not in (0, None):
            raise ProgramStateError(
                ERROR_STATE_SEQUENCE,
                "manifest.dependency_sequence must be 0 when no dependency events",
            )
        if claimed_dep_path is not None or claimed_dep_hash is not None:
            raise ProgramStateError(
                ERROR_STATE_PATH,
                "manifest dependency tip fields must be null without events",
            )

    for path, record in evidence:
        require_uuid_v4(record.get("evidence_id"), label="evidence_id")
        if path.stem != record["evidence_id"]:
            raise ProgramStateError(
                ERROR_STATE_PATH,
                f"evidence filename must equal evidence_id: {path.name}",
            )
        verify_self_hash(record, "record_sha256")
        verify_persisted_bytes(path, record)

    # Projection from dependency events must match the authoritative manifest.
    projection: list[dict[str, Any]] = []
    if dep_events:
        # Terminality and external satisfaction come from independently
        # validated receipts/evidence — not from self-asserted manifest fields.
        terminal_issues = _derive_terminal_issues_from_receipts(receipts)
        external_satisfied = _derive_external_satisfied_ids(evidence)

        # If the manifest claims a different terminal set, fail closed.
        claimed_terminal: set[int] = set()
        for entry in manifest.get("resolved_issues") or []:
            if isinstance(entry, Mapping) and _is_int(entry.get("issue_number")):
                claimed_terminal.add(int(entry["issue_number"]))
            elif _is_int(entry):
                claimed_terminal.add(int(entry))
        for entry in manifest.get("terminal_lineage") or []:
            if isinstance(entry, Mapping) and _is_int(entry.get("issue_number")):
                claimed_terminal.add(int(entry["issue_number"]))
        if claimed_terminal and claimed_terminal != set(terminal_issues):
            raise ProgramStateError(
                ERROR_STATE_PROJECTION,
                "manifest resolved/terminal claims do not match receipt-derived terminal set",
            )

        projection = projection_from_events(
            [event for _, event in dep_events],
            effective_terminal=terminal_issues,
            external_satisfied_ids=external_satisfied,
        )
        manifest_projection = manifest.get("dependency_projection")
        if not isinstance(manifest_projection, list):
            raise ProgramStateError(
                ERROR_STATE_PROJECTION,
                "manifest.dependency_projection must be a list",
            )

        def _normalize_proj_row(row: Mapping[str, Any]) -> dict[str, Any]:
            # Full closed projection fields from build_dependency_projection.
            return {
                "dependency_id": row.get("dependency_id"),
                "subject_issue_number": row.get("subject_issue_number"),
                "related_issue_number": row.get("related_issue_number"),
                "related_issue_node_id": row.get("related_issue_node_id"),
                "related_is_baseline": row.get("related_is_baseline"),
                "classification": row.get("classification"),
                "predecessor_issue_number": row.get("predecessor_issue_number"),
                "successor_issue_number": row.get("successor_issue_number"),
                "status": row.get("status"),
                "current_event_sha256": row.get("current_event_sha256"),
            }

        def _proj_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
            return (
                row.get("subject_issue_number"),
                row.get("related_issue_number"),
                row.get("dependency_id"),
            )

        got = sorted(
            (_normalize_proj_row(r) for r in projection if isinstance(r, Mapping)),
            key=_proj_key,
        )
        want = sorted(
            (
                _normalize_proj_row(r)
                for r in manifest_projection
                if isinstance(r, Mapping)
            ),
            key=_proj_key,
        )
        if got != want:
            raise ProgramStateError(
                ERROR_STATE_PROJECTION,
                "manifest.dependency_projection does not match replayed event chain",
            )
        # Unique ordered-pair count is independent of append-only event count
        # (reclassifications supersede; D stays the frozen unique-pair count).
        claimed_pair_count = manifest.get("dependency_pair_count")
        if not _is_int(claimed_pair_count):
            raise ProgramStateError(
                ERROR_STATE_PROJECTION,
                "manifest.dependency_pair_count must be an integer",
            )
        if len(projection) != claimed_pair_count:
            raise ProgramStateError(
                ERROR_STATE_PROJECTION,
                "replayed projection row count must equal "
                f"dependency_pair_count ({claimed_pair_count}), got {len(projection)}",
            )
        if len(manifest_projection) != claimed_pair_count:
            raise ProgramStateError(
                ERROR_STATE_PROJECTION,
                "manifest.dependency_projection length must equal dependency_pair_count",
            )

        # Membership must match the frozen pair source advertised by the manifest.
        if manifest.get("dependency_pair_source_sha256") == PAIRS_SOURCE_SHA256:
            repo_root = _find_repo_root_near(state_root)
            frozen_keys = _load_frozen_pair_keys(repo_root)
            replay_keys = {
                (
                    int(row["subject_issue_number"]),
                    int(row["related_issue_number"]),
                    bool(row["related_is_baseline"]),
                )
                for row in projection
            }
            if replay_keys != frozen_keys:
                raise ProgramStateError(
                    ERROR_STATE_PROJECTION,
                    "replayed pair keys/related_is_baseline must equal frozen pair source",
                )

        # Recompute authoritative summary counts from replay.
        unresolved_dep = sum(
            1
            for row in projection
            if row.get("status") in {"unresolved", "blocking"}
        )
        if manifest.get("unresolved_dependency_count") != unresolved_dep:
            raise ProgramStateError(
                ERROR_STATE_PROJECTION,
                "manifest.unresolved_dependency_count must equal "
                f"replayed unresolved/blocking rows ({unresolved_dep})",
            )
        resolved_count = len(terminal_issues)
        if manifest.get("resolved_issue_count") != resolved_count:
            raise ProgramStateError(
                ERROR_STATE_PROJECTION,
                "manifest.resolved_issue_count must equal receipt-derived "
                f"terminal set size ({resolved_count})",
            )
        unresolved_lineage = ISSUE_COUNT - resolved_count
        if manifest.get("unresolved_lineage_count") != unresolved_lineage:
            raise ProgramStateError(
                ERROR_STATE_PROJECTION,
                "manifest.unresolved_lineage_count must equal "
                f"{ISSUE_COUNT}-resolved ({unresolved_lineage})",
            )
    else:
        if manifest.get("dependency_projection") not in ([], None):
            raise ProgramStateError(
                ERROR_STATE_PROJECTION,
                "manifest.dependency_projection must be empty without events",
            )

    # Permanent complete sink requires full eligibility, not structural nulls only.
    if pointer["status"] == "complete":
        terminal_now = _derive_terminal_issues_from_receipts(receipts)
        if terminal_now != frozenset(activation_issue_numbers):
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                "complete requires receipt-derived terminal set to equal "
                "the activation inventory exactly",
            )
        if projection:
            still_open = [
                row
                for row in projection
                if row.get("status") in {"unresolved", "blocking"}
            ]
            if still_open:
                raise ProgramStateError(
                    ERROR_STATE_PROJECTION,
                    "complete forbids unresolved/blocking dependency rows",
                )
        if manifest.get("open_program_authorizations") not in ([], None):
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                "complete forbids open_program_authorizations",
            )
        if pointer.get("owner_token") is not None or pointer.get(
            "active_issue_number"
        ) is not None:
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                "complete pointer must clear owner and active issue",
            )

    # Soft closed-schema transition replay when receipts expose transition fields.
    previous_view: PointerView | None = None
    for _path, receipt in receipts:
        operation = str(receipt.get("operation") or receipt.get("event_type") or "")
        if not operation:
            continue
        from_status = receipt.get("from_status") or receipt.get("previous_status")
        to_status = receipt.get("to_status") or receipt.get("status")
        from_phase = receipt.get("from_phase") or receipt.get("previous_phase")
        to_phase = receipt.get("to_phase") or receipt.get("phase")
        if previous_view is None and from_status in STATUS_ENUM:
            previous_view = PointerView(
                status=str(from_status),
                phase=str(from_phase or "idle"),
                epoch=int(receipt.get("epoch") or 0),
                owner_token=receipt.get("owner_token"),
                owner_identity=receipt.get("owner_identity"),
                active_issue_number=receipt.get("active_issue_number")
                if _is_int(receipt.get("active_issue_number"))
                else None,
                active_pr_ordinal=receipt.get("active_pr_ordinal")
                if _is_int(receipt.get("active_pr_ordinal"))
                else None,
                acceptance_complete=bool(receipt.get("acceptance_complete", False)),
            )
        elif previous_view is not None and from_status in STATUS_ENUM:
            # Claimed source state must match the prior replayed tip.
            if str(from_status) != previous_view.status:
                raise ProgramStateError(
                    ERROR_STATE_SCHEMA,
                    "receipt from_status does not match prior replayed status",
                )
            if from_phase is not None and str(from_phase) != previous_view.phase:
                raise ProgramStateError(
                    ERROR_STATE_SCHEMA,
                    "receipt from_phase does not match prior replayed phase",
                )
        if previous_view is not None and to_status in STATUS_ENUM:
            request = TransitionRequest(
                event_type=operation,
                to_status=str(to_status),
                to_phase=str(to_phase or to_status),
                issue_number=receipt.get("issue_number")
                if _is_int(receipt.get("issue_number"))
                else receipt.get("active_issue_number")
                if _is_int(receipt.get("active_issue_number"))
                else None,
                owner_token=receipt.get("owner_token"),
                owner_identity=receipt.get("owner_identity"),
                epoch=int(receipt["epoch"]) if _is_int(receipt.get("epoch")) else None,
                acceptance_complete=receipt.get("acceptance_complete")
                if isinstance(receipt.get("acceptance_complete"), bool)
                else None,
            )
            try:
                check_forbidden_transition(previous_view, request)
            except ProgramStateError as exc:
                raise ProgramStateError(
                    exc.code,
                    f"receipt transition rejected for {operation}: {exc}",
                ) from exc
            previous_view = PointerView(
                status=str(to_status),
                phase=str(to_phase or to_status),
                epoch=request.epoch if request.epoch is not None else previous_view.epoch,
                owner_token=request.owner_token
                if request.owner_token is not None
                else previous_view.owner_token,
                owner_identity=request.owner_identity
                if request.owner_identity is not None
                else previous_view.owner_identity,
                active_issue_number=request.issue_number
                if request.issue_number is not None
                else previous_view.active_issue_number,
                active_pr_ordinal=previous_view.active_pr_ordinal,
                acceptance_complete=bool(
                    request.acceptance_complete
                    if request.acceptance_complete is not None
                    else previous_view.acceptance_complete
                ),
            )

    # Final replayed receipt tip must match the persisted pointer when replay ran.
    if previous_view is not None:
        if previous_view.status != pointer["status"]:
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                "replayed receipt tip status does not match pointer.status",
            )
        if previous_view.phase != pointer["phase"]:
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                "replayed receipt tip phase does not match pointer.phase",
            )
        if previous_view.epoch != pointer["epoch"]:
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                "replayed receipt tip epoch does not match pointer.epoch",
            )
        if previous_view.owner_token != pointer.get("owner_token"):
            raise ProgramStateError(
                ERROR_OWNER_MISMATCH,
                "replayed receipt tip owner_token does not match pointer",
            )
        if previous_view.active_issue_number != pointer.get("active_issue_number"):
            raise ProgramStateError(
                ERROR_STATE_SCHEMA,
                "replayed receipt tip active_issue_number does not match pointer",
            )

    # Per-pair supersession: non-bootstrap events for a pair must keep dependency_id
    # and must name the previous pair-tip hash.
    latest_by_pair: dict[tuple[int, int], dict[str, Any]] = {}
    for _path, event in dep_events:
        key = (
            int(event["subject_issue_number"]),
            int(event["related_issue_number"]),
        )
        dep_id = str(event["dependency_id"])
        prev = latest_by_pair.get(key)
        if prev is None:
            if event.get("supersedes_event_sha256") not in (None, ""):
                raise ProgramStateError(
                    ERROR_STATE_SCHEMA,
                    "first event for a pair must not supersede another event",
                )
        else:
            if dep_id != str(prev["dependency_id"]):
                raise ProgramStateError(
                    ERROR_STATE_SCHEMA,
                    "dependency_id is immutable per ordered pair across updates",
                )
            supersedes = event.get("supersedes_event_sha256") or event.get(
                "previous_pair_event_sha256"
            )
            if supersedes != prev.get("event_sha256"):
                raise ProgramStateError(
                    ERROR_STATE_HASH,
                    "dependency update must supersede the current pair-tip event hash",
                )
        latest_by_pair[key] = dict(event)

    return {
        "ok": True,
        "mode": "state-root",
        "state_root": str(state_root),
        "pointer_status": pointer["status"],
        "pointer_phase": pointer["phase"],
        "state_sequence": pointer["state_sequence"],
        "receipt_count": len(receipts),
        "dependency_event_count": len(dep_events),
        "evidence_count": len(evidence),
        "projection_rows": len(projection),
        "manifest_sha256": manifest["manifest_sha256"],
        "pointer_sha256": pointer["pointer_sha256"],
    }


# ---------------------------------------------------------------------------
# Synthetic self-checks (default CLI mode)
# ---------------------------------------------------------------------------


def _synthetic_pointer(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "program_id": PROGRAM_ID,
        "state_sequence": 1,
        "epoch": 0,
        "status": "idle",
        "phase": "idle",
        "owner_token": None,
        "owner_identity": None,
        "active_issue_number": None,
        "active_pr_ordinal": None,
        "active_branch": None,
        "active_authorization_id": None,
        "active_pr_number": None,
        "active_pr_node_id": None,
        "active_pr_url": None,
        "active_initial_head_sha": None,
        "completed_pr_receipt_sha256s": [],
        "blocked_reason": None,
        "blocked_from_status": None,
        "blocked_from_phase": None,
        "last_receipt_sequence": 1,
        "last_receipt_sha256": "a" * 64,
        "state_parent_oid": "b" * 40,
        "updated_at": "2026-07-28T00:00:00Z",
        "pointer_sha256": "",
    }
    base.update(overrides)
    base["pointer_sha256"] = self_hash(base, "pointer_sha256")
    return base


def run_self_checks() -> dict[str, Any]:
    checks: list[str] = []

    # Canonical + self-hash round trip
    sample = {"b": 2, "a": 1, "self": ""}
    sample["self"] = self_hash(sample, "self")
    assert sample["self"] == sha256_hex(
        canonical_bytes({"a": 1, "b": 2})
    ), "self-hash excludes only named field"
    assert persisted_file_bytes({"x": 1}).endswith(b"\n")
    assert not persisted_file_bytes({"x": 1})[:-1].endswith(b"\n")
    checks.append("canonical_self_hash")

    # Strict JSON rejects duplicates / non-finite
    try:
        strict_loads('{"a":1,"a":2}')
        raise AssertionError("duplicate keys should fail")
    except ProgramStateError as exc:
        assert exc.code == ERROR_STATE_SCHEMA
    try:
        strict_loads('{"a":Infinity}')
        raise AssertionError("Infinity should fail")
    except ProgramStateError as exc:
        assert exc.code == ERROR_STATE_SCHEMA
    checks.append("strict_json")

    # UUIDv4
    good = "123e4567-e89b-42d3-a456-426614174000"
    # Force variant bits: use uuid4
    good = str(uuid.uuid4())
    assert is_uuid_v4(good)
    assert not is_uuid_v4("not-a-uuid")
    assert not is_uuid_v4("123e4567-e89b-12d3-a456-426614174000")  # version 1
    assert not is_uuid_v4("123e4567-e89b-42d3-c456-426614174000")  # bad variant
    try:
        require_uuid_v4("zzzzzzzz-zzzz-4zzz-azzz-zzzzzzzzzzzz", label="id")
        raise AssertionError("bad uuid accepted")
    except ProgramStateError as exc:
        assert exc.code == ERROR_STATE_ID
    checks.append("uuid_v4")

    # Sequence formatting
    assert format_sequence_prefix(1) == "0" * 19 + "1"
    assert format_sequence_prefix(212) == "0" * 17 + "212"
    validate_sequence_chain([1, 2, 3], label="test")
    try:
        validate_sequence_chain([1, 3], label="test")
        raise AssertionError("gap should fail")
    except ProgramStateError as exc:
        assert exc.code == ERROR_STATE_SEQUENCE
    try:
        validate_sequence_chain([2, 3], label="test")
        raise AssertionError("start!=1 should fail")
    except ProgramStateError as exc:
        assert exc.code == ERROR_STATE_SEQUENCE
    checks.append("sequence_rules")

    # Pointer schema
    idle = _synthetic_pointer()
    validate_pointer(idle)
    owned = _synthetic_pointer(
        status="owned",
        phase="selected",
        epoch=1,
        owner_token="tok",
        owner_identity="alice",
        active_issue_number=12,
        active_pr_ordinal=1,
        active_branch="issue-12/pr-1",
        state_sequence=2,
        last_receipt_sequence=2,
    )
    validate_pointer(owned)
    checks.append("pointer_schema")

    # Activation / manifest shape constants
    order_entries = []
    for ordinal, issue in enumerate(
        [
            12,
            13,
            62,
            68,
            61,
            17,
            63,
            35,
            28,
            26,
            29,
            10,
            16,
            36,
            38,
            69,
            67,
            66,
            65,
            48,
            47,
            46,
            45,
            44,
            43,
            42,
            41,
            40,
            39,
            37,
            34,
            33,
            32,
            30,
            27,
            25,
            24,
            23,
            22,
            19,
            18,
            15,
            8,
            7,
        ],
        start=1,
    ):
        wave = 1 if ordinal <= 2 else 2 if ordinal <= 11 else 3 if ordinal <= 15 else 4
        order_entries.append(
            {
                "issue_number": issue,
                "issue_node_id": f"I_{issue}",
                "wave_number": wave,
                "ledger_ordinal": ordinal,
                "selection_wave_number": wave,
            }
        )
    activation = {
        "snapshot_at": ACTIVATION_SNAPSHOT_AT,
        "main_sha": ACTIVATION_MAIN_SHA,
        "issue_count": ISSUE_COUNT,
        "issue_numbers": sorted(entry["issue_number"] for entry in order_entries),
        "issue_order": order_entries,
        "issue_order_source_path": ORDER_SOURCE_PATH,
        "issue_order_source_sha256": ORDER_SOURCE_SHA256,
        "baseline_manifest_sha256": BASELINE_MANIFEST_SHA256,
        "anchor_commit_oid": "c" * 40,
        "anchor_tree_oid": "d" * 40,
        "anchor_inventory_sha256": "e" * 64,
        "anchor_evidence_ref": {
            "evidence_id": str(uuid.uuid4()),
            "evidence_type": "wave0-full-tree",
            "schema_version": 1,
            "record_sha256": "f" * 64,
        },
    }
    validate_activation_block(activation)
    checks.append("activation_block")

    # Forbidden transitions
    owned_view = PointerView(
        status="owned",
        phase="selected",
        epoch=1,
        owner_token="tok",
        owner_identity="alice",
        active_issue_number=12,
        active_pr_ordinal=1,
        acceptance_complete=False,
    )
    try:
        check_forbidden_transition(
            owned_view,
            TransitionRequest(
                event_type="program-completed",
                to_status="complete",
                to_phase="complete",
            ),
        )
        raise AssertionError("owned -> complete must fail")
    except ProgramStateError as exc:
        assert "owned -> complete" in exc.message

    complete_view = PointerView(
        status="complete",
        phase="complete",
        epoch=1,
        owner_token=None,
        owner_identity=None,
        active_issue_number=None,
        active_pr_ordinal=None,
        acceptance_complete=True,
    )
    try:
        check_forbidden_transition(
            complete_view,
            TransitionRequest(
                event_type="issue-acquired",
                to_status="owned",
                to_phase="selected",
                issue_number=13,
            ),
        )
        raise AssertionError("acquire after complete must fail")
    except ProgramStateError as exc:
        assert exc.code == ERROR_PROGRAM_COMPLETE

    try:
        check_forbidden_transition(
            owned_view,
            TransitionRequest(
                event_type="pr-checkpointed",
                to_status="owned",
                to_phase="selected",
                issue_number=99,
                owner_token="tok",
                owner_identity="alice",
                epoch=1,
            ),
        )
        raise AssertionError("issue change on continuation must fail")
    except ProgramStateError as exc:
        assert exc.code == ERROR_OWNER_MISMATCH

    try:
        check_forbidden_transition(
            owned_view,
            TransitionRequest(
                event_type="pr-checkpointed",
                to_status="owned",
                to_phase="selected",
                issue_number=12,
                owner_token="other",
                owner_identity="alice",
                epoch=1,
            ),
        )
        raise AssertionError("owner change must fail")
    except ProgramStateError as exc:
        assert exc.code == ERROR_OWNER_MISMATCH

    try:
        check_forbidden_transition(
            owned_view,
            TransitionRequest(
                event_type="pr-checkpointed",
                to_status="owned",
                to_phase="selected",
                issue_number=12,
                owner_token="tok",
                owner_identity="alice",
                epoch=2,
            ),
        )
        raise AssertionError("epoch change must fail")
    except ProgramStateError as exc:
        assert exc.code == ERROR_EPOCH_MISMATCH

    try:
        check_forbidden_transition(
            owned_view,
            TransitionRequest(
                event_type="issue-released",
                to_status="idle",
                to_phase="idle",
                acceptance_complete=False,
            ),
        )
        raise AssertionError("release incomplete must fail")
    except ProgramStateError as exc:
        assert exc.code == ERROR_ACCEPTANCE_INCOMPLETE

    # Legal continuation (no raise)
    check_forbidden_transition(
        owned_view,
        TransitionRequest(
            event_type="pr-checkpointed",
            to_status="owned",
            to_phase="selected",
            issue_number=12,
            owner_token="tok",
            owner_identity="alice",
            epoch=1,
        ),
    )
    checks.append("forbidden_transitions")

    # Zero-outgoing pairs: no sentinel
    dep_a = str(uuid.uuid4())
    pairs = [
        PairSpec(
            subject_issue_number=12,
            related_issue_number=10,
            related_is_baseline=True,
            dependency_id=dep_a,
            classification="unknown",
        )
    ]
    projection = build_dependency_projection(pairs)
    assert len(projection) == 1
    assert projection[0]["status"] == "unresolved"
    zero = issues_with_zero_outgoing_pairs([12, 13, 10], pairs)
    assert zero == [10, 13]
    # Building projection for only declared pairs never invents rows for 13.
    assert all(row["subject_issue_number"] != 13 for row in projection)
    checks.append("no_sentinel_zero_pair")

    # Selection key order
    cands = [
        SelectionCandidate(issue_number=20, selection_wave_number=2, ledger_ordinal=5),
        SelectionCandidate(issue_number=10, selection_wave_number=1, ledger_ordinal=9),
        SelectionCandidate(issue_number=11, selection_wave_number=1, ledger_ordinal=2),
        SelectionCandidate(issue_number=12, selection_wave_number=1, ledger_ordinal=2),
    ]
    chosen = select_minimum_eligible(cands)
    assert chosen is not None
    assert chosen.issue_number == 11  # wave 1, ordinal 2, lower issue than 12
    assert selection_key(chosen) == (1, 2, 11)
    checks.append("selection_key")

    # Filename parsing
    op = str(uuid.uuid4())
    name = f"{format_sequence_prefix(7)}-{op}.json"
    seq, parsed_id = parse_sequenced_filename(name)
    assert seq == 7 and parsed_id == op
    checks.append("filename_sequence")

    return {
        "ok": True,
        "mode": "self-check",
        "program_id": PROGRAM_ID,
        "checks": checks,
        "check_count": len(checks),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate program-state schemas and transition guards."
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=None,
        help="Path to state/ directory (pointer.json, manifest.json, ...)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.state_root is not None:
            summary = validate_state_root(args.state_root.resolve())
        else:
            summary = run_self_checks()
    except ProgramStateError as exc:
        print(
            json.dumps(
                {"ok": False, "error_code": exc.code, "error": exc.message},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    except AssertionError as exc:
        print(
            json.dumps(
                {"ok": False, "error_code": "E_SELF_CHECK", "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    except OSError as exc:
        print(
            json.dumps(
                {"ok": False, "error_code": "E_IO", "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
