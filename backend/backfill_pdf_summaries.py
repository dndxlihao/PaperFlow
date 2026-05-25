"""
Backfill paper summaries in backend DB using local PDFs first.

Behavior:
1) For papers without summary, try to use existing PDF under docs/.
2) If PDF missing, try to download it (IEEE/arXiv supported).
3) Generate AI summary from full text.
4) Optional fallback to abstract-only summary (disabled by default).

Usage examples:
  python backfill_pdf_summaries.py
  python backfill_pdf_summaries.py --limit 200
  python backfill_pdf_summaries.py --force --limit 100
  python backfill_pdf_summaries.py --allow-abstract-fallback
"""

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Optional

import pdfplumber
from flask import Flask

from config import Config
from models import Paper, db
from pdf_download import download_pdf_by_article
from summarizer import normalize_summary_html, summarize_from_abstract, summarize_paper

SUMMARY_SOURCE_PDF = "pdf_full_text"
SUMMARY_SOURCE_ABSTRACT = "abstract_only"


def pack_summary_payload(summary_html: str, source: Optional[str]):
    clean = (summary_html or "").strip()
    if not clean:
        return clean
    if not source:
        return clean
    meta = json.dumps({"source": source}, ensure_ascii=False)
    return f"<!--PF_SUMMARY_META:{meta}-->\n{clean}"


def extract_text_from_pdf(pdf_path: str) -> str:
    text_chunks = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_chunks.append(page_text)
    return "\n".join(text_chunks)


def resolve_pdf_path(paper: Paper, pdf_dir: str) -> Optional[str]:
    arn = (paper.article_number or "").strip()
    if not arn:
        return None

    candidates = []
    if paper.pdf_path:
        candidates.append(paper.pdf_path)
    candidates.append(os.path.join(pdf_dir, f"{arn}.pdf"))

    for path in candidates:
        if path and os.path.exists(path):
            return path

    # Try downloading when possible.
    try:
        download_pdf_by_article(
            article_number=arn,
            out_dir=pdf_dir,
            source_url=paper.source_url or "",
            elsevier_api_key="",
        )
    except Exception:
        return None

    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def backfill_summaries(limit=0, force=False, allow_abstract_fallback=False):
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)
    with app.app_context():
        pdf_dir = app.config["PDF_DIR"]
        os.makedirs(pdf_dir, exist_ok=True)

        q = Paper.query.order_by(Paper.created_at.desc())
        if not force:
            q = q.filter((Paper.summary.is_(None)) | (Paper.summary == ""))
        papers = q.limit(limit).all() if limit and limit > 0 else q.all()

        total = len(papers)
        print(f"[SUMMARY-BACKFILL] Target papers: {total}")

        ok = 0
        skipped = 0
        failed = 0
        pdf_used = 0
        abstract_used = 0

        for idx, paper in enumerate(papers, 1):
            arn = (paper.article_number or "").strip()
            title = (paper.title or "").strip()
            abstract = (paper.abstract or "").strip()
            print(f"[{idx}/{total}] {arn} | {title[:72]}")

            summary_html = ""
            source = None

            pdf_path = resolve_pdf_path(paper, pdf_dir)
            if pdf_path and os.path.exists(pdf_path):
                try:
                    full_text = extract_text_from_pdf(pdf_path)
                except Exception as e:
                    print(f"  - PDF text extract failed: {e}")
                    full_text = ""

                if full_text.strip():
                    try:
                        summary = summarize_paper(
                            title=title,
                            abstract=abstract,
                            full_text=full_text,
                        )
                        summary_html = normalize_summary_html(summary)
                        source = SUMMARY_SOURCE_PDF
                        paper.pdf_path = pdf_path
                        pdf_used += 1
                    except Exception as e:
                        print(f"  - summarize_paper failed: {e}")

            if not summary_html and allow_abstract_fallback and abstract:
                try:
                    summary = summarize_from_abstract(title=title, abstract=abstract)
                    summary_html = normalize_summary_html(summary)
                    source = SUMMARY_SOURCE_ABSTRACT
                    abstract_used += 1
                except Exception as e:
                    print(f"  - summarize_from_abstract failed: {e}")

            if not summary_html:
                skipped += 1
                reason = "no_pdf_or_text"
                if not allow_abstract_fallback:
                    reason += " (abstract fallback disabled)"
                print(f"  - skipped: {reason}")
                continue

            try:
                paper.summary = pack_summary_payload(summary_html, source)
                paper.summary_generated_at = datetime.now(timezone.utc)
                db.session.add(paper)
                db.session.commit()
                ok += 1
                print(f"  + saved summary ({source})")
            except Exception as e:
                db.session.rollback()
                failed += 1
                print(f"  - db save failed: {e}")

        print(
            "[SUMMARY-BACKFILL] done "
            f"ok={ok}, skipped={skipped}, failed={failed}, "
            f"pdf_used={pdf_used}, abstract_used={abstract_used}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill summaries from local PDFs.")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N papers (0 = no limit).")
    parser.add_argument("--force", action="store_true", help="Re-generate even if summary already exists.")
    parser.add_argument(
        "--allow-abstract-fallback",
        action="store_true",
        help="When PDF unavailable, allow abstract-only summary fallback.",
    )
    args = parser.parse_args()

    backfill_summaries(
        limit=args.limit,
        force=args.force,
        allow_abstract_fallback=args.allow_abstract_fallback,
    )
