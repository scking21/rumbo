# Rumbo privacy statement

Rumbo is a Claude Code plugin that runs entirely on your machine. It makes no network requests, has no telemetry, and sends nothing to its author or to any third party.

## What it stores

- **The decision record**, `.rumbo/record.json` in your project. It holds the objective, each decision with your exact words (`quote`), and the checks the agent writes. These can include anything you typed, such as names, dates or amounts. It stays in your project until you delete it. If you share the project (for example by pushing it to a git host), the record goes with it unless `.rumbo/` is in your `.gitignore`; `init` warns you when it is not.
- **Small per-session marker files** in your system's temporary directory under `rumbo/` (or `$RUMBO_STATE_DIR` if you set it). They hold the record path, a block count and the ids of failing checks. They contain none of your words.

## What it reads

- The decision record and your project's `.gitignore`.
- **Claude Code's own transcript of the current session**, at the path Claude Code passes to the Stop hook, to check that each quote in the record matches something you actually wrote. It is read in place and never copied or stored.
- Hook input from Claude Code (your prompt text, the session id), used only to decide whether to show the planning nudge.

## What reaches the model

Each time you send a prompt, the `UserPromptSubmit` hook adds a short summary of the record to the conversation, and the Stop hook can add a reason when it blocks. That text becomes part of your Claude conversation and is handled under the terms that already apply to your use of Claude. Rumbo itself sends it nowhere else.

## Removing it

Delete `.rumbo/` from your project and the `rumbo/` folder in your temporary directory. Uninstall the plugin from the `/plugin` menu in Claude Code.

## Contact

Questions or problems: https://github.com/scking21/rumbo/issues
