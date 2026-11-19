"""Run crysta's existing checks with private logs and export only numeric receipts."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory

from collect import capture, parse_coverage, successful_tests

COMMANDS = {
    "install": ["pixi", "install", "--frozen", "-e", "cpp-ci", "-e", "lint", "-e", "lint-docs-ci"],
    "clang": ["pixi", "run", "--frozen", "-e", "lint", "cpp-tidy"],
    "ruff": ["pixi", "run", "--frozen", "-e", "lint-docs-ci", "check"],
    "coverage": ["pixi", "run", "--frozen", "-e", "cpp-ci", "bash", "tools/ci/cpp-coverage-unit.sh"],
    "python": ["pixi", "run", "--frozen", "-e", "cpp-ci", "py-surface-cov-unit"],
}
CHECK_NAMES = {"clang": "Clang static analysis", "ruff": "Ruff"}
RUNNER_EXPORTS = {"GITHUB_ENV", "GITHUB_OUTPUT", "GITHUB_PATH", "GITHUB_STATE", "GITHUB_STEP_SUMMARY"}


def measure(phase, root):
    env = {key: value for key, value in os.environ.items() if key not in RUNNER_EXPORTS}
    with TemporaryDirectory(dir=os.environ["RUNNER_TEMP"]) as temporary:
        scratch = Path(temporary)
        junit = scratch / "pytest.xml"
        if phase == "python":
            env["PYTEST_ADDOPTS"] = f"--junitxml={junit}"
            (root / "build" / "python-surface-coverage.json").unlink(missing_ok=True)
        elif phase == "coverage":
            (root / "build" / "coverage-unit" / "coverage-report.txt").unlink(missing_ok=True)
        with (scratch / "command.log").open("w", encoding="utf-8") as log:
            status = subprocess.run(COMMANDS[phase], cwd=root, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, check=False).returncode
        print(f"{phase}: exit {status}")
        if phase == "install":
            if status:
                raise RuntimeError("The frozen toolchain installation failed")
            return {}
        if phase in CHECK_NAMES:
            return {"status": "Passed" if status == 0 else "Failed"}
        if phase == "python" and not successful_tests(junit):
            print("Python coverage unavailable: no successful unit test receipt")
            return {}
        # The native producer writes its report after validating the complete
        # test tier. Both producers write the counts before applying the floor.
        directory = root / "build" if phase == "python" else root / "build" / "coverage-unit"
        report = parse_coverage("crysta", directory).get(phase)
        if report is None:
            print(f"{phase}: no valid report produced")
            return {}
        return report


def assemble(parts, pin):
    checks = {name: json.loads((parts / f"{phase}.json").read_text())["status"]
              for phase, name in CHECK_NAMES.items()}
    receipt = {
        "repo": "crysta", "sha": pin, "run_id": int(os.environ["GITHUB_RUN_ID"]), "checks": checks,
    }
    for phase in ("coverage", "python"):
        if report := json.loads((parts / f"{phase}.json").read_text()):
            receipt[phase] = {key: report[key] for key in ("covered", "total")}
    for name, status in checks.items():
        print(f"{name}: {status}")
    for phase in ("coverage", "python"):
        if report := receipt.get(phase):
            print(f"{phase}: {report['covered']}/{report['total']}")
    output = Path("measurement") / "crysta.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=[*COMMANDS, "assemble"])
    args = parser.parse_args()
    root = Path("inputs/crysta").resolve()
    pin = os.environ["CRYSTA_PIN"]
    if not re.fullmatch(r"[0-9a-f]{40}", pin) or capture("git", "rev-parse", "HEAD", cwd=root).strip() != pin:
        raise ValueError("The checkout does not match the requested SDK pin")
    parts = Path(os.environ["RUNNER_TEMP"]) / "crysta-measurements"
    parts.mkdir(exist_ok=True)
    if args.phase == "assemble":
        assemble(parts, pin)
    else:
        report = measure(args.phase, root)
        (parts / f"{args.phase}.json").write_text(json.dumps(report), encoding="utf-8")


if __name__ == "__main__":
    main()
