"""
Expand paper library with:
1. IEEE Transactions on Power Systems (ISSN: 0885-8950) - latest
2. IEEE Transactions on Sustainable Energy (ISSN: 1949-3029) - latest
3. IEEE Transactions on Industrial Electronics (ISSN: 0278-0046) - latest
4. Renewable and Sustainable Energy Reviews (ISSN: 1364-0321) - 2026
5. More CCF-A conference papers (CVPR, ACL, SIGMOD, SIGCOMM, OSDI, etc.)

Run: python seed_expand.py
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
    params = urllib.parse.urlencode({
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    url = f"{ARXIV_API}?{params}"
    print(f"  Fetching: {url[:120]}...")

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
    "IEEE Transactions on Power Systems Information for Authors",
    "IEEE Transactions on Sustainable Energy Information for Authors",
    "IEEE Transactions on Industrial Electronics Information for Authors",
}


def fetch_crossref_papers(issn, journal_name, max_results=100, from_date="2026-01-01"):
    params = urllib.parse.urlencode({
        "filter": f"issn:{issn},from-pub-date:{from_date}",
        "sort": "published",
        "order": "desc",
        "rows": max_results,
        "select": "DOI,title,author,abstract,published-print,published-online,container-title,volume,issue",
    })
    url = f"{CROSSREF_API}?{params}"
    print(f"  Fetching: {url[:120]}...")

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


# ─── OpenAlex abstract fetcher ────────────────────────────────

def fetch_openalex_abstract(doi):
    try:
        r = requests.get(
            f"https://api.openalex.org/works/doi:{doi}",
            timeout=15,
            headers={"User-Agent": "PaperFlow/1.0 (mailto:paperflow@research.edu)"},
        )
        if r.status_code == 200:
            inv = r.json().get("abstract_inverted_index")
            if inv:
                words = {}
                for w, positions in inv.items():
                    for pos in positions:
                        words[pos] = w
                return " ".join(words[i] for i in sorted(words))
    except Exception:
        pass
    return None


# ─── Seed into DB ─────────────────────────────────────────────

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

    # ═══════════════════════════════════════════════════════════
    # 1. IEEE Transactions on Power Systems (ISSN: 0885-8950)
    # ═══════════════════════════════════════════════════════════
    print("=" * 60)
    print("[1/8] IEEE Trans. Power Systems (latest)")
    print("=" * 60)
    tps_papers = fetch_crossref_papers(
        issn="0885-8950",
        journal_name="IEEE Transactions on Power Systems",
        max_results=100,
        from_date="2026-01-01",
    )
    print(f"  Found {len(tps_papers)} papers")
    total_new += seed_papers(tps_papers, "IEEE TPS")
    time.sleep(3)

    # ═══════════════════════════════════════════════════════════
    # 2. IEEE Transactions on Sustainable Energy (ISSN: 1949-3029)
    # ═══════════════════════════════════════════════════════════
    print("=" * 60)
    print("[2/8] IEEE Trans. Sustainable Energy (latest)")
    print("=" * 60)
    tse_papers = fetch_crossref_papers(
        issn="1949-3029",
        journal_name="IEEE Transactions on Sustainable Energy",
        max_results=100,
        from_date="2026-01-01",
    )
    print(f"  Found {len(tse_papers)} papers")
    total_new += seed_papers(tse_papers, "IEEE TSE")
    time.sleep(3)

    # ═══════════════════════════════════════════════════════════
    # 3. IEEE Transactions on Industrial Electronics (ISSN: 0278-0046)
    # ═══════════════════════════════════════════════════════════
    print("=" * 60)
    print("[3/8] IEEE Trans. Industrial Electronics (latest)")
    print("=" * 60)
    tie_papers = fetch_crossref_papers(
        issn="0278-0046",
        journal_name="IEEE Transactions on Industrial Electronics",
        max_results=100,
        from_date="2026-01-01",
    )
    print(f"  Found {len(tie_papers)} papers")
    total_new += seed_papers(tie_papers, "IEEE TIE")
    time.sleep(3)

    # ═══════════════════════════════════════════════════════════
    # 4. Renewable and Sustainable Energy Reviews (ISSN: 1364-0321)
    #    Only papers we can get abstracts for (CrossRef + OpenAlex)
    # ═══════════════════════════════════════════════════════════
    print("=" * 60)
    print("[4/8] Renewable & Sustainable Energy Reviews 2026")
    print("=" * 60)
    rser_papers = fetch_crossref_papers(
        issn="1364-0321",
        journal_name="Renewable and Sustainable Energy Reviews",
        max_results=100,
        from_date="2026-01-01",
    )
    # Try to get abstracts from OpenAlex for those without
    for p in rser_papers:
        if not p["abstract"]:
            doi = p["article_number"].replace("crossref_", "").replace("_", "/", 1)
            abstract = fetch_openalex_abstract(doi)
            if abstract:
                p["abstract"] = abstract
                print(f"  [OA] Got abstract for {p['title'][:50]}...")
            time.sleep(0.5)

    # Filter to only keep papers with abstracts
    rser_with_abs = [p for p in rser_papers if p["abstract"]]
    print(f"  Found {len(rser_papers)} total, {len(rser_with_abs)} with abstracts")
    total_new += seed_papers(rser_with_abs, "RSER")
    time.sleep(3)

    # ═══════════════════════════════════════════════════════════
    # 5-8. More CCF-A conference papers
    # ═══════════════════════════════════════════════════════════

    ccf_a_conferences = [
        # (query, max_results, pub_title, label)
        ('all:"CVPR 2025" OR all:"CVPR 2026"', 20, "CVPR", "CVPR"),
        ('all:"ACL 2025" OR all:"ACL 2026"', 20, "ACL", "ACL"),
        ('all:"SIGKDD 2025" OR all:"KDD 2025" OR all:"KDD 2026"', 15, "KDD", "KDD"),
        ('all:"IJCAI 2025" OR all:"IJCAI 2026"', 15, "IJCAI", "IJCAI"),
    ]

    for i, (query, max_results, pub_title, label) in enumerate(ccf_a_conferences, 5):
        print("=" * 60)
        print(f"[{i}/8] {label} papers from arXiv")
        print("=" * 60)
        papers = fetch_arxiv_papers(
            query=query,
            max_results=max_results,
            pub_title=pub_title,
        )
        print(f"  Found {len(papers)} {label} papers")
        total_new += seed_papers(papers, label)
        time.sleep(5)  # arXiv rate limit

    print("=" * 60)
    print(f"All done! {total_new} new papers added total.")


if __name__ == "__main__":
    from app import create_app
    app = create_app()
    with app.app_context():
        main()
