"""
Enrich existing papers with AI summaries, keywords, categories, Chinese titles, and affiliations.
Flow:
  1. For papers missing abstract: fetch from Semantic Scholar / OpenAlex API
  2. Use abstract (or title) to generate keywords + category via AI
  3. Use abstract (or title) to generate summary via AI
  4. Translate title to Chinese (title_zh) via AI
  5. Fetch affiliations from OpenAlex

Run: python enrich_papers.py [--force]
"""
import json
import os
import re
import time
import requests
import pdfplumber
from datetime import datetime, timezone
from openai import OpenAI

from app import create_app
from models import Paper, db
from summarizer import summarize_paper, extract_keywords_and_category
from pdf_download import download_pdf_by_article

SUMMARY_SOURCE_PDF = "pdf_full_text"


def pack_summary_payload(summary_html: str, source: str):
    clean = (summary_html or "").strip()
    if not clean:
        return clean
    meta = json.dumps({"source": source}, ensure_ascii=False)
    return f"<!--PF_SUMMARY_META:{meta}-->\n{clean}"


# ─── Abstract fetch helpers ─────────────────────────────────────


def extract_doi_from_arn(article_number: str) -> str:
    """Extract DOI from crossref article_number like crossref_10.1016_j.apenergy.2026.127855"""
    if article_number.startswith("crossref_"):
        raw = article_number[len("crossref_"):]
        m = re.match(r'(10\.\d{4,9})_(.*)', raw)
        if m:
            return f"{m.group(1)}/{m.group(2)}"
    return ""


def fetch_abstract_semantic_scholar(doi: str) -> str | None:
    """Fetch abstract from Semantic Scholar API."""
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=abstract"
        r = requests.get(url, timeout=15, headers={"User-Agent": "PaperFlow/1.0"})
        if r.status_code == 200:
            abstract = r.json().get("abstract")
            if abstract and len(abstract) > 20:
                return abstract
    except Exception:
        pass
    return None


def fetch_abstract_openalex(doi: str) -> str | None:
    """Fetch abstract from OpenAlex API (inverted-index → plain text)."""
    try:
        url = f"https://api.openalex.org/works/doi:{doi}"
        r = requests.get(url, timeout=15, headers={"User-Agent": "PaperFlow/1.0 (mailto:paperflow@research.edu)"})
        if r.status_code == 200:
            inv_abs = r.json().get("abstract_inverted_index")
            if inv_abs:
                words = {}
                for word, positions in inv_abs.items():
                    for pos in positions:
                        words[pos] = word
                abstract = " ".join(words[i] for i in sorted(words))
                if len(abstract) > 20:
                    return abstract
    except Exception:
        pass
    return None


def fetch_abstract(doi: str) -> str | None:
    """Try multiple sources to get an abstract for a DOI."""
    abstract = fetch_abstract_semantic_scholar(doi)
    if abstract:
        return abstract
    time.sleep(0.5)
    abstract = fetch_abstract_openalex(doi)
    return abstract


def fetch_affiliations_openalex(doi: str) -> list[str]:
    """Fetch author affiliations from OpenAlex API."""
    try:
        url = f"https://api.openalex.org/works/doi:{doi}"
        r = requests.get(url, timeout=15, headers={"User-Agent": "PaperFlow/1.0 (mailto:paperflow@research.edu)"})
        if r.status_code == 200:
            data = r.json()
            affiliations = set()
            for authorship in data.get("authorships", []):
                for inst in authorship.get("institutions", []):
                    name = inst.get("display_name")
                    if name:
                        affiliations.add(name)
            return list(affiliations) if affiliations else []
    except Exception:
        pass
    return []


def resolve_pdf_path(paper: Paper, pdf_dir: str) -> str | None:
    arn = (paper.article_number or "").strip()
    candidates = []
    if arn:
        candidates.append(os.path.join(pdf_dir, f"{arn}.pdf"))
        candidates.append(os.path.join(os.path.dirname(__file__), "docs", f"{arn}.pdf"))
    if paper.pdf_path:
        if os.path.isabs(paper.pdf_path):
            candidates.append(paper.pdf_path)
        else:
            candidates.append(os.path.join(os.path.dirname(__file__), "..", paper.pdf_path))
            candidates.append(os.path.join(os.path.dirname(__file__), paper.pdf_path))

    seen = set()
    for p in candidates:
        ap = os.path.abspath(p)
        if ap in seen:
            continue
        seen.add(ap)
        if os.path.exists(ap):
            return ap
    return None


def ensure_pdf_path(paper: Paper, pdf_dir: str) -> str | None:
    pdf_path = resolve_pdf_path(paper, pdf_dir)
    if pdf_path:
        return pdf_path
    arn = (paper.article_number or "").strip()
    try:
        download_pdf_by_article(
            article_number=arn,
            out_dir=pdf_dir,
            source_url=paper.source_url or "",
            elsevier_api_key="",
        )
    except Exception:
        return resolve_pdf_path(paper, pdf_dir)
    return resolve_pdf_path(paper, pdf_dir)


