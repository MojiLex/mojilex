# Normative examples and test vectors

The JSON documents in this directory are textual, non-media fixtures. They do
not assert ownership of, or redistribute, any Telegram artwork.

`telegram/collection.json`, `telegram/emoji.json`, and
`telegram/membership.json` form one internally consistent example. Their UUIDv5
identifiers and the Telegram set fingerprint are normative schema-v1 vectors.
`facets/adaptive-icon.json` and `facets/number-404.json` demonstrate adaptive
rendering without a fabricated palette and literal numeric text respectively.
`visual-relation.json` fixes the reviewed relation shape and UUIDv5 rule.
`test-vectors.json` also fixes NUL-delimited UTF-8 identity bytes, media and
review hashes, one- and sixteen-sample pHash decoding, and stable duplicate
group IDs.

Examples use illustrative metadata only and are released under CC0-1.0. They
are not canonical records under `data/`.
