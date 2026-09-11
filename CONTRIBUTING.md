# Contributing to MojiLex data

Thank you for improving the open semantic index. Contributions are accepted
through a fork and pull request. Direct pushes are limited to explicitly
authorized maintainers.

## Before opening a pull request

1. Work from an up-to-date branch of `MojiLex/mojilex`.
2. Use `mojilex-cli` for imports when available, or edit textual records with
   exceptional care. Do not add an importer to this repository.
3. Do not commit original WebP/TGS/WebM files, frames, screenshots, contact
   sheets, archives, Git LFS pointers, caches, temporary files, or credentials.
4. Do not publish quarantined, illegal, privacy-sensitive, or unreviewed
   sensitive/adult/unknown content.
5. Preserve manual approved descriptions when the referenced media hashes have
   not changed. A semantic/media/provenance change resets review to `unreviewed`.
6. Keep candidate lists, comparison sheets, decoded media, and local LSH/BK-tree
   indexes out of Git. Only approved human visual relations are canonical.
7. Run the complete offline checks:

   ```bash
   python -m pip install -r requirements-dev.txt
   python tools/validate.py . --strict
   python -m unittest discover -s tests -v
   ```

## Data rules

- Keep all identity components Unicode NFC and free of U+0000.
- Store platform numeric IDs as JSON strings.
- Put platform-only fields under `extensions.<platform>`.
- Supply both `ru` and `en` descriptions with equivalent meaning.
- Describe observable content and principal motion; do not invent a story or
  infer a person, character, or brand without adequate visual evidence.
- Keep semantic tags in unique lowercase kebab-case English.
- Keep controlled content types, styles, and suggested uses in `facets`, not in
  `semantic_tags`; literal visible text stays in `facets.text_content`.
- Do not copy a description between native IDs merely because fingerprints
  match, and never merge or delete native identities during deduplication.
- Do not submit unreviewed AI output unless its full provenance tuple matches an
  active qualification registry entry. Human approval is required otherwise.
- Record public provenance. Handles must be GitHub logins or stable project
  handles, never email addresses.
- Do not update timestamps on a no-op import. `last_verified_at` changes only
  after an explicit, successful source check or documented reviewer decision.
- Do not physically delete ordinary unavailable/deleted entities. Physical
  removal is reserved for the takedown/security/privacy process.

## Pull request scope

Prefer one collection or one tightly related policy/schema change per pull
request. Explain the source, affected IDs, review state, and whether a generated
index changes. CI is read-only and does not contact Telegram, AI providers, or
URLs contained in the pull request.

Schema changes require tests and examples. Backward-incompatible changes need a
new major schema directory. Do not silently change the v1 namespace or normative
vectors.

## Contribution license declaration

By submitting a contribution, you agree that:

- code, JSON Schema, and documentation you contribute are licensed under MIT;
- metadata, descriptions, tags, and example data you contribute are dedicated
  under CC0-1.0 to the extent you hold the necessary rights; and
- you have the right to make those grants and have not included third-party
  media, secrets, or material that you are not authorized to publish.

No separate contributor license agreement is required for the MVP.
