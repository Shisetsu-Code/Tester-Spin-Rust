# GitHub Actions game coverage audit

## Purpose and scope

Run the checked-in engine on a clean GitHub-hosted runner and identify the
games that finish OK, PARCIAL, ERROR or cannot be executed. The initial audit
samples at most three distinct games from each of the 24 registered providers.
It is a bounded catalog sample, not a claim about every game in a provider.

The application is a Rust/egui desktop interface with a vendored Python engine.
The main workflow tests Rust on Windows and the Python suite on Ubuntu, and runs
the same Python scheduler used by the desktop bridge through the existing
independent CLI. No local Windows paths, personal database, VPN or historical
execution contracts are imported.

## Historical baseline and current report views

Keep the [original audit](../../reports/2026-10-27-actions/README.md) as the
historical baseline. Its missing fixtures/helpers and Rust dependency on a
developer SQLite database were findings of that checkout, not requirements for
running the corrected repository.

The [corrections report](../../reports/2026-10-27-fixes/README.md) separates:

- **Original:** the initial 72-game observation and its original test failures.
- **Primary:** the comparable 72-game campaign in `games.json` / `games.csv`,
  preserving every result from that campaign.
- **Latest:** [latest-games.csv](../../reports/2026-10-27-fixes/latest-games.csv)
  and `latest-games.json`, which incorporate explicitly identified fresh
  follow-ups for the same provider/slug cohort. This is not one campaign.

Each updated game retains its run, commit and artifact origin and the primary
observation. For example, the primary Hacksaw HTTP 404 failures remain recorded
even though a subsequent run with the same engine completed successfully.
The cause of those earlier responses remains undetermined.

Consult the report's `verification.json` for CI evidence tied to each commit.
The primary campaign verified 173 Python tests and four Rust tests in Actions;
batch 2 verified 190 Python tests. Batch 3 confirmed **220 Python tests** both
locally and in [Actions 40561470969](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40561470969)
for commit `20a5f9f`. Its three Yggdrasil game results remain PARCIAL because of
unsupported return outcomes, detailed in [the Yggdrasil report](../../reports/2026-10-27-fixes/YGGDRASIL.md).
Keep the Rust evidence from the primary commit separate from this focused run.

## Execution design

1. Collect and persist a small public catalog sample for each provider. Keep
   the selected identities in `selected-games.json` before game execution.
2. Use `tester_spin.cli run` with `--statuses ALL --spins 2 --timeout 30
   --wall-timeout 240`, up to eight independent provider jobs at a time.
3. Preserve the engine's final status and coverage gates. `--spins 2` also
   sets the scheduler's sample target for each observed path. Some incomplete
   adapters only implement one base round; the report exposes actual attempts.
4. Read the final SQLite callback payload, not a potentially earlier
   `run_dir/result.json` or manual GUI override. Export a sanitized JSON, CSV
   and Markdown report, with bounded evidence JSON files.
5. Aggregate all reports and keep build/unit failures visible separately.

A successful Actions job means the audit ran and wrote its report. It does
not mean the games passed. The CLI itself can exit zero when a completed
batch contains only partial or error results.

Five current registry entries have no executable adapter: greentube, netent,
pgsoft, blueprint and wazdan. They are reported separately as SIN_EJECUTOR.
Missing catalog samples and missing result payloads never count as OK.

## Bounds and evidence

Catalog discovery has a 180-second limit. Each game has the existing worker's
240-second wall limit and cgroup v2 process cleanup. The batch has a
900-second guard. A timeout is evidence of an incomplete execution, not
permission to replay an uncertain purchase. The workflow never automatically
retries gameplay. The report identifies remaining work for a subsequent run.

The sampler permits up to 100 catalog pages while selecting only the requested
number of games. Some providers, including RubyPlay's REST catalog, validate
all pages before emitting their first records. A one-page limit would prevent
those providers from returning any sample. The targeted RubyPlay validation
uses a 240-second catalog bound; the initial failed selection made no gameplay
requests. The original report records that replacement validation separately.

The aggregate compares uploaded reports with the expected provider matrix and
explicitly flags missing artifacts. Its completeness flag describes report
availability; each game's status remains the engine's canonical final status.

Only public demo entry points supplied by the adapters are used. The standard
audit uploads bounded sanitized result/coverage JSON, not complete databases or
raw session-bearing captures. Its artifacts record the code commit and exact
resolved Python dependency versions. The diagnostic workflow below additionally
exports sanitized protocol evidence; those exports are not unredacted HARs.

## Reproducible tests

Install `requirements-ci.txt` and run `python -m unittest discover -s tests -v`
from the repository root. Create the scratch `evidence` directory first, as the
workflows do for tests that create temporary subdirectories there. The suite
uses versioned fixtures instead of requiring a developer's ignored `data` or
`evidence` contents. Added synthetic fixtures are labelled explicitly; see
[fixture provenance](../../tests/fixtures/REPRODUCIBILITY.md). They are unit-test
inputs, not remote captures or authorization to execute a demo.

Run `cargo test --locked` on the supported Windows desktop target with Python
and the same Python dependencies installed. The integration test creates a
temporary project/configuration and SQLite catalogue, invokes the real bridge
in dry-run mode and checks that no gameplay results were created. It does not
need a pre-existing catalogue or the Python path from a developer's config.
`TESTER_SPIN_TEST_PYTHON` can select the interpreter; otherwise the test uses
`python` on Windows and `python3` elsewhere. Temporary integration data is
removed after the test.

## Run it

After the workflow is on the repository's default branch, run **Game coverage
audit** from Actions using `providers=all`, or a comma
separated list of registered provider keys. `games_per_provider` supports
1, 3, 5 or 15. Pushes of audit code to `ci/game-audit-*` also trigger a
three-game sample. Documentation-only report commits do not launch a new run.

The `game-audit-combined` artifact is the full aggregate. Each `audit-<provider>`
artifact contains the provider report and sanitized coverage evidence.
`python-unit-results` contains the full Python test output and dependency list.
Build/unit outcomes and game outcomes must be inspected separately.

## Focused diagnostic protocol capture

**Diagnostic protocol evidence** (`.github/workflows/diagnostic-capture.yml`)
currently targets only **Yggdrasil**. Select the exact reviewed branch/commit
when dispatching it; this focused workflow is not the 24-provider campaign.
Matching changes on `ci/evidence-*` branches can also trigger it.

The workflow first installs dependencies and runs the **complete Python suite**.
It then freezes three catalogue identities and uses the existing independent
CLI, fresh demo sessions and the same two-samples-per-path target. Catalogue
collection is bounded at 240 seconds; execution retains the 900-second batch
and 240-second game limits. It does not replay an uncertain wager identifier.

An `always()` reporting step exports `audit.json`, `audit.csv` and `audit.md`
from canonical final results, including catalogue/execution exit codes. The
public CLI `summary.json` provides a separate batch checkpoint. A diagnostic
job can finish successfully while games remain PARCIAL or ERROR; read those
statuses and their evidence, not the job colour, to assess game coverage.

The `diagnostic-yggdrasil` artifact includes the commit, full test log, selected
identities, canonical audit and `protocol/index.json`. The passive exporter can
include captured HAR request/response structures, XML and public source assets
as **sanitized JSON exports**, with source hashes and explicit skipped-file
records. Binary payloads are omitted; cookies, session identifiers, tokens and
other secrets are redacted. Export bounds are 32 MiB per source file and
180 MiB total, and artifact retention is seven days. Missing or redacted
evidence is a limitation, not proof of successful execution or complete paid
inventory. Keep these exported records distinct from raw private capture files.
