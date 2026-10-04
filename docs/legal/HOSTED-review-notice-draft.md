# Rumbo Sites candidate data handling

Separate experimental notice for review · 4 October 2026

This describes the optional owner-private Sites candidate, not the local plugin. It is not a launch-ready privacy policy. The deployed runtime remains v3, source `ca406c4`; the proposed changes below are source-only changes awaiting deployment review and do not change the published review policy. Use only synthetic, non-sensitive material while the deployment remains experimental.

Sites supplies a signed-in user ID and verified email. Rumbo uses the ID for authorization and does not persist the email or name. Its D1 database stores project membership and roles, worker attribution, requests, criteria, task and evidence history, decisions, upload reservations and hashed browser-session identifiers. R2 stores the UTF-8 artifact content you upload.

These records support access control, coordination, review and owner export. Project information may be available to the deployment operator, authorized project members and connected AI clients through their permitted workflows. Sites provides the hosting and managed sign-in. Hosting and connected AI clients process requests under their own policies. Project access depends on authenticated identity and configured membership. The candidate cannot read your laptop files, retrieve your repository or execute shell tests.

## Current deployed retention

The deployed v3 candidate has no automatic retention/deletion schedule or self-service project deletion. Contract, event and artifact history is retained. Browser sessions expire after one hour and worker sessions after 24 hours; expiry alone does not remove their database records. Owners can download an export of the retained ledger and artifact bytes. Hosted restore is not implemented; a tested operator deletion procedure covering provider-held copies is not yet established.

## Proposed source-only controls

The source change adds deletion in the signed-in owner browser, requiring the exact project ID and a fresh confirmation. It is not available through MCP. Export first if you need a copy: once deletion starts, the project is blocked for all members and cannot be restored in the hosted service. Cleanup works in bounded batches; a pending or interrupted deletion needs continuation and is not confirmation that all content has been removed.

On completion, application-held project content, uploaded file contents, membership, worker attribution and artifact metadata are removed. A hash-derived deleted-project key and empty objects at hash-derived project/content keys remain indefinitely to prevent delayed uploads from restoring content. They contain no filenames, emails, contract text or uploaded content, but the keys are pseudonymous and potentially linkable. This is not anonymous or zero-data erasure. The same owner cannot reuse that project ID.

Expired browser-session/CSRF rows are also removed on owner-page navigation in the source change. Expired worker attribution remains until project deletion. No automatic age-based project purge, application analytics/marketing tracking or model API is added.

These controls do not erase downloaded exports, copies received by connected clients or other recipients, or provider-managed backups and logs. Their deletion timing is unknown. Section 3.3 of the [ChatGPT Sites Data Processing Addendum](https://openai.com/policies/chatgpt-sites-data-processing-addendum/) assigns retention/deletion configuration and design responsibilities to the Site creator. It does not provide a verified backup/log deletion timetable for this candidate.

## Choices and review limits

You choose what to upload and can use the owner export to download retained project data. Avoid confidential or personal information in the experimental candidate. Do not submit payment-card data, protected health information, government identifiers, passwords, API keys, one-time codes or other authentication secrets. General questions can go to [Rumbo's public issue tracker](https://github.com/scking21/rumbo/issues); do not include private project data there.

Before this becomes a public service policy, confirm the actual operator and a suitable contact for private requests, live provider data handling, retention and deletion procedure, and deployed access behavior. Do not publish the local privacy notice as if it covers this hosted service.
