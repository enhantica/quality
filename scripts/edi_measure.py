"""Measure edi's native and Python tiers without exporting its private SDK inputs."""

import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
import xml.etree.ElementTree as ET
from collect import capture, coverage_targets, parse_coverage

ROOT = Path(__file__).resolve().parents[1]


def run(label, command, cwd, log, env):
    """Keep all build and analyzer output on the ephemeral runner."""
    print(f"Running {label}", flush=True)
    with log.open("w", encoding="utf-8") as stream:
        return subprocess.run(command, cwd=cwd, env=env, stdout=stream,
                              stderr=subprocess.STDOUT, check=False).returncode


def tidy_core(root, run_check):
    compile_db = root / "build" / "ci" / "compile_commands.json"
    if not compile_db.is_file():
        return "No report"

    prefix = re.escape(str(root))
    owned = prefix + r"/(?:core/src|cli|lib/src)/.*\.cpp$"
    deferred = (root / "tools" / "ci" / "static-checks-deferred.txt").read_text().splitlines()
    deferred = [re.escape(str(root / line.strip())) for line in deferred if line.strip() and not line.startswith("#")]
    exclusions = "|".join(deferred) or "^"
    translation_units = [
        entry["file"] for entry in json.loads(compile_db.read_text())
        if re.fullmatch(owned, entry["file"]) and not re.fullmatch(exclusions, entry["file"])
    ]
    if not translation_units:
        return "No report"

    status = run_check("Clang static analysis",
                       ["pixi", "run", "--frozen", "-e", "cpp-lint", "run-clang-tidy",
                        "-quiet", "-p", "build/ci", "-j", "4", "-warnings-as-errors=*",
                        f"-header-filter=^{prefix}/(core|cli|lib)/", f"-exclude-header-filter=^(?:{exclusions})$",
                        "-extra-arg=-Wno-unknown-warning-option", rf"(?!^(?:{exclusions})$)^{owned}"],
                       "clang.log")
    return "Passed" if status == 0 else "Failed"


def junit_counts(junit):
    if junit.is_file():
        try:
            suites = ET.parse(junit).findall(".//testsuite")
            return {key: sum(int(suite.get(key, 0)) for suite in suites)
                    for key in ("tests", "failures", "errors", "skipped")}
        except (ET.ParseError, ValueError):
            print("Python unit tier wrote an unreadable test report")
    return {}


def explain_python_gap(log, counts):
    if counts:
        print("Python unit tier: " + ", ".join(f"{value} {key}" for key, value in counts.items()))
        return
    output = log.read_text(errors="replace")
    for pattern, reason in (
        (r"No space left on device", "runner disk space"),
        (r"CMake Error|ninja: build stopped", "native extension build"),
        (r"No module named|ImportError", "Python import"),
    ):
        if re.search(pattern, output):
            print(f"Python unit tier stopped before writing its test report ({reason})")
            return
    print("Python unit tier stopped before writing its test report")


def completed_cpp_failures(log):
    summary = re.search(
        r"^\[doctest\]\s+test cases:\s*(\d+)\s*\|\s*(\d+) passed\s*\|"
        r"\s*(\d+) failed\s*\|\s*(\d+) skipped\s*$", log, re.M,
    )
    if not summary or not re.search(r"^\[doctest\]\s+Status: FAILURE!?\s*$", log, re.M):
        return 0
    total, passed, failed, skipped = map(int, summary.groups())
    return failed if total == passed + failed and skipped == 0 else 0


def native_coverage(edi, scratch, run_edi):
    status = run_edi("C++ unit coverage", ["pixi", "run", "--frozen", "cpp-coverage-unit"], "cpp.log")
    tree = edi / "build" / "coverage-unit"
    if report := parse_coverage("edi", tree).get("coverage"):
        return report, status
    if status != 1:
        return None, status
    # Keep the product gate's failure while measuring reach from a complete,
    # non-vacuous doctest run that wrote its profile before exiting.
    profiles = list(tree.glob("profraw.*/edi_tests.profraw"))
    if len(profiles) != 1 or not profiles[0].stat().st_size:
        return None, status
    profile = profiles[0]
    log = profile.with_name("run.log")
    if not log.is_file() or not (failed := completed_cpp_failures(log.read_text(errors="replace"))):
        return None, status
    merged = scratch / "edi.profdata"
    if run_edi("Merge the completed C++ profile",
               ["pixi", "run", "--frozen", "llvm-profdata", "merge", "-sparse", str(profile), "-o", str(merged)],
               "profdata.log") != 0:
        return None, status
    if run_edi("Measure C++ reach from the completed test tier",
               ["pixi", "run", "--frozen", "llvm-cov", "report", str(tree / "core" / "edi_tests"),
                f"-instr-profile={merged}", "core/src", "core/include"], "coverage-report.txt") != 0:
        return None, status
    report = parse_coverage("edi", scratch).get("coverage")
    if report:
        report["failed_tests"] = failed
        print(f"C++ unit tier: {failed} tests failed")
    return report, status


