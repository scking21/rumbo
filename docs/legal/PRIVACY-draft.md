# Rumbo local plugin privacy notice

Draft for review · 4 October 2026

Rumbo is a free, open-source project by Corby King. This notice covers the local Python plugin and Claude Code adapter described in the [Rumbo repository](https://github.com/scking21/rumbo). A separately hosted Rumbo service has different data handling and needs its own operator's notice.

## Where local data is stored

Rumbo uses project information to track agreed work, artifact versions, evidence and decisions. Data is stored in the environment where you run the local plugin. The local engine stores original requests, goals, constraints, acceptance criteria, task claims, actor identifiers, timestamps, artifact paths and hashes, review statements, questions and decisions in the selected project's `.rumbo/state.sqlite3`.

It reads registered project files to calculate hashes and perform the configured checks. It does not copy those files into its database. Text you explicitly upload through the artifact-ingestion tool is stored in `.rumbo/artifacts/`. Connected tools can return registered artifact text for review.

The installed OpenAI plugin also uses an owner-provisioned `PLUGIN_DATA/projects.json` file containing approved project aliases, local paths, project IDs and directory identifiers. It starts without a selected project.

The separate Claude adapter stores planning records in `.rumbo/record.json`. It reads the compatible conversation transcript supplied by Claude Code to check quotations. Verified-quote fingerprints, session IDs and dates are stored in `.rumbo/verified-quotes.json`; temporary session markers are stored separately. Record summaries and Stop reasons can be included in the Claude conversation.

## Network use and other recipients

The deterministic local engine, CLI and demo contain no telemetry and make no network requests. Rumbo does not call a model or analytics service. Installing or updating it through a host or package service is subject to that service's data handling.

If you connect an AI host, that host can receive tool results, artifact text, project summaries and other information used in your workflow. Its own terms and privacy policy apply. Local operation does not mean information shown to a connected AI host stays on your computer.

If you deliberately deploy the optional Python HTTP server, its configured authorization provider receives access tokens for validation. Its separate browser login also exchanges authentication information with that provider. The server operator can access the project data it hosts. See the repository's [technical privacy information](https://github.com/scking21/rumbo/blob/4270f264970b30957bc4120d63250ab4e6b74fb0/PRIVACY.md) before choosing that deployment.

## Retention and your controls

Rumbo does not automatically delete or back up local project state. Records remain until you or your operator remove them. Stop Rumbo before removing a project's `.rumbo` directory, and preserve anything you still need first. Removing that directory deletes its coordination history and uploaded artifacts; registered files outside it are unchanged. The installed registry and legacy temporary session markers are separate files.

Backups created with Rumbo's explicit backup command contain project history and uploaded content. Those archives are unencrypted. Copies sent to hosts, copied into backups or shared elsewhere have their own retention and deletion controls.

Choose carefully which projects and content you connect. Keep `.rumbo/` out of shared repositories. Do not put passwords, access tokens or other secrets in requests, criteria, artifacts or reports.

## Questions and support

For general questions, use [Rumbo's GitHub issues](https://github.com/scking21/rumbo/issues). Issues are public: do not include private project records, personal information, credentials or sensitive security details. GitHub processes information you post under its own policies.
