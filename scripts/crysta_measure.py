"""Run crysta's existing checks with private logs and export only numeric receipts."""

import argparse
import base64
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


def checkout(root, pin):
    root.mkdir(parents=True)
    repo = "https://github.com/enhantica/crysta.git"
    token = base64.b64encode(f"x-access-token:{os.environ['CRYSTA_SOURCE_TOKEN']}".encode()).decode()
    env = dict(os.environ, CRYSTA_SOURCE_AUTH=f"Authorization: basic {token}", GIT_TERMINAL_PROMPT="0")
    commands = [
        ["git", "init", "--quiet"],
        ["git", "remote", "add", "origin", repo],
        ["git", "--config-env=http.extraHeader=CRYSTA_SOURCE_AUTH", "fetch", "--quiet", "--no-tags",
         "origin", "refs/heads/main:refs/remotes/origin/main", pin],
        ["git", "checkout", "--quiet", "--detach", pin],
    ]
    for command in commands:
        if subprocess.run(command, cwd=root, env=env, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode:
            raise RuntimeError("The private SDK checkout could not be prepared")


def python_diagnostic(log, junit):
    if junit.is_file():
        print("Python coverage unavailable: unit tests did not all pass")
        return
    output = log.read_text(errors="replace")
    classifications = {
        r"No space left on device": "runner disk space",
        r"Could not resolve host|[Cc]onnection timed out|[Tt]imed out downloading": "dependency network",
        r"No built crysta binary|no built crysta binary": "native CLI link",
        r"CMake Error|ninja: build stopped|Failed to build": "native Python extension build",
        r"No module named|ImportError": "Python import",
        r"Not a valid object name|bad revision|bad object|Needed a single revision": "Git history",
    }
    reason = next((label for pattern,label in classifications.items() if re.search(pattern, output)), None)
    if not reason:
        reason = "pytest setup" if "Task (py-surface-cov-unit" in output else "before pytest"
    print(f"Python coverage unavailable: {reason}")


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
        command = COMMANDS[phase]
        if phase == "install" and os.environ.get("CRYSTA_PYTHON_ONLY") == "true":
            command = ["pixi", "install", "--frozen", "-e", "cpp-ci"]
        log_path = scratch / "command.log"
        with log_path.open("w", encoding="utf-8") as log:
            status = subprocess.run(command, cwd=root, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, check=False).returncode
        print(f"{phase}: exit {status}")
        if phase == "install":
            if status:
                raise RuntimeError("The frozen toolchain installation failed")
            return {}
        if phase in CHECK_NAMES:
            return {"status": "Passed" if status == 0 else "Failed"}
        if phase == "python" and not successful_tests(junit):
            python_diagnostic(log_path, junit)
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
              for phase, name in CHECK_NAMES.items() if (parts / f"{phase}.json").is_file()}
    receipt = {
        "repo": "crysta", "sha": pin, "run_id": int(os.environ["GITHUB_RUN_ID"]), "checks": checks,
    }
    for phase in ("coverage", "python"):
        part = parts / f"{phase}.json"
        if part.is_file() and (report := json.loads(part.read_text())):
            receipt[phase] = {key: report[key] for key in ("covered", "total")}
    if not any(receipt.get(key) for key in ("checks", "coverage", "python")):
        raise RuntimeError("The workflow could not prove any measurements")
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
    parser.add_argument("phase", choices=["checkout", *COMMANDS, "assemble"])
    args = parser.parse_args()
    root = Path("inputs/crysta").resolve()
    pin = os.environ["CRYSTA_PIN"]
    if not re.fullmatch(r"[0-9a-f]{40}", pin):
        raise ValueError("Invalid SDK pin")
    if args.phase == "checkout":
        checkout(root, pin)
    if capture("git", "rev-parse", "HEAD", cwd=root).strip() != pin:
        raise ValueError("The checkout does not match the requested SDK pin")
    if args.phase == "checkout":
        return
    parts = Path(os.environ["RUNNER_TEMP"]) / "crysta-measurements"
    parts.mkdir(exist_ok=True)
    if args.phase == "assemble":
        assemble(parts, pin)
    else:
        report = measure(args.phase, root)
        (parts / f"{args.phase}.json").write_text(json.dumps(report), encoding="utf-8")


if __name__ == "__main__":
    main()
