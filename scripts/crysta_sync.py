"""Transfer normalized pinned-SDK receipts and schedule measurements that are missing."""

import argparse
import json
from pathlib import Path
import re

from collect import capture

WORKFLOW = "crysta-measurements.yml"


def workflow_runs(repo):
    return json.loads(capture(
        "gh", "run", "list", "--repo", repo, "--workflow", WORKFLOW, "--branch", "main",
        "--limit", "100", "--json", "displayTitle,databaseId,status,conclusion",
    ))


def measurement_pin(run):
    title = re.fullmatch(r"crysta SDK ([0-9a-f]{40})", run["displayTitle"])
    return title[1] if title else None


def download(repo, snapshots, directory):
    # Select the newest available receipt for each exact pin. Archived receipts
    # continue to work after their original Actions artifacts have expired.
    received = set()
    for run in workflow_runs(repo):
        pin = measurement_pin(run)
        if pin not in snapshots or pin in received or run["conclusion"] != "success":
            continue
        run_id = run["databaseId"]
        if run_id <= snapshots[pin].get("measurement_run", 0):
            received.add(pin)
            continue
        name = f"crysta-measurements-{pin}"
        artifacts = json.loads(capture("gh", "api", f"repos/{repo}/actions/runs/{run_id}/artifacts"))
        if any(item["name"] == name and not item["expired"] for item in artifacts["artifacts"]):
            target = directory / pin
            capture("gh", "run", "download", str(run_id), "--repo", repo, "--name", name, "--dir", str(target))
            receipt = json.loads((target / "crysta.json").read_text())
            if receipt["sha"] != pin or receipt["run_id"] != run_id:
                raise ValueError("SDK receipt identity differs from its producing run")
            received.add(pin)


def queue(repo, pending):
    if not pending:
        return
    active = {measurement_pin(run) for run in workflow_runs(repo) if run["status"] != "completed"}
    for pin in pending:
        if not re.fullmatch(r"[0-9a-f]{40}", pin):
            raise ValueError("Invalid pending SDK pin")
        if pin not in active:
            capture("gh", "workflow", "run", WORKFLOW, "--repo", repo, "--ref", "main", "-f", f"pin={pin}")
            print(f"Queued crysta SDK {pin[:7]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["download", "queue"])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    archive = json.loads(args.history.read_text())["projects"]["crysta"]
    if args.action == "queue":
        queue(args.repo, archive.get("pending_measurements", []))
    else:
        if args.directory is None:
            parser.error("--directory is required for download")
        download(args.repo, archive.get("pins", {}), args.directory)


if __name__ == "__main__":
    main()
