#!/usr/bin/env python3
"""Recover a missing Codex Desktop project sidebar from an inactive snapshot.

Run only while Codex Desktop is fully closed. The default invocation previews
the recovery; --apply makes an exact backup before replacing the state file.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


STATE_KEY = "electron-account-renderer-state-v1"
PROJECT_KEYS = (
    "local-projects",
    "project-order",
    "thread-project-assignments",
    "app-server-project-id-by-legacy-project-id-by-host",
    "thread-workspace-root-hints",
    "sidebar-project-thread-orders",
)


class RecoveryError(Exception):
    pass


def candidates(state):
    renderer = state.get(STATE_KEY)
    if not isinstance(renderer, dict) or not isinstance(renderer.get("inactive"), dict):
        raise RecoveryError("No supported inactive account snapshots were found.")
    found = []
    for owner, snapshot in sorted(renderer["inactive"].items()):
        globals_ = snapshot.get("globals") if isinstance(snapshot, dict) else None
        projects = globals_.get("local-projects") if isinstance(globals_, dict) else None
        if isinstance(projects, (dict, list)) and projects:
            found.append((owner, globals_))
    if not found:
        raise RecoveryError("No inactive snapshot contains a project catalog.")
    return found


def recovery_plan(state, source_index=None):
    if not isinstance(state, dict):
        raise RecoveryError("The Codex state file must contain a JSON object.")
    for key in PROJECT_KEYS:
        if state.get(key):
            raise RecoveryError(f"The active state already contains {key}; refusing to overwrite it.")
    found = candidates(state)
    if source_index is None:
        if len(found) != 1:
            raise RecoveryError(
                f"Found {len(found)} project snapshots. Select one with --source-index N."
            )
        source_index = 0
    if not 0 <= source_index < len(found):
        raise RecoveryError(f"Source index must be between 0 and {len(found) - 1}.")
    source = found[source_index][1]
    return found, source_index, {key: source[key] for key in PROJECT_KEYS if key in source}


def read_state(path):
    if path.is_symlink() or not path.is_file():
        raise RecoveryError("The state path must be a regular file, not a symlink.")
    original = path.read_bytes()
    try:
        state = json.loads(original)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecoveryError("The state file is not valid UTF-8 JSON.") from error
    return original, state


def require_closed_desktop():
    if sys.platform == "win32":
        try:
            running = subprocess.check_output([
                "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                "$ErrorActionPreference = 'Stop'; "
                "@(Get-Process | Where-Object { $_.ProcessName -in @('Codex','ChatGPT') }).Count",
            ], text=True, timeout=15).strip()
            count = int(running)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise RecoveryError("Could not confirm that Codex Desktop is closed.") from error
        if count:
            raise RecoveryError("Codex or ChatGPT processes are still running. Close them before applying recovery.")
        return
    if sys.platform != "darwin":
        raise RecoveryError("Applying recovery is supported only on macOS and Windows.")
    try:
        processes = subprocess.check_output(["ps", "-axo", "command="], text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as error:
        raise RecoveryError("Could not confirm that Codex Desktop is closed.") from error
    if any(f"/{app}.app/Contents/MacOS/" in process
           for process in processes.splitlines() for app in ("Codex", "ChatGPT")):
        raise RecoveryError("Codex Desktop is still running. Fully quit it before applying recovery.")


def apply_recovery(path, original, state, fields):
    require_closed_desktop()
    if path.read_bytes() != original:
        raise RecoveryError("The state file changed during preview; close Desktop and retry.")
    updated = dict(state)
    updated.update(fields)
    payload = (json.dumps(updated, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    mode = stat.S_IMODE(path.stat().st_mode)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.switcher-backup-{timestamp}")
    try:
        descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise RecoveryError("A backup with this timestamp already exists; retry in a second.") from error

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, mode)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink() or path.read_bytes() != original:
            raise RecoveryError("The state file changed during recovery; the backup was kept.")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return backup


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=Path.home() / ".codex" / ".codex-global-state.json")
    parser.add_argument("--source-index", type=int, metavar="N")
    parser.add_argument("--apply", action="store_true", help="back up and restore the selected snapshot")
    args = parser.parse_args(argv)
    try:
        original, state = read_state(args.state)
        if not isinstance(state, dict):
            raise RecoveryError("The Codex state file must contain a JSON object.")
        found = candidates(state)
        for index, (_, snapshot) in enumerate(found):
            print(f"Snapshot {index}: {len(snapshot['local-projects'])} projects, "
                  f"{len(snapshot.get('thread-project-assignments') or {})} chat assignments")
        _, selected, fields = recovery_plan(state, args.source_index)
        print(f"Selected snapshot {selected}; restoring {len(fields)} project-related fields.")
        if args.apply:
            backup = apply_recovery(args.state, original, state, fields)
            print(f"Restored project organization. Exact backup: {backup}")
        else:
            print("Preview only. Fully quit Codex Desktop, then rerun with --apply to restore.")
    except (OSError, RecoveryError) as error:
        print(f"Recovery stopped: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
