#!/usr/bin/env python3
"""Validate the Wave 0 tracked activation baseline, order, pairs, and ledger.

stdlib-only. From a clean checkout, verify raw-byte and canonical self-hashes,
strict JSON rules, 44 unique records with nested hashes, order/pairs integrity,
and optional byte-identity against planning copies under .omx/plans/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PROGRAM_ID = "all-open-issues-sequential-prs-20260728"
ISSUE_COUNT = 44
PAIR_COUNT = 212

TRACKED_DIR = Path("plans/all-open-issues-sequential-prs")
JSONL_REL = TRACKED_DIR / "activation-baseline-20260728.jsonl"
MANIFEST_REL = TRACKED_DIR / "activation-baseline-20260728.manifest.json"
PAIRS_REL = TRACKED_DIR / "activation-dependency-pairs-20260728.json"
ORDER_REL = TRACKED_DIR / "activation-order-20260728.json"
LEDGER_REL = TRACKED_DIR / "activation-issue-ledger-20260728.md"

PLANNING_DIR = Path(".omx/plans")
PLANNING_JSONL = PLANNING_DIR / "activation-baseline-20260728.jsonl"
PLANNING_MANIFEST = PLANNING_DIR / "activation-baseline-20260728.manifest.json"
PLANNING_PAIRS = PLANNING_DIR / "activation-dependency-pairs-20260728.json"
PLANNING_ORDER = PLANNING_DIR / "activation-order-20260728.json"
PLANNING_LEDGER = PLANNING_DIR / "activation-issue-ledger-20260728.md"

EXPECTED_JSONL_SHA256 = (
    "015bc85de1fdcdbfa2b2cc0f7d4b175cbc51cd99b97589dbc95f4c02b269d3aa"
)
EXPECTED_MANIFEST_SHA256 = (
    "72af3d77babab06250bb6682bf9c649e2021e68bc86db4cf9af690476fe6b303"
)
EXPECTED_MANIFEST_RAW_SHA256 = (
    "6b8b460581729929d87931d6640b9c9c71508cacba26541e13eab0e8b4612eec"
)
EXPECTED_PAIRS_SHA256 = (
    "341592eeb1b7bbacd3ff28c8db7073da1042c92cf75e1a474f512cc71268ec3f"
)
EXPECTED_ORDER_SHA256 = (
    "c0d171be7406c7cae1475e40c51cbbc0ba4c913e4217507ce8decdecb806f36d"
)
EXPECTED_LEDGER_SHA256 = (
    "d9543e78de5b2c38bd1b67251f59f464723a98c3f37b2492f9e138c8302cb651"
)

EXPECTED_ORDER_ISSUE_SEQUENCE = [
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

EXPECTED_WAVE_BY_ISSUE: dict[int, int] = {}
_wave_lists = {
    1: [12, 13],
    2: [62, 68, 61, 17, 63, 35, 28, 26, 29],
    3: [10, 16, 36, 38],
    4: [
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
}
for _wave, _issues in _wave_lists.items():
    for _issue in _issues:
        EXPECTED_WAVE_BY_ISSUE[_issue] = _wave

REQUIRED_RECORD_FIELDS = frozenset(
    {
        "schema_version",
        "program_id",
        "snapshot_at",
        "activation_main_sha",
        "issue_number",
        "issue_url",
        "title",
        "activation_state",
        "labels",
        "author",
        "assignees",
        "milestone",
        "created_at",
        "activation_updated_at",
        "enrichment_updated_at",
        "fetched_at",
        "provenance",
        "body_normalization",
        "body_source_sha256",
        "body_normalized",
        "body_normalized_sha256",
        "acceptance_source",
        "acceptance_contract_normalized",
        "acceptance_contract_sha256",
        "acceptance_sections_index",
        "acceptance_sections_index_sha256",
        "acceptance_status",
        "dependency_classification",
        "record_sha256",
    }
)

SHA256_HEX = frozenset("0123456789abcdef")


class ValidationError(Exception):
    """Collected validation failure with an error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def detect_repo_root(start: Path | None = None) -> Path:
    """Locate repository root from an explicit path, this file, or CWD markers."""
    if start is not None:
        candidate = start.resolve()
        if (candidate / "plans").is_dir() and (candidate / "scripts").is_dir():
            return candidate
        raise ValidationError(
            "E_REPO_ROOT",
            f"--repo does not look like a portable-resume-skills root: {candidate}",
        )

    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        if (parent / JSONL_REL).is_file() and (parent / "scripts").is_dir():
            return parent
        if (parent / "Agents.md").is_file() and (parent / "scripts").is_dir():
            return parent
    cwd = Path.cwd().resolve()
    if (cwd / JSONL_REL).is_file():
        return cwd
    raise ValidationError("E_REPO_ROOT", "could not locate repository root")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: object) -> bytes:
    """Canonical UTF-8 JSON: sorted keys, compact separators, no BOM/trailing NL."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("E_JSON_DUPLICATE_KEY", f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def reject_nonfinite(token: str) -> Any:
    raise ValidationError("E_JSON_NONFINITE", f"non-finite JSON number: {token}")


def strict_loads(text: str) -> Any:
    return json.loads(
        text,
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_nonfinite,
    )


def is_sha256_hex(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in SHA256_HEX for ch in value)
    )


def require_file(path: Path, code: str = "E_PATH_MISSING") -> bytes:
    if not path.is_file():
        raise ValidationError(code, f"required file missing: {path}")
    return path.read_bytes()


def validate_record(record: Any, *, line_no: int) -> int:
    if not isinstance(record, dict):
        raise ValidationError(
            "E_RECORD_TYPE",
            f"JSONL line {line_no}: expected object, got {type(record).__name__}",
        )
    missing = sorted(REQUIRED_RECORD_FIELDS - set(record))
    if missing:
        raise ValidationError(
            "E_RECORD_FIELDS",
            f"JSONL line {line_no}: missing fields {missing}",
        )

    issue_number = record["issue_number"]
    if type(issue_number) is not int or isinstance(issue_number, bool):
        raise ValidationError(
            "E_RECORD_ISSUE",
            f"JSONL line {line_no}: issue_number must be a JSON integer",
        )
    if record.get("program_id") != PROGRAM_ID:
        raise ValidationError(
            "E_RECORD_PROGRAM",
            f"JSONL line {line_no}/#{issue_number}: program_id mismatch",
        )
    if record.get("schema_version") != 1:
        raise ValidationError(
            "E_RECORD_SCHEMA",
            f"JSONL line {line_no}/#{issue_number}: schema_version must be 1",
        )

    body_normalized = record["body_normalized"]
    acceptance = record["acceptance_contract_normalized"]
    if not isinstance(body_normalized, str) or not isinstance(acceptance, str):
        raise ValidationError(
            "E_RECORD_BODY",
            f"JSONL line {line_no}/#{issue_number}: body fields must be strings",
        )
    if body_normalized != acceptance:
        raise ValidationError(
            "E_RECORD_BODY",
            f"JSONL line {line_no}/#{issue_number}: "
            "body_normalized must equal acceptance_contract_normalized",
        )
    if "\r" in body_normalized:
        raise ValidationError(
            "E_RECORD_BODY",
            f"JSONL line {line_no}/#{issue_number}: normalized body still contains CR",
        )

    body_norm_digest = sha256_bytes(body_normalized.encode("utf-8"))
    if record["body_normalized_sha256"] != body_norm_digest:
        raise ValidationError(
            "E_RECORD_HASH",
            f"JSONL line {line_no}/#{issue_number}: body_normalized_sha256 mismatch",
        )
    if record["acceptance_contract_sha256"] != body_norm_digest:
        raise ValidationError(
            "E_RECORD_HASH",
            f"JSONL line {line_no}/#{issue_number}: acceptance_contract_sha256 mismatch",
        )
    if not is_sha256_hex(record["body_source_sha256"]):
        raise ValidationError(
            "E_RECORD_HASH",
            f"JSONL line {line_no}/#{issue_number}: body_source_sha256 is not sha256 hex",
        )

    sections = record["acceptance_sections_index"]
    if not isinstance(sections, list):
        raise ValidationError(
            "E_RECORD_SECTIONS",
            f"JSONL line {line_no}/#{issue_number}: acceptance_sections_index must be list",
        )
    sections_digest = sha256_bytes(canonical_bytes(sections))
    if record["acceptance_sections_index_sha256"] != sections_digest:
        raise ValidationError(
            "E_RECORD_HASH",
            f"JSONL line {line_no}/#{issue_number}: "
            "acceptance_sections_index_sha256 mismatch",
        )

    recorded = record["record_sha256"]
    if not is_sha256_hex(recorded):
        raise ValidationError(
            "E_RECORD_HASH",
            f"JSONL line {line_no}/#{issue_number}: record_sha256 is not sha256 hex",
        )
    without_hash = {key: value for key, value in record.items() if key != "record_sha256"}
    computed = sha256_bytes(canonical_bytes(without_hash))
    if recorded != computed:
        raise ValidationError(
            "E_RECORD_HASH",
            f"JSONL line {line_no}/#{issue_number}: record_sha256 mismatch "
            f"(got {recorded}, expected {computed})",
        )
    return issue_number


def validate_jsonl(path: Path) -> tuple[list[dict[str, Any]], set[int], str]:
    raw = require_file(path)
    digest = sha256_bytes(raw)
    if digest != EXPECTED_JSONL_SHA256:
        raise ValidationError(
            "E_JSONL_SHA256",
            f"JSONL raw sha256 mismatch: got {digest}, expected {EXPECTED_JSONL_SHA256}",
        )
    text = raw.decode("utf-8")
    if text.startswith("\ufeff"):
        raise ValidationError("E_JSONL_BOM", "JSONL must not have a UTF-8 BOM")
    lines = text.splitlines()
    if not lines:
        raise ValidationError("E_JSONL_EMPTY", "JSONL has no records")
    # Preserve final-newline state: raw file should end with newline for each record.
    if not raw.endswith(b"\n"):
        raise ValidationError(
            "E_JSONL_NEWLINE",
            "JSONL must end with a trailing newline after the last record",
        )

    records: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            raise ValidationError("E_JSONL_BLANK", f"JSONL line {index}: blank line")
        obj = strict_loads(line)
        issue_number = validate_record(obj, line_no=index)
        if issue_number in seen:
            raise ValidationError(
                "E_JSONL_DUP_ISSUE",
                f"JSONL line {index}: duplicate issue_number {issue_number}",
            )
        seen.add(issue_number)
        records.append(obj)

    if len(records) != ISSUE_COUNT:
        raise ValidationError(
            "E_JSONL_COUNT",
            f"JSONL record count {len(records)} != {ISSUE_COUNT}",
        )
    return records, seen, digest


def validate_manifest(path: Path, issue_numbers: set[int]) -> tuple[dict[str, Any], str, str]:
    raw = require_file(path)
    raw_digest = sha256_bytes(raw)
    if raw_digest != EXPECTED_MANIFEST_RAW_SHA256:
        raise ValidationError(
            "E_MANIFEST_RAW_SHA256",
            f"manifest raw sha256 mismatch: got {raw_digest}, "
            f"expected {EXPECTED_MANIFEST_RAW_SHA256}",
        )
    text = raw.decode("utf-8")
    if text.startswith("\ufeff"):
        raise ValidationError("E_MANIFEST_BOM", "manifest must not have a UTF-8 BOM")
    manifest = strict_loads(text)
    if not isinstance(manifest, dict):
        raise ValidationError("E_MANIFEST_TYPE", "manifest root must be a JSON object")

    if manifest.get("program_id") != PROGRAM_ID:
        raise ValidationError("E_MANIFEST_PROGRAM", "manifest program_id mismatch")
    if manifest.get("issue_count") != ISSUE_COUNT:
        raise ValidationError(
            "E_MANIFEST_COUNT",
            f"manifest issue_count {manifest.get('issue_count')!r} != {ISSUE_COUNT}",
        )
    if manifest.get("jsonl_sha256") != EXPECTED_JSONL_SHA256:
        raise ValidationError(
            "E_MANIFEST_JSONL_SHA",
            "manifest jsonl_sha256 does not match expected JSONL raw hash",
        )

    listed = manifest.get("issue_numbers")
    if not isinstance(listed, list) or len(listed) != ISSUE_COUNT:
        raise ValidationError(
            "E_MANIFEST_ISSUES",
            "manifest issue_numbers must be a list of length 44",
        )
    listed_set: set[int] = set()
    for value in listed:
        if type(value) is not int or isinstance(value, bool):
            raise ValidationError(
                "E_MANIFEST_ISSUES",
                "manifest issue_numbers must contain only integers",
            )
        if value in listed_set:
            raise ValidationError(
                "E_MANIFEST_ISSUES",
                f"manifest issue_numbers has duplicate {value}",
            )
        listed_set.add(value)
    if listed_set != issue_numbers:
        raise ValidationError(
            "E_MANIFEST_ISSUES",
            "manifest issue_numbers set does not match JSONL issue set",
        )

    recorded = manifest.get("manifest_sha256")
    if not is_sha256_hex(recorded):
        raise ValidationError("E_MANIFEST_HASH", "manifest_sha256 missing or invalid")
    without = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    computed = sha256_bytes(canonical_bytes(without))
    if recorded != computed:
        raise ValidationError(
            "E_MANIFEST_HASH",
            f"manifest_sha256 mismatch: got {recorded}, expected {computed}",
        )
    if recorded != EXPECTED_MANIFEST_SHA256:
        raise ValidationError(
            "E_MANIFEST_HASH",
            f"manifest_sha256 {recorded} != pinned {EXPECTED_MANIFEST_SHA256}",
        )
    if computed == raw_digest:
        raise ValidationError(
            "E_MANIFEST_HASH",
            "canonical self-hash unexpectedly equals raw file hash",
        )
    if manifest.get("manifest_raw_file_sha256_equals_manifest_sha256") is not False:
        raise ValidationError(
            "E_MANIFEST_META",
            "manifest_raw_file_sha256_equals_manifest_sha256 must be false",
        )
    return manifest, computed, raw_digest


def validate_order(path: Path, baseline_issues: set[int]) -> tuple[dict[str, Any], str]:
    raw = require_file(path)
    digest = sha256_bytes(raw)
    if digest != EXPECTED_ORDER_SHA256:
        raise ValidationError(
            "E_ORDER_SHA256",
            f"order raw sha256 mismatch: got {digest}, expected {EXPECTED_ORDER_SHA256}",
        )
    payload = strict_loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValidationError("E_ORDER_TYPE", "order payload must be an object")
    if payload.get("program_id") != PROGRAM_ID:
        raise ValidationError("E_ORDER_PROGRAM", "order program_id mismatch")
    if payload.get("baseline_issue_count") != ISSUE_COUNT:
        raise ValidationError(
            "E_ORDER_COUNT",
            f"order baseline_issue_count {payload.get('baseline_issue_count')!r} "
            f"!= {ISSUE_COUNT}",
        )
    entries = payload.get("entries")
    if not isinstance(entries, list) or len(entries) != ISSUE_COUNT:
        raise ValidationError(
            "E_ORDER_ENTRIES",
            f"order entries must be a list of length {ISSUE_COUNT}",
        )

    seen_issues: set[int] = set()
    seen_ordinals: set[int] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValidationError(
                "E_ORDER_ENTRY",
                f"order entry {index} must be an object",
            )
        for key in ("issue_number", "ledger_ordinal", "wave_number"):
            if key not in entry:
                raise ValidationError(
                    "E_ORDER_ENTRY",
                    f"order entry {index} missing {key}",
                )
            if type(entry[key]) is not int or isinstance(entry[key], bool):
                raise ValidationError(
                    "E_ORDER_ENTRY",
                    f"order entry {index} field {key} must be an integer",
                )
        issue = entry["issue_number"]
        ordinal = entry["ledger_ordinal"]
        wave = entry["wave_number"]
        if issue in seen_issues:
            raise ValidationError(
                "E_ORDER_DUP",
                f"order has duplicate issue_number {issue}",
            )
        seen_issues.add(issue)
        if ordinal in seen_ordinals:
            raise ValidationError(
                "E_ORDER_DUP",
                f"order has duplicate ledger_ordinal {ordinal}",
            )
        seen_ordinals.add(ordinal)
        if ordinal != index + 1:
            raise ValidationError(
                "E_ORDER_ORDINAL",
                f"order entry {index}: ledger_ordinal {ordinal} != {index + 1}",
            )
        if issue != EXPECTED_ORDER_ISSUE_SEQUENCE[index]:
            raise ValidationError(
                "E_ORDER_SEQUENCE",
                f"order entry {index}: issue {issue} != expected "
                f"{EXPECTED_ORDER_ISSUE_SEQUENCE[index]}",
            )
        expected_wave = EXPECTED_WAVE_BY_ISSUE[issue]
        if wave != expected_wave:
            raise ValidationError(
                "E_ORDER_WAVE",
                f"order entry issue {issue}: wave_number {wave} != {expected_wave}",
            )

    if seen_issues != baseline_issues:
        raise ValidationError(
            "E_ORDER_ISSUES",
            "order issue set does not equal baseline JSONL issue set",
        )
    if seen_ordinals != set(range(1, ISSUE_COUNT + 1)):
        raise ValidationError(
            "E_ORDER_ORDINAL",
            "order ledger_ordinal values must be exactly 1..44",
        )
    return payload, digest


def validate_pairs(path: Path, baseline_issues: set[int]) -> tuple[dict[str, Any], str]:
    raw = require_file(path)
    digest = sha256_bytes(raw)
    if digest != EXPECTED_PAIRS_SHA256:
        raise ValidationError(
            "E_PAIRS_SHA256",
            f"pairs raw sha256 mismatch: got {digest}, expected {EXPECTED_PAIRS_SHA256}",
        )
    payload = strict_loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValidationError("E_PAIRS_TYPE", "pairs payload must be an object")
    if payload.get("program_id") != PROGRAM_ID:
        raise ValidationError("E_PAIRS_PROGRAM", "pairs program_id mismatch")
    if payload.get("baseline_issue_count") != ISSUE_COUNT:
        raise ValidationError(
            "E_PAIRS_BASELINE_COUNT",
            f"pairs baseline_issue_count {payload.get('baseline_issue_count')!r} "
            f"!= {ISSUE_COUNT}",
        )
    if payload.get("pair_count") != PAIR_COUNT:
        raise ValidationError(
            "E_PAIRS_COUNT",
            f"pairs pair_count {payload.get('pair_count')!r} != {PAIR_COUNT}",
        )
    pairs = payload.get("pairs")
    if not isinstance(pairs, list):
        raise ValidationError("E_PAIRS_LIST", "pairs.pairs must be a list")
    if len(pairs) != PAIR_COUNT or payload["pair_count"] != len(pairs):
        raise ValidationError(
            "E_PAIRS_COUNT",
            f"pair_count/len(pairs) mismatch: "
            f"pair_count={payload.get('pair_count')}, len={len(pairs)}",
        )

    seen_keys: set[tuple[int, int]] = set()
    ordered_keys: list[tuple[int, int]] = []
    for index, pair in enumerate(pairs):
        if not isinstance(pair, dict):
            raise ValidationError("E_PAIRS_ITEM", f"pair {index} must be an object")
        required = {
            "subject_issue_number",
            "related_issue_number",
            "related_is_baseline",
        }
        missing = sorted(required - set(pair))
        if missing:
            raise ValidationError(
                "E_PAIRS_ITEM",
                f"pair {index} missing fields {missing}",
            )
        subject = pair["subject_issue_number"]
        related = pair["related_issue_number"]
        related_flag = pair["related_is_baseline"]
        if type(subject) is not int or isinstance(subject, bool):
            raise ValidationError(
                "E_PAIRS_ITEM",
                f"pair {index}: subject_issue_number must be int",
            )
        if type(related) is not int or isinstance(related, bool):
            raise ValidationError(
                "E_PAIRS_ITEM",
                f"pair {index}: related_issue_number must be int",
            )
        if not isinstance(related_flag, bool):
            raise ValidationError(
                "E_PAIRS_ITEM",
                f"pair {index}: related_is_baseline must be bool",
            )
        if subject not in baseline_issues:
            raise ValidationError(
                "E_PAIRS_SUBJECT",
                f"pair {index}: subject {subject} not in baseline",
            )
        if subject == related:
            raise ValidationError(
                "E_PAIRS_SELF",
                f"pair {index}: self-pair subject=related={subject}",
            )
        expected_flag = related in baseline_issues
        if related_flag is not expected_flag:
            raise ValidationError(
                "E_PAIRS_FLAG",
                f"pair {index}: related_is_baseline {related_flag} "
                f"!= expected {expected_flag}",
            )
        key = (subject, related)
        if key in seen_keys:
            raise ValidationError(
                "E_PAIRS_DUP",
                f"pair {index}: duplicate ordered pair {key}",
            )
        seen_keys.add(key)
        ordered_keys.append(key)

    if ordered_keys != sorted(ordered_keys):
        raise ValidationError(
            "E_PAIRS_SORT",
            "pairs must be sorted by (subject_issue_number, related_issue_number)",
        )
    return payload, digest


def validate_ledger(path: Path) -> str:
    raw = require_file(path)
    digest = sha256_bytes(raw)
    if digest != EXPECTED_LEDGER_SHA256:
        raise ValidationError(
            "E_LEDGER_SHA256",
            f"ledger raw sha256 mismatch: got {digest}, expected {EXPECTED_LEDGER_SHA256}",
        )
    return digest


def optional_planning_byte_compare(repo: Path) -> list[dict[str, Any]]:
    """Byte-compare planning copies when present; skip with note when missing."""
    notes: list[dict[str, Any]] = []
    pairs = [
        (JSONL_REL, PLANNING_JSONL),
        (MANIFEST_REL, PLANNING_MANIFEST),
        (PAIRS_REL, PLANNING_PAIRS),
        (ORDER_REL, PLANNING_ORDER),
        (LEDGER_REL, PLANNING_LEDGER),
    ]
    for tracked_rel, planning_rel in pairs:
        tracked = repo / tracked_rel
        planning = repo / planning_rel
        if not planning.is_file():
            notes.append(
                {
                    "path": str(planning_rel),
                    "status": "skipped",
                    "note": "planning copy absent; tracked path is authority",
                }
            )
            continue
        tracked_bytes = tracked.read_bytes()
        planning_bytes = planning.read_bytes()
        if tracked_bytes != planning_bytes:
            raise ValidationError(
                "E_PLANNING_MISMATCH",
                f"planning copy differs from tracked: {planning_rel} vs {tracked_rel}",
            )
        notes.append(
            {
                "path": str(planning_rel),
                "status": "byte-identical",
                "tracked": str(tracked_rel),
            }
        )
    return notes


def validate_activation_baseline(repo: Path) -> dict[str, Any]:
    records, issues, jsonl_sha = validate_jsonl(repo / JSONL_REL)
    manifest, manifest_sha, manifest_raw_sha = validate_manifest(
        repo / MANIFEST_REL,
        issues,
    )
    order_payload, order_sha = validate_order(repo / ORDER_REL, issues)
    pairs_payload, pairs_sha = validate_pairs(repo / PAIRS_REL, issues)
    ledger_sha = validate_ledger(repo / LEDGER_REL)
    planning_notes = optional_planning_byte_compare(repo)

    return {
        "ok": True,
        "program_id": PROGRAM_ID,
        "repo": str(repo),
        "issue_count": len(records),
        "issue_numbers": sorted(issues),
        "jsonl_sha256": jsonl_sha,
        "manifest_sha256": manifest_sha,
        "manifest_raw_sha256": manifest_raw_sha,
        "order_sha256": order_sha,
        "order_entry_count": len(order_payload["entries"]),
        "pairs_sha256": pairs_sha,
        "pair_count": pairs_payload["pair_count"],
        "ledger_sha256": ledger_sha,
        "planning_comparisons": planning_notes,
        "paths": {
            "jsonl": str(JSONL_REL),
            "manifest": str(MANIFEST_REL),
            "order": str(ORDER_REL),
            "pairs": str(PAIRS_REL),
            "ledger": str(LEDGER_REL),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate tracked activation baseline artifacts for Wave 0."
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Repository root (default: detect from this script / CWD)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        repo = detect_repo_root(args.repo)
        summary = validate_activation_baseline(repo)
    except ValidationError as exc:
        print(
            json.dumps(
                {"ok": False, "error_code": exc.code, "error": exc.message},
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
