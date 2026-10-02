# Rumbo Sites candidate: data handling for review

This document describes the experimental hosted adapter only. It is not the final publisher-approved privacy policy or a claim of directory approval.

## Data received and stored

The Sites hosting boundary supplies a Site-scoped authenticated user ID and verified email. Rumbo requires both to identify a signed-in request; it uses the user ID for authorization and does not persist email or names. No workspace connectors, model APIs, billing integration, telemetry client, or external repository synchronization is configured.

D1 stores project owner/member Site IDs and roles; distinct worker-session IDs, labels and attribution; contract goals, original requests, constraints and acceptance criteria; hash-linked ledger events containing claims, artifact metadata, check receipts, reviewer assertions and owner decisions; uploaded-content quota reservations; and hashed browser-session/CSRF identifiers with expiration times.

R2 stores explicitly uploaded UTF-8 artifact bytes under a project-scoped content digest. Uploads are limited to 128 KiB each and 64 MiB of unique content per project. Historical bytes remain available for integrity and owner export. Filenames are display-only. The service cannot read or watch local files, retrieve repositories, execute shell tests, or infer provenance from a content hash.

## Access and authentication

Sites manages sign-in and OAuth. The candidate is owner-private unless its owner explicitly changes the Site's audience. Project memberships are an additional server-side restriction. A worker session is bound to its authenticated account and project. A reviewer requires a distinct, explicitly authorized account that has not opened a worker session for that project. These controls establish attribution; they do not prove organizational independence.

Owner create/revise/decision and role-grant actions use a separate same-origin signed-in browser session, CSRF checks and explicit confirmation dialogs. They are absent from MCP. Browser authorization is not proof of physical human presence. A delegated agent with the user's browser control can still act within the permissions the user gives it.

## Retention and export

No automatic retention or deletion schedule is implemented. The application retains contract, event and artifact history; an operator deletion procedure, including provider-held copies, has not yet been established or tested. Browser session tokens expire after one hour; worker sessions expire after 24 hours, but historical attribution records remain. Expiration does not itself delete database rows.

The owner can download an NDJSON export containing the verified ledger and all retained uploaded artifact bytes. `scripts/verify-export.py` checks completeness, event hashes and artifact digests. Hosted restore and self-service deletion are not implemented in this review candidate; the existing local distribution keeps its separately verified backup/restore workflow. A production retention/deletion and recovery procedure remains a release gate.

## Limits

Hosting and the connected AI client process requests under their own terms and platform policies. This repository cannot independently verify their infrastructure retention. Error logs contain an error category, not request bodies, artifact contents or credentials. Hash chaining is tamper-evident relative to a trusted checkpoint, not cryptographic witnessing against a database administrator.

Use only synthetic, non-sensitive material in this experimental review candidate. Never upload payment-card data covered by PCI DSS, protected health information, government identifiers, passwords, API keys, one-time codes or other authentication secrets. User permission does not make these restricted categories acceptable plugin inputs. All verification data in this candidate is synthetic. See the [OpenAI plugin data-collection requirements](https://developers.openai.com/plugins/plugin-guidelines#data-collection).
