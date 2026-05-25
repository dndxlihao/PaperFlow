"""
Daily conference paper update.
Fetches 3 ICLR + 3 AAAI + 2 ICML + 2 NeurIPS = 10 new papers from arXiv,
enriches them (abstract, summary, keywords, category, Chinese title, affiliations),
extracts figures + AI explanations, and creates daily recommendations.

Can be run standalone:  python daily_update.py
Or called from scheduler via run_daily_update(app, strategy="daily").
"""
import json
import os
import random
import re
import time
import urllib3
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

import pdfplumber
import requests
from openai import OpenAI
from paper_filters import is_index_or_toc_content

ARXIV_API = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

FIGURES_DIR = os.path.join(os.path.dirname(__file__), "..", "figures")
PDF_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SUMMARY_SOURCE_PDF = "pdf_full_text"
SUMMARY_META_PATTERN = re.compile(r"^\s*<!--PF_SUMMARY_META:(\{.*?\})-->\s*", re.DOTALL)

# Strategy source mixes: (query, pub_title, count)
STRATEGY_SOURCES = {
    "daily": [
        ('all:"ICLR 2026" OR all:"ICLR 2025"', "ICLR", 3),
        ('all:"AAAI 2026" OR all:"AAAI 2025"', "AAAI", 3),
        ('all:"ICML 2025" OR all:"ICML 2026"', "ICML", 2),
        ('all:"NeurIPS 2025" OR all:"NeurIPS 2026"', "NeurIPS", 2),
    ],
    "weekly": [
        ('all:"ICLR 2026" OR all:"ICLR 2025"', "ICLR", 5),
        ('all:"AAAI 2026" OR all:"AAAI 2025"', "AAAI", 5),
        ('all:"ICML 2025" OR all:"ICML 2026"', "ICML", 4),
        ('all:"NeurIPS 2025" OR all:"NeurIPS 2026"', "NeurIPS", 4),
    ],
    "realtime": [
        ('cat:cs.LG OR cat:cs.AI OR cat:eess.SY', "arXiv Realtime", 5),
    ],
}

STRATEGY_DAILY_CAP = {
    "daily": 10,
    "weekly": 18,
    "realtime": 30,
}


def _pack_summary_payload(summary_html: str, source: str):
    clean = (summary_html or "").strip()
    if not clean:
        return clean
    meta = json.dumps({"source": source}, ensure_ascii=False)
    return f"<!--PF_SUMMARY_META:{meta}-->\n{clean}"


def _unpack_summary_payload(summary_text: str):
    if not summary_text:
        return summary_text, None
    text = str(summary_text)
    m = SUMMARY_META_PATTERN.match(text)
    if not m:
        return text, None
    try:
        source = json.loads(m.group(1)).get("source")
    except Exception:
        source = None
    return text[m.end():].lstrip(), source


def _to_repo_relative(path: str) -> str:
    if not path:
        return path
    ap = os.path.abspath(path)
    try:
        rel = os.path.relpath(ap, REPO_ROOT)
    except Exception:
        return ap
    return rel if not rel.startswith("..") else ap


def _resolve_pdf_path(paper_obj):
    arn = (paper_obj.article_number or "").strip()
    candidates = []
    if arn:
        candidates.append(os.path.join(PDF_DIR, f"{arn}.pdf"))
        candidates.append(os.path.join(REPO_ROOT, "backend", "docs", f"{arn}.pdf"))

    if paper_obj.pdf_path:
        if os.path.isabs(paper_obj.pdf_path):
            candidates.append(paper_obj.pdf_path)
        else:
            candidates.append(os.path.join(REPO_ROOT, paper_obj.pdf_path))
            candidates.append(os.path.join(REPO_ROOT, "backend", paper_obj.pdf_path))

    seen = set()
    for p in candidates:
        ap = os.path.abspath(p)
        if ap in seen:
            continue
        seen.add(ap)
        if os.path.exists(ap):
            return ap
    return None


