"""Find published product releases and resolve their exact tag commits."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from collect import crysta_pin

QUERY = """
query($name: String!, $endCursor: String) {
  repository(owner: "enhantica", name: $name) {
    releases(first: 100, after: $endCursor, orderBy: {field: CREATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes { id tagName isDraft isPrerelease publishedAt tagCommit { oid } }
    }
  }
}
"""


def published_releases(repo):
    response = subprocess.check_output(
        ["gh", "api", "graphql", "--paginate", "--slurp", "-f", f"query={QUERY}", "-f", f"name={repo}"],
        text=True,
    )
    rows = []
    for page in json.loads(response):
        for release in page["data"]["repository"]["releases"]["nodes"]:
            if release["isDraft"] or not release["publishedAt"]:
                continue
            sha = (release["tagCommit"] or {}).get("oid")
            if not sha or not re.fullmatch(r"[0-9a-f]{40}", sha):
                print(f"{repo}: a published release has no resolvable tag commit")
                continue
            rows.append({
                "id": release["id"],
                "tag": release["tagName"],
                "sha": sha,
                "published_at": release["publishedAt"],
                "prerelease": release["isPrerelease"],
            })
    return sorted(rows, key=lambda row: (row["published_at"], row["id"]))


def release_changed(catalogue, history):
    for repo, releases in catalogue.items():
        prior = history.get("projects", {}).get(repo, {}).get("releases", [])
        known = {row["id"]: row for row in prior}
        for release in releases:
            archived = known.get(release["id"], {})
            if any(archived.get(key) != value for key, value in release.items()):
                return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prior = json.loads(args.history.read_text())
    catalogue = {"edi": published_releases("edi")}
    args.output.write_text(json.dumps(catalogue) + "\n", encoding="utf-8")
    manifest = subprocess.check_output(
        ["gh", "api", "-H", "Accept: application/vnd.github.raw+json", "repos/enhantica/edi/contents/pixi.toml?ref=main"],
        text=True,
    )
    main = prior.get("projects", {}).get("edi", {}).get("samples", [])
    previous_pin = main[-1].get("crysta_pin") if main else None
    changed = release_changed(catalogue, prior) or crysta_pin(manifest) != previous_pin
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as stream:
            print(f"changed={str(changed).lower()}", file=stream)
    print("Published releases: " + ", ".join(f"{repo} {len(rows)}" for repo, rows in catalogue.items()))


if __name__ == "__main__":
    main()
