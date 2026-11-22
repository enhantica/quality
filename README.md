# Enhantica code quality

A code quality dashboard for edi and the crysta SDK it uses. The picker lists **main** first, then published edi releases newest first, and opens at the latest release. Every card shows edi and the crysta commit pinned by that edi version, with C++ and Python side by side.

## Preview

Run the two build commands from the repository root and open `dist/index.html` in a browser. Both pages are self-contained and use clearly labeled illustrative data by default.

```sh
python3 scripts/render.py
python3 scripts/render.py --trends --output dist/trends.html
```

## Collection and publishing

The dashboard refreshes daily at 08:25 Stockholm time, on pushes to this repo’s main branch, and on dispatch. At 25 minutes past each other hour it looks for a new edi release or a changed edi main SDK pin. The edi measurement workflow runs daily at 07:15 and also triggers a dashboard refresh after a successful run. Enable GitHub Actions as the Pages source. Until live publication is enabled, deploys contain only the demo.

The collector requests read access to Actions and Contents for both product repositories. It uses the existing Enhantica app configuration by default. The repository variable `QUALITY_APP_ID` and secret `QUALITY_APP_KEY` can point it to a different app.

Run the workflow manually with `collect_only=true` to download the `quality-dashboard-report` Actions artifact. Open `index.html` from the extracted archive. The same run saves its machine-readable metrics as `quality-snapshots`. Set `QUALITY_PUBLISH_LIVE` to `true` to publish live aggregates once the Pages audience is confirmed. The current Pages site is public.

The workflow checks out edi main and reads each selected edi commit's `CRYSTA_COMMIT` in `pixi.toml`. It measures or reuses the exact pinned crysta commit. BCA reads the declared production C++ and Python source roots. Metrics include physical code lines, logical lines, file and function counts, median file Visual Studio MI for files with measured Halstead volume, documentation lines, and nearest-rank 90th percentiles across functions for cyclomatic complexity, cognitive complexity, physical code lines, arguments, and exits. Reports contain aggregates and public edi function links. The crysta report omits function names and source paths. The analyzers suppress diagnostics that could quote source in Actions logs.

Doxygen counts the documented declarations it extracts from public headers, excluding private members and the `detail` namespace. Python docstring coverage counts handwritten modules, public classes, and their public functions and methods. The API documentation card shows those percentages alongside BCA's count of documentation lines across the measured source. The test coverage card includes crysta's compiled Python binding coverage, measured over public API entries.

Clang, sanitizer and docs results come from completed push runs for the measured commit. Unit test coverage uses an exact-commit coverage artifact or normalized edi receipt. The dashboard also accepts a verified artifact when both coverage steps and its upload passed before a later workflow step failed. For historical releases without a matching report, CI metrics show **No report**.

The [metrics-history branch](https://github.com/enhantica/quality/tree/metrics-history) keeps only normalized aggregates. Each publication adds a Git revision. The dashboard carries the latest 90 edi main snapshots and every collected edi release, whose crysta snapshots are indexed by SDK commit. Captured CI evidence stays with its commit after the original artifact expires.

To sample local committed sources, install BCA 2.6.0 and optionally Doxygen, then run:

```sh
python3 scripts/collect.py --crysta /path/to/crysta --edi /path/to/edi --output /tmp/quality.json
python3 scripts/render.py --data /tmp/quality.json
python3 scripts/render.py --data /tmp/quality.json --trends --output dist/trends.html
```

### Dashboard colors

Hover over, focus, or tap a card heading or value to see its definition and color bands. Select the source link to open the recommendation, dashboard policy, or the CI setting at the measured commit. Green marks a passed check or a value within its reference. Amber flags a value for review. Red flags a failed check or a value that warrants attention. Blue marks measurements without a target. Gray marks unavailable results.

- BCA's median file maintainability index is a score on the 0–100 scale. This view uses the [Visual Studio reference](https://learn.microsoft.com/en-us/visualstudio/code-quality/code-metrics-maintainability-index-range-and-meaning), with green at 20 or higher, amber from 10 to below 20, and red below 10.
- Test coverage uses each producer's declared CI target. It is green at or above the target and red below it.
- Function P90 is green at or below its reference and amber above it. The dashboard uses **10** for cyclomatic complexity from [NIST SP 500-235, §2.5](https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication500-235.pdf#page=35), **25 for C++ and 15 for Python** cognitive complexity from [SonarSource S3776](https://community.sonarsource.com/t/cognitive-complexity-for-python-vs-c/45303), and **5 arguments and 5 explicit exits** from the [BCA 2.6.0 defaults](https://github.com/dekobon/big-code-analysis/blob/v2.6.0/big-code-analysis-cli/src/default_thresholds.rs). These published per-function references are applied to BCA’s 90th-percentile summaries.

#### API documentation

The dashboard uses advisory coverage bands. Green is 80% or higher, amber is 50% to below 80%, and red is below 50%. The adjacent documentation-line count is blue.

#### Function length

The dashboard uses 50 physical code lines as its P90 reference. Green is at or below 50 and amber is above it.

#### Functions per file

The dashboard marks increases of at most 10% from the previous ratio as green and larger increases as amber. It uses blue when there is no prior positive ratio for the same project and language. The function and file counts are blue.

### edi measurement workflow

**edi coverage and static checks** measures edi main daily. The dashboard queues the newest published edi release when coverage is missing and no measurement has been attempted for that commit. To retry a release manually, dispatch the workflow with its full edi commit SHA. Each run uses the exact crysta pin from that edi commit and reuses a qualified Linux SDK from edi’s own CI when available. The SDK, source checkout, and compiler logs stay on the runner. A verified coverage result for either language is published independently and refreshes Pages.

The C++ figure uses edi's instrumented core unit tier. Python uses the unit tier's statement coverage and requires a completed test report. A completed suite with failing tests displays its measured coverage in red and explains the failure count in the tooltip. The Linux clang-tidy result covers the core, CLI, and bindings compilation database. Ruff uses edi's existing style task. The collector matches each receipt to both the edi commit and its crysta pin, and keeps previous verified measurements for either language on that same commit.

### crysta SDK measurement workflow

The dashboard queues **crysta SDK measurements** for newly observed pins and for the active edi main and latest release pins when their recorded checks or coverage are incomplete. After uploading a receipt, the measurement workflow dispatches a dashboard refresh. An Actions dispatch can also measure any full crysta SHA already recorded as a pin in edi's snapshot history. When only Python coverage is missing, the retry keeps the earlier check and C++ results.

The workflow uses the pinned crysta commit's Linux clang-tidy, Ruff lint and format, LLVM C++ unit coverage, and narrow Python public API coverage tasks. Its private checkout, test output, and compiler logs stay on the ephemeral runner. The sole uploaded receipt contains the commit, the run ID, two check outcomes, and available aggregate coverage counts.
