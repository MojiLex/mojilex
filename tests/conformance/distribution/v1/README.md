# SPEC-003 Stage A/B conformance fixture

`valid/snapshot-a-monolith/fixture.json` pins a deliberately small synthetic
metadata source set. The fixture contains no media bytes and grants only the
metadata/annotation operations of the selected rights profile. Its source
records reuse the repository's visibly synthetic examples by exact SHA-256, so
changing an example does not silently change the fixture.

`tests/test_conformance_distribution_v1.py` installs those pinned records in a
fresh canonical source tree, builds a monolith snapshot, runs the independent
distribution validator, traverses the complete search-to-rights relationship,
and compares every emitted file with `expected-hashes.json`. This makes a joint
builder/validator drift visible without committing a second copy of all embedded
schema and profile resources.
