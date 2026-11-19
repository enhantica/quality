# Enhantica code quality

A main-branch dashboard for crysta and edi. The default view compares the two projects on metric cards. Choose C++, Python, or Both for source metrics. The coverage cards keep their explicit scope and the trend view includes detailed component data.

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

The workflow checks out each project's own main commit. BCA reads the declared production C++ and Python source roots. Metrics include physical code lines, logical lines, file and function counts, median file Visual Studio MI for files with measured Halstead volume, and the nearest-rank 90th percentile of function cyclomatic complexity. Reports contain aggregates and public edi function links. The crysta report omits function names and source paths. The analyzers suppress diagnostics that could quote source in Actions logs.

Doxygen counts the documented declarations it extracts from public headers, excluding private members and the `detail` namespace. Python docstring coverage counts handwritten modules, public classes, and their public functions and methods. Compiled Python bindings have a separate API test coverage card for crysta.

Clang, sanitizer and docs results come from completed push runs for the measured commit. Unit test coverage uses the existing `unit-coverage` artifact from a successful coverage dispatch on main at that same commit. Missing runs and expired artifacts leave a metric unmeasured. The workflow retains only normalized dashboard data and reuses it for history. It does not dispatch coverage jobs or publish source, logs, or raw analysis reports.

To sample local committed sources, install BCA 2.6.0 and optionally Doxygen, then run:

```sh
python3 scripts/collect.py --crysta /path/to/crysta --edi /path/to/edi --output /tmp/quality.json
python3 scripts/render.py --data /tmp/quality.json
python3 scripts/render.py --data /tmp/quality.json --trends --output dist/trends.html
```
