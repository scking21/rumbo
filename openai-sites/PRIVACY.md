# Rumbo Sites candidate: data handling for review

This document describes the experimental hosted adapter only. It is not the final publisher-approved privacy policy or a claim of directory approval. The owner-private deployed runtime remains v3, source `ca406c4`; the deletion and session-cleanup changes below are source-only changes awaiting deployment review. They have not been deployed, and the published review policy is unchanged.

## Data received and stored

The Sites hosting boundary supplies a Site-scoped authenticated user ID and verified email. Rumbo requires both to identify a signed-in request; it uses the user ID for authorization and does not persist email or names. No workspace connectors, model APIs, billing integration, application analytics or marketing tracking, telemetry client, or external repository synchronization is configured.

D1 stores project owner/member Site IDs and roles; distinct worker-session IDs, labels and attribution; contract goals, original requests, constraints and acceptance criteria; hash-linked ledger events containing claims, artifact metadata, check receipts, reviewer assertions and owner decisions; uploaded-content quota reservations; and hashed browser-session/CSRF identifiers with expiration times.

R2 stores explicitly uploaded UTF-8 artifact bytes under a project-scoped content digest. Uploads are limited to 128 KiB each and 64 MiB of unique content per project. Historical bytes remain available for integrity and owner export. Filenames are display-only. The service cannot read or watch local files, retrieve repositories, execute shell tests, or infer provenance from a content hash.

## Access and authentication

Sites manages sign-in and OAuth. The candidate is owner-private unless its owner explicitly changes the Site's audience. Project memberships are an additional server-side restriction. A worker session is bound to its authenticated account and project. A reviewer requires a distinct, explicitly authorized account that has not opened a worker session for that project. These controls establish attribution; they do not prove organizational independence.

Owner create/revise/decision and role-grant actions use a separate same-origin signed-in browser session, CSRF checks and explicit confirmation dialogs. They are absent from MCP. Browser authorization is not proof of physical human presence. A delegated agent with the user's browser control can still act within the permissions the user gives it.

## Current deployed retention and export

The deployed v3 candidate has no automatic retention/deletion schedule or self-service project deletion. It retains contract, event and artifact history. Browser session tokens expire after one hour; worker sessions expire after 24 hours, but expiration does not itself delete their database rows. An operator deletion procedure covering provider-held copies has not been established or tested.

The owner can download an NDJSON export containing the verified ledger and all retained uploaded artifact bytes. `scripts/verify-export.py` checks completeness, event hashes and artifact digests. Hosted restore is not implemented. The local distribution keeps its separate backup/restore workflow.

## Source-only deletion and cleanup proposal

The source change adds project deletion only in the signed-in owner browser, with the exact project ID (alias) typed and a fresh confirmation dialog. There is no MCP delete tool. Owners should export before starting: deletion affects every project member, cannot be undone in the hosted service, and blocks further project access while cleanup is pending.

A D1 deletion fence stops new mutations and upload reservations. Cleanup replaces each known project/digest R2 object with an empty guard object, including keys reserved for an upload that has not finished. Existing conditional uploads cannot overwrite these guards with delayed content. Each call handles at most 64 guards; larger or interrupted cleanups remain pending and need the owner to continue or retry. Pending does not mean content deletion is complete. Only after all guards are in place are the project, event, membership, worker and artifact-metadata rows removed.

After completion, retained application-level data for the deleted project is limited to a hash-derived deleted-project key in D1 and empty R2 objects at the project's hash-derived keys, kept indefinitely. These guards contain no filenames, emails, contract text or uploaded file contents. The keys and content digests remain pseudonymous, potentially linkable technical metadata; they are not anonymous and this is not zero-data erasure. The same owner cannot reuse the deleted project ID; creation returns an explicit error. The guards are retained to prevent delayed uploads or reuse from restoring deleted content.

The source change also purges expired browser-session/CSRF rows when an owner page is opened. It does not schedule background cleanup or automatically age out projects. Expired worker-session attribution remains until the project is deleted so that historical evidence and reviewer separation can still be checked.

These are application-storage controls. They do not delete exports, copies already received by connected clients or other recipients, or provider-managed backups and logs. Their retention and deletion timing have not been verified. Section 3.3 of the [ChatGPT Sites Data Processing Addendum](https://openai.com/policies/chatgpt-sites-data-processing-addendum/) assigns retention and deletion configuration/design responsibilities to the Site creator; it does not establish a backup/log deletion deadline for this candidate. Source tests do not establish managed-host behavior or legal compliance.

## Limits

Hosting and the connected AI client process requests under their own terms and platform policies. This repository cannot independently verify their infrastructure retention. Error logs contain an error category, not request bodies, artifact contents or credentials. Hash chaining is tamper-evident relative to a trusted checkpoint, not cryptographic witnessing against a database administrator.

Use only synthetic, non-sensitive material in this experimental review candidate. Never upload payment-card data covered by PCI DSS, protected health information, government identifiers, passwords, API keys, one-time codes or other authentication secrets. User permission does not make these restricted categories acceptable plugin inputs. All verification data in this candidate is synthetic. See the [OpenAI plugin data-collection requirements](https://developers.openai.com/plugins/plugin-guidelines#data-collection).
