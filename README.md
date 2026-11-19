# Enhantica code quality

A main-branch dashboard for crysta and edi. Each overview card compares C++ and Python side by side. Card accents group verification, maintainability, function structure, and code size. The trend view includes detailed component data.

## Preview

Run the two build commands from the repository root and open `dist/index.html` in a browser. Both pages are self-contained and use clearly labeled illustrative data by default.

```sh
python3 scripts/render.py
python3 scripts/render.py --trends --output dist/trends.html
```

## Collection and publishing

The workflow runs on this repo’s main branch, on dispatch, and weekly. Enable GitHub Actions as the Pages source. Until live publication is enabled, deploys contain only the demo.

The collector requests read access to Actions and Contents for both product repositories. It uses the existing Enhantica app configuration by default. The repository variable `QUALITY_APP_ID` and secret `QUALITY_APP_KEY` can point it to a different app.

Run the workflow manually with `collect_only=true` to download the `quality-dashboard-report` Actions artifact. Open `index.html` from the extracted archive. The same run saves its machine-readable metrics as `quality-snapshots`. Set `QUALITY_PUBLISH_LIVE` to `true` to publish live aggregates once the Pages audience is confirmed. The current Pages site is public.

The workflow checks out each project's own main commit. BCA reads the declared production C++ and Python source roots. Metrics include physical code lines, logical lines, file and function counts, median file Visual Studio MI for files with measured Halstead volume, documentation lines, and nearest-rank 90th percentiles across functions for cyclomatic complexity, cognitive complexity, physical code lines, arguments, and exits. Reports contain aggregates and public edi function links. The crysta report omits function names and source paths. The analyzers suppress diagnostics that could quote source in Actions logs.

Doxygen counts the documented declarations it extracts from public headers, excluding private members and the `detail` namespace. Python docstring coverage counts handwritten modules, public classes, and their public functions and methods. The API documentation card shows those percentages alongside BCA's count of documentation lines across the measured source. The test coverage card includes crysta's compiled Python binding coverage, measured over public API entries.

Clang, sanitizer and docs results come from completed push runs for the measured commit. Unit test coverage uses the existing `unit-coverage` artifact from a coverage dispatch on main at that same commit. The dashboard also accepts a verified artifact when both coverage steps and its upload passed before a later workflow step failed. Missing runs and expired artifacts leave a metric unmeasured. The workflow retains only normalized dashboard data and reuses it for history. It does not dispatch coverage jobs or publish source, logs, or raw analysis reports.

To sample local committed sources, install BCA 2.6.0 and optionally Doxygen, then run:

```sh
python3 scripts/collect.py --crysta /path/to/crysta --edi /path/to/edi --output /tmp/quality.json
python3 scripts/render.py --data /tmp/quality.json
python3 scripts/render.py --data /tmp/quality.json --trends --output dist/trends.html
```

### Dashboard colors

Green marks a passed check or a value within its target or advisory reference. Amber flags a value for review. Red identifies a failed check. Blue marks measured counts and other values without targets. Gray marks unavailable results.

Function P90 references are presentation defaults and do not change product CI gates. The dashboard starts with McCabe complexity at 12 for C++ and 10 for Python, cognitive complexity at 15, function length at 50 physical lines, arguments at 5, and explicit exits at 8. The median file MI uses the Visual Studio green boundary of 20. Functions per file is a measured ratio, with a review signal for an increase above 10% from the previous sample. Test coverage keeps each producer's declared target.

### edi measurement workflow

Run **edi coverage and static checks** to refresh edi's coverage and code-quality results. It uses one standard Linux runner and the exact crysta pin in edi's lock. The SDK, source checkout, and compiler logs stay on the runner. The workflow publishes only coverage counts and check outcomes, and a successful run refreshes Pages.

The C++ figure uses edi's instrumented core unit tier. Python uses the unit tier's statement coverage and requires a completed JUnit report with no failed tests. The Linux clang-tidy result covers the core, CLI, and bindings compilation database. Ruff uses edi's existing style task. The collector accepts this receipt only for the exact edi commit it is displaying.
