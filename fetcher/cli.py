"""
cli.py — argument parsing and orchestration for the fetcher package.

Entry points:
    python -m fetcher [options]
    python scripts/flightlines_fetch.py [options]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from fetcher.artifacts import ARTIFACT_DIR, write_all
from fetcher.config import load_sources
from fetcher.crawler import DEFAULT_SLEEP, MAX_FILE_BYTES, Crawler


def _setup_logging(verbose: bool, log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"

    # Root logger
    root = logging.getLogger()
    root.setLevel(level)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter(fmt))
    root.addHandler(ch)

    # File handler
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(fmt))
    root.addHandler(fh)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flightlines-fetch",
        description=(
            "Crawl public aviation documentation sources and produce metadata "
            "artifacts (manifest, index, log). Downloaded PDFs are NOT committed."
        ),
    )
    parser.add_argument(
        "--sources",
        default="sources.yaml",
        metavar="PATH",
        help="Path to sources.yaml (default: sources.yaml)",
    )
    parser.add_argument(
        "--artifacts-dir",
        default=str(ARTIFACT_DIR),
        metavar="DIR",
        help="Directory for output artifacts (default: artifacts/)",
    )
    parser.add_argument(
        "--downloads-dir",
        default="./_downloads",
        metavar="DIR",
        help="Directory for downloaded files (default: ./_downloads/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover files and log metadata but do NOT download anything",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Crawl pages and record metadata but skip actual file downloads",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_SLEEP,
        metavar="SECONDS",
        help=f"Pause between requests in seconds (default: {DEFAULT_SLEEP})",
    )
    parser.add_argument(
        "--max-file-mb",
        type=int,
        default=MAX_FILE_BYTES // (1024 * 1024),
        metavar="MB",
        help="Maximum file size to download in MB (default: 200)",
    )
    parser.add_argument(
        "--group",
        metavar="GROUP",
        help="Only process sources whose group contains this string (case-insensitive)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable DEBUG-level logging",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    artifact_path = Path(args.artifacts_dir)
    log_file = artifact_path / "_run.log"
    _setup_logging(args.verbose, log_file)
    logger = logging.getLogger(__name__)

    start_ts = datetime.now(timezone.utc)
    logger.info("=== flightlines-fetch started at %s ===", start_ts.isoformat())
    logger.info(
        "options: dry_run=%s no_download=%s sleep=%.1fs max_file=%dMB",
        args.dry_run,
        args.no_download,
        args.sleep,
        args.max_file_mb,
    )

    # Load sources
    try:
        sources = load_sources(args.sources)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("failed to load sources: %s", exc)
        return 1

    # Optional group filter
    if args.group:
        filter_str = args.group.lower()
        sources = [s for s in sources if filter_str in s.get("group", "").lower()]
        logger.info("filtered to %d sources matching group '%s'", len(sources), args.group)

    # Build crawler
    crawler = Crawler(
        work_dir=args.downloads_dir,
        dry_run=args.dry_run,
        no_download=args.no_download,
        sleep=args.sleep,
        max_file_bytes=args.max_file_mb * 1024 * 1024,
    )

    # Crawl all sources
    all_records: list[dict] = []
    for source in sources:
        try:
            records = crawler.crawl_source(source)
            all_records.extend(records)
        except Exception as exc:
            logger.error("unexpected error crawling %s: %s", source.get("url"), exc, exc_info=True)

    end_ts = datetime.now(timezone.utc)
    elapsed = (end_ts - start_ts).total_seconds()
    logger.info(
        "=== crawl finished at %s (%.1fs elapsed) — %d files found ===",
        end_ts.isoformat(),
        elapsed,
        len(all_records),
    )

    # Write artifacts
    write_all(all_records, sources, path=artifact_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
