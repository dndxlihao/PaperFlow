"""
Download IEEE PDFs via campus network (by issue) and extract figures.
1. Crawl each IEEE issue via REST API to get real arnumber for each paper
2. Match with DB papers by DOI
3. Download PDFs and extract figures

Handles crossref_10.1109_* papers that don't have figures yet.
"""
import os
import re
import sys
import time
import random

from app import create_app
from models import Paper, db
from getDoc import get_cookie_and_ua, get_pdf_doc, make_session
from extract_figures import (
    extract_best_figure,
    generate_figure_explanation,
    FIGURES_DIR,
    PDF_DIR,
)
from openai import OpenAI

# IEEE journal punumber -> [(isnumber, vol, issue), ...]
# 2026 issues discovered from IEEE REST API
JOURNAL_ISSUES = {
    "TSG": {
        "punumber": "5165411",
        "issues": [
            ("11404354", "17", "2"),
            ("11311981", "17", "1"),
        ],
    },
    "TIE": {
        "punumber": "41",
        "issues": [
            ("11474704", "73", "5"),
            ("11447357", "73", "4"),
            ("11417365", "73", "3"),
            ("11385824", "73", "2"),
            ("11318836", "73", "1"),
        ],
    },
    "TPWRS": {
        "punumber": "59",
        "issues": [
            ("11418389", "41", "2"),
            ("11345511", "41", "1"),
        ],
    },
    "TSTE": {
        "punumber": "5165391",
        "issues": [
            ("11455529", "17", "2"),
            ("11313737", "17", "1"),
        ],
    },
}


def doi_from_article_number(article_number):
    """Convert DB article_number to DOI.
    crossref_10.1109_tsg.2025.3632848 -> 10.1109/tsg.2025.3632848
    """
    raw = article_number.replace("crossref_", "")
    m = re.match(r"(10\.\d{4,9})_(.*)", raw)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    return None


def crawl_issue_papers(sess, cookie_head, ua, punumber, isnumber, rows_per_page=100):
    """Crawl all papers in an IEEE issue, return list of {doi, arnumber, title}."""
    all_records = []
    page = 1
    while True:
        url = "https://ieeexplore.ieee.org/rest/search"
        data = {
            "punumber": punumber,
            "isnumber": isnumber,
            "sortType": "vol-only-seq",
            "pageNumber": page,
            "rowsPerPage": rows_per_page,
            "returnType": "SEARCH",
            "returnFacets": ["ALL"],
        }
        referer = f"https://ieeexplore.ieee.org/xpl/tocresult.jsp?isnumber={isnumber}&punumber={punumber}"
        headers = {
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://ieeexplore.ieee.org",
            "Referer": referer,
            "Cookie": cookie_head,
        }
        r = sess.post(url, json=data, headers=headers, timeout=(15, 90))
        if r.status_code != 200:
            print(f"  [WARN] Search API returned {r.status_code}")
            break
        result = r.json()
        records = result.get("records", [])
        all_records.extend(records)
        total = result.get("totalRecords", 0)
        if len(all_records) >= total or not records:
            break
        page += 1
        time.sleep(1)

    # Parse records
    papers = []
    for rec in all_records:
        doi = (rec.get("doi") or "").lower()
        arn = rec.get("articleNumber")
        title = rec.get("articleTitle", "")
        if arn and doi:
            papers.append({"doi": doi, "arnumber": str(arn), "title": title})
    return papers


