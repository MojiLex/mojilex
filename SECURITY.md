# Security policy

## Supported versions

Security fixes apply to the current default branch and the latest published data
snapshot/schema-v1 tooling. Older snapshots are immutable historical artifacts
unless a targeted revocation is required.

## Reporting a vulnerability

Report vulnerabilities privately through a GitHub Security Advisory:
<https://github.com/MojiLex/mojilex/security/advisories/new>.

Do not disclose credentials, exploit details, personal data, or suspicious
media in a public issue. Include affected paths/versions, impact, reproduction
steps using synthetic text-only fixtures, and any proposed mitigation. We aim to
acknowledge ordinary reports within 72 hours; active credential exposure or
obviously illegal content receives immediate containment priority.

## Repository security model

Validation and index building are offline. CI never contacts Telegram, AI
providers, or data-supplied URLs. Pull requests run with read-only contents
permission. Contributor code is not run through `pull_request_target`.
Third-party actions are pinned to full commit SHAs.

Secrets, `.env` files, raw Telegram download URLs, binary media, Git LFS
pointers, and symlinks are rejected. Treat a detected token as compromised and
revoke/rotate it; deleting it from the latest commit is not sufficient.

This policy covers vulnerabilities in the schema and repository maintenance
tools. Product/CLI vulnerabilities should be reported to the corresponding
`MojiLex/mojilex-cli` security channel.
