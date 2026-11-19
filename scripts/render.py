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


def write_summary(data: dict, path: Path) -> None:
    projects = ("crysta", "edi")
    languages = ("C++", "Python")
    samples = {name: data["projects"][name]["samples"][-1] for name in projects}
    columns = [
        (name, language, samples[name],
         samples[name].get("static" if language == "C++" else "python_static", {}))
        for name in projects for language in languages
    ]

    def formatted(value):
        if value is None:
            return "No report"
        return f"{value:,}" if isinstance(value, int) else f"{value:,.1f}"

    def ratio(report):
        if not report or not report["total"]:
            return "No report"
        covered, total = report["covered"], report["total"]
        target = report.get("target")
        return (f"{100 * covered / total:.1f}% ({covered:,}/{total:,})"
                + (f" · target {target:g}%" if target is not None else ""))

    rows = [
        ("Code quality", lambda s, m, lang: s.get("checks", {}).get(
            "Clang static analysis" if lang == "C++" else "Ruff", "No report")),
        ("Maintainability index (file median)", lambda s, m, lang: formatted(m.get("mi"))),
        ("Cyclomatic complexity (P90)", lambda s, m, lang: formatted(m.get("p90"))),
        ("Physical code lines", lambda s, m, lang: formatted(
            sum(row["lines"] for row in m["components"]) if "components" in m else None)),
        ("Logical lines", lambda s, m, lang: formatted(m.get("logical"))),
        ("Functions", lambda s, m, lang: formatted(m.get("functions"))),
        ("Files", lambda s, m, lang: formatted(m.get("files"))),
        ("Functions per file", lambda s, m, lang: formatted(m["functions"] / m["files"] if m.get("files") else None)),
        ("Unit-test coverage", lambda s, m, lang: ratio(s.get("coverage" if lang == "C++" else "python"))),
        ("Documentation coverage", lambda s, m, lang: ratio(s.get("docs" if lang == "C++" else "python_docs"))),
    ]
    title = "Code quality (demo data)" if data["demo"] else "Code quality"
    lines = [
        f"## {title}",
        "",
        "| Metric | " + " | ".join(f"{name} {language}" for name, language, _, _ in columns) + " |",
        "| --- | --- | --- | --- | --- |",
    ]
    for label, read in rows:
        lines.append("| " + " | ".join([label] + [read(sample, metrics, language)
                     for _, language, sample, metrics in columns]) + " |")
    lines += [
        "",
        "crysta Python test coverage measures public API entries. edi Python test coverage measures statements.",
        "C++ documentation coverage measures public header declarations. Python documentation coverage measures handwritten docstrings.",
        "",
    ]
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data" / "demo.json")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "index.html")
    parser.add_argument("--trends", action="store_true", help="Render the trend and component view")
    parser.add_argument("--summary", type=Path, help="Append a metrics table to a Markdown step summary")
    args = parser.parse_args()
    render(args.data, args.output, "index.html" if args.trends else "card-layouts.html")
    if args.summary:
        write_summary(json.loads(args.data.read_text(encoding="utf-8")), args.summary)
