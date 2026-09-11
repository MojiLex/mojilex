## Summary

Describe the narrowly scoped data/schema/policy change.

## Source and affected entities

- Source URL or non-secret reference:
- Collection IDs:
- Emoji IDs:
- Membership/tombstone IDs:
- Review status and reviewer basis:

## Validation

- [ ] `python tools/validate.py . --strict`
- [ ] `python -m unittest discover -s tests -v`
- [ ] The change is deterministic/no-op safe and `dist/` was not committed.
- [ ] Russian and English descriptions express the same observable meaning.
- [ ] Sensitive/adult/unknown or warned content is manually approved.
- [ ] Facet values are sorted and come from the active taxonomy; rendering and
      fingerprints cover every media role/variant and use the manifest profiles.
- [ ] Any unreviewed AI record exactly matches an active qualification, or a
      human has approved it; no computed `blocking` review reason remains.
- [ ] Visual relations are current human-approved decisions with fresh media
      digests and independently recomputed relation hashes.

## Media, privacy, and licensing declaration

- [ ] I included no original emoji, frame, screenshot, contact sheet, archive,
      Git LFS pointer, credential, raw download URL, or quarantined material.
- [ ] I have the right to submit this contribution.
- [ ] I license contributed code, JSON Schema, and documentation under MIT.
- [ ] I dedicate contributed metadata, descriptions, tags, and examples under
      CC0-1.0 to the extent I hold the necessary rights.
- [ ] I understand MojiLex grants no rights to third-party media or trademarks.
