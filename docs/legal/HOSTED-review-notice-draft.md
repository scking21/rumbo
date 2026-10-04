# Rumbo Sites candidate data handling

Separate experimental notice for review · 4 October 2026

This describes the optional owner-private Sites candidate, not the local plugin. It is not a launch-ready privacy policy. Use only synthetic, non-sensitive material while the deployment remains experimental.

Sites supplies a signed-in user ID and verified email. Rumbo uses the ID for authorization and does not persist the email or name. Its D1 database stores project membership and roles, worker attribution, requests, criteria, task and evidence history, decisions, upload reservations and hashed browser-session identifiers. R2 stores the UTF-8 artifact content you upload.

These records support access control, coordination, review and owner export. Project information may be available to the deployment operator, authorized project members and connected AI clients through their permitted workflows. Sites provides the hosting and managed sign-in. Hosting and connected AI clients process requests under their own policies. Project access depends on authenticated identity and configured membership. The candidate cannot read your laptop files, retrieve your repository or execute shell tests.

There is no automatic retention or deletion schedule. Contract, event and artifact history is retained. Expiring a session does not delete its historical records. Owners can download an export of the retained ledger and artifact bytes. Hosted restore and self-service deletion are not implemented; a tested operator deletion procedure, including provider-held copies, is not yet established.

You choose what to upload and can use the owner export to download retained project data. Avoid confidential or personal information in the experimental candidate. Do not submit payment-card data, protected health information, government identifiers, passwords, API keys, one-time codes or other authentication secrets. General questions can go to [Rumbo's public issue tracker](https://github.com/scking21/rumbo/issues); do not include private project data there.

Before this becomes a public service policy, confirm the actual operator and a suitable contact for private requests, live provider data handling, retention and deletion procedure, and deployed access behavior. Do not publish the local privacy notice as if it covers this hosted service.
