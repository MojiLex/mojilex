# Taxonomy

`v1/` contains the immutable dictionaries used by schema 1.0.0. IDs are stable
lowercase kebab-case values. New values increment the taxonomy minor version;
wording-only clarification increments patch; changed meaning requires a new
major version. A deprecated ID remains resolvable and names one unambiguous
active `replaced_by` value, but new CLI output must not create it.

Each entry has bilingual names and definitions plus positive and negative text
examples. These examples never contain third-party media.