def _extract_text_from_pdf(pdf_path: str) -> str:
    chunks = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            txt = page.extract_text()
            if txt:
                chunks.append(txt)
    return "\n".join(chunks)


# ─── arXiv fetch ─────────────────────────────────────────────


def fetch_arxiv_new(query, pub_title, max_results=30):
    """Fetch papers from arXiv with retry on rate limit."""
    params = urllib.parse.urlencode({
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    url = f"{ARXIV_API}?{params}"
    print(f"  Fetching arXiv: {query[:50]}...")

    for attempt in range(5):
        try:
            headers = {"User-Agent": "PaperFlow/1.0 (academic research)"}
            try:
                resp = requests.get(url, headers=headers, timeout=60)
                resp.raise_for_status()
                xml_data = resp.content
            except requests.exceptions.SSLError:
                # Fallback for environments with incomplete local CA chain.
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                print("  ⚠ SSL verification failed, retrying arXiv fetch with verify=False once...")
                resp = requests.get(url, headers=headers, timeout=60, verify=False)
                resp.raise_for_status()
                xml_data = resp.content

            root = ET.fromstring(xml_data)
            entries = root.findall("atom:entry", NS)
            papers = []
            for entry in entries:
                arxiv_id_url = entry.find("atom:id", NS).text.strip()
                arxiv_id = arxiv_id_url.split("/abs/")[-1].split("v")[0]
                title = re.sub(r"\s+", " ", entry.find("atom:title", NS).text.strip())
                abstract = re.sub(r"\s+", " ", entry.find("atom:summary", NS).text.strip())
                authors = [a.find("atom:name", NS).text.strip()
                            for a in entry.findall("atom:author", NS)]
                published = entry.find("atom:published", NS).text.strip()[:10]
                papers.append({
                    "article_number": f"arxiv_{arxiv_id}",
                    "title": title,
                    "authors": authors,
                    "abstract": abstract,
                    "published": published,
                    "publication_title": pub_title,
                    "source_url": f"https://arxiv.org/abs/{arxiv_id}",
                })
            return papers
        except Exception as e:
            wait = 30 * (2 ** attempt)  # 30, 60, 120, 240, 480
            print(f"  ⚠ Attempt {attempt+1} failed: {e}, retrying in {wait}s...")
            time.sleep(wait)
    return []


# ─── Enrichment helpers ──────────────────────────────────────


def enrich_paper(paper_obj, client, model):
    """Enrich a single Paper model instance with all metadata."""
    from summarizer import summarize_paper, extract_keywords_and_category
    from flask import current_app
    from pdf_download import download_pdf_by_article_with_report
    from pdf_retry_service import record_pdf_download_outcome

    title = paper_obj.title or ""
    arn = paper_obj.article_number or ""

    # Keywords + category
    if not paper_obj.keywords_json or not paper_obj.category:
        text = paper_obj.abstract or title
        try:
            info = extract_keywords_and_category(title, text)
            paper_obj.keywords_json = json.dumps(info.get("keywords", []), ensure_ascii=False)
            paper_obj.category = info.get("category", "其他")
            print(f"    ✓ Keywords: {paper_obj.category}")
        except Exception as e:
            print(f"    ✗ Keywords failed: {e}")
        time.sleep(1)

    # Summary (must be based on PDF full text)
    summary_text, summary_source = _unpack_summary_payload(paper_obj.summary or "")
    if paper_obj.summary and summary_source == SUMMARY_SOURCE_PDF:
        print("    ○ Summary already based on PDF full text")
    else:
        pdf_path = _resolve_pdf_path(paper_obj)
        if not pdf_path:
            try:
                downloaded, report = download_pdf_by_article_with_report(
                    article_number=arn,
                    out_dir=PDF_DIR,
                    source_url=paper_obj.source_url or "",
                    elsevier_api_key=current_app.config.get("ELSEVIER_API_KEY", ""),
                    elsevier_selenium_attach_debugger=current_app.config.get("ELSEVIER_SELENIUM_ATTACH_DEBUGGER"),
                    elsevier_selenium_debugger_address=current_app.config.get("ELSEVIER_CHROME_DEBUGGER_ADDRESS"),
                    elsevier_selenium_allow_new_browser_on_attach_fail=current_app.config.get(
                        "ELSEVIER_SELENIUM_ALLOW_NEW_BROWSER_ON_ATTACH_FAIL"
                    ),
                )
                record_pdf_download_outcome(
                    app=current_app,
                    article_number=arn,
                    source_url=paper_obj.source_url or "",
                    report=report,
                    paper_id=paper_obj.id,
                    enqueue_on_fail=True,
                )
                pdf_path = downloaded if downloaded and os.path.exists(downloaded) else _resolve_pdf_path(paper_obj)
                if pdf_path:
                    paper_obj.pdf_path = _to_repo_relative(pdf_path)
                    print("    ✓ PDF downloaded for summary")
            except Exception as e:
                print(f"    ✗ PDF download failed: {e}")

        if pdf_path:
            # If summary exists but source metadata is missing, tag it directly.
            if paper_obj.summary and summary_source != SUMMARY_SOURCE_PDF:
                paper_obj.summary = _pack_summary_payload(summary_text, SUMMARY_SOURCE_PDF)
                paper_obj.pdf_path = _to_repo_relative(pdf_path)
                print("    ✓ Summary source tagged as pdf_full_text")
            else:
                try:
                    full_text = _extract_text_from_pdf(pdf_path)
                    if full_text.strip():
                        summary = summarize_paper(
                            title=title,
                            abstract=paper_obj.abstract or "",
                            full_text=full_text,
                        )
                        paper_obj.summary = _pack_summary_payload(summary, SUMMARY_SOURCE_PDF)
                        paper_obj.summary_generated_at = datetime.now(timezone.utc)
                        paper_obj.pdf_path = _to_repo_relative(pdf_path)
                        print(f"    ✓ Summary from PDF full text ({len(summary)} chars)")
                    else:
                        print("    ✗ Summary skipped: PDF text empty")
                except Exception as e:
                    print(f"    ✗ Summary failed: {e}")
            time.sleep(2)
        else:
            print("    ✗ Summary skipped: no local PDF")

    # Chinese title
    if not paper_obj.title_zh:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是一个学术翻译专家。将英文论文标题翻译为准确、专业的中文。只返回翻译结果，不要其他文字。"},
                    {"role": "user", "content": title},
                ],
                temperature=0.1,
                max_tokens=200,
            )
            paper_obj.title_zh = resp.choices[0].message.content.strip()
            print(f"    ✓ Title ZH: {paper_obj.title_zh[:40]}")
        except Exception as e:
            print(f"    ✗ Title ZH failed: {e}")
        time.sleep(1)


