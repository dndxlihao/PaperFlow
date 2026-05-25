"""
Seed additional papers into PaperFlow:
- TSG latest issue (all articles)
- Applied Energy latest issue (all articles)
- AAAI 2025/2026 (10 papers)
- ICML 2025 (10 papers)
- NeurIPS 2025 (10 papers)
- Energy journal latest issue (all articles)

Run: python seed_new_papers.py
"""
import re
import time
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import requests
from datetime import date, datetime, timezone


# ─── arXiv helper ──────────────────────────────────────────────

ARXIV_API = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def fetch_arxiv_papers(query, max_results=10, pub_title=""):
    """Fetch papers from arXiv API."""
    params = urllib.parse.urlencode({
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    url = f"{ARXIV_API}?{params}"
    print(f"  Fetching: {url[:100]}...")

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


# ─── CrossRef helper ──────────────────────────────────────────

CROSSREF_API = "https://api.crossref.org/works"
INVALID_TITLES = {
    "", "Blank Page",
    "IEEE Transactions on Smart Grid Information for Authors",
    "IEEE Transactions on Smart Grid Publication Information",
}


def fetch_crossref_papers(issn, journal_name, max_results=100, from_date="2026-01-01"):
    """Fetch recent papers from CrossRef by ISSN."""
    params = urllib.parse.urlencode({
        "filter": f"issn:{issn},from-pub-date:{from_date}",
        "sort": "published",
        "order": "desc",
        "rows": max_results,
        "select": "DOI,title,author,abstract,published-print,published-online,container-title,volume,issue",
    })
    url = f"{CROSSREF_API}?{params}"
    print(f"  Fetching: {url[:100]}...")

    req = urllib.request.Request(url)
    req.add_header("User-Agent", "PaperFlow/1.0 (mailto:paperflow@research.edu)")
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())

    items = data.get("message", {}).get("items", [])
    papers = []
    for item in items:
        doi = item.get("DOI", "")
        title_list = item.get("title", [])
        title = title_list[0] if title_list else ""
        if not title or title in INVALID_TITLES:
            continue

        authors = []
        for auth in item.get("author", []):
            given = auth.get("given", "")
            family = auth.get("family", "")
            if given and family:
                authors.append(f"{given} {family}")
            elif family:
                authors.append(family)

        abstract = item.get("abstract", "")
        abstract = re.sub(r"<[^>]+>", "", abstract).strip()

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


def resolve_doi_url(doi):
    """Resolve DOI to direct publisher URL."""
    try:
        r = requests.head(f"https://doi.org/{doi}", allow_redirects=True, timeout=15,
                          headers={"User-Agent": "Mozilla/5.0"})
        return r.url
    except:
        return f"https://doi.org/{doi}"


# ─── Seed into DB ────────────────────────────────────────────

def seed_papers(papers_list, source_label):
    """Import papers into DB and create recommendations."""
    from models import Paper, Recommendation, db

    today = date.today()
    new_count = 0

    for p in papers_list:
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
            new_count += 1
            print(f"  [+] {p['title'][:70]}")
        else:
            if not paper.source_url and p.get("source_url"):
                paper.source_url = p["source_url"]
            print(f"  [=] exists: {p['title'][:60]}")

        existing_rec = Recommendation.query.filter_by(
            paper_id=paper.id, recommended_date=today
        ).first()
        if not existing_rec:
            rec = Recommendation(paper_id=paper.id, recommended_date=today)
            db.session.add(rec)

    db.session.commit()
    print(f"  [{source_label}] {new_count} new papers added.\n")
    return new_count


def main():
    total_new = 0

    # ── 1. TSG latest issue (March 2026, all articles) ─────────
    print("=" * 60)
    print("[1/6] TSG - IEEE Transactions on Smart Grid (latest issue)")
    print("=" * 60)
    tsg_papers = fetch_crossref_papers(
        issn="1949-3053",
        journal_name="IEEE Transactions on Smart Grid",
        max_results=100,
        from_date="2026-03-01",
    )
    print(f"  Found {len(tsg_papers)} TSG papers")
    total_new += seed_papers(tsg_papers, "TSG")
    time.sleep(3)

    # ── 2. Applied Energy latest issue ─────────────────────────
    print("=" * 60)
    print("[2/6] Applied Energy (latest issue, vol 414)")
    print("=" * 60)
    ae_papers = fetch_crossref_papers(
        issn="0306-2619",
        journal_name="Applied Energy",
        max_results=100,
        from_date="2026-07-01",
    )
    print(f"  Found {len(ae_papers)} Applied Energy papers")
    total_new += seed_papers(ae_papers, "Applied Energy")
    time.sleep(3)

    # ── 3. AAAI 2025/2026 ─────────────────────────────────────
    print("=" * 60)
    print("[3/6] AAAI 2025/2026 papers from arXiv")
    print("=" * 60)
    aaai_papers = fetch_arxiv_papers(
        query='all:"AAAI 2025" OR all:"AAAI 2026"',
        max_results=15,  # fetch more, skip dups
        pub_title="AAAI",
    )
    print(f"  Found {len(aaai_papers)} AAAI papers")
    total_new += seed_papers(aaai_papers, "AAAI")
    time.sleep(3)

    # ── 4. ICML 2025 ──────────────────────────────────────────
    print("=" * 60)
    print("[4/6] ICML 2025 papers from arXiv")
    print("=" * 60)
    icml_papers = fetch_arxiv_papers(
        query='all:"ICML 2025"',
        max_results=15,
        pub_title="ICML 2025",
    )
    print(f"  Found {len(icml_papers)} ICML papers")
    total_new += seed_papers(icml_papers, "ICML")
    time.sleep(3)

    # ── 5. NeurIPS 2025 ───────────────────────────────────────
    print("=" * 60)
    print("[5/6] NeurIPS 2025 papers from arXiv")
    print("=" * 60)
    nips_papers = fetch_arxiv_papers(
        query='all:"NeurIPS 2025"',
        max_results=15,
        pub_title="NeurIPS 2025",
    )
    print(f"  Found {len(nips_papers)} NeurIPS papers")
    total_new += seed_papers(nips_papers, "NeurIPS")
    time.sleep(3)

    # ── 6. Energy journal latest issue ────────────────────────
    print("=" * 60)
    print("[6/6] Energy journal (latest issue)")
    print("=" * 60)
    energy_papers = fetch_crossref_papers(
        issn="0360-5442",
        journal_name="Energy",
        max_results=100,
        from_date="2026-06-01",
    )
    print(f"  Found {len(energy_papers)} Energy papers")
    total_new += seed_papers(energy_papers, "Energy")

    print("=" * 60)
    print(f"All done! {total_new} new papers added total.")


if __name__ == "__main__":
    from app import create_app
    app = create_app()
    with app.app_context():
        main()