def main():
    os.makedirs(FIGURES_DIR, exist_ok=True)
    os.makedirs(PDF_DIR, exist_ok=True)

    app = create_app()
    with app.app_context():
        client = OpenAI(
            api_key=app.config["DEEPSEEK_API_KEY"],
            base_url=app.config["DEEPSEEK_BASE_URL"],
        )
        model = app.config["DEEPSEEK_MODEL"]

        # Get IEEE papers without figures
        db_papers = Paper.query.filter(
            Paper.article_number.like("crossref_10.1109%"),
            (Paper.figure_path == None) | (Paper.figure_path == ""),
        ).all()

        print(f"Found {len(db_papers)} IEEE papers without figures")
        if not db_papers:
            print("Nothing to do.")
            return

        # Build DOI -> DB paper mapping
        doi_to_paper = {}
        for p in db_papers:
            doi = doi_from_article_number(p.article_number)
            if doi:
                doi_to_paper[doi.lower()] = p

        print(f"Built DOI mapping for {len(doi_to_paper)} papers")

        # Step 1: Get IEEE cookies via campus network
        print("Getting IEEE cookies via Selenium...")
        try:
            cookie_head, ua = get_cookie_and_ua(debug=True)
        except Exception as e:
            print(f"Failed to get cookies: {e}")
            sys.exit(1)

        sess = make_session()

        # Step 2: Crawl each issue to build DOI -> arnumber mapping
        doi_to_arnumber = {}
        for journal_name, info in JOURNAL_ISSUES.items():
            pun = info["punumber"]
            for isnumber, vol, iss in info["issues"]:
                print(f"\nCrawling {journal_name} vol={vol} iss={iss} (isn={isnumber})...")
                issue_papers = crawl_issue_papers(sess, cookie_head, ua, pun, isnumber)
                matched = 0
                for ip in issue_papers:
                    if ip["doi"] in doi_to_paper:
                        doi_to_arnumber[ip["doi"]] = ip["arnumber"]
                        matched += 1
                print(f"  Got {len(issue_papers)} papers, {matched} matched our DB")
                time.sleep(2)

        print(f"\nTotal DOI->arnumber matches: {len(doi_to_arnumber)}/{len(doi_to_paper)}")

        # Step 3: Download PDFs and extract figures
        success = 0
        no_fig = 0
        dl_fail = 0
        errors = 0
        total = len(doi_to_arnumber)

        for i, (doi, arnumber) in enumerate(doi_to_arnumber.items(), 1):
            paper = doi_to_paper[doi]
            fig_filename = f"{paper.article_number}.png"
            fig_path = os.path.join(FIGURES_DIR, fig_filename)
            # get_pdf_doc saves to "docs/{arnumber}.pdf" relative to CWD
            pdf_path = os.path.join("docs", f"{arnumber}.pdf")

            # Download PDF if not exists
            if not os.path.exists(pdf_path):
                print(f"[{i}/{total}] Downloading IEEE#{arnumber} ({paper.title[:40]}...)...")
                downloaded = False
                for backoff_attempt in range(4):  # up to 3 retries with backoff
                    try:
                        get_pdf_doc(
                            sess=sess,
                            cookie_head=cookie_head,
                            user_agent=ua,
                            pdf_number=arnumber,
                            selenium_fallback=False,
                        )
                        downloaded = True
                        break
                    except Exception as e:
                        if "418" in str(e) and backoff_attempt < 3:
                            wait = [120, 240, 480][backoff_attempt]
                            print(f"  ⚠ 418 detected, backing off {wait}s then refreshing cookies...")
                            time.sleep(wait)
                            try:
                                cookie_head, ua = get_cookie_and_ua(debug=False)
                                sess = make_session()
                                print(f"  ✓ Cookies refreshed, retrying...")
                            except Exception as ce:
                                print(f"  ✗ Cookie refresh failed: {ce}")
                        else:
                            print(f"  ✗ Download failed: {e}")
                            break
                if not downloaded:
                    dl_fail += 1
                    continue
                time.sleep(random.uniform(30.0, 45.0))
            else:
                print(f"[{i}/{total}] PDF exists for IEEE#{arnumber}")

            if not os.path.exists(pdf_path):
                print(f"  ✗ PDF not found after download")
                dl_fail += 1
                continue

            # Update paper's pdf_path
            paper.pdf_path = pdf_path

            # Extract figure
            print(f"  Extracting figure...")
            try:
                found, caption = extract_best_figure(pdf_path, fig_path)
            except Exception as e:
                print(f"  ✗ Extraction error: {e}")
                db.session.commit()
                errors += 1
                continue

            if not found:
                print(f"  - No valid figure found")
                db.session.commit()
                no_fig += 1
                continue

            fig_size = os.path.getsize(fig_path)
            print(
                f"  ✓ Figure saved ({fig_size} bytes)"
                + (f" caption: {caption[:60]}..." if caption else "")
            )

            # Generate AI explanation
            try:
                explanation = generate_figure_explanation(
                    client, model,
                    paper.title or "",
                    paper.abstract or "",
                    caption,
                )
                paper.figure_path = fig_filename
                paper.figure_explanation = explanation
                db.session.commit()
                success += 1
                print(f"  ✓ Explanation ({len(explanation)} chars)")
            except Exception as e:
                paper.figure_path = fig_filename
                db.session.commit()
                success += 1
                print(f"  ⚠ Figure saved but explanation failed: {e}")

            time.sleep(0.5)

        # Report unmatched papers
        unmatched = len(doi_to_paper) - len(doi_to_arnumber)
        print(f"\n{'='*60}")
        print(f"Done! Success: {success}, Download failed: {dl_fail}, "
              f"No valid figure: {no_fig}, Errors: {errors}")
        print(f"Unmatched papers (not found in any issue): {unmatched}")


if __name__ == "__main__":
    main()
