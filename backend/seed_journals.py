"""
Seed papers from TSG (IEEE Transactions on Smart Grid),
Applied Energy (Elsevier), and more ICLR papers.

Run: python seed_journals.py
"""
import re
import time
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from paper_filters import is_index_or_toc_content

# ─── arXiv helper ──────────────────────────────────────────────

ARXIV_API = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def fetch_arxiv_papers(query, max_results=10, pub_title=""):
    params = urllib.parse.urlencode({
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    url = f"{ARXIV_API}?{params}"
    print(f"  Fetching: {url}")

    req = urllib.request.Request(url)
    req.add_header("User-Agent", "PaperFlow/1.0 (academic research)")
    with urllib.request.urlopen(req, timeout=30) as resp:
        xml_data = resp.read()

    root = ET.fromstring(xml_data)
    entries = root.findall("atom:entry", NS)
    papers = []
    for entry in entries[:max_results]:
        arxiv_id_url = entry.find("atom:id", NS).text.strip()
        arxiv_id = arxiv_id_url.split("/abs/")[-1].split("v")[0]
        title = re.sub(r"\s+", " ", entry.find("atom:title", NS).text.strip())
        abstract = re.sub(r"\s+", " ", entry.find("atom:summary", NS).text.strip())
        authors = [a.find("atom:name", NS).text.strip() for a in entry.findall("atom:author", NS)]
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


# ─── CrossRef helper (for TSG & Applied Energy) ───────────────

CROSSREF_API = "https://api.crossref.org/works"


def fetch_crossref_papers(issn, journal_name, max_results=10):
    """Fetch recent papers from CrossRef by ISSN."""
    params = urllib.parse.urlencode({
        "filter": f"issn:{issn},from-pub-date:2024-01-01",
        "sort": "published",
        "order": "desc",
        "rows": max_results,
        "select": "DOI,title,author,abstract,published-print,published-online,container-title",
    })
    url = f"{CROSSREF_API}?{params}"
    print(f"  Fetching: {url}")

    req = urllib.request.Request(url)
    req.add_header("User-Agent", "PaperFlow/1.0 (mailto:paperflow@research.edu)")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())

    items = data.get("message", {}).get("items", [])
    papers = []
    for item in items:
        doi = item.get("DOI", "")
        title_list = item.get("title", [])
        title = title_list[0] if title_list else ""
        if not title:
            continue

        # Authors
        authors = []
        for auth in item.get("author", []):
            given = auth.get("given", "")
            family = auth.get("family", "")
            if given and family:
                authors.append(f"{given} {family}")
            elif family:
                authors.append(family)

        # Abstract (may have JATS XML tags)
        abstract = item.get("abstract", "")
        abstract = re.sub(r"<[^>]+>", "", abstract).strip()  # strip HTML/XML tags

        # Date
        date_parts = (
            item.get("published-print", {}).get("date-parts", [[]])
            or item.get("published-online", {}).get("date-parts", [[]])
        )
        pub_date = ""
        if date_parts and date_parts[0]:
            parts = date_parts[0]
            pub_date = f"{parts[0]}"
            if len(parts) > 1:
                pub_date += f"-{parts[1]:02d}"
            if len(parts) > 2:
                pub_date += f"-{parts[2]:02d}"

        # Article number from DOI
        safe_doi = doi.replace("/", "_")
        arn = f"crossref_{safe_doi}"

        papers.append({
            "article_number": arn,
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "published": pub_date,
            "publication_title": journal_name,
            "source_url": f"https://doi.org/{doi}",
        })

    return papers


# ─── Main seed function ──────────────────────────────────────

def seed_papers(papers_list, source_label):
    """Import a list of papers into DB and create recommendations."""
    from models import Paper, Recommendation, db

    today = date.today()
    count = 0

    for p in papers_list:
        if is_index_or_toc_content(p.get("title", ""), p.get("abstract", "")):
            continue
        arn = p["article_number"]
        paper = Paper.query.filter_by(article_number=arn).first()
        if not paper:
            paper = Paper(
                article_number=arn,
                title=p["title"],
                abstract=p.get("abstract", ""),
                publication_date=p.get("published", ""),
                publication_title=p.get("publication_title", ""),
                source_url=p.get("source_url", ""),
                download_count=0,
            )
            paper.authors = p.get("authors", [])
            db.session.add(paper)
            db.session.flush()
            print(f"  [+] {p['title'][:65]}...")
        else:
            # Update source_url if not set
            if not paper.source_url and p.get("source_url"):
                paper.source_url = p["source_url"]
            print(f"  [=] Already exists: {p['title'][:55]}...")

        existing_rec = Recommendation.query.filter_by(
            paper_id=paper.id, recommended_date=today
        ).first()
        if not existing_rec:
            rec = Recommendation(paper_id=paper.id, recommended_date=today)
            db.session.add(rec)
            count += 1

    db.session.commit()
    print(f"  [{source_label}] {count} new recommendations.\n")


def main():
    # 1. ICLR 2026 (10 more, different from existing ones)
    print("=" * 60)
    print("[1/3] Fetching ICLR 2026 papers from arXiv...")
    print("=" * 60)
    iclr_papers = fetch_arxiv_papers(
        query='all:"ICLR 2026"',
        max_results=20,  # fetch 20, skip duplicates
        pub_title="ICLR 2026",
    )
    print(f"  Found {len(iclr_papers)} ICLR papers")
    seed_papers(iclr_papers, "ICLR")

    time.sleep(3)  # politeness delay

    # 2. TSG - IEEE Transactions on Smart Grid (ISSN: 1949-3053)
    print("=" * 60)
    print("[2/3] Fetching TSG (IEEE Trans. Smart Grid) from CrossRef...")
    print("=" * 60)
    tsg_papers = fetch_crossref_papers(
        issn="1949-3053",
        journal_name="IEEE Transactions on Smart Grid",
        max_results=10,
    )
    print(f"  Found {len(tsg_papers)} TSG papers")
    seed_papers(tsg_papers, "TSG")

    time.sleep(3)

    # 3. Applied Energy (ISSN: 0306-2619)
    print("=" * 60)
    print("[3/3] Fetching Applied Energy from CrossRef...")
    print("=" * 60)
    ae_papers = fetch_crossref_papers(
        issn="0306-2619",
        journal_name="Applied Energy",
        max_results=10,
    )
    print(f"  Found {len(ae_papers)} Applied Energy papers")
    seed_papers(ae_papers, "Applied Energy")

    print("=" * 60)
    print("All done!")


if __name__ == "__main__":
    from app import create_app
    app = create_app()
    with app.app_context():
        main()
