#!/usr/bin/env python3
"""Collect commit-specific, publishable code metrics for crysta and edi."""
import argparse
import ast
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
from tempfile import TemporaryDirectory
import xml.etree.ElementTree as ET

SCOPES = {
    "crysta": {
        "include/crysta": "Public headers",
        "src/core": "Engine",
        "src/bindings": "Bindings",
        "src/cli": "Native CLI",
        "lib/crysta": "Python bootstrap",
    },
    "edi": {
        "core/include": "Core & headers",
        "core/src": "Core & headers",
        "lib/src": "Bindings",
        "cli": "Native CLI",
        "app/src": "Desktop app",
        "assistant/native": "Assistant native",
        "lib/edi": "Python package",
        "lib/easydiffraction": "Python import alias",
    },
}
HEADERS = {"crysta": "include/crysta", "edi": "core/include/edi"}
CXX_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}
CHECKS = {
    "Clang static analysis": re.compile(r"^clang-tidy\b", re.I),
    "Ruff": re.compile(r"^ruff\b", re.I),
    "Sanitizer tests": re.compile(r"addresssanitizer|threadsanitizer|asan|ubsan|sanitized", re.I),
    "Docs build": re.compile(r"docs.build|mkdocs", re.I),
}


def capture(*command, cwd=None):
    return subprocess.check_output(command, cwd=cwd, text=True)


