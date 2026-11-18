import json
import io
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import restore_codex_projects as recovery


def sample_state():
    return {
        "unrelated-setting": {"keep": "unchanged"},
        recovery.STATE_KEY: {
            "owner": "target",
            "inactive": {
                "source": {
                    "atoms": {"private": "unchanged"},
                    "globals": {
                        "local-projects": {"project-1": {"path": "/example"}},
                        "project-order": ["project-1"],
                        "thread-project-assignments": {"thread-1": "project-1"},
                        "sidebar-project-thread-orders": {"project-1": ["thread-1"]},
                    },
                }
            },
        },
    }


class RecoveryTests(unittest.TestCase):
    def test_multiple_snapshot_preview_shows_counts_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = sample_state()
            state[recovery.STATE_KEY]["inactive"]["second"] = {
                "globals": {"local-projects": {"project-2": {}}}
            }
            path.write_text(json.dumps(state), encoding="utf-8")
            before = path.read_bytes()
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(io.StringIO()):
                result = recovery.main(["--state", str(path)])
            self.assertEqual(result, 1)
            self.assertIn("Snapshot 0:", output.getvalue())
            self.assertIn("Snapshot 1:", output.getvalue())
            self.assertEqual(path.read_bytes(), before)

    def test_restores_project_ids_and_assignments_without_touching_other_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".codex-global-state.json"
            original = sample_state()
            path.write_text(json.dumps(original), encoding="utf-8")
            before, state = recovery.read_state(path)
            _, _, fields = recovery.recovery_plan(state)
            with patch.object(recovery, "require_closed_desktop"):
                backup = recovery.apply_recovery(path, before, state, fields)
            restored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(backup.read_bytes(), before)
            self.assertEqual(restored[recovery.STATE_KEY], original[recovery.STATE_KEY])
            self.assertEqual(restored["unrelated-setting"], original["unrelated-setting"])
            self.assertEqual(restored["local-projects"], original[recovery.STATE_KEY]["inactive"]["source"]["globals"]["local-projects"])
            self.assertEqual(restored["thread-project-assignments"], {"thread-1": "project-1"})

    def test_refuses_to_replace_an_existing_catalog_or_assignment(self):
        for key, value in (("local-projects", {"project-2": {}}),
                           ("thread-project-assignments", {"thread-2": "project-2"})):
            with self.subTest(key=key):
                state = sample_state()
                state[key] = value
                with self.assertRaises(recovery.RecoveryError):
                    recovery.recovery_plan(state)

    def test_requires_selection_when_two_snapshots_have_projects(self):
        state = sample_state()
        state[recovery.STATE_KEY]["inactive"]["second"] = {
            "globals": {"local-projects": {"project-2": {}}}
        }
        with self.assertRaises(recovery.RecoveryError):
            recovery.recovery_plan(state)
        found, selected, fields = recovery.recovery_plan(state, 1)
        self.assertEqual(len(found), 2)
        self.assertEqual(selected, 1)
        self.assertEqual(fields["local-projects"], {"project-1": {"path": "/example"}})

    def test_refuses_changed_file_and_leaves_it_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".codex-global-state.json"
            path.write_text(json.dumps(sample_state()), encoding="utf-8")
            before, state = recovery.read_state(path)
            _, _, fields = recovery.recovery_plan(state)
            path.write_text('{"changed": true}', encoding="utf-8")
            with self.assertRaises(recovery.RecoveryError):
                recovery.apply_recovery(path, before, state, fields)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"changed": True})

    def test_refuses_apply_while_macos_desktop_is_running(self):
        with patch.object(recovery.sys, "platform", "darwin"), \
             patch.object(recovery.subprocess, "check_output",
                          return_value="/Applications/Codex.app/Contents/MacOS/Codex\n"):
            with self.assertRaises(recovery.RecoveryError):
                recovery.require_closed_desktop()

    def test_windows_process_check(self):
        with patch.object(recovery.sys, "platform", "win32"), \
             patch.object(recovery.subprocess, "check_output", return_value="1\n"):
            with self.assertRaises(recovery.RecoveryError):
                recovery.require_closed_desktop()
        with patch.object(recovery.sys, "platform", "win32"), \
             patch.object(recovery.subprocess, "check_output", return_value="0\n"):
            recovery.require_closed_desktop()

    def test_windows_process_check_failure_stops_recovery(self):
        with patch.object(recovery.sys, "platform", "win32"), \
             patch.object(recovery.subprocess, "check_output", side_effect=OSError("failed")):
            with self.assertRaises(recovery.RecoveryError):
                recovery.require_closed_desktop()


if __name__ == "__main__":
    unittest.main()
