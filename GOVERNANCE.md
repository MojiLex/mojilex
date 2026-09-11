# Governance

MojiLex uses a maintainer-led governance model for the MVP.

## Roles

- **Owner** manages the organization, repository permissions, branch rules,
  releases, and emergency actions.
- **Maintainers** review and merge ordinary changes and may publish only within
  explicitly granted repository permissions.
- **Reviewers** verify source/description quality and may set review and manual
  availability states. Reviewer identity is recorded as a public project handle.
- **Contributors** propose changes through forks and pull requests.

The current owners are represented by `CODEOWNERS`. Adding or removing a
maintainer requires an owner-approved pull request that updates that file and
this document when responsibilities change.

## Decisions

Routine data changes require passing CI and code-owner review. Schema, licensing,
moderation, and release-policy changes require explicit owner approval. Decisions
are documented in the pull request. Backward-incompatible format changes require
a new major schema version; the schema-v1 UUID namespace is immutable after the
first public release.

No reviewer should decide an appeal of their own moderation decision when
another reviewer is available. If there is only one owner/reviewer, the decision
and conflict are documented without disclosing sensitive complaint details.

## Releases

The Git commit is the dataset revision. Snapshot tags use
`data-YYYY.MM.DD.N`. Generated `dist/` artifacts are reproducible from the tagged
commit and are not the source of truth.

## Emergency authority

The owner may temporarily restrict merges, revoke credentials, remove dangerous
current-tree content, or initiate the narrow history-rewrite procedure described
in `TAKEDOWN.md`. Emergency action must be documented after containment without
republishing the removed information.
