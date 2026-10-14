import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("control", Path(__file__).with_name("control.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        (self.runtime / "policy.json").write_text(json.dumps({"task_ids": ["pr", "radar", "code"]}))
        (self.runtime / "tasks.json").write_text("{}")
        self.control = module.Control(self.runtime, self.root / "codex")

    def archive(self, indexed=False):
        root = self.root / "archive"
        for folder in ["reports", "data"]:
            (root / folder / "2026").mkdir(parents=True, exist_ok=True)
        value = {field: [] for field in module.REQUIRED}
        value.update(task_name="fixture", generated_at="2026-10-14T11:00:00+08:00",
                     baseline={"sha": "a" * 40}, no_material_change=True)
        data = json.dumps(value).encode()
        (root / "data/2026/report.json").write_bytes(data)
        (root / "reports/2026/report.md").write_text("# Verified report\n")
        if indexed:
            (root / "LATEST.json").write_text(json.dumps({"generated_at": value["generated_at"],
                "data": "data/2026/report.json", "report": "reports/2026/report.md"}))
            (root / "LATEST.md").write_text("[Report](reports/2026/report.md)\n")
        else:
            (root / "LATEST.json").write_bytes(data)
            (root / "LATEST.md").write_bytes((root / "reports/2026/report.md").read_bytes())
        return root

    def test_index_consumer_resolves_complete_data_and_promotion_preserves_history(self):
        archive = self.archive(indexed=True)
        originals = {str(p): p.read_bytes() for folder in ["data", "reports"] for p in (archive / folder / "2026").iterdir()}
        self.control.registry = {"radar": {"archive_dir": str(archive)}}
        self.control.policy["archive_directories"] = {"radar": str(archive)}
        self.assertEqual(module.archive_state(archive)["status"], "legacy-index")
        result = self.control.normalize_archives()
        self.assertEqual(result["promoted"][0]["status"], "valid")
        self.assertEqual((archive / "LATEST.json").read_bytes(), (archive / "data/2026/report.json").read_bytes())
        for path, content in originals.items():
            self.assertEqual(Path(path).read_bytes(), content)
        self.assertTrue(Path(result["promoted"][0]["backup"]).joinpath("LATEST.json").exists())

    def test_invalid_index_does_not_overwrite_previous_success(self):
        archive = self.archive(indexed=True)
        data = json.loads((archive / "data/2026/report.json").read_text())
        data["generated_at"] = "2026-10-13T11:00:00+08:00"
        (archive / "data/2026/report.json").write_text(json.dumps(data))
        original = (archive / "LATEST.json").read_bytes()
        self.control.registry = {"radar": {"archive_dir": str(archive)}}
        self.control.policy["archive_directories"] = {"radar": str(archive)}
        with self.assertRaisesRegex(ValueError, "generation times differ"):
            self.control.normalize_archives()
        self.assertEqual((archive / "LATEST.json").read_bytes(), original)

    def test_supplementary_payload_is_not_mistaken_for_another_primary_archive(self):
        archive = self.archive()
        folder = archive / "data/2026/report"
        folder.mkdir()
        (folder / "payload.json").write_bytes((archive / "data/2026/report.json").read_bytes())
        self.assertEqual(module.archive_state(archive)["status"], "valid")

    def test_interrupted_two_file_promotion_is_detected_as_a_mixed_pair(self):
        archive = self.archive()
        data = json.loads((archive / "data/2026/report.json").read_text())
        data["generated_at"] = "2026-10-15T11:00:00+08:00"
        encoded = json.dumps(data).encode()
        (archive / "data/2026/new.json").write_bytes(encoded)
        (archive / "LATEST.json").write_bytes(encoded)
        with self.assertRaisesRegex(ValueError, "mixed immutable"):
            module.archive_state(archive)

    def test_path_traversal_and_symlink_are_rejected(self):
        with self.assertRaises(ValueError):
            module.safe_relative(self.root, "../private.json")
        outside = self.root / "outside"
        outside.mkdir()
        link = self.runtime / "link"
        link.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            module.safe_relative(self.runtime, "link/value.json")

    def test_archive_reader_rejects_latest_and_year_directory_symlinks(self):
        archive = self.archive()
        latest = archive / "LATEST.json"
        outside = self.root / "outside.json"
        outside.write_bytes(latest.read_bytes())
        latest.unlink()
        latest.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symlink"):
            module.archive_state(archive)
        latest.unlink()
        latest.write_bytes(outside.read_bytes())
        (archive / "data/2027").symlink_to(archive / "data/2026", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            module.archive_state(archive)

    def test_restore_rejects_tampering_and_traversal_before_claiming_success(self):
        source, target = self.root / "source", self.root / "target"
        source.mkdir()
        (source / "config.json").write_bytes(b"original")
        manifest = {"files": [{"path": "config.json", "sha256": module.digest(b"original"), "bytes": 8}]}
        self.assertEqual(module.Control.verify_restore(source, target, manifest), 1)
        (source / "config.json").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            module.Control.verify_restore(source, self.root / "second", manifest)
        manifest["files"][0]["path"] = "../config.json"
        with self.assertRaises(ValueError):
            module.Control.verify_restore(source, self.root / "third", manifest)

    def test_secret_detector_withholds_values(self):
        value = "ghp_" + "a" * 36
        with self.assertRaises(ValueError) as error:
            module.secret_check(value.encode())
        self.assertNotIn(value, str(error.exception))

    def test_recovery_preserves_allowlisted_progress_without_copying_arbitrary_state(self):
        for name in ["prepare.py", "control.py", "README.md"]:
            (self.runtime / name).write_text("fixture\n")
        worktree = self.root / "repo"
        for name in ["docs/architecture/agent/action-card-ledger.md", ".github/dependabot.yml"]:
            path = worktree / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture\n")
        self.control.state.mkdir()
        (self.control.state / "decision-queue.json").write_text('{"items":[]}')
        (self.control.state / "action-queue.json").write_text('{"cards":[]}')
        (self.control.state / "unrelated-private.json").write_text('"excluded"')
        runtime = Mock()
        runtime.manifest.return_value = (None, None, {"task_id": "code", "state": "prepared",
            "worktree": str(worktree), "baseline_sha": "a" * 40})
        with patch.object(self.control, "runtime", return_value=runtime):
            receipt = self.control.recovery(self.root / "run")
        records = json.loads((Path(receipt["backup"]) / "manifest.json").read_text())["files"]
        paths = {record["path"] for record in records}
        self.assertIn("runtime/control-state/decision-queue.json", paths)
        self.assertIn("runtime/control-state/action-queue.json", paths)
        self.assertFalse(any("unrelated-private" in path for path in paths))
        self.assertEqual(receipt["files"], receipt["restored_files"])

    def test_writer_lease_never_steals_another_owner_even_after_time_passes(self):
        runtime = Mock()
        runtime.manifest.side_effect = lambda p: (None, None, {"state": "prepared", "task_id": "code"})
        with patch.object(self.control, "runtime", return_value=runtime):
            self.assertTrue(self.control.lease(str(self.root / "one"))["ok"])
            self.assertFalse(self.control.lease(str(self.root / "two"))["ok"])
            self.assertFalse(self.control.lease(str(self.root / "two"), release=True)["ok"])
            self.assertTrue(self.control.lease(str(self.root / "one"), release=True)["ok"])
            self.assertTrue(self.control.lease(str(self.root / "two"))["ok"])

    def test_closed_owner_can_release_without_reopening_missing_worktree(self):
        runtime = Mock()
        runtime.manifest.return_value = (None, None, {"state": "prepared", "task_id": "code"})
        owner = str(self.root / "one")
        with patch.object(self.control, "runtime", return_value=runtime):
            self.control.lease(owner)
            runtime.manifest.return_value = (None, None, {"state": "completed", "task_id": "code"})
            runtime.verify_worktree.reset_mock()
            self.assertTrue(self.control.lease(owner, release=True)["ok"])
            runtime.verify_worktree.assert_not_called()
            with self.assertRaises(ValueError):
                self.control.lease(owner)

    def test_observation_acknowledgement_rejects_forged_digest_and_foreign_scope(self):
        data = {"main": "a" * 40}
        with patch.object(self.control, "remote_observation", return_value=data):
            first = self.control.preflight("pr")
        self.assertTrue(first["changed"])
        self.control.acknowledge("pr", first["observation"], "waiting")
        with patch.object(self.control, "remote_observation", side_effect=AssertionError("unexpected API")):
            self.assertEqual(self.control.preflight("pr")["reason"], "backoff")
        path = Path(first["observation"])
        saved = json.loads(path.read_text())
        saved["data"] = {"main": "b" * 40}
        path.write_text(json.dumps(saved))
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.control.acknowledge("pr", path, "handled")
        with self.assertRaises(ValueError):
            self.control.acknowledge("code", path, "handled")

    def test_issue_observation_stores_comment_digest_without_body(self):
        raw = [{"number": 1, "updatedAt": "now", "comments": [{"id": "1", "body": "private text"}]}]
        self.control.policy["task_ids"].append("issue")
        with patch.object(module, "gh", side_effect=[raw, []]):
            result = self.control.remote_observation("issue")
        self.assertNotIn("private text", json.dumps(result))
        self.assertEqual(result["issues"][0]["comments"][0]["body_sha256"], module.digest("private text"))

    def test_issue_rechecks_when_a_pr_changes_without_an_issue_comment(self):
        self.control.policy["task_ids"].append("issue")
        issue = [{"number": 1, "updatedAt": "same", "comments": []}]
        opened = [{"number": 2, "state": "OPEN", "headRefOid": "a" * 40}]
        merged = [{"number": 2, "state": "MERGED", "headRefOid": "a" * 40}]
        with patch.object(module, "gh", side_effect=[issue, opened, issue, merged]):
            first = module.digest(self.control.remote_observation("issue"))
            second = module.digest(self.control.remote_observation("issue"))
        self.assertNotEqual(first, second)

    def test_unknown_task_has_no_side_effects(self):
        with self.assertRaises(ValueError):
            self.control.preflight("unapproved")
        self.assertFalse(self.control.state.exists())

    def test_registry_cannot_redirect_backups_to_an_unapproved_directory(self):
        approved = self.archive()
        self.control.policy["archive_directories"] = {"radar": str(approved)}
        self.control.registry = {"radar": {"archive_dir": str(self.root / "private")}}
        with self.assertRaisesRegex(ValueError, "approved task scope"):
            self.control.archive_directory("radar")

    def test_workflow_approval_changes_are_detected_without_any_check_runs(self):
        sha = "a" * 40
        self.control.policy["excluded_pr_authors"] = []
        repository = {"data": {"repository": {"defaultBranchRef": {"name": "main"},
            "pullRequests": {"pageInfo": {"hasNextPage": False}, "nodes": [{"number": 1,
                "headRefOid": sha, "author": {"login": "contributor"},
                "reviewThreads": {"pageInfo": {"hasNextPage": False}},
                "commits": {"nodes": [{"commit": {"statusCheckRollup": None}}]}}]}}}}
        status = {"conclusion": "action_required"}
        def response(args):
            if args[1] == "graphql":
                return repository
            if "/actions/runs?" in args[1]:
                return {"total_count": 1, "workflow_runs": [{"id": 1, "workflow_id": 2,
                    "head_sha": sha, "status": "completed", "created_at": "2026-10-01", **status}]}
            return []
        with patch.object(module, "gh", side_effect=response):
            first = module.digest(self.control.remote_observation("pr"))
            status["conclusion"] = "failure"
            second = module.digest(self.control.remote_observation("pr"))
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
