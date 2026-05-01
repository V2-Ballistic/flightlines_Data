"""
crawler.py — HTML page crawler and file downloader.

Responsibilities:
- Accept a seed URL and optional depth limit.
- Fetch the page, parse links with BeautifulSoup.
- Follow links that point to downloadable files (PDF, ZIP, …) or further HTML
  pages (up to max_depth), optionally restricted to same host.
- Download files to a work directory, saving with a `.part` extension until
  the download is complete (then rename), to avoid partial files.
- Apply rate-limiting and exponential-back-off retries.
- Treat 401/403 responses as "login required" and record them.
- Respect a per-file size cap to avoid Actions storage blow-ups.
- De-duplicate by SHA-256 digest.
- Emit structured metadata for every discovered/downloaded file.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from typing import Iterator

logger = logging.getLogger(__name__)

# File extensions considered directly downloadable
DOWNLOADABLE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".7z",
        ".rar",
        ".xlsx",
        ".xls",
        ".docx",
        ".doc",
        ".csv",
        ".txt",
    }
)

# Maximum file size to download (200 MB)
MAX_FILE_BYTES: int = 200 * 1024 * 1024

# Default pause between HTTP requests (seconds)
DEFAULT_SLEEP: float = 1.5

# Number of retry attempts on transient errors
MAX_RETRIES: int = 3

USER_AGENT = (
    "FlightlinesDataCrawler/1.0 "
    "(https://github.com/V2-Ballistic/flightlines_Data; "
    "aviation-document-index-bot)"
)


def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _is_downloadable_url(url: str) -> bool:
    """Return True if the URL appears to point directly to a downloadable file."""
    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower()
    return ext in DOWNLOADABLE_EXTENSIONS


def _safe_filename(url: str) -> str:
    """Derive a filesystem-safe filename from a URL."""
    parsed = urlparse(url)
    name = Path(parsed.path).name or "index"
    # Strip query strings that ended up in the name
    name = re.sub(r"[?#].*$", "", name)
    # Replace unsafe chars
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    return name or "download"


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_with_retries(
    session: requests.Session,
    url: str,
    stream: bool = False,
    timeout: int = 30,
    sleep: float = DEFAULT_SLEEP,
) -> requests.Response | None:
    """GET *url* with exponential-backoff retries. Returns None on auth errors."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, stream=stream, timeout=timeout, allow_redirects=True)
        except requests.RequestException as exc:
            wait = sleep * (2 ** (attempt - 1))
            logger.warning("request error (attempt %d/%d) %s: %s", attempt, MAX_RETRIES, url, exc)
            if attempt < MAX_RETRIES:
                time.sleep(wait)
            continue

        if resp.status_code in (401, 403):
            logger.info("auth required (HTTP %s): %s", resp.status_code, url)
            return None  # Caller treats None as login-required

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", sleep * 4))
            logger.warning("rate-limited; sleeping %ss before retry: %s", retry_after, url)
            time.sleep(retry_after)
            continue

        if resp.status_code >= 400:
            logger.warning("HTTP %s for %s", resp.status_code, url)
            return resp  # caller checks status

        return resp

    logger.error("all retries failed for %s", url)
    return None


