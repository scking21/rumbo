# Rumbo privacy statement

Rumbo is a Claude Code plugin that runs entirely on your machine. It makes no direct network requests and no telemetry submissions, and sends nothing to its author. Its hook output does enter your Claude conversation, where it is processed by the Claude service you have configured (see [What reaches the model](#what-reaches-the-model)).

## What it stores

- **The decision record**, `.rumbo/record.json` in your project by default (the command-line tool also accepts another path with `--record`). It holds the objective, each decision with your exact words (`quote`), and the checks the agent writes. These can include anything you typed, such as names, dates or amounts. It stays until you delete it. If you share the project, the record goes with it unless you exclude it. Adding `.rumbo/` to `.gitignore` keeps it out of future git commits only: it does not remove a record that is already tracked, and it does not apply to other ways of sharing a folder (zip files, synced drives, backups). `init` warns you when `.rumbo/` is not in `.gitignore`.
- **Per-session state files** in your system's temporary directory under `rumbo/`, or in `$RUMBO_STATE_DIR` if you set it. Each file name is built from the Claude Code session id. They hold:
  - `.nudged` / `.enforced`: the path of the record file the planning nudge pointed to;
  - `.blocks`: how many times the Stop hook has blocked in that session;
  - `.failed`: the ids of checks that were failing, as written in the record by the agent. Check ids are usually short labels such as `C1`, but they can contain any text the agent chose.

## What it reads

- The decision record and your project's `.gitignore`.
- **Claude Code's own transcript of the current session**, at the path Claude Code passes to the Stop hook (`transcript_path`), to check that each quote in the record matches something you actually wrote. It is read in place and never copied or stored.
- Hook input from Claude Code:
  - your prompt text, only to decide whether to show the planning nudge (it is not stored);
  - the session id, which names the per-session state files above;
  - `stop_hook_active`, which Claude Code sets when a Stop hook has already blocked, and which Rumbo uses to avoid blocking in a loop.

## What reaches the model

Each time you send a prompt, the `UserPromptSubmit` hook adds a short summary of the record (including your quoted words) to the conversation, and the Stop hook can add a reason when it blocks. That text becomes part of your Claude conversation and is handled by the Claude service you use, under the terms that already apply to it. Rumbo itself sends it nowhere else.

## Removing it

- Delete `.rumbo/` from your project, and any record you created elsewhere with `--record`.
- Delete the `rumbo/` folder in your temporary directory, or your `$RUMBO_STATE_DIR` if you set one.
- Uninstall the plugin from the `/plugin` menu in Claude Code.

Deleting these files does not remove text that already entered your Claude conversation history, or copies of the record you have already shared or committed.

## Contact

Questions or problems: https://github.com/scking21/rumbo/issues
