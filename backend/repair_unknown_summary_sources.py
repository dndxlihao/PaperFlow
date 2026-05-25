"""
Repair papers whose summary has no source metadata.

What this script does:
1) Find papers with summary text but missing PF_SUMMARY_META source.
2) If local PDF exists, only add source=pdf_full_text metadata (no content rewrite).
3) If local PDF missing, optionally try download (arXiv/IEEE), then regenerate summary from full text.
4) Print final stats.

Usage:
  python backend/repair_unknown_summary_sources.py --dry-run
  python backend/repair_unknown_summary_sources.py
  python backend/repair_unknown_summary_sources.py --limit 200
"""

import argparse
import json
import os
import re
from datetime import datetime, timezone
from typing import Optional

import pdfplumber
from flask import Flask

from config import Config
from models import Paper, db
from pdf_download import download_pdf_by_article
from summarizer import normalize_summary_html, summarize_paper

SUMMARY_SOURCE_PDF = "pdf_full_text"
SUMMARY_META_PATTERN = re.compile(r"^\s*<!--PF_SUMMARY_META:(\{.*?\})-->\s*", re.DOTALL)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _pack_summary_payload(summary_html: str, source: Optional[str]):
    clean = (summary_html or "").strip()
    if not clean:
        return clean
    if not source:
        return clean
    meta = json.dumps({"source": source}, ensure_ascii=False)
    return f"<!--PF_SUMMARY_META:{meta}-->\n{clean}"


def _unpack_summary_payload(summary_text: str):
    if not summary_text:
        return summary_text, None
    text = str(summary_text)
    match = SUMMARY_META_PATTERN.match(text)
    if not match:
        return text, None

    source = None
    try:
        source = json.loads(match.group(1)).get("source")
    except Exception:
        source = None
    return text[match.end():].lstrip(), source


def _to_repo_relative(path: str) -> str:
    if not path:
        return path
    abs_path = os.path.abspath(path)
    try:
        rel = os.path.relpath(abs_path, REPO_ROOT)
    except Exception:
        return path
    return rel if not rel.startswith("..") else abs_path


def _build_pdf_candidates(paper: Paper, pdf_dir: str):
    arn = (paper.article_number or "").strip()
    candidates = []
    # Config path: usually repo/docs
    if arn:
        candidates.append(os.path.join(pdf_dir, f"{arn}.pdf"))
        # Historical path: repo/backend/docs
        candidates.append(os.path.join(REPO_ROOT, "backend", "docs", f"{arn}.pdf"))

    if paper.pdf_path:
        if os.path.isabs(paper.pdf_path):
            candidates.append(paper.pdf_path)
        else:
            # Could be relative to repo root or backend dir.
            candidates.append(os.path.join(REPO_ROOT, paper.pdf_path))
            candidates.append(os.path.join(REPO_ROOT, "backend", paper.pdf_path))

    dedup = []
    seen = set()
    for p in candidates:
        ap = os.path.abspath(p)
        if ap in seen:
            continue
        seen.add(ap)
        dedup.append(ap)
    return dedup


def _resolve_pdf_path(paper: Paper, pdf_dir: str) -> Optional[str]:
    for path in _build_pdf_candidates(paper, pdf_dir):
        if os.path.exists(path):
            return path
    return None


def _try_download_pdf(paper: Paper, pdf_dir: str) -> Optional[str]:
    arn = (paper.article_number or "").strip()
    if not arn:
        return None
    try:
        download_pdf_by_article(
            article_number=arn,
            out_dir=pdf_dir,
            source_url=paper.source_url or "",
            elsevier_api_key="",
        )
    except Exception:
        return None
    return _resolve_pdf_path(paper, pdf_dir)


def _extract_full_text(pdf_path: str) -> str:
    chunks = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            txt = page.extract_text()
            if txt:
                chunks.append(txt)
    return "\n".join(chunks)


def repair_unknown_sources(limit=0, dry_run=False, try_download=True):
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    with app.app_context():
        pdf_dir = os.path.abspath(app.config["PDF_DIR"])
        os.makedirs(pdf_dir, exist_ok=True)

        q = Paper.query.filter(Paper.summary.isnot(None), Paper.summary != "").order_by(Paper.created_at.desc())
        papers = q.limit(limit).all() if limit and limit > 0 else q.all()

        stats = {
            "scanned": 0,
            "unknown_total": 0,
            "tagged_from_existing_pdf": 0,
            "regenerated_after_download": 0,
            "still_unknown_no_pdf": 0,
            "regen_failed": 0,
            "extract_failed": 0,
            "download_attempted": 0,
            "download_succeeded": 0,
        }

        pending_commit = 0
        for idx, paper in enumerate(papers, 1):
            stats["scanned"] += 1
            clean_summary, source = _unpack_summary_payload(paper.summary or "")
            if source:
                continue

            stats["unknown_total"] += 1
            arn = (paper.article_number or "").strip()
            title = (paper.title or "").strip()
            abstract = (paper.abstract or "").strip()
            print(f"[{stats['unknown_total']}] {arn} | {title[:72]}")

            existing_pdf = _resolve_pdf_path(paper, pdf_dir)
            if existing_pdf:
                paper.summary = _pack_summary_payload(clean_summary, SUMMARY_SOURCE_PDF)
                paper.pdf_path = _to_repo_relative(existing_pdf)
                stats["tagged_from_existing_pdf"] += 1
                pending_commit += 1
                if dry_run:
                    db.session.rollback()
                    pending_commit = 0
                elif pending_commit >= 50:
                    db.session.commit()
                    pending_commit = 0
                continue

            # Missing local PDF
            downloaded_pdf = None
            if try_download:
                stats["download_attempted"] += 1
                downloaded_pdf = _try_download_pdf(paper, pdf_dir)
                if downloaded_pdf:
                    stats["download_succeeded"] += 1

            if not downloaded_pdf:
                stats["still_unknown_no_pdf"] += 1
                continue

            try:
                full_text = _extract_full_text(downloaded_pdf)
            except Exception as e:
                print(f"  - extract failed: {e}")
                stats["extract_failed"] += 1
                continue

            if not full_text.strip():
                stats["extract_failed"] += 1
                continue

            try:
                new_summary = summarize_paper(
                    title=title,
                    abstract=abstract,
                    full_text=full_text,
                )
                paper.summary = _pack_summary_payload(normalize_summary_html(new_summary), SUMMARY_SOURCE_PDF)
                paper.summary_generated_at = datetime.now(timezone.utc)
                paper.pdf_path = _to_repo_relative(downloaded_pdf)
                stats["regenerated_after_download"] += 1
                pending_commit += 1
                if dry_run:
                    db.session.rollback()
                    pending_commit = 0
                elif pending_commit >= 10:
                    db.session.commit()
                    pending_commit = 0
            except Exception as e:
                print(f"  - regenerate failed: {e}")
                stats["regen_failed"] += 1

        if not dry_run and pending_commit > 0:
            db.session.commit()

        print("\n[REPAIR-UNKNOWN-SOURCES] done")
        for k, v in stats.items():
            print(f"{k}={v}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Repair papers with unknown summary source metadata.")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N papers (0 = no limit).")
    parser.add_argument("--dry-run", action="store_true", help="Do not persist DB changes.")
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Do not attempt downloading missing PDFs.",
    )
    args = parser.parse_args()
    repair_unknown_sources(
        limit=args.limit,
        dry_run=args.dry_run,
        try_download=not args.no_download,
    )
