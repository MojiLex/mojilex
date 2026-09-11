# Dataset release staging

Tags matching `data-YYYY.MM.DD.N` run a validation workflow and upload the exact
`dist/index` file tree as a short-lived GitHub Actions artifact. This artifact is
for CI review and reproducibility checks only. It is not an official MojiLex
snapshot publication, a transport bundle, or a GitHub Release.

The current MVP manifest declares `storage.mode = git-native`,
`build.parameters.bundle_mode = none`, and `bundles = []`. Consequently, the
workflow must not wrap the snapshot in an undeclared `.tar.gz` carrier or publish
that carrier as an official release asset. GitHub Actions' own artifact envelope
is outside the dataset protocol and must not be offered to readers as a manifest
bundle.

Official transport publication remains disabled until the project implements one
of the carriers declared by the distribution contract:

- a verified relative-path tree whose files are served at their manifest paths;
- the normative deterministic `tar-zstd` bundle mode, with matching bundle
  descriptors and reader support.

Promotion must preserve every file byte and relative path from the validated CI
staging build, then validate the published carrier through the same manifest,
resource, artifact, size, and hash checks. Creating an official GitHub Release is
therefore a separate future workflow, not a side effect of the validation tag.
