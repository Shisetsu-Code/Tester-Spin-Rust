# GitHub Actions game coverage audit

## Purpose and scope

Run the checked-in engine on a clean GitHub-hosted runner and identify the
games that finish OK, PARCIAL, ERROR or cannot be executed. The initial audit
samples at most three distinct games from each of the 24 registered providers.
It is a bounded catalog sample, not a claim about every game in a provider.

The application is a Rust/egui desktop interface with a vendored Python engine.
The workflow tests Rust on Windows and the Python suite on Ubuntu, and runs
the same Python scheduler used by the desktop bridge through the existing
independent CLI. No local Windows paths, personal database, VPN or historical
execution contracts are imported.

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
requests and is replaced by that validation in the published campaign report.

The aggregate compares uploaded reports with the expected provider matrix and
explicitly flags missing artifacts. Its completeness flag describes report
availability; each game's status remains the engine's canonical final status.

Only public demo entry points supplied by the existing adapters are used.
Raw HARs, complete databases and session-bearing private captures are not
uploaded; reports use the engine's sanitizer. Each artifact records the code
commit and exact resolved Python dependency versions.

## Run it

After the workflow is on the repository's default branch, run **Game coverage
audit** from Actions using `providers=all`, or a comma
separated list of registered provider keys. `games_per_provider` supports
1, 3, 5 or 15. Pushes of audit code to `ci/game-audit-*` also trigger a
three-game sample. Documentation-only report commits do not launch a new run.

The `game-audit-combined` artifact is the full aggregate. Each `audit-<provider>`
artifact contains the provider report and sanitized coverage evidence.
`python-unit-results` contains full test output, including baseline problems
caused by fixtures or helper files missing from the published repository.
