# Sanitized release evidence

Files in this directory preserve claim-relevant host readbacks without
committing machine identifiers, temporary paths, logs, credentials, or local
configuration.

Each evidence record identifies the public source, immutable commit or release
asset, installed version, host-visible result, and SHA-256 of the original raw
readback. Raw host files are intentionally not tracked because they contain
ephemeral absolute paths and host state.

These records prove only the scoped claims they name. They do not establish a
vendor-curated directory listing, untested visual picker behavior, or live
session restoration.
