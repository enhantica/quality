#!/usr/bin/env python3
"""Build a standalone static dashboard from a validated snapshot file."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render(source: Path, output: Path, template_name: str) -> None:
    data = json.loads(source.read_text(encoding="utf-8"))
    if set(data["projects"]) != {"crysta", "edi"} or type(data["demo"]) is not bool:
        raise ValueError("Expected crysta and edi dashboard data with an explicit demo flag")
    template = (ROOT / "src" / template_name).read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("<", r"\u003c")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template.replace("__DASHBOARD_DATA__", payload), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data" / "demo.json")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "index.html")
    parser.add_argument("--trends", action="store_true", help="Render the trend and component view")
    args = parser.parse_args()
    render(args.data, args.output, "index.html" if args.trends else "card-layouts.html")
