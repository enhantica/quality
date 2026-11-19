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


def successful_tests(report):
    if not report.is_file():
        return False
    suites = ET.parse(report).findall(".//testsuite")
    return bool(suites) and sum(int(s.get("tests", 0)) - int(s.get("skipped", 0)) for s in suites) > 0 and all(
        int(s.get("failures", 0)) == int(s.get("errors", 0)) == 0 for s in suites
    )


def measure(edi, crysta, scratch):
    pin = os.environ["CRYSTA_PIN"]
    if not re.fullmatch("[0-9a-f]{40}", pin) or capture("git", "rev-parse", "HEAD", cwd=crysta).strip() != pin:
        raise ValueError("The crysta checkout does not match the edi pin")
    sdk = scratch / "sdk"
    sdk.mkdir()
    env = dict(os.environ, CRYSTA_SRC=str(crysta), CRYSTA_SDK_ARCHIVES=str(sdk),
               NO_COLOR="1", PY_COLORS="0")
    sdk_status = run("Linux SDK build and qualification",
                     ["pixi", "run", "--frozen", "-e", "cpp-ci", "sdk-pack", pin, "linux-64", str(sdk)],
                     crysta, scratch / "sdk.log", env)
    if sdk_status != 0:
        raise RuntimeError(f"The locked SDK build or qualification failed (exit {sdk_status})")

    def run_edi(label, command, filename, extra_env=None):
        return run(label, command, edi, scratch / filename, env | (extra_env or {}))

    cpp_status = run_edi("C++ unit coverage", ["pixi", "run", "--frozen", "cpp-coverage-unit"], "cpp.log")
    junit = scratch / "pytest.xml"
    python_status = run_edi("Python unit coverage", ["pixi", "run", "--frozen", "py-cov-unit"],
                            "py-coverage-report.txt", {"PYTEST_ADDOPTS": f"--junitxml={junit}"})
    cpp_report = parse_coverage("edi", edi / "build" / "coverage-unit").get("coverage")
    python_report = parse_coverage("edi", scratch).get("python")
    reports = {}
    if cpp_report is not None:
        # The producer writes this report only after a successful doctest run.
        reports["coverage"] = cpp_report
    if python_report is not None and successful_tests(junit):
        reports["python"] = python_report
    coverage_targets("edi", (edi / "pyproject.toml").read_text(), reports)
    print(f"C++ coverage: {'measured' if 'coverage' in reports else 'unavailable'} (exit {cpp_status})")
    print(f"Python coverage: {'measured' if 'python' in reports else 'unavailable'} (exit {python_status})")

    ruff_status = run_edi("Ruff checks", ["pixi", "run", "--frozen", "lint", "style"], "ruff.log")
    checks = {
        "Clang static analysis": tidy_core(edi, run_edi),
        "Ruff": "Passed" if ruff_status == 0 else "Failed",
    }
    if set(reports) != {"coverage", "python"}:
        raise RuntimeError("The run could not prove both coverage measurements")

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