def extract_figure_for_paper(paper_obj, client, model):
    """Download PDF (multi-source) and extract best figure + explanation."""
    from extract_figures import extract_best_figure, generate_figure_explanation
    from flask import current_app
    from pdf_download import download_pdf_by_article_with_report
    from pdf_retry_service import record_pdf_download_outcome

    arn = paper_obj.article_number or ""
    if paper_obj.figure_path:
        print(f"    ○ Figure already exists")
        return

    # Find or download PDF
    pdf_path = _resolve_pdf_path(paper_obj)
    if not pdf_path:
        try:
            downloaded, report = download_pdf_by_article_with_report(
                article_number=arn,
                out_dir=PDF_DIR,
                source_url=paper_obj.source_url or "",
                elsevier_api_key=current_app.config.get("ELSEVIER_API_KEY", ""),
                elsevier_selenium_attach_debugger=current_app.config.get("ELSEVIER_SELENIUM_ATTACH_DEBUGGER"),
                elsevier_selenium_debugger_address=current_app.config.get("ELSEVIER_CHROME_DEBUGGER_ADDRESS"),
                elsevier_selenium_allow_new_browser_on_attach_fail=current_app.config.get(
                    "ELSEVIER_SELENIUM_ALLOW_NEW_BROWSER_ON_ATTACH_FAIL"
                ),
            )
            record_pdf_download_outcome(
                app=current_app,
                article_number=arn,
                source_url=paper_obj.source_url or "",
                report=report,
                paper_id=paper_obj.id,
                enqueue_on_fail=True,
            )
            if downloaded and os.path.exists(downloaded):
                pdf_path = downloaded
                paper_obj.pdf_path = _to_repo_relative(pdf_path)
                print("    ✓ PDF downloaded")
                time.sleep(1)
        except Exception as e:
            print(f"    ✗ PDF download failed: {e}")
            return

    if not pdf_path:
        print(f"    - No PDF available for {arn}")
        return

    if not pdf_path or not os.path.exists(pdf_path):
        return

    # Extract figure
    fig_filename = f"{arn}.png"
    fig_path = os.path.join(FIGURES_DIR, fig_filename)
    try:
        found, caption = extract_best_figure(pdf_path, fig_path)
    except Exception as e:
        print(f"    ✗ Figure extraction error: {e}")
        return

    if not found:
        print(f"    - No valid figure found")
        return

    print(f"    ✓ Figure saved")

    # AI explanation
    try:
        explanation = generate_figure_explanation(
            client, model,
            paper_obj.title or "",
            paper_obj.abstract or "",
            caption,
        )
        paper_obj.figure_path = fig_filename
        paper_obj.figure_explanation = explanation
        print(f"    ✓ Explanation ({len(explanation)} chars)")
    except Exception as e:
        paper_obj.figure_path = fig_filename
        print(f"    ⚠ Figure saved but explanation failed: {e}")
    time.sleep(0.5)


