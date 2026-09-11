# Quality registries

These files are normative offline inputs for AI provenance and review routing.
`model-qualifications.json` starts empty: no provider/model combination is
officially qualified until a rights-cleared `golden-v1` benchmark and holdout
report pass every mandatory gate. A qualification is immutable except for the
one-way transition from `active` to `revoked`; extension creates a new ID.

Likewise, no dedupe holdout report is fabricated: the required rights-cleared
or synthetic set of at least 500 labelled pairs must be measured by the CLI
before a future profile/ruleset is claimed as benchmark-qualified.

The repository intentionally includes no invented benchmark measurements or
third-party benchmark media. Benchmark fixtures and runners belong to
`mojilex-cli`; only verified report hashes and qualification records belong
here.
