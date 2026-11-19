# Enhantica code quality

A code quality dashboard for crysta and edi. Choose **Current main** to compare both projects or a published release to see that project's tagged commit. The picker includes crysta SDK prereleases. Every card shows C++ and Python side by side.

## Preview

Run the two build commands from the repository root and open `dist/index.html` in a browser. Both pages are self-contained and use clearly labeled illustrative data by default.

```sh
python3 scripts/render.py
python3 scripts/render.py --trends --output dist/trends.html
```

## Collection and publishing

The dashboard refreshes daily at 08:25 Stockholm time, on pushes to this repo’s main branch, and on dispatch. At 25 minutes past each other hour it checks both product repositories for new published releases and refreshes when it finds one. The edi measurement workflow runs daily at 07:15 and also triggers a dashboard refresh after a successful run. Enable GitHub Actions as the Pages source. Until live publication is enabled, deploys contain only the demo.

The collector requests read access to Actions and Contents for both product repositories. It uses the existing Enhantica app configuration by default. The repository variable `QUALITY_APP_ID` and secret `QUALITY_APP_KEY` can point it to a different app.

Run the workflow manually with `collect_only=true` to download the `quality-dashboard-report` Actions artifact. Open `index.html` from the extracted archive. The same run saves its machine-readable metrics as `quality-snapshots`. Set `QUALITY_PUBLISH_LIVE` to `true` to publish live aggregates once the Pages audience is confirmed. The current Pages site is public.

The workflow checks out each project's own main commit. BCA reads the declared production C++ and Python source roots. Metrics include physical code lines, logical lines, file and function counts, median file Visual Studio MI for files with measured Halstead volume, documentation lines, and nearest-rank 90th percentiles across functions for cyclomatic complexity, cognitive complexity, physical code lines, arguments, and exits. Reports contain aggregates and public edi function links. The crysta report omits function names and source paths. The analyzers suppress diagnostics that could quote source in Actions logs.

Doxygen counts the documented declarations it extracts from public headers, excluding private members and the `detail` namespace. Python docstring coverage counts handwritten modules, public classes, and their public functions and methods. The API documentation card shows those percentages alongside BCA's count of documentation lines across the measured source. The test coverage card includes crysta's compiled Python binding coverage, measured over public API entries.

Clang, sanitizer and docs results come from completed push runs for the measured commit. Unit test coverage uses an exact-commit coverage artifact or normalized edi receipt. The dashboard also accepts a verified artifact when both coverage steps and its upload passed before a later workflow step failed. For historical releases without a matching report, CI metrics show **No report**.

The [metrics-history branch](https://github.com/enhantica/quality/tree/metrics-history) keeps only normalized aggregates. Each publication adds a Git revision. The dashboard carries the latest 90 main snapshots and every collected release. Release source measurements use the exact tag commit and the same available production scopes as main. Captured CI evidence stays with its commit after the original artifact expires.

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

Run **edi coverage and static checks** to refresh edi's coverage and code-quality results. It uses one standard Linux runner and the exact crysta pin in edi's lock. The SDK, source checkout, and compiler logs stay on the runner. The workflow publishes only coverage counts and check outcomes, and a successful run refreshes Pages.

The C++ figure uses edi's instrumented core unit tier. Python uses the unit tier's statement coverage and requires a completed JUnit report with no failed tests. The Linux clang-tidy result covers the core, CLI, and bindings compilation database. Ruff uses edi's existing style task. The collector accepts this receipt only for the exact edi commit it is displaying.