# ─── Main logic ──────────────────────────────────────────────


def run_daily_update(app, strategy="daily"):
    """Entry point called by scheduler or standalone."""
    with app.app_context():
        from models import Paper, Recommendation, db

        strategy = (strategy or "daily").strip().lower()
        if strategy not in STRATEGY_SOURCES:
            strategy = "daily"

        today = date.today()

        sources = STRATEGY_SOURCES[strategy]
        daily_cap = STRATEGY_DAILY_CAP.get(strategy, 10)

        # Keep each strategy bounded per day to avoid runaway updates.
        # Count quota by strategy-scoped publication buckets so realtime updates
        # do not consume daily/weekly quota.
        strategy_publications = [pub_title for _, pub_title, _ in sources]
        existing_query = Recommendation.query.filter_by(recommended_date=today)
        if strategy_publications:
            existing_query = existing_query.join(Paper, Paper.id == Recommendation.paper_id).filter(
                Paper.publication_title.in_(strategy_publications)
            )
        existing = existing_query.count()
        if existing >= daily_cap:
            msg = f"[DAILY][{strategy}] Already have {existing} recommendations for {today}, skipping."
            print(msg)
            return {
                "status": "skipped",
                "message": msg,
                "strategy": strategy,
                "date": today.isoformat(),
                "added": 0,
                "existing": existing,
                "cap": daily_cap,
            }

        remaining_quota = max(0, daily_cap - existing)
        if remaining_quota == 0:
            return {
                "status": "skipped",
                "message": "No remaining quota",
                "strategy": strategy,
                "date": today.isoformat(),
                "added": 0,
                "existing": existing,
                "cap": daily_cap,
            }

        os.makedirs(FIGURES_DIR, exist_ok=True)
        os.makedirs(PDF_DIR, exist_ok=True)

        client = OpenAI(
            api_key=app.config["DEEPSEEK_API_KEY"],
            base_url=app.config["DEEPSEEK_BASE_URL"],
        )
        model = app.config["DEEPSEEK_MODEL"]

        # Get existing article_numbers AND titles in DB to avoid duplicates
        all_papers = Paper.query.all()
        existing_arns = {p.article_number for p in all_papers}
        existing_titles = {(p.title or "").strip().lower() for p in all_papers}

        total_added = 0

        for query, pub_title, count_needed in sources:
            if remaining_quota <= 0:
                break

            count_needed = min(count_needed, remaining_quota)
            print(f"\n{'=' * 50}")
            print(f"[DAILY][{strategy}] {pub_title}: need {count_needed} new papers")
            print(f"{'=' * 50}")

            try:
                max_results = 60 if strategy == "weekly" else 30
                candidates = fetch_arxiv_new(query, pub_title, max_results=max_results)
            except Exception as e:
                print(f"  ✗ Fetch failed: {e}")
                time.sleep(15)
                continue

            # Prefer papers not already in DB (by article_number OR title)
            new_candidates = [c for c in candidates
                              if c["article_number"] not in existing_arns
                              and c["title"].strip().lower() not in existing_titles
                              and not is_index_or_toc_content(c.get("title", ""), c.get("abstract", ""))]
            old_candidates = [
                c for c in candidates
                if c["article_number"] in existing_arns
                and not is_index_or_toc_content(c.get("title", ""), c.get("abstract", ""))
            ]

            # Pick from new first, then existing without historical recommendations
            selected = []
            for c in new_candidates:
                if len(selected) >= count_needed:
                    break
                selected.append(c)

            # If not enough new ones, pick existing that were never recommended before.
            if len(selected) < count_needed:
                for c in old_candidates:
                    if len(selected) >= count_needed:
                        break
                    p = Paper.query.filter_by(article_number=c["article_number"]).first()
                    if p:
                        # Allow re-recommendation across days; only avoid duplicates on the same date.
                        has_rec = Recommendation.query.filter_by(paper_id=p.id, recommended_date=today).first()
                        if not has_rec:
                            selected.append(c)

            print(f"  Selected {len(selected)} papers")

            for item in selected:
                arn = item["article_number"]
                if is_index_or_toc_content(item.get("title", ""), item.get("abstract", "")):
                    continue
                print(f"\n  [{pub_title}] {item['title'][:60]}...")

                # Ensure paper in DB
                paper = Paper.query.filter_by(article_number=arn).first()
                if not paper:
                    paper = Paper(
                        article_number=arn,
                        title=item["title"],
                        abstract=item.get("abstract", ""),
                        publication_date=item.get("published", ""),
                        publication_title=item.get("publication_title", ""),
                        source_url=item.get("source_url", ""),
                        download_count=0,
                    )
                    paper.authors = item.get("authors", [])
                    db.session.add(paper)
                    db.session.flush()
                    existing_arns.add(arn)
                    existing_titles.add((paper.title or "").strip().lower())
                    print(f"    + New paper added to DB")

                # Enrich: keywords, summary, Chinese title
                enrich_paper(paper, client, model)

                # Extract figure
                extract_figure_for_paper(paper, client, model)

                db.session.commit()

                # Create recommendation
                _, summary_source = _unpack_summary_payload(paper.summary or "")
                if summary_source != SUMMARY_SOURCE_PDF:
                    print("    - Skip recommendation: summary is not PDF full-text based")
                    continue
                has_rec = Recommendation.query.filter_by(
                    paper_id=paper.id, recommended_date=today
                ).first()
                if not has_rec:
                    rec = Recommendation(paper_id=paper.id, recommended_date=today)
                    db.session.add(rec)
                    db.session.commit()
                    total_added += 1
                    remaining_quota -= 1

            time.sleep(20 if strategy == "realtime" else 30)  # Avoid arXiv rate limits

        print(f"\n{'=' * 50}")
        print(f"[DAILY][{strategy}] Done! {total_added} new recommendations for {today}")
        print(f"{'=' * 50}")
        return {
            "status": "ok",
            "message": f"Added {total_added} recommendations",
            "strategy": strategy,
            "date": today.isoformat(),
            "added": total_added,
            "existing": existing,
            "cap": daily_cap,
        }


if __name__ == "__main__":
    from app import create_app
    app = create_app()
    run_daily_update(app)