def extract_pdf_text(pdf_path: str) -> str:
    chunks = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            txt = page.extract_text()
            if txt:
                chunks.append(txt)
    return "\n".join(chunks)


def translate_title_zh(client: OpenAI, title: str) -> str:
    """Translate an English paper title to Chinese using DeepSeek."""
    from flask import current_app
    resp = client.chat.completions.create(
        model=current_app.config["DEEPSEEK_MODEL"],
        messages=[
            {"role": "system", "content": "你是一个学术翻译专家。将英文论文标题翻译为准确、专业的中文。只返回翻译结果，不要其他文字。"},
            {"role": "user", "content": title},
        ],
        temperature=0.1,
        max_tokens=200,
    )
    return resp.choices[0].message.content.strip()


# ─── Main enrich function ──────────────────────────────────────


def enrich_all_papers(force_resummarize=False):
    flask_app = create_app()
    with flask_app.app_context():
        from flask import current_app
        client = OpenAI(
            api_key=current_app.config["DEEPSEEK_API_KEY"],
            base_url=current_app.config["DEEPSEEK_BASE_URL"],
        )

        pdf_dir = current_app.config["PDF_DIR"]

        papers = Paper.query.all()
        total = len(papers)
        print(f"[ENRICH] Found {total} papers to process")

        for i, paper in enumerate(papers, 1):
            title = paper.title or ""
            if not title or title in ("Blank Page", "IEEE Transactions on Smart Grid Information for Authors"):
                print(f"\n[{i}/{total}] Skip invalid: {title}")
                continue

            print(f"\n[{i}/{total}] {title[:60]}...")
            arn = paper.article_number or ""
            doi = extract_doi_from_arn(arn)

            # Step 1: Fetch abstract if missing
            if not paper.abstract or len(paper.abstract.strip()) < 20:
                if doi:
                    print(f"  ↓ Fetching abstract for DOI {doi}...")
                    abstract = fetch_abstract(doi)
                    if abstract:
                        paper.abstract = abstract
                        db.session.commit()
                        print(f"  ✓ Abstract fetched ({len(abstract)} chars)")
                    else:
                        print(f"  ✗ Abstract not found via API")
                    time.sleep(1)
            else:
                print(f"  ○ Abstract already exists ({len(paper.abstract)} chars)")

            # Step 2: Extract keywords and category
            if not paper.keywords_json or not paper.category:
                text_for_ai = paper.abstract or title or ""
                if text_for_ai:
                    try:
                        info = extract_keywords_and_category(title, text_for_ai)
                        paper.keywords_json = json.dumps(info.get("keywords", []), ensure_ascii=False)
                        paper.category = info.get("category", "其他")
                        db.session.commit()
                        print(f"  ✓ Keywords: {info.get('keywords', [])}, Category: {paper.category}")
                    except Exception as e:
                        print(f"  ✗ Keywords failed: {e}")
                    time.sleep(1)
            else:
                print(f"  ○ Keywords already set: {paper.category}")

            # Step 3: Generate summary
            need_summary = not paper.summary or force_resummarize
            if need_summary:
                try:
                    pdf_path = ensure_pdf_path(paper, pdf_dir)
                    if not pdf_path:
                        print("  ✗ Summary skipped: no PDF available")
                    else:
                        full_text = extract_pdf_text(pdf_path)
                        if not full_text.strip():
                            print("  ✗ Summary skipped: PDF text is empty")
                        else:
                            summary = summarize_paper(title, paper.abstract or "", full_text)
                            print(f"  ✓ Summary generated from PDF ({len(summary)} chars)")
                            paper.summary = pack_summary_payload(summary, SUMMARY_SOURCE_PDF)
                            paper.summary_generated_at = datetime.now(timezone.utc)
                            paper.pdf_path = os.path.relpath(pdf_path, os.path.join(os.path.dirname(__file__), ".."))
                            db.session.commit()
                except Exception as e:
                    print(f"  ✗ Summary failed: {e}")
                time.sleep(2)
            else:
                print(f"  ○ Summary already exists ({len(paper.summary)} chars)")

            # Step 4: Translate title to Chinese
            if not paper.title_zh:
                try:
                    zh = translate_title_zh(client, title)
                    paper.title_zh = zh
                    db.session.commit()
                    print(f"  ✓ Title ZH: {zh}")
                except Exception as e:
                    print(f"  ✗ Title translation failed: {e}")
                time.sleep(1)
            else:
                print(f"  ○ Title ZH already set")

            # Step 5: Fetch affiliations
            if not paper.affiliations_json and doi:
                affs = fetch_affiliations_openalex(doi)
                if affs:
                    paper.affiliations_json = json.dumps(affs, ensure_ascii=False)
                    db.session.commit()
                    print(f"  ✓ Affiliations: {len(affs)} institutions")
                else:
                    print(f"  ✗ No affiliations found")
                time.sleep(0.5)

        print(f"\n[ENRICH] Done! Processed {total} papers.")


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    if force:
        print("[ENRICH] Force mode: will re-generate all summaries")
    enrich_all_papers(force_resummarize=force)
