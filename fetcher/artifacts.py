"""
artifacts.py — write output artifact files from crawl results.

Artifacts produced:
    artifacts/_index.json
    artifacts/_manifest.csv
    artifacts/_manifest.jsonl
    artifacts/_LOGIN_REQUIRED_TODO.md
    artifacts/_run.log          (managed by logging handler in cli.py)
    artifacts/_sources_expanded.json
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ARTIFACT_DIR = Path("artifacts")

# CSV column order
CSV_FIELDS = [
    "url",
    "final_url",
    "filename",
    "content_type",
    "size",
    "sha256",
    "group",
    "manual_type",
    "discovered_from",
    "local_path",
    "status",
]


def ensure_artifact_dir(path: Path = ARTIFACT_DIR) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_index(records: list[dict[str, Any]], path: Path = ARTIFACT_DIR) -> None:
    """Write _index.json: url -> artifact info."""
    index: dict[str, dict] = {}
    for rec in records:
        url = rec.get("url", "")
        if url:
            index[url] = {
                "sha256": rec.get("sha256", ""),
                "size": rec.get("size", 0),
                "group": rec.get("group", ""),
                "manual_type": rec.get("manual_type", ""),
                "local_path": rec.get("local_path", ""),
                "filename": rec.get("filename", ""),
                "content_type": rec.get("content_type", ""),
                "status": rec.get("status", ""),
                "final_url": rec.get("final_url", ""),
                "discovered_from": rec.get("discovered_from", ""),
            }

    out = path / "_index.json"
    with out.open("w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=2, ensure_ascii=False)
    logger.info("wrote %s (%d entries)", out, len(index))


def write_manifest_csv(records: list[dict[str, Any]], path: Path = ARTIFACT_DIR) -> None:
    """Write _manifest.csv."""
    out = path / "_manifest.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    logger.info("wrote %s (%d rows)", out, len(records))


def write_manifest_jsonl(records: list[dict[str, Any]], path: Path = ARTIFACT_DIR) -> None:
    """Write _manifest.jsonl (one JSON object per line)."""
    out = path / "_manifest.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    logger.info("wrote %s (%d lines)", out, len(records))


def write_login_required(
    sources: list[dict[str, Any]], path: Path = ARTIFACT_DIR
) -> None:
    """Write _LOGIN_REQUIRED_TODO.md for sources marked login_required."""
    login_sources = [s for s in sources if s.get("login_required")]
    out = path / "_LOGIN_REQUIRED_TODO.md"
    lines = [
        "# Login-Required Sources — Manual Action Needed\n",
        f"Generated: {datetime.now(timezone.utc).isoformat()}\n\n",
        "The following sources were **not** crawled because they require authentication.\n",
        "To include their documents, obtain access credentials and download manually.\n\n",
        "| Group | Manual Type | URL | Notes |\n",
        "|---|---|---|---|\n",
    ]
    for s in login_sources:
        lines.append(
            f"| {s.get('group','')} | {s.get('manual_type','')} "
            f"| {s.get('url','')} | {s.get('notes','')} |\n"
        )
    with out.open("w", encoding="utf-8") as fh:
        fh.writelines(lines)
    logger.info("wrote %s (%d login-required sources)", out, len(login_sources))


def write_sources_expanded(
    sources: list[dict[str, Any]], path: Path = ARTIFACT_DIR
) -> None:
    """Write _sources_expanded.json — normalised source list."""
    out = path / "_sources_expanded.json"
    with out.open("w", encoding="utf-8") as fh:
        json.dump(sources, fh, indent=2, ensure_ascii=False)
    logger.info("wrote %s (%d sources)", out, len(sources))


def write_all(
    records: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    path: Path = ARTIFACT_DIR,
) -> None:
    """Write all artifact files."""
    ensure_artifact_dir(path)
    write_index(records, path)
    write_manifest_csv(records, path)
    write_manifest_jsonl(records, path)
    write_login_required(sources, path)
    write_sources_expanded(sources, path)
    logger.info("all artifacts written to %s/", path)
