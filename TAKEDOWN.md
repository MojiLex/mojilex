# Takedown policy

MojiLex accepts reports concerning copyright, trademark, privacy,
impersonation, security, legal requirements, and mistakenly published data.

## How to report

For a non-sensitive request, open the public **Takedown request** issue template.
For a report containing personal data, secrets, confidential evidence, or
potentially illegal material, do not open an issue: use a private GitHub Security
Advisory at <https://github.com/MojiLex/mojilex/security/advisories/new>.

Include the affected MojiLex ID/path, the applicable category, your relationship
to the material, a concise explanation, and a safe means for maintainers to
verify the claim. Do not attach disputed media or reproduce personal data.

We target an initial review within 72 hours for ordinary reports. Credential
exposure and obviously illegal material are handled as quickly as practicable.
This is a response target, not a promise of final resolution.

## Outcomes

Ordinary platform unavailability is not a takedown: the full record remains with
an availability status. A substantiated takedown removes the affected current
record and cascading memberships, then may leave only a schema-valid anonymized
tombstone with one of the public reason codes. A tombstone must never contain a
platform/native ID, URL, title, description, media hash, personal data, or text
from the complaint.

- Emoji takedown removes every membership referencing that emoji.
- Collection takedown removes its memberships but preserves unrelated emoji.
- Membership takedown removes only the relationship.
- No public record may reference an entity absent from the current tree.

Removal from the current tree does not remove prior Git objects, forks, caches,
or downloads. If law, safety, or privacy requires history removal, the owner may
run a separate documented emergency procedure: rewrite only affected history,
revoke affected snapshots/releases, point users to a clean snapshot, coordinate
with hosting providers as needed, and publish a notice that does not repeat the
removed data. Credentials found in history are revoked regardless of rewrite.

Appeals should reference the decision without republishing removed information.
Another reviewer handles the appeal where possible.