def run_analyzer(tool, *arguments, cwd, input_text=None):
    # The dashboard workflow is public. Analyzer diagnostics can quote private source.
    result = subprocess.run([tool, *arguments], cwd=cwd, input=input_text, text=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if result.returncode:
        raise RuntimeError(f"{Path(tool).name} failed with exit code {result.returncode}")


def walk(space):
    yield space
    for child in space["spaces"]:
        yield from walk(child)


def summarize(records, scope, include_locations):
    components = Counter()
    hotspots = []
    file_scores = []
    function_count = logical_lines = documentation_lines = 0
    distributions = {
        "p90": [],
        "p90_cognitive": [],
        "p90_length": [],
        "p90_arguments": [],
        "p90_exits": [],
    }
    for file in records:
        name = file["name"]
        component = next(label for path, label in scope.items() if name.startswith(path + "/"))
        metrics = file["metrics"]
        physical = metrics["loc"]["ploc"]
        components[component] += physical
        logical_lines += metrics["loc"]["lloc"]
        documentation_lines += metrics["loc"]["dloc"]
        function_count += metrics["nom"]["functions"]
        if physical and metrics["halstead"]["volume"]:
            file_scores.append(metrics["mi"]["visual_studio"])
        for child in walk(file):
            if child["kind"] != "function" or child["metrics"]["nom"]["functions"] < 1:
                continue
            function = child["metrics"]
            complexity = function["cyclomatic"]["value"]
            distributions["p90"].append(complexity)
            distributions["p90_cognitive"].append(function["cognitive"]["value"])
            distributions["p90_length"].append(function["loc"]["ploc"])
            distributions["p90_arguments"].append(function["nargs"]["value"])
            # BCA's exit sum includes nested callable spaces. Those have their own rows.
            nested_exits = sum(space["metrics"]["nexits"]["sum"] for space in child["spaces"])
            distributions["p90_exits"].append(function["nexits"]["sum"] - nested_exits)
            row = {"score": complexity, "component": component}
            if include_locations:
                row.update(name=child["name"], path=name, line=child["start_line"])
            else:
                row["name"] = "Function in " + component
            hotspots.append(row)
    hotspots.sort(key=lambda row: (-row["score"], row.get("path", ""), row.get("line", 0)))
    return {
        "mi": statistics.median(file_scores) if file_scores else None,
        **{name: sorted(values)[math.ceil(0.9 * len(values)) - 1] if values else None
           for name, values in distributions.items()},
        "files": len(records),
        "functions": function_count,
        "logical": logical_lines,
        "documentation_lines": documentation_lines,
        "components": [{"name": name, "lines": value} for name, value in components.most_common()],
        "hotspots": hotspots[:6],
    }


def doxygen_counts(root, path):
    with TemporaryDirectory() as temporary:
        output = Path(temporary)
        config = f'''
INPUT = "{root / path}"
OUTPUT_DIRECTORY = "{output}"
FILE_PATTERNS = *.hpp *.h *.hxx *.hh
RECURSIVE = YES
EXTRACT_ALL = YES
EXTRACT_PRIVATE = NO
GENERATE_HTML = NO
GENERATE_LATEX = NO
GENERATE_XML = YES
QUIET = YES
'''
        run_analyzer("doxygen", "-", cwd=root, input_text=config)
        index = ET.parse(output / "xml" / "index.xml")
        symbols = {}
        for element in index.findall("compound"):
            xml = ET.parse(output / "xml" / (element.attrib["refid"] + ".xml"))
            for node in xml.findall(".//compounddef") + xml.findall(".//memberdef"):
                kind = node.get("kind")
                name = node.findtext("qualifiedname") or node.findtext("compoundname") or node.findtext("name")
                if node.get("prot", "public") != "public" or kind not in {
                    "class", "struct", "concept", "function", "typedef", "enum", "variable",
                } or not name or "detail" in name.split("::"):
                    continue
                location = node.find("location")
                if location is None:
                    continue
                file = (root / location.get("file", "")).resolve()
                if not file.is_relative_to(root / path):
                    continue
                key = (kind, name, node.findtext("argsstring"))
                descriptions = [n for n in (node.find("briefdescription"), node.find("detaileddescription")) if n is not None]
                documented = any("".join(n.itertext()).strip() for n in descriptions)
                symbols[key] = symbols.get(key, False) or documented
    if not symbols:
        raise ValueError(f"No eligible public-header symbols extracted from {path}")
    return {"covered": sum(symbols.values()), "total": len(symbols)}


def python_docs(root, files):
    symbols = []
    for file in files:
        try:
            tree = ast.parse((root / file).read_text(encoding="utf-8"))
        except SyntaxError:
            raise ValueError("Could not parse a Python source file for docstring metrics") from None
        symbols.append(tree)
        for node in tree.body:
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
                symbols.append(node)
                if isinstance(node, ast.ClassDef):
                    symbols.extend(child for child in node.body
                                   if isinstance(child, (ast.AsyncFunctionDef, ast.FunctionDef))
                                   and not child.name.startswith("_"))
    return {"covered": sum(bool(ast.get_docstring(node)) for node in symbols), "total": len(symbols)}


def workflow_run(repo, sha, workflow, event):
    rows = json.loads(capture("gh", "run", "list", "--repo", f"enhantica/{repo}", "--branch", "main",
                              "--workflow", workflow, "--commit", sha, "--event", event,
                              "--status", "completed", "--limit", "1", "--json", "databaseId,conclusion,url"))
    return rows[0] if rows else None


def test_results(repo, sha):
    run = workflow_run(repo, sha, "ci.yml", "push")
    if not run:
        return {}, None
    pages = json.loads(capture("gh", "api", "--paginate", "--slurp",
                               f"repos/enhantica/{repo}/actions/runs/{run['databaseId']}/jobs?per_page=100"))
    steps = [step for page in pages for job in page["jobs"] for step in job["steps"]]
    result = {}
    for label, pattern in CHECKS.items():
        conclusions = {step["conclusion"] for step in steps if pattern.search(step["name"])}
        useful = conclusions - {"skipped", None}
        if "failure" in useful:
            result[label] = "Failed"
        elif useful == {"success"}:
            # Ruff is platform-independent. The other matrix leg may skip it by design.
            result[label] = "Passed" if label == "Ruff" or "skipped" not in conclusions else "Partial"
        elif useful == {"cancelled"} or (not useful and run["conclusion"] == "cancelled"):
            result[label] = "Cancelled"
        elif useful:
            result[label] = "Partial"
        elif conclusions:
            result[label] = "Skipped"
    return result, run["url"]


def parse_coverage(repo, directory):
    results = {}
    for report in directory.rglob("coverage-report.txt"):
        for row in report.read_text().splitlines():
            fields = row.split()
            if len(fields) >= 10 and fields[0] == "TOTAL" and fields[7].isdigit() and fields[8].isdigit():
                total, missed = int(fields[7]), int(fields[8])
                results["coverage"] = {"covered": total-missed, "total": total}
    if repo == "crysta":
        for report in directory.rglob("python-surface-coverage.json"):
            data = json.loads(report.read_text())
            results["python"] = {"covered": data["narrow"]["exercised"], "total": data["denominator"]["total"]}
    else:
        for report in directory.rglob("py-coverage-report.txt"):
            matches = re.findall(r"^\s*TOTAL\s+(\d+)\s+(\d+)\s+[\d.]+%", report.read_text(), re.M)
            if matches:
                total, missed = map(int, matches[-1])
                results["python"] = {"covered": total-missed, "total": total}
    return results


def coverage_targets(repo, manifest, reports):
    import tomllib

    config = tomllib.loads(manifest)["tool"]
    thresholds = config.get(repo, {}).get("coverage", {})
    targets = {
        "coverage": thresholds.get("cpp_lines_min"),
        "python": (thresholds.get("python_surface_min") if repo == "crysta"
                   else config.get("coverage", {}).get("report", {}).get("fail_under")),
    }
    for key, report in reports.items():
        if type(targets[key]) in (int, float):
            report["target"] = targets[key]


def coverage_results(repo, sha, root):
    run = workflow_run(repo, sha, "coverage.yml", "workflow_dispatch")
    if not run:
        return {}
    receipt = {"coverage_url": run["url"]}
    if run["conclusion"] != "success":
        jobs = json.loads(capture("gh", "api", "--paginate", "--slurp",
                                  f"repos/enhantica/{repo}/actions/runs/{run['databaseId']}/jobs?per_page=100"))
        required = {
            "crysta": ("C++ unit coverage, gated", "Python surface coverage, gated",
                       "Upload the coverage reports + lcov export"),
            "edi": ("C++ unit coverage", "Python coverage", "Upload both reports"),
        }[repo]
        # An unrelated failure after the upload does not invalidate measurements.
        if not any(all(any(step["name"].startswith(prefix) and step["conclusion"] == "success"
                           for step in job["steps"]) for prefix in required)
                   for page in jobs for job in page["jobs"]):
            return receipt
    with TemporaryDirectory() as temporary:
        artifacts = json.loads(capture("gh", "api",
                                       f"repos/enhantica/{repo}/actions/runs/{run['databaseId']}/artifacts"))
        if any(a["name"] == "unit-coverage" and not a["expired"] for a in artifacts["artifacts"]):
            capture("gh", "run", "download", str(run["databaseId"]), "--repo", f"enhantica/{repo}",
                    "--name", "unit-coverage", "--dir", temporary)
            reports = parse_coverage(repo, Path(temporary))
            if reports:
                coverage_targets(repo, capture("git", "show", f"{sha}:pyproject.toml", cwd=root), reports)
            receipt.update(reports)
    return receipt


def merge_edi_measurements(sample, receipt, root):
    if not receipt or receipt["repo"] != "edi" or receipt["sha"] != sample["sha"]:
        return

    import tomllib

    manifest = capture("git", "show", f"{sample['sha']}:pixi.toml", cwd=root)
    expected_sdk = tomllib.loads(manifest)["activation"]["env"]["CRYSTA_COMMIT"]
    if receipt["sdk_sha"] != expected_sdk or type(receipt["run_id"]) is not int or receipt["run_id"] < 1:
        raise ValueError("The coverage receipt does not match edi's declared SDK or workflow run")

    reports = {}
    for key in ("coverage", "python"):
        covered, total = (receipt[key][field] for field in ("covered", "total"))
        if type(total) is not int or type(covered) is not int or not 0 <= covered <= total or total == 0:
            raise ValueError("Invalid coverage counts in the edi measurement receipt")
        reports[key] = {"covered": covered, "total": total}

    checks = {name: receipt["checks"][name] for name in ("Clang static analysis", "Ruff")}
    if any(value not in {"Passed", "Failed", "No report"} for value in checks.values()):
        raise ValueError("Invalid check status in the edi measurement receipt")
    coverage_targets("edi", capture("git", "show", f"{sample['sha']}:pyproject.toml", cwd=root), reports)
    sample.update(reports)
    sample["checks"] = sample.get("checks", {}) | checks
    sample["checks_scope"] = {"Clang static analysis": "Linux core, CLI, and bindings compilation database"}
    sample["coverage_url"] = f"https://github.com/enhantica/quality/actions/runs/{receipt['run_id']}"


def collect(repo, root, bca, docs, from_github):
    scope = SCOPES[repo]
    sha = capture("git", "rev-parse", "HEAD", cwd=root).strip()
    tracked = {p for p in capture("git", "ls-files", "-z", "--", *scope, cwd=root).split("\0")
               if Path(p).suffix in CXX_SUFFIXES | {".py"}}
    if not tracked:
        raise ValueError(f"No tracked production source in {repo}")
    if capture("git", "status", "--porcelain", "--untracked-files=no", "--", *scope, cwd=root).strip():
        raise ValueError(f"{repo} production scope differs from {sha}")
    with TemporaryDirectory() as temporary:
        report = Path(temporary) / "reports.json"
        run_analyzer(bca, "metrics", *scope, "-O", "json", "--output", report, cwd=root)
        files = [record for record in json.loads(report.read_text()) if record["name"] in tracked]
    missing = tracked - {record["name"] for record in files}
    if missing:
        raise ValueError(f"{repo} BCA did not report {len(missing)} tracked production source files")
    python = sorted(p for p in tracked if p.endswith(".py"))
    sample = {
        "sha": sha,
        "date": datetime.now(timezone.utc).isoformat(),
        "static": summarize([record for record in files if record["name"] not in python], scope, repo == "edi"),
        "python_static": summarize([record for record in files if record["name"] in python], scope, repo == "edi"),
        "python_docs": python_docs(root, python),
    }
    if docs:
        sample["docs"] = doxygen_counts(root, HEADERS[repo])
    if from_github:
        sample["checks"], sample["ci_url"] = test_results(repo, sha)
        sample.update(coverage_results(repo, sha, root))
    return sample


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crysta", type=Path, required=True)
    parser.add_argument("--edi", type=Path, required=True)
    parser.add_argument("--bca", default="bca")
    parser.add_argument("--docs", action="store_true")
    parser.add_argument("--github", action="store_true")
    parser.add_argument("--history", type=Path)
    parser.add_argument("--edi-measurements", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prev = json.loads(args.history.read_text()) if args.history and args.history.exists() else {}
    edi_measurements = (json.loads(args.edi_measurements.read_text())
                        if args.edi_measurements and args.edi_measurements.exists() else None)
    data = {"schema": 1, "demo": False, "projects": {}}
    with ThreadPoolExecutor() as pool:
        jobs = {repo: pool.submit(collect, repo, getattr(args, repo).resolve(), args.bca, args.docs, args.github)
                for repo in SCOPES}
        for repo, job in jobs.items():
            sample = job.result()
            if repo == "edi":
                merge_edi_measurements(sample, edi_measurements, args.edi.resolve())
            history = prev.get("projects", {}).get(repo, {}).get("samples", []) if prev.get("schema") == 1 else []
            history = [row for row in history if row["sha"] != sample["sha"]]
            data["projects"][repo] = {"branch": "main", "samples": (history + [sample])[-90:]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, allow_nan=False)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
