# Local projects during account switching (issue #44)

This branch adds a macOS compatibility path for the legacy
`electron-account-renderer-state-v1` format in
`$CODEX_HOME/.codex-global-state.json` (default `~/.codex`). It is not yet
validated with a real macOS account round trip. Windows does not activate this
path; its shared merge tests do run on Windows.

## Automatic handoff

After Desktop exits normally and the installed target credential is verified,
`AccountStore.commitActiveAccountID` prepares the target account's inactive
renderer snapshot before committing the registry and reopening Desktop. It
derives the legacy owner key as SHA-256 of the compact JSON array
`[chatgpt_user_id, chatgpt_account_id]`, using the ID-token user claim and the
selected workspace account ID. The source owner must match the current renderer
owner. Missing identity claims, a different owner, or an unsupported state shape
leave the file untouched.

The handoff copies missing folder-backed project definitions, preserving their
IDs, and missing chat assignments for compatible local projects. Existing target
assignments and explicitly projectless chats take precedence. It adds imported
projects to the target order and copies missing project or thread metadata from
the supported mapping fields. Existing values win recursively.

Projects with a `g-p-` ID, a non-null `chatGptBacking`, another recognized account
backing, or missing `rootPaths` are excluded. A root already registered under a
different target ID is skipped. Account atoms, renderer ownership, other account
snapshots and the live source project catalog are preserved. The implementation
does not edit SQLite or conversation files or grant access to conversations.

Before replacing state, the switcher writes an exact private backup named
`project-state-before-switch-<UUID>.json` in
`~/Library/Application Support/Codex Account Switcher/`. A file comparison stops
the operation if state changed since it was read. The replacement uses the
existing atomic writer. Read, backup, or write errors fail the commit stage and
trigger the existing credential restoration. If the later registry write fails,
the prepared target snapshot and backup may remain, while the original
credential is restored. Backups contain private workspace metadata and are not
automatically pruned.

This is additive compatibility, not continuous synchronization. Project removal,
rename conflicts, alternate IDs for the same folder, custom sections, appearance,
and account-specific preferences are not reconciled. Missing projects that exist
only in a different inactive archive are not selected automatically. New Desktop
formats without the legacy container are left to Desktop's own migration.

## Manual recovery of an empty sidebar

The standalone Python 3 tool supports a different case: the active project
metadata is empty and an inactive snapshot still contains it. From the repository
root, after fully quitting Codex Desktop:

```sh
python3 scripts/restore_codex_projects.py
python3 scripts/restore_codex_projects.py --source-index 0 --apply
```

The first command previews counts without writing. With several snapshots,
choose the index based on those counts. `--apply` refuses populated active
metadata, makes an exact adjacent backup, and atomically replaces state. It
checks for running Codex/ChatGPT processes on macOS and Windows, but Desktop must
remain closed throughout recovery. It restores six project fields from the
selected snapshot; it does not change credentials, databases or chat files.
Python 3 is required separately; this script is not bundled into the native app.
On Windows use `py -3` instead of `python3`. For a non-default home pass
`--state /path/to/.codex-global-state.json`.

To undo a manual recovery, fully quit Desktop and restore the exact adjacent
backup over the state file. To undo an automatic handoff, fully quit Desktop and
restore its application-support backup over the active global-state file.
These are whole-file backups: restoring one also restores unrelated settings to
their values at backup time. Keep both the state file and backups private.

## Validation and release gate

Executed on Windows: four `LocalProjectHandoffTests` plus the existing switch
ordering and local identity suites (18 tests total); eight Python recovery tests.
The merge tests cover target conflicts, new chats on later switches, repeated
preparation, cloud backings, duplicate roots, owner mismatch and modern formats.
The Windows run excludes the CryptoKit owner derivation and macOS storage hook.

Before releasing the native change, build and test on macOS, verify the legacy
owner derivation against a supported Desktop build, then run a backed-up A→B→A
test. Check exact project IDs, chat assignments, existing target moves,
projectless chats, cloud exclusion, and creation of a new local chat before the
return switch. Also verify that a current Desktop format without the legacy
container is unchanged. Passing synthetic merge tests does not establish that
Desktop will hydrate the prepared snapshot or complete its database migration.

Related reports: [switcher #44](https://github.com/liuzhao1225/codex-account-switcher/issues/44),
[Codex account switching #60364](https://github.com/openai/codex/issues/60364),
and [the related provider-switch fix #60604](https://github.com/openai/codex/issues/60604).
The provider-switch fix alone is not evidence that every account-switch case is
resolved.
