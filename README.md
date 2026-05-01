# flightlines_Data

> **Automated, config-driven public aviation documentation index.**
>
> This repository crawls a curated list of public aviation documentation sources (FAA handbooks,
> engine manufacturer pubs, avionics docs, etc.), extracts metadata about every downloadable file,
> and commits only the metadata artifacts — **no PDFs are committed to the repo**.

---

## Table of Contents

1. [Purpose](#purpose)
2. [What IS committed](#what-is-committed)
3. [Repository layout](#repository-layout)
4. [Quick start — run locally](#quick-start--run-locally)
5. [CLI reference](#cli-reference)
6. [How the GitHub Actions workflow works](#how-the-github-actions-workflow-works)
7. [How to add a source](#how-to-add-a-source)
8. [Artifact file reference](#artifact-file-reference)
9. [Legal & copyright notes](#legal--copyright-notes)
10. [Contributing](#contributing)

---

## Purpose

Flightlines needs a machine-readable index of public aviation documents so that document types,
sources, and links can be surfaced to users without requiring bulk PDF storage in the repository.

This project:

- Reads `sources.yaml` — a curated list of public aviation documentation URLs.
- Crawls those URLs (HTML link-discovery or direct-file mode).
- Downloads files temporarily to `./_downloads/` (never committed).
- Extracts metadata: URL, final URL, filename, content-type, size, SHA-256, source group,
  manual type, discovered-from URL.
- De-duplicates by SHA-256.
- Writes structured metadata artifacts to `artifacts/`.
- Runs weekly via GitHub Actions.

---

## What IS committed

| Path | Description |
|---|---|
| `sources.yaml` | Curated source list (the config) |
| `artifacts/_index.json` | URL → artifact info mapping |
| `artifacts/_manifest.csv` | All rows in CSV format |
| `artifacts/_manifest.jsonl` | One JSON object per line — easy to stream/ingest |
| `artifacts/_LOGIN_REQUIRED_TODO.md` | Sources that require authentication (not crawled) |
| `artifacts/_run.log` | Last crawl run log |
| `artifacts/_sources_expanded.json` | Normalised source list with all defaults filled in |
| `fetcher/` | Python crawler package |
| `scripts/flightlines_fetch.py` | CLI convenience wrapper |
| `requirements.txt` | Python dependencies |

**`./_downloads/` is in `.gitignore` and is never committed.**

---

## Repository layout

```
flightlines_Data/
├── .github/
│   └── workflows/
│       └── fetch-docs.yml      ← scheduled GitHub Actions workflow
├── artifacts/
│   ├── _index.json
│   ├── _manifest.csv
│   ├── _manifest.jsonl
│   ├── _LOGIN_REQUIRED_TODO.md
│   ├── _run.log
│   └── _sources_expanded.json
├── fetcher/
│   ├── __init__.py
│   ├── __main__.py             ← enables `python -m fetcher`
│   ├── cli.py                  ← argument parsing & orchestration
│   ├── config.py               ← sources.yaml loader
│   ├── crawler.py              ← HTML crawler + file downloader
│   └── artifacts.py            ← artifact writers
├── scripts/
│   └── flightlines_fetch.py    ← standalone CLI wrapper
├── sources.yaml                ← curated aviation doc sources
├── requirements.txt
├── .gitignore
└── README.md
```

---

## Quick start — run locally

### 1. Clone and set up

```bash
git clone https://github.com/V2-Ballistic/flightlines_Data.git
cd flightlines_Data
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Dry run (no downloads, just link discovery)

```bash
python -m fetcher --dry-run
```

### 3. Full run (downloads files to `./_downloads/`, writes metadata to `artifacts/`)

```bash
python -m fetcher
```

### 4. Metadata-only run (crawl pages, record metadata, skip actual file writes)

```bash
python -m fetcher --no-download
```

### 5. Filter to a specific source group

```bash
python -m fetcher --group "Lycoming" --dry-run
```

---

## CLI reference

```
usage: flightlines-fetch [-h] [--sources PATH] [--artifacts-dir DIR]
                         [--downloads-dir DIR] [--dry-run] [--no-download]
                         [--sleep SECONDS] [--max-file-mb MB] [--group GROUP]
                         [--verbose]

options:
  --sources PATH        Path to sources.yaml (default: sources.yaml)
  --artifacts-dir DIR   Directory for output artifacts (default: artifacts/)
  --downloads-dir DIR   Directory for downloaded files (default: ./_downloads/)
  --dry-run             Discover links and log metadata; do NOT download files
  --no-download         Crawl pages and record metadata; skip actual downloads
  --sleep SECONDS       Pause between requests in seconds (default: 1.5)
  --max-file-mb MB      Maximum file size to download in MB (default: 200)
  --group GROUP         Only process sources whose group contains this string
  --verbose, -v         Enable DEBUG-level logging
```

---

## How the GitHub Actions workflow works

File: `.github/workflows/fetch-docs.yml`

| Trigger | When |
|---|---|
| `workflow_dispatch` | Manual run from the Actions tab (optionally with dry-run and group-filter inputs) |
| `schedule` | Every Sunday at 02:00 UTC |

**Steps:**

1. Check out the repository.
2. Set up Python 3.12 with pip caching.
3. Install dependencies from `requirements.txt`.
4. Run `python -m fetcher` with configured arguments.
5. Stage only `artifacts/**` and `sources.yaml` (`./_downloads/` is gitignored).
6. If `git diff --cached` shows changes, commit and push with message `chore(artifacts): update fetch metadata [skip ci]`.
7. If no changes, exit cleanly (no failure).
8. Upload `artifacts/_run.log` as a workflow artifact (retained 30 days) regardless of outcome.

**Concurrency:** The `fetch-docs` concurrency group ensures only one run executes at a time;
a new run cancels any in-progress run.

**No PDFs are committed.** The `./_downloads/` directory is excluded by `.gitignore`.

---

## How to add a source

Edit `sources.yaml` and add a new entry under `sources:`:

```yaml
- group: My Manufacturer
  manual_type: Maintenance Manual
  url: https://example.com/manuals/
  mode: page          # "page" = crawl HTML for links | "file" = direct download
  max_depth: 1        # how many link levels to follow (page mode)
  same_host_only: true
  login_required: false
  notes: "Optional human-readable context"
```

### Field reference

| Field | Type | Default | Description |
|---|---|---|---|
| `url` | string | **required** | Seed URL |
| `group` | string | `Uncategorised` | Logical grouping (e.g. manufacturer name) |
| `manual_type` | string | `Unknown` | Document category tag |
| `mode` | `page` or `file` | `page` | Crawl HTML (`page`) or fetch a direct file URL (`file`) |
| `max_depth` | integer | `1` | Max HTML link-follow depth (page mode only) |
| `same_host_only` | boolean | `true` | Restrict link-following to the same hostname |
| `login_required` | boolean | `false` | If `true`, skip crawling and record in `_LOGIN_REQUIRED_TODO.md` |
| `notes` | string | `""` | Human-readable notes |

---

## Artifact file reference

### `artifacts/_index.json`

JSON object mapping each discovered URL to its metadata:

```json
{
  "https://example.com/manual.pdf": {
    "sha256": "abc123...",
    "size": 2097152,
    "group": "FAA Handbooks",
    "manual_type": "Pilot Handbook",
    "local_path": "_downloads/FAA Handbooks/manual.pdf",
    "filename": "manual.pdf",
    "content_type": "application/pdf",
    "status": "ok",
    "final_url": "https://example.com/manual.pdf",
    "discovered_from": "https://example.com/manuals/"
  }
}
```

### `artifacts/_manifest.csv` / `_manifest.jsonl`

Flat table / line-delimited JSON with columns:

`url, final_url, filename, content_type, size, sha256, group, manual_type, discovered_from, local_path, status`

**`status` values:**

| Value | Meaning |
|---|---|
| `ok` | Downloaded successfully |
| `dry_run` | Discovered but not downloaded (--dry-run) |
| `no_download` | Discovered but skipped (--no-download) |
| `duplicate` | SHA-256 already seen; file discarded |
| `too_large` | File exceeded `--max-file-mb` cap |
| `error` | Download or I/O error |

### `artifacts/_LOGIN_REQUIRED_TODO.md`

Markdown table listing sources that require authentication.  These must be
downloaded manually.

### `artifacts/_run.log`

Full structured log from the last crawler run.

### `artifacts/_sources_expanded.json`

The normalised `sources.yaml` entries with all defaults applied — useful for
auditing what the crawler was configured to process.

---

## Legal & copyright notes

> **This tool only accesses publicly available documents.**

- The crawler respects HTTP `401`/`403` responses and does not attempt to
  bypass authentication or paywalls.
- All sources in `sources.yaml` are public, free-to-access documentation
  portals.  Sources that require login are flagged `login_required: true` and
  are skipped automatically.
- Downloaded documents remain subject to the copyright and licensing terms of
  each original publisher.  The `_downloads/` folder is **not committed** to
  this repository to avoid inadvertent redistribution.
- The metadata artifacts (URLs, filenames, SHA-256 hashes, sizes) are factual
  bibliographic information and are not themselves copyright works.
- If you believe a source has been included in error, please open an issue or
  remove it from `sources.yaml`.

---

## Contributing

1. Fork the repo and create a feature branch.
2. Add or update entries in `sources.yaml`.
3. Run `python -m fetcher --dry-run` to verify the config parses without errors.
4. Open a pull request.

Bug reports and source suggestions are welcome via GitHub Issues.
