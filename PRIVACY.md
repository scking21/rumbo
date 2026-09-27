# Rumbo privacy statement

Rumbo is a Claude Code plugin that runs entirely on your machine. It makes no direct network requests and no telemetry submissions, and sends nothing to its author. Its hook output does enter your Claude conversation, where it is processed by the Claude service you have configured (see [What reaches the model](#what-reaches-the-model)).

## What it stores

- **The decision record**, `.rumbo/record.json` in your project by default (the command-line tool also accepts another path with `--record`). It holds the objective, each decision with your exact words (`quote`), and the checks the agent writes. These can include anything you typed, such as names, dates or amounts. It stays until you delete it. If you share the project, the record goes with it unless you exclude it. Adding `.rumbo/` to `.gitignore` keeps it out of future git commits only: it does not remove a record that is already tracked, and it does not apply to other ways of sharing a folder (zip files, synced drives, backups).

  `init` gives a limited warning: it reads only the `.gitignore` in the directory above the record's folder (for the default `.rumbo/record.json`, your project's top-level `.gitignore`) and looks for a line that is exactly `.rumbo` or `.rumbo/`. It does not read other ignore files or patterns, and for a record saved elsewhere with `--record` it does not tell you whether that record is excluded. Check that yourself.
- **Per-session state files** in your system's temporary directory under `rumbo/`, or in `$RUMBO_STATE_DIR` if you set it. Each file name is built from the Claude Code session id. They hold:
  - `.nudged` / `.enforced`: the path of the record file the planning nudge pointed to;
  - `.blocks`: how many times in a row the Stop hook has blocked (reset when the record passes);
  - `.failed`: the ids of checks that were failing, as written in the record by the agent. Check ids are usually short labels such as `C1`, but they can contain any text the agent chose.

## What it reads

- The decision record, and the `.gitignore` described above (only when `init` runs).
- Its own per-session state files, to enforce the nudge once and to limit how many times it blocks.
- **Claude Code's own transcript of the current session**, at the path Claude Code passes to the Stop hook (`transcript_path`), to check that each quote in the record matches something you actually wrote. It is read in place and never copied or stored.
- Hook input from Claude Code:
  - your prompt text, only to decide whether to show the planning nudge (it is not stored);
  - the session id, which names the per-session state files above;
  - `stop_hook_active`, which Claude Code sets when a Stop hook has already blocked, and which Rumbo uses to avoid blocking in a loop.
- A transcript file you name yourself, if you run `record.py check --transcript <path>` by hand.

## What reaches the model

When a valid record exists, the `UserPromptSubmit` hook adds a summary of its text (the objective and the wording and status of selected active decisions) and its checks to the conversation each time you send a prompt. The `quote` fields are not included, but the summary may still contain your words or other sensitive information. When there is no record, it may add a planning nudge instead: a few lines that include the path of the plugin's script and of the record it suggests creating. The Stop hook can add a reason when it blocks, naming failing checks and record entries. That text becomes part of your Claude conversation and is handled by the Claude service you use, under the terms that already apply to it. Rumbo itself sends it nowhere else.

## Removing it

- Delete `.rumbo/` from your project, and any record you created elsewhere with `--record`.
- Delete the `rumbo/` folder in your temporary directory, or your `$RUMBO_STATE_DIR` if you set one.
- Uninstall the plugin from the `/plugin` menu in Claude Code.

Deleting these files does not remove text that already entered your Claude conversation history, or copies of the record you have already shared or committed.

## Contact

Questions or problems: https://github.com/scking21/rumbo/issues
