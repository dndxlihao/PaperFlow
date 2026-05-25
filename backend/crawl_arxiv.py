"""
arXiv paper crawler.
Uses the public arXiv API (no authentication needed).
Supports searching by category (e.g. cs.AI, cs.LG) or by keyword.
"""

import os
import time
import requests
import xml.etree.ElementTree as ET


ARXIV_API = "http://export.arxiv.org/api/query"
ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

# CCF-A related arXiv categories
CCFA_CATEGORIES = [
    "cs.AI",    # Artificial Intelligence
    "cs.CL",    # Computation and Language (NLP)
    "cs.CV",    # Computer Vision
    "cs.LG",    # Machine Learning
    "cs.CR",    # Cryptography and Security
    "cs.DB",    # Databases
    "cs.DC",    # Distributed Computing
    "cs.DS",    # Data Structures and Algorithms
    "cs.IR",    # Information Retrieval
    "cs.IT",    # Information Theory
    "cs.NI",    # Networking
    "cs.OS",    # Operating Systems
    "cs.PL",    # Programming Languages
    "cs.SE",    # Software Engineering
    "stat.ML",  # Machine Learning (Statistics)
]


def search_arxiv(
    query: str = "",
    category: str = "",
    start: int = 0,
    max_results: int = 25,
    sort_by: str = "submittedDate",
    sort_order: str = "descending",
) -> list[dict]:
    """
    Search arXiv papers.

    Args:
        query: Search keyword (searches title and abstract)
        category: arXiv category, e.g. "cs.AI"
        start: Pagination offset
        max_results: Number of results (max 100)
        sort_by: "relevance", "lastUpdatedDate", or "submittedDate"
        sort_order: "ascending" or "descending"

    Returns:
        List of paper dicts
    """
    search_parts = []
    if query:
        search_parts.append(f"all:{query}")
    if category:
        search_parts.append(f"cat:{category}")

    if not search_parts:
        search_parts.append("cat:cs.AI")

    search_query = "+AND+".join(search_parts)

    params = {
        "search_query": search_query,
        "start": start,
        "max_results": min(max_results, 100),
        "sortBy": sort_by,
        "sortOrder": sort_order,
    }

    resp = requests.get(ARXIV_API, params=params, timeout=30)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    entries = root.findall("atom:entry", ARXIV_NS)

    results = []
    for entry in entries:
        arxiv_id = entry.find("atom:id", ARXIV_NS).text.strip()
        # Extract clean ID: "http://arxiv.org/abs/2301.12345v1" -> "2301.12345"
        clean_id = arxiv_id.split("/abs/")[-1].split("v")[0] if "/abs/" in arxiv_id else arxiv_id

        title = entry.find("atom:title", ARXIV_NS).text.strip().replace("\n", " ")
        abstract = entry.find("atom:summary", ARXIV_NS).text.strip().replace("\n", " ")
        published = entry.find("atom:published", ARXIV_NS).text.strip()[:10]

        authors = []
        for author in entry.findall("atom:author", ARXIV_NS):
            name = author.find("atom:name", ARXIV_NS)
            if name is not None:
                authors.append(name.text.strip())

        categories = []
        for cat in entry.findall("atom:category", ARXIV_NS):
            term = cat.get("term", "")
            if term:
                categories.append(term)

        # PDF link
        pdf_link = None
        for link in entry.findall("atom:link", ARXIV_NS):
            if link.get("title") == "pdf":
                pdf_link = link.get("href")
                break
        if not pdf_link:
            pdf_link = f"https://arxiv.org/pdf/{clean_id}.pdf"

        results.append({
            "articleNumber": f"arxiv_{clean_id}",
            "articleTitle": title,
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "publicationDate": published,
            "publicationTitle": f"arXiv [{', '.join(categories[:3])}]",
            "displayPublicationTitle": "arXiv",
            "downloadCount": None,
            "pdfLink": pdf_link,
            "arxivId": clean_id,
            "categories": categories,
            "source": "arxiv",
        })

    return results


def download_arxiv_pdf(arxiv_id: str, out_dir: str = "docs") -> str:
    """Download an arXiv paper PDF."""
    clean_id = arxiv_id.replace("arxiv_", "")
    safe_name = f"arxiv_{clean_id.replace('/', '_')}"
    out_path = os.path.join(out_dir, f"{safe_name}.pdf")

    if os.path.exists(out_path):
        return out_path

    os.makedirs(out_dir, exist_ok=True)
    pdf_url = f"https://arxiv.org/pdf/{clean_id}.pdf"

    resp = requests.get(pdf_url, timeout=60, stream=True)
    resp.raise_for_status()

    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 128):
            if chunk:
                f.write(chunk)

    # Verify it's a PDF
    with open(out_path, "rb") as f:
        head = f.read(4)
    if head != b"%PDF":
        os.remove(out_path)
        raise RuntimeError(f"Downloaded file is not a valid PDF (header={head!r})")

    print(f"[OK] arXiv PDF downloaded: {out_path}")
    return out_path


if __name__ == "__main__":
    results = search_arxiv(category="cs.AI", max_results=5)
    for r in results:
        print(f"  {r['arxivId']}: {r['title'][:80]}")
    print(f"Total: {len(results)}")