def measure(edi, crysta, scratch):
    pin = os.environ["CRYSTA_PIN"]
    if not re.fullmatch("[0-9a-f]{40}", pin) or capture("git", "rev-parse", "HEAD", cwd=crysta).strip() != pin:
        raise ValueError("The crysta checkout does not match the edi pin")
    qualified_sdk = os.environ.get("EDI_QUALIFIED_SDK")
    sdk = Path(qualified_sdk) if qualified_sdk else scratch / "sdk"
    runner_exports = {"GITHUB_ENV", "GITHUB_OUTPUT", "GITHUB_PATH", "GITHUB_STATE", "GITHUB_STEP_SUMMARY"}
    env = {key: value for key, value in os.environ.items() if key not in runner_exports}
    env.update(CRYSTA_SRC=str(crysta), CRYSTA_SDK_ARCHIVES=str(sdk), NO_COLOR="1", PY_COLORS="0")
    if not qualified_sdk:
        sdk.mkdir()
        sdk_status = run("Linux SDK build and qualification",
                         ["pixi", "run", "--frozen", "-e", "cpp-ci", "sdk-pack", pin, "linux-64", str(sdk)],
                         crysta, scratch / "sdk.log", env)
        if sdk_status != 0:
            raise RuntimeError(f"The locked SDK build or qualification failed (exit {sdk_status})")

    def run_edi(label, command, filename, extra_env=None):
        return run(label, command, edi, scratch / filename, env | (extra_env or {}))

    cpp_only = os.environ.get("EDI_CPP_ONLY") == "true"
    cpp_report, cpp_status = native_coverage(edi, scratch, run_edi)
    print(f"C++ coverage: {'measured' if cpp_report else 'unavailable'} (exit {cpp_status})")
    reports = {}
    if cpp_report:
        reports["coverage"] = cpp_report
    if not cpp_only:
        junit = scratch / "pytest.xml"
        python_status = run_edi("Python unit coverage", ["pixi", "run", "--frozen", "py-cov-unit"],
                                "py-coverage-report.txt", {"PYTEST_ADDOPTS": f"--maxfail=0 --junitxml={junit}"})
        python_report = parse_coverage("edi", scratch).get("python")
        counts = junit_counts(junit)
        if (python_report is not None and python_status in (0, 1) and counts
                and counts["errors"] == 0 and counts["tests"] > counts["skipped"]):
            if counts["failures"]:
                python_report["failed_tests"] = counts["failures"]
            reports["python"] = python_report
        print(f"Python coverage: {'measured' if 'python' in reports else 'unavailable'} (exit {python_status})")
        if "python" not in reports or counts.get("failures"):
            explain_python_gap(scratch / "py-coverage-report.txt", counts)
    coverage_targets("edi", (edi / "pyproject.toml").read_text(), reports)
    if not reports:
        raise RuntimeError("Neither test tier produced a verified coverage report")

    checks = {}
    if not cpp_only:
        ruff_status = run_edi("Ruff checks", ["pixi", "run", "--frozen", "lint", "style"], "ruff.log")
        checks = {
            "Clang static analysis": tidy_core(edi, run_edi),
            "Ruff": "Passed" if ruff_status == 0 else "Failed",
        }
    return {
        "repo": "edi",
        "sha": capture("git", "rev-parse", "HEAD", cwd=edi).strip(),
        "sdk_sha": pin,
        "run_id": int(os.environ["GITHUB_RUN_ID"]),
        "checks": checks,
        **reports,
    }


if __name__ == "__main__":
    with TemporaryDirectory(dir=os.environ["RUNNER_TEMP"]) as scratch:
        receipt = measure(ROOT / "inputs" / "edi", ROOT / "inputs" / "crysta", Path(scratch))
        output = ROOT / "measurement" / "edi.json"
        output.parent.mkdir()
        output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
