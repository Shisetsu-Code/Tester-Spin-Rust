# Offline fixture provenance

These fixtures make the unit suite reproducible without ignored `data/` or
`evidence/` directories. They are not execution authority or live audit results.

Existing versioned fixtures were searched before adding replacements:

- `elk-capi-night/001-015*.xml` and `result.json` are the existing redacted CAPI
  campaign. `test_elk_campaign_import.py` now imports the already versioned
  `tester_spin.providers.elk_evidence.convert_case`, also used by the native
  executor. It does not depend on the missing historical `evidence/elk-store.py`.
- `playngo-gamehub/redacted-frames.json` is the existing frame fixture, reused
  without alteration. Its multibyte length prefix exercises the existing
  invocation decoder. Framing does not prove numeric action semantics or closure.
- Existing Push `big-bamboo`, `jammin-jars` and cascade fixtures retain their
  recorded step dialect; those files are unchanged.

## Explicitly synthetic additions

- `push-hive/synthetic-numeric-data-round.json`: authored minimal numeric-ID/data
  dialect with a 50-unit debit and 25-unit acknowledged credit. The unavailable
  Diamond Supernova HAR was **not** reconstructed or represented as a capture.
- `push-hive/synthetic-public-launcher.html`: authored parser input using the
  documented authority expected by the existing validator and an unusable marker
  token. It is not a captured public launcher or runtime session.
- `elk-capi-night/synthetic-purchase-observation.json`: authored purchase-only
  request/response exercising the primitive's quote, currency, round and public
  result checks. It is not a Ryze capture, settlement or inventory proof. The
  existing Night Trax public result dialect lacks a betlevel attribute required
  by this separate observation primitive, so that recording was not modified.
- `playson-rest/synthetic-bootstrap-contract.json`: synthetic contract wrapper
  around the existing `connect-request.xml`, with placeholder query values. Its
  SHA256 identifies the versioned source XML; it does not certify a launcher.
- `relax-rest/synthetic-bootstrap-contract.json`: synthetic contract wrapper
  around the existing `funmoneylogin.json` request. Its SHA256 identifies that
  file; it does not certify independent bootstrap provenance.

JSON additions include `_fixture.kind` and `network_capture: false`; synthetic
HTML has a leading warning comment. Tests read these files directly from
`tests/fixtures` and do not install them into provider runtime `analysis` folders.
The Rust integration test authors a synthetic catalogue row in a disposable
project and asserts that a real bridge dry run creates no gameplay results.
