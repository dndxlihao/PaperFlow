"""
Batch seed: all 2026 IEEE journal articles + 50 each of ICLR/ICML/NeurIPS.
Handles CrossRef pagination (1000 rows max per request) and arXiv rate limits.

Run: python seed_batch_2026.py
"""
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date

# ─── CrossRef ─────────────────────────────────────────────────

CROSSREF_API = "https://api.crossref.org/works"
INVALID_TITLES = {
    "", "Blank Page",
    "IEEE Transactions on Smart Grid Information for Authors",
    "IEEE Transactions on Power Systems Information for Authors",
    "IEEE Transactions on Sustainable Energy Information for Authors",
    "IEEE Transactions on Industrial Electronics Information for Authors",
    "Table of Contents", "IEEE Society Information",
    "IEEE Publication Information", "Introducing IEEE Collabratec",
}


def fetch_crossref_all(issn, journal_name, from_date="2026-01-01"):
    """Fetch ALL 2026 papers from CrossRef with pagination."""
    all_papers = []
    offset = 0
    per_page = 500  # CrossRef allows up to 1000

    while True:
        params = urllib.parse.urlencode({
            "filter": f"issn:{issn},from-pub-date:{from_date}",
            "sort": "published",
            "order": "desc",
            "rows": per_page,
            "offset": offset,
            "select": "DOI,title,author,abstract,published-print,published-online,container-title,volume,issue",
        })
        url = f"{CROSSREF_API}?{params}"
        print(f"  Fetching offset={offset}...")

        req = urllib.request.Request(url)
        req.add_header("User-Agent", "PaperFlow/1.0 (mailto:paperflow@research.edu)")
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())

        items = data.get("message", {}).get("items", [])
        total_results = data.get("message", {}).get("total-results", 0)

        for item in items:
            doi = item.get("DOI", "")
            title_list = item.get("title", [])
            title = title_list[0] if title_list else ""
            if not title or title in INVALID_TITLES:
                continue
            # Skip non-article entries
            if any(kw in title.lower() for kw in [
                "table of contents", "society information",
                "publication information", "information for authors",
                "introducing ieee", "blank page",
            ]):
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

            all_papers.append({
                "article_number": arn,
                "title": title,
                "authors": authors,
                "abstract": abstract,
                "published": pub_date,
                "publication_title": journal_name,
                "source_url": f"https://doi.org/{doi}",
            })

        offset += per_page
        if offset >= total_results or not items:
            break
        time.sleep(1)

    return all_papers


# ─── arXiv ────────────────────────────────────────────────────

ARXIV_API = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def fetch_arxiv_batch(query, pub_title, total_needed=50, fetch_per_call=100):
    """Fetch papers from arXiv with pagination and retry."""
    all_papers = []
    seen_ids = set()
    start = 0

    while len(all_papers) < total_needed:
        params = urllib.parse.urlencode({
            "search_query": query,
            "start": start,
            "max_results": fetch_per_call,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        })
        url = f"{ARXIV_API}?{params}"
        print(f"  Fetching arXiv start={start}...")

        for attempt in range(3):
            try:
                req = urllib.request.Request(url)
                req.add_header("User-Agent", "PaperFlow/1.0 (academic research)")
                with urllib.request.urlopen(req, timeout=60) as resp:
                    xml_data = resp.read()

                root = ET.fromstring(xml_data)
                entries = root.findall("atom:entry", NS)

                if not entries:
                    return all_papers

                for entry in entries:
                    arxiv_id_url = entry.find("atom:id", NS).text.strip()
                    arxiv_id = arxiv_id_url.split("/abs/")[-1].split("v")[0]

                    if arxiv_id in seen_ids:
                        continue
                    seen_ids.add(arxiv_id)

                    title = re.sub(r"\s+", " ", entry.find("atom:title", NS).text.strip())
                    abstract = re.sub(r"\s+", " ", entry.find("atom:summary", NS).text.strip())
                    authors = [a.find("atom:name", NS).text.strip()
                               for a in entry.findall("atom:author", NS)]
                    published = entry.find("atom:published", NS).text.strip()[:10]

                    all_papers.append({
                        "article_number": f"arxiv_{arxiv_id}",
                        "title": title,
                        "authors": authors,
                        "abstract": abstract,
                        "published": published,
                        "publication_title": pub_title,
                        "source_url": f"https://arxiv.org/abs/{arxiv_id}",
                    })

                break  # success
            except Exception as e:
                wait = 15 * (attempt + 1)
                print(f"  ⚠ Attempt {attempt+1} failed: {e}, retrying in {wait}s...")
                time.sleep(wait)

        start += fetch_per_call
        time.sleep(5)  # arXiv rate limit

    return all_papers


# ─── DB seed ──────────────────────────────────────────────────

def seed_papers(papers_list, source_label):
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
            print(f"    [+] {p['title'][:70]}")
        else:
            if not paper.source_url and p.get("source_url"):
                paper.source_url = p["source_url"]

        existing_rec = Recommendation.query.filter_by(
            paper_id=paper.id, recommended_date=today
        ).first()
        if not existing_rec:
            rec = Recommendation(paper_id=paper.id, recommended_date=today)
            db.session.add(rec)

    db.session.commit()
    print(f"  [{source_label}] {new_count} new papers added.\n")
    return new_count


# ─── Main ─────────────────────────────────────────────────────

def main():
    total_new = 0

    # ── Part 1: IEEE Journals (all 2026 issues) ──────────────
    ieee_journals = [
        ("1949-3053", "IEEE Transactions on Smart Grid", "TSG"),
        ("0885-8950", "IEEE Transactions on Power Systems", "TPWRS"),
        ("1949-3029", "IEEE Transactions on Sustainable Energy", "TSTE"),
        ("0278-0046", "IEEE Transactions on Industrial Electronics", "TIE"),
    ]

    for i, (issn, journal_name, label) in enumerate(ieee_journals, 1):
        print("=" * 60)
        print(f"[{i}/7] {label} - {journal_name}")
        print("=" * 60)
        papers = fetch_crossref_all(issn, journal_name)
        print(f"  Fetched {len(papers)} valid papers")
        total_new += seed_papers(papers, label)
        time.sleep(2)

    # ── Part 2: Conference papers (50 each) ───────────────────
    conferences = [
        ('all:"ICLR 2026" OR all:"ICLR 2025"', "ICLR", 50),
        ('all:"ICML 2025" OR all:"ICML 2026"', "ICML", 50),
        ('all:"NeurIPS 2025" OR all:"NeurIPS 2026"', "NeurIPS", 50),
    ]

    for i, (query, pub_title, count) in enumerate(conferences, 5):
        print("=" * 60)
        print(f"[{i}/7] {pub_title} - fetching {count} papers")
        print("=" * 60)
        papers = fetch_arxiv_batch(query, pub_title, total_needed=count + 30)
        print(f"  Fetched {len(papers)} papers from arXiv")
        total_new += seed_papers(papers, pub_title)
        time.sleep(10)  # arXiv rate limit between conferences

    print("=" * 60)
    print(f"ALL DONE! {total_new} new papers added total.")
    print("=" * 60)


if __name__ == "__main__":
    from app import create_app
    app = create_app()
    with app.app_context():
        main()