class Crawler:
    """Crawl a seed URL and download linked files, collecting metadata."""

    def __init__(
        self,
        work_dir: str | Path = "./_downloads",
        dry_run: bool = False,
        no_download: bool = False,
        sleep: float = DEFAULT_SLEEP,
        max_file_bytes: int = MAX_FILE_BYTES,
    ) -> None:
        self.work_dir = Path(work_dir)
        self.dry_run = dry_run
        self.no_download = no_download
        self.sleep = sleep
        self.max_file_bytes = max_file_bytes
        self._session = _make_session()
        self._seen_urls: set[str] = set()
        self._seen_sha256: set[str] = set()

    # ── public API ────────────────────────────────────────────────────────────

    def crawl_source(self, source: dict) -> list[dict]:
        """Process one entry from sources.yaml.

        Returns a list of metadata dicts (one per file found/downloaded).
        """
        url: str = source["url"]
        mode: str = source.get("mode", "page")
        max_depth: int = int(source.get("max_depth", 1))
        same_host_only: bool = bool(source.get("same_host_only", True))
        login_required: bool = bool(source.get("login_required", False))
        group: str = source.get("group", "Uncategorised")
        manual_type: str = source.get("manual_type", "Unknown")

        if login_required:
            logger.info("skipping login-required source: %s", url)
            return []

        logger.info("crawling source: %s [mode=%s, depth=%d]", url, mode, max_depth)

        if mode == "file":
            # Direct file download — no page crawl
            meta = self._download_file(url, group=group, manual_type=manual_type, discovered_from=url)
            return [meta] if meta else []

        # Page crawl
        results: list[dict] = []
        self._crawl_page(
            url=url,
            depth=0,
            max_depth=max_depth,
            same_host_only=same_host_only,
            seed_host=urlparse(url).netloc,
            group=group,
            manual_type=manual_type,
            discovered_from=url,
            results=results,
        )
        return results

    # ── internals ─────────────────────────────────────────────────────────────

    def _crawl_page(
        self,
        url: str,
        depth: int,
        max_depth: int,
        same_host_only: bool,
        seed_host: str,
        group: str,
        manual_type: str,
        discovered_from: str,
        results: list[dict],
    ) -> None:
        if url in self._seen_urls:
            return
        self._seen_urls.add(url)

        if depth > max_depth:
            return

        time.sleep(self.sleep)
        resp = _get_with_retries(self._session, url, sleep=self.sleep)
        if resp is None:
            # 401/403 — log but don't crash
            return
        if resp.status_code >= 400:
            return

        content_type = resp.headers.get("Content-Type", "")
        # If the server redirected us to a file, handle it
        if _is_downloadable_url(resp.url) or not content_type.startswith("text/"):
            meta = self._process_response(
                resp,
                original_url=url,
                group=group,
                manual_type=manual_type,
                discovered_from=discovered_from,
            )
            if meta:
                results.append(meta)
            return

        # Parse HTML for links
        try:
            soup = BeautifulSoup(resp.content, "lxml")
        except Exception:
            soup = BeautifulSoup(resp.content, "html.parser")

        links: list[str] = []
        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            if not href or href.startswith(("#", "mailto:", "javascript:")):
                continue
            abs_url = urljoin(resp.url, href)
            # Strip fragment
            abs_url = abs_url.split("#")[0]
            if same_host_only and urlparse(abs_url).netloc != seed_host:
                continue
            links.append(abs_url)

        for link in links:
            if link in self._seen_urls:
                continue
            if _is_downloadable_url(link):
                meta = self._download_file(
                    link, group=group, manual_type=manual_type, discovered_from=url
                )
                if meta:
                    results.append(meta)
                    self._seen_urls.add(link)
            elif depth < max_depth:
                self._crawl_page(
                    url=link,
                    depth=depth + 1,
                    max_depth=max_depth,
                    same_host_only=same_host_only,
                    seed_host=seed_host,
                    group=group,
                    manual_type=manual_type,
                    discovered_from=url,
                    results=results,
                )

    def _process_response(
        self,
        resp: requests.Response,
        original_url: str,
        group: str,
        manual_type: str,
        discovered_from: str,
    ) -> dict | None:
        """Handle a response that points to a downloadable file."""
        return self._download_from_response(
            resp,
            original_url=original_url,
            group=group,
            manual_type=manual_type,
            discovered_from=discovered_from,
        )

    def _download_file(
        self,
        url: str,
        group: str,
        manual_type: str,
        discovered_from: str,
    ) -> dict | None:
        """Fetch *url* and download it, returning a metadata dict or None."""
        if url in self._seen_urls:
            return None
        self._seen_urls.add(url)

        time.sleep(self.sleep)
        resp = _get_with_retries(self._session, url, stream=True, sleep=self.sleep)
        if resp is None:
            return None
        if not resp.ok:
            return None

        return self._download_from_response(
            resp,
            original_url=url,
            group=group,
            manual_type=manual_type,
            discovered_from=discovered_from,
        )

    def _download_from_response(
        self,
        resp: requests.Response,
        original_url: str,
        group: str,
        manual_type: str,
        discovered_from: str,
    ) -> dict | None:
        """Stream the response body to disk; return metadata dict."""
        final_url = resp.url
        content_type = resp.headers.get("Content-Type", "").split(";")[0].strip()
        filename = self._resolve_filename(resp, original_url)

        # Check Content-Length before streaming
        content_length = resp.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > self.max_file_bytes:
                    logger.warning(
                        "skipping oversized file (%d bytes > %d cap): %s",
                        int(content_length),
                        self.max_file_bytes,
                        final_url,
                    )
                    return None
            except ValueError:
                pass

        meta: dict = {
            "url": original_url,
            "final_url": final_url,
            "filename": filename,
            "content_type": content_type,
            "size": 0,
            "sha256": "",
            "group": group,
            "manual_type": manual_type,
            "discovered_from": discovered_from,
            "local_path": "",
            "status": "dry_run" if self.dry_run else "pending",
        }

        if self.dry_run or self.no_download:
            meta["status"] = "dry_run" if self.dry_run else "no_download"
            logger.info("[%s] %s", meta["status"], final_url)
            return meta

        # Determine destination path
        dest_dir = self._group_dir(group)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / filename
        part_path = dest_path.with_suffix(dest_path.suffix + ".part")

        try:
            size = 0
            h = hashlib.sha256()
            with part_path.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > self.max_file_bytes:
                        logger.warning("file exceeded size cap mid-download; discarding: %s", final_url)
                        part_path.unlink(missing_ok=True)
                        meta["status"] = "too_large"
                        return meta
                    h.update(chunk)
                    fh.write(chunk)
        except Exception as exc:
            logger.error("download error for %s: %s", final_url, exc)
            part_path.unlink(missing_ok=True)
            meta["status"] = "error"
            return meta

        sha = h.hexdigest()

        # De-duplicate by sha256
        if sha in self._seen_sha256:
            logger.info("duplicate (sha256 match); discarding: %s", final_url)
            part_path.unlink(missing_ok=True)
            meta["status"] = "duplicate"
            meta["sha256"] = sha
            return meta

        self._seen_sha256.add(sha)

        # Rename .part → final
        # If a file with the same name exists, version it
        if dest_path.exists():
            stem = dest_path.stem
            suffix = dest_path.suffix
            for i in range(1, 9999):
                dest_path = dest_dir / f"{stem}_{i}{suffix}"
                if not dest_path.exists():
                    break

        part_path.rename(dest_path)

        meta.update(
            {
                "size": size,
                "sha256": sha,
                "local_path": str(dest_path.relative_to(self.work_dir.parent)),
                "status": "ok",
            }
        )
        logger.info("downloaded %s -> %s (%d bytes)", final_url, dest_path.name, size)
        return meta

    def _resolve_filename(self, resp: requests.Response, original_url: str) -> str:
        """Work out a sensible filename for the response."""
        # Try Content-Disposition first
        cd = resp.headers.get("Content-Disposition", "")
        if cd:
            match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', cd, re.IGNORECASE)
            if match:
                name = match.group(1).strip().strip('"\'')
                if name:
                    return re.sub(r'[\\/:*?"<>|]', "_", name)

        # Fall back to path component
        name = _safe_filename(resp.url) or _safe_filename(original_url)

        # Append extension from Content-Type if missing
        if "." not in name:
            ct = resp.headers.get("Content-Type", "").split(";")[0].strip()
            ext = mimetypes.guess_extension(ct) or ""
            if ext and ext not in (".ksh", ".bat"):  # guess_extension quirks
                name += ext

        return name or "download.bin"

    def _group_dir(self, group: str) -> Path:
        """Return the download subdirectory for *group*."""
        safe_group = re.sub(r'[\\/:*?"<>|]', "_", group).strip()
        return self.work_dir / safe_group
