"""
Example: download PDFs for Applied Energy latest 2026 issue papers.

What it does:
1) Pull Applied Energy 2026 metadata from Crossref.
2) Identify the latest issue (by publication date, then volume/issue).
3) Try downloading PDFs for several papers via the unified downloader.

Usage:
  python backend/example_applied_energy_2026_pdf_download.py
  python backend/example_applied_energy_2026_pdf_download.py --limit 8 --from-date 2026-01-01
"""

import argparse
import json
import os
import urllib.parse
from datetime import datetime

import requests

from config import Config
from pdf_download import download_pdf_by_article

CROSSREF_API = "https://api.crossref.org/works"
APPLIED_ENERGY_ISSN = "0306-2619"


def _parse_date(item):
    parts = (
        item.get("published-print", {}).get("date-parts", [[]])
        or item.get("published-online", {}).get("date-parts", [[]])
        or item.get("issued", {}).get("date-parts", [[]])
    )
    if not parts or not parts[0]:
        return datetime(1900, 1, 1)
    p = parts[0]
    year = int(p[0]) if len(p) > 0 else 1900
    month = int(p[1]) if len(p) > 1 else 1
    day = int(p[2]) if len(p) > 2 else 1
    month = max(1, min(month, 12))
    day = max(1, min(day, 28))
    return datetime(year, month, day)


def fetch_applied_energy_2026(from_date="2026-01-01", rows=200):
    params = urllib.parse.urlencode({
        "filter": f"issn:{APPLIED_ENERGY_ISSN},from-pub-date:{from_date}",
        "sort": "published",
        "order": "desc",
        "rows": rows,
        "select": "DOI,title,published-print,published-online,issued,volume,issue,container-title",
        "mailto": "paperflow@example.com",
    })
    url = f"{CROSSREF_API}?{params}"

    resp = requests.get(
        url,
        timeout=90,
        headers={"User-Agent": "PaperFlow/1.0 (mailto:paperflow@example.com)"},
    )
    resp.raise_for_status()
    payload = resp.json()

    items = payload.get("message", {}).get("items", []) or []
    papers = []
    for item in items:
        doi = (item.get("DOI") or "").strip()
        if not doi:
            continue
        title_list = item.get("title") or []
        title = title_list[0].strip() if title_list else ""
        if not title:
            continue

        volume = str(item.get("volume") or "").strip()
        issue = str(item.get("issue") or "").strip()
        pub_date = _parse_date(item)
        papers.append({
            "doi": doi,
            "title": title,
            "volume": volume,
            "issue": issue,
            "published": pub_date,
            "source_url": f"https://doi.org/{doi}",
        })
    return papers


def _volume_as_int(text: str):
    try:
        return int(str(text).strip())
    except Exception:
        return -1


def pick_latest_issue(papers):
    if not papers:
        return [], "", ""
    ranked = sorted(
        papers,
        key=lambda x: (
            x["published"],
            _volume_as_int(x.get("volume", "")),
            _volume_as_int(x.get("issue", "")),
        ),
        reverse=True,
    )
    latest = ranked[0]
    latest_volume = latest.get("volume", "")
    latest_issue = latest.get("issue", "")

    if latest_volume and latest_issue:
        target = [p for p in ranked if p.get("volume") == latest_volume and p.get("issue") == latest_issue]
    else:
        # Fallback: if issue metadata sparse, use latest-date papers.
        latest_day = latest["published"].date()
        target = [p for p in ranked if p["published"].date() == latest_day]
    return target, latest_volume, latest_issue


def to_article_number_from_doi(doi: str):
    return f"crossref_{doi.replace('/', '_')}"


def main(limit=5, from_date="2026-01-01"):
    pdf_dir = os.path.abspath(Config.PDF_DIR)
    elsevier_api_key = Config.ELSEVIER_API_KEY or ""

    print("=" * 72)
    print("Applied Energy 2026 latest issue PDF download example")
    print("=" * 72)

    papers = fetch_applied_energy_2026(from_date=from_date, rows=240)
    print(f"Fetched {len(papers)} Applied Energy papers since {from_date}.")
    if not papers:
        return

    issue_papers, volume, issue = pick_latest_issue(papers)
    issue_label = f"vol={volume or 'N/A'} issue={issue or 'N/A'}"
    print(f"Latest issue inferred: {issue_label}, papers={len(issue_papers)}")

    targets = issue_papers[: max(1, limit)]
    ok = 0
    fail = 0
    for idx, p in enumerate(targets, 1):
        doi = p["doi"]
        arn = to_article_number_from_doi(doi)
        print(f"\n[{idx}/{len(targets)}] {p['title'][:90]}")
        print(f"  DOI: {doi}")
        path = download_pdf_by_article(
            article_number=arn,
            out_dir=pdf_dir,
            source_url=p["source_url"],
            elsevier_api_key=elsevier_api_key,
        )
        if path and os.path.exists(path):
            size_kb = round(os.path.getsize(path) / 1024, 1)
            print(f"  ✓ PDF downloaded: {path} ({size_kb} KB)")
            ok += 1
        else:
            print("  ✗ PDF download failed (likely paywall or anti-bot)")
            fail += 1

    print("\n" + "-" * 72)
    print(f"Done. success={ok}, failed={fail}, total={len(targets)}")
    print(f"PDF directory: {pdf_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5, help="How many papers to test from latest issue")
    parser.add_argument("--from-date", default="2026-01-01", help="Crossref from-pub-date filter")
    args = parser.parse_args()
    main(limit=max(1, args.limit), from_date=args.from_date)
