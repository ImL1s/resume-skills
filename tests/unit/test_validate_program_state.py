from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "validate_program_state.py"


def load_validator_module():
    # Register before exec so @dataclass can resolve annotations via sys.modules.
    name = "validate_program_state"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


class ValidateProgramStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_validator_module()

    def test_cli_self_check_ok(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["mode"], "self-check")
        self.assertIn("forbidden_transitions", payload["checks"])
        self.assertIn("no_sentinel_zero_pair", payload["checks"])

    def test_canonical_self_hash_excludes_only_named_field(self) -> None:
        record = {"z": 3, "a": 1, "marker": ""}
        record["marker"] = self.mod.self_hash(record, "marker")
        expected = self.mod.sha256_hex(self.mod.canonical_bytes({"a": 1, "z": 3}))
        self.assertEqual(record["marker"], expected)
        # LF is part of persisted bytes but not of the hash input.
        persisted = self.mod.persisted_file_bytes(record)
        self.assertTrue(persisted.endswith(b"\n"))
        self.assertEqual(persisted, self.mod.canonical_bytes(record) + b"\n")
        # Mutating an included field changes the hash.
        mutated = dict(record)
        mutated["a"] = 2
        self.assertNotEqual(
            self.mod.self_hash(mutated, "marker"),
            record["marker"],
        )

    def test_uuid_v4_rejects_non_v4_and_bad_variant(self) -> None:
        self.assertTrue(self.mod.is_uuid_v4(str(uuid.uuid4())))
        self.assertFalse(self.mod.is_uuid_v4("not-uuid"))
        # version nibble 1
        self.assertFalse(self.mod.is_uuid_v4("123e4567-e89b-12d3-a456-426614174000"))
        # variant nibble not 8/9/a/b
        self.assertFalse(self.mod.is_uuid_v4("123e4567-e89b-42d3-c456-426614174000"))
        with self.assertRaises(self.mod.ProgramStateError) as ctx:
            self.mod.require_uuid_v4("00000000-0000-0000-0000-000000000000", label="x")
        self.assertEqual(ctx.exception.code, self.mod.ERROR_STATE_ID)

    def test_forbidden_owned_to_complete(self) -> None:
        current = self.mod.PointerView(
            status="owned",
            phase="selected",
            epoch=1,
            owner_token="t",
            owner_identity="u",
            active_issue_number=12,
            active_pr_ordinal=1,
            acceptance_complete=True,
        )
        with self.assertRaises(self.mod.ProgramStateError) as ctx:
            self.mod.check_forbidden_transition(
                current,
                self.mod.TransitionRequest(
                    event_type="program-completed",
                    to_status="complete",
                    to_phase="complete",
                ),
            )
        self.assertIn("owned -> complete", ctx.exception.message)

    def test_forbidden_acquire_when_complete(self) -> None:
        current = self.mod.PointerView(
            status="complete",
            phase="complete",
            epoch=3,
            owner_token=None,
            owner_identity=None,
            active_issue_number=None,
            active_pr_ordinal=None,
        )
        with self.assertRaises(self.mod.ProgramStateError) as ctx:
            self.mod.check_forbidden_transition(
                current,
                self.mod.TransitionRequest(
                    event_type="issue-acquired",
                    to_status="owned",
                    to_phase="selected",
                    issue_number=12,
                ),
            )
        self.assertEqual(ctx.exception.code, self.mod.ERROR_PROGRAM_COMPLETE)

    def test_forbidden_continuation_identity_change(self) -> None:
        current = self.mod.PointerView(
            status="owned",
            phase="pr-open",
            epoch=2,
            owner_token="tok",
            owner_identity="alice",
            active_issue_number=12,
            active_pr_ordinal=1,
        )
        with self.assertRaises(self.mod.ProgramStateError) as ctx:
            self.mod.check_forbidden_transition(
                current,
                self.mod.TransitionRequest(
                    event_type="pr-checkpointed",
                    to_status="owned",
                    to_phase="selected",
                    issue_number=13,
                    owner_token="tok",
                    owner_identity="alice",
                    epoch=2,
                ),
            )
        self.assertEqual(ctx.exception.code, self.mod.ERROR_OWNER_MISMATCH)

        with self.assertRaises(self.mod.ProgramStateError) as ctx2:
            self.mod.check_forbidden_transition(
                current,
                self.mod.TransitionRequest(
                    event_type="pr-opened",
                    to_status="owned",
                    to_phase="pr-open",
                    issue_number=12,
                    owner_token="tok",
                    owner_identity="alice",
                    epoch=9,
                ),
            )
        self.assertEqual(ctx2.exception.code, self.mod.ERROR_EPOCH_MISMATCH)

    def test_forbidden_release_with_incomplete_acceptance(self) -> None:
        current = self.mod.PointerView(
            status="owned",
            phase="pr-open",
            epoch=1,
            owner_token="tok",
            owner_identity="alice",
            active_issue_number=12,
            active_pr_ordinal=1,
            acceptance_complete=False,
        )
        with self.assertRaises(self.mod.ProgramStateError) as ctx:
            self.mod.check_forbidden_transition(
                current,
                self.mod.TransitionRequest(
                    event_type="issue-released",
                    to_status="idle",
                    to_phase="idle",
                    acceptance_complete=False,
                ),
            )
        self.assertEqual(ctx.exception.code, self.mod.ERROR_ACCEPTANCE_INCOMPLETE)

    def test_no_sentinel_for_zero_outgoing_pair_issues(self) -> None:
        dep_id = str(uuid.uuid4())
        pairs = [
            self.mod.PairSpec(
                subject_issue_number=12,
                related_issue_number=10,
                related_is_baseline=True,
                dependency_id=dep_id,
                classification="unknown",
            )
        ]
        projection = self.mod.build_dependency_projection(pairs)
        self.assertEqual(len(projection), 1)
        self.assertEqual(projection[0]["status"], "unresolved")
        zero = self.mod.issues_with_zero_outgoing_pairs([12, 13, 10], pairs)
        self.assertEqual(zero, [10, 13])
        # No invented sentinel row for issue 13.
        self.assertEqual(
            [row["subject_issue_number"] for row in projection],
            [12],
        )

        events = [
            {
                "subject_issue_number": 12,
                "related_issue_number": 10,
                "related_is_baseline": True,
                "dependency_id": dep_id,
                "classification": "unknown",
                "event_sha256": "a" * 64,
            }
        ]
        from_events = self.mod.projection_from_events(events)
        self.assertEqual(len(from_events), 1)

    def test_selection_key_order(self) -> None:
        candidates = [
            self.mod.SelectionCandidate(30, selection_wave_number=2, ledger_ordinal=1),
            self.mod.SelectionCandidate(12, selection_wave_number=1, ledger_ordinal=2),
            self.mod.SelectionCandidate(13, selection_wave_number=1, ledger_ordinal=1),
            self.mod.SelectionCandidate(11, selection_wave_number=1, ledger_ordinal=1),
        ]
        chosen = self.mod.select_minimum_eligible(candidates)
        assert chosen is not None
        self.assertEqual(chosen.issue_number, 11)
        self.assertEqual(self.mod.selection_key(chosen), (1, 1, 11))

    def test_sequence_filename_and_chain(self) -> None:
        op = str(uuid.uuid4())
        name = f"{self.mod.format_sequence_prefix(1)}-{op}.json"
        seq, parsed = self.mod.parse_sequenced_filename(name)
        self.assertEqual(seq, 1)
        self.assertEqual(parsed, op)
        self.mod.validate_sequence_chain([1, 2, 3], label="x")
        with self.assertRaises(self.mod.ProgramStateError):
            self.mod.validate_sequence_chain([1, 1], label="x")

    def test_pointer_validate_idle_hash(self) -> None:
        pointer = {
            "schema_version": 2,
            "program_id": self.mod.PROGRAM_ID,
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
        pointer["pointer_sha256"] = self.mod.self_hash(pointer, "pointer_sha256")
        validated = self.mod.validate_pointer(pointer)
        self.assertEqual(validated["status"], "idle")

    def test_state_root_minimal_idle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pointer = {
                "schema_version": 2,
                "program_id": self.mod.PROGRAM_ID,
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
            pointer["pointer_sha256"] = self.mod.self_hash(pointer, "pointer_sha256")
            order_entries = []
            issues = [
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
            for ordinal, issue in enumerate(issues, start=1):
                wave = (
                    1
                    if ordinal <= 2
                    else 2
                    if ordinal <= 11
                    else 3
                    if ordinal <= 15
                    else 4
                )
                order_entries.append(
                    {
                        "issue_number": issue,
                        "issue_node_id": f"I_{issue}",
                        "wave_number": wave,
                        "ledger_ordinal": ordinal,
                        "selection_wave_number": wave,
                    }
                )
            manifest = {
                "schema_version": 2,
                "program_id": self.mod.PROGRAM_ID,
                "activation": {
                    "snapshot_at": self.mod.ACTIVATION_SNAPSHOT_AT,
                    "main_sha": self.mod.ACTIVATION_MAIN_SHA,
                    "issue_count": 44,
                    "issue_numbers": sorted(issues),
                    "issue_order": order_entries,
                    "issue_order_source_path": self.mod.ORDER_SOURCE_PATH,
                    "issue_order_source_sha256": self.mod.ORDER_SOURCE_SHA256,
                    "baseline_manifest_sha256": self.mod.BASELINE_MANIFEST_SHA256,
                    "anchor_commit_oid": "c" * 40,
                    "anchor_tree_oid": "d" * 40,
                    "anchor_inventory_sha256": "e" * 64,
                    "anchor_evidence_ref": {
                        "evidence_id": str(uuid.uuid4()),
                        "evidence_type": "wave0-full-tree",
                        "schema_version": 1,
                        "record_sha256": "f" * 64,
                    },
                },
                "state_sequence": 1,
                "last_receipt_path": "state/receipts/"
                + f"{self.mod.format_sequence_prefix(1)}-{uuid.uuid4()}.json",
                "last_receipt_sha256": "a" * 64,
                "dependency_pair_source_path": self.mod.PAIRS_SOURCE_PATH,
                "dependency_pair_source_sha256": self.mod.PAIRS_SOURCE_SHA256,
                "dependency_pair_count": 212,
                "dependency_sequence": 0,
                "last_dependency_event_path": None,
                "last_dependency_event_sha256": None,
                "pointer_path": "state/pointer.json",
                "pointer_sha256": pointer["pointer_sha256"],
                "previous_manifest_sha256": None,
                "expected_parent_state_oid": "b" * 40,
                "resolved_issue_count": 0,
                "resolved_issues": [],
                "dependency_projection": [],
                "unresolved_dependency_count": 0,
                "terminal_lineage": [],
                "unresolved_lineage_count": 44,
                "open_program_authorizations": [],
                "updated_at": "2026-07-28T00:00:00Z",
                "manifest_sha256": "",
            }
            manifest["manifest_sha256"] = self.mod.self_hash(manifest, "manifest_sha256")
            (root / "pointer.json").write_bytes(self.mod.persisted_file_bytes(pointer))
            (root / "manifest.json").write_bytes(self.mod.persisted_file_bytes(manifest))
            summary = self.mod.validate_state_root(root)
            self.assertTrue(summary["ok"])
            self.assertEqual(summary["pointer_status"], "idle")


if __name__ == "__main__":
    unittest.main()
