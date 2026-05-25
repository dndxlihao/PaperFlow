"""
Seed 10 ICLR 2026 papers from arXiv into the database as recommendations.
These are top papers from ICLR 2026 (conference on Learning Representations).
"""
import re
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

ARXIV_API = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def fetch_iclr_2026_papers(max_results=10):
    """Search arXiv for ICLR 2026 papers."""
    # Search for papers with "ICLR 2026" in their comments (how authors usually tag conference papers)
    query = 'all:"ICLR 2026"'
    params = urllib.parse.urlencode({
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    url = f"{ARXIV_API}?{params}"
    print(f"[ICLR SEED] Fetching: {url}")

    req = urllib.request.Request(url)
    req.add_header("User-Agent", "PaperFlow/1.0 (academic research)")
    with urllib.request.urlopen(req, timeout=30) as resp:
        xml_data = resp.read()

    root = ET.fromstring(xml_data)
    entries = root.findall("atom:entry", NS)
    print(f"[ICLR SEED] Found {len(entries)} papers from arXiv")

    papers = []
    for entry in entries[:max_results]:
        arxiv_id_url = entry.find("atom:id", NS).text.strip()
        arxiv_id = arxiv_id_url.split("/abs/")[-1].split("v")[0]

        title = entry.find("atom:title", NS).text.strip()
        title = re.sub(r"\s+", " ", title)

        abstract = entry.find("atom:summary", NS).text.strip()
        abstract = re.sub(r"\s+", " ", abstract)

        authors = []
        for author_el in entry.findall("atom:author", NS):
            name = author_el.find("atom:name", NS).text.strip()
            authors.append(name)

        published = entry.find("atom:published", NS).text.strip()[:10]  # YYYY-MM-DD

        categories = []
        for cat_el in entry.findall("atom:category", NS):
            categories.append(cat_el.attrib.get("term", ""))

        comment_el = entry.find("arxiv:comment", NS)
        comment = comment_el.text.strip() if comment_el is not None else ""

        papers.append({
            "arxiv_id": arxiv_id,
            "article_number": f"arxiv_{arxiv_id}",
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "published": published,
            "categories": categories,
            "comment": comment,
            "publication_title": "ICLR 2026",
        })

    return papers


def seed_iclr_papers():
    """Import ICLR 2026 papers into DB and create recommendations."""
    # Import inside function so Flask app context is available
    from models import Paper, Recommendation, db

    papers = fetch_iclr_2026_papers(max_results=10)
    if not papers:
        print("[ICLR SEED] No papers found. Check network.")
        return

    today = date.today()
    count = 0

    for p in papers:
        arn = p["article_number"]
        paper = Paper.query.filter_by(article_number=arn).first()
        if not paper:
            paper = Paper(
                article_number=arn,
                title=p["title"],
                abstract=p["abstract"],
                publication_date=p["published"],
                publication_title=p["publication_title"],
                download_count=0,
            )
            paper.authors = p["authors"]
            db.session.add(paper)
            db.session.flush()
            print(f"  [+] Added paper: {p['title'][:60]}...")
        else:
            print(f"  [=] Already exists: {p['title'][:60]}...")

        # Create recommendation if not already recommended today
        existing_rec = Recommendation.query.filter_by(
            paper_id=paper.id, recommended_date=today
        ).first()
        if not existing_rec:
            rec = Recommendation(paper_id=paper.id, recommended_date=today)
            db.session.add(rec)
            count += 1

    db.session.commit()
    print(f"[ICLR SEED] Done! {count} new recommendations created for {today}.")


if __name__ == "__main__":
    # When run directly, create app context
    from app import create_app
    app = create_app()
    with app.app_context():
        seed_iclr_papers()
