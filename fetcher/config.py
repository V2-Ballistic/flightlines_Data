"""
config.py — load and validate sources.yaml.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Default values applied to every source entry
SOURCE_DEFAULTS: dict[str, Any] = {
    "mode": "page",
    "max_depth": 1,
    "same_host_only": True,
    "login_required": False,
    "notes": "",
    "manual_type": "Unknown",
    "group": "Uncategorised",
}

REQUIRED_FIELDS = ("url",)


def load_sources(path: str | Path = "sources.yaml") -> list[dict[str, Any]]:
    """Load, validate and normalise source entries from *path*.

    Returns a list of source dicts with all defaults filled in.
    Raises ``ValueError`` if the file cannot be parsed or a required field is
    missing.
    """
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"sources file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, dict) or "sources" not in raw:
        raise ValueError(
            f"{config_path}: expected a YAML mapping with a top-level 'sources' key"
        )

    entries: list[dict[str, Any]] = raw["sources"]
    if not isinstance(entries, list):
        raise ValueError(f"{config_path}: 'sources' must be a list")

    normalised: list[dict[str, Any]] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"{config_path}: entry #{i} is not a mapping")
        for field in REQUIRED_FIELDS:
            if field not in entry:
                raise ValueError(
                    f"{config_path}: entry #{i} is missing required field '{field}'"
                )
        # Merge defaults beneath the entry values
        merged = {**SOURCE_DEFAULTS, **entry}
        normalised.append(merged)
        logger.debug("loaded source: %s (%s)", merged["url"], merged["group"])

    logger.info("loaded %d source entries from %s", len(normalised), config_path)
    return normalised
