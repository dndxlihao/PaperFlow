"""
Download early-access IEEE papers that aren't assigned to any issue yet.

Instead of crawling issue TOCs, resolves each DOI → arnumber via doi.org redirect,
then downloads the PDF and extracts figures.

Handles all IEEE journals: TIE, TSG, TPWRS, TSTE.
"""
import os
import re
import sys
import time
import random
import requests

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

# ── Rate-limit settings ────────────────────────────────
DOI_RESOLVE_DELAY = 0.3       # seconds between DOI resolutions (HEAD is fast)
PDF_DOWNLOAD_DELAY = (25, 40) # random range between PDF downloads
COOKIE_REFRESH_BACKOFF = [90, 180, 360]  # seconds after 418/block


def resolve_doi_to_arnumber(doi, sess=None, timeout=10):
    """Resolve a DOI to IEEE arnumber via doi.org HEAD redirect (fast)."""
    if sess is None:
        sess = requests.Session()
    url = f"https://doi.org/{doi}"
    try:
        # Use HEAD with no redirect following - much faster than GET
        for _ in range(5):  # follow up to 5 hops manually
            r = sess.head(
                url, timeout=timeout, allow_redirects=False,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
            )
            loc = r.headers.get("Location", "")
            m = re.search(r"/document/(\d+)", loc)
            if m:
                return m.group(1)
            if loc and r.status_code in (301, 302, 303, 307, 308):
                url = loc
                continue
            break
    except Exception as e:
        print(f"  [WARN] DOI resolve failed for {doi}: {e}")
    return None


def doi_from_article_number(article_number):
    raw = article_number.replace("crossref_", "")
    m = re.match(r"(10\.\d{4,9})_(.*)", raw)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    return None


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

        # Get all IEEE papers without figures (and without PDF)
        papers = Paper.query.filter(
            Paper.article_number.like("crossref_10.1109%"),
            (Paper.figure_path == None) | (Paper.figure_path == ""),
        ).order_by(Paper.id).all()

        print(f"Found {len(papers)} IEEE papers without figures")
        if not papers:
            print("Nothing to do.")
            return

        # Step 1: Get IEEE cookies
        print("Getting IEEE cookies via Selenium...")
        try:
            cookie_head, ua = get_cookie_and_ua(debug=True)
        except Exception as e:
            print(f"Failed to get cookies: {e}")
            sys.exit(1)

        sess = make_session()
        doi_sess = requests.Session()  # separate session for DOI resolution

        # Step 2: Resolve DOIs to arnumbers (batch, fast)
        print(f"\nStep 1/3: Resolving DOIs to arnumbers...")
        doi_map = []  # list of (paper, doi, arnumber)
        skip_has_pdf = 0

        for i, p in enumerate(papers, 1):
            doi = doi_from_article_number(p.article_number)
            if not doi:
                continue

            # Check if PDF already exists from a previous run with known arnumber
            # (pdf_path might be set but file doesn't exist, or file exists but path not set)
            if p.pdf_path and os.path.exists(p.pdf_path):
                with open(p.pdf_path, "rb") as f:
                    head = f.read(4)
                if head == b"%PDF":
                    # Have PDF, just need figure extraction
                    doi_map.append((p, doi, None, p.pdf_path))
                    skip_has_pdf += 1
                    continue

            if i % 20 == 0:
                print(f"  [{i}/{len(papers)}] resolving...")

            arnumber = resolve_doi_to_arnumber(doi, doi_sess)
            if arnumber:
                pdf_path = os.path.join("docs", f"{arnumber}.pdf")
                # Check if PDF already downloaded
                if os.path.exists(pdf_path):
                    with open(pdf_path, "rb") as f:
                        head = f.read(4)
                    if head == b"%PDF":
                        p.pdf_path = pdf_path
                        db.session.commit()
                        doi_map.append((p, doi, arnumber, pdf_path))
                        skip_has_pdf += 1
                        continue
                doi_map.append((p, doi, arnumber, None))
            else:
                print(f"  ✗ Could not resolve {doi}")

            time.sleep(DOI_RESOLVE_DELAY)

        need_download = [x for x in doi_map if x[3] is None]
        already_have = [x for x in doi_map if x[3] is not None]
        print(f"  Resolved: {len(doi_map)} total, {len(need_download)} need download, {len(already_have)} already have PDF")

        # Step 3: Download PDFs
        print(f"\nStep 2/3: Downloading {len(need_download)} PDFs...")
        success_dl = 0
        fail_dl = 0

        for i, (paper, doi, arnumber, _) in enumerate(need_download, 1):
            pdf_path = os.path.join("docs", f"{arnumber}.pdf")
            print(f"[{i}/{len(need_download)}] Downloading IEEE#{arnumber} | {paper.title[:50]}...")

            downloaded = False
            for backoff_attempt in range(4):
                try:
                    get_pdf_doc(
                        sess=sess,
                        cookie_head=cookie_head,
                        user_agent=ua,
                        pdf_number=arnumber,
                        selenium_fallback=False,
                    )
                    if os.path.exists(pdf_path):
                        with open(pdf_path, "rb") as f:
                            head = f.read(4)
                        if head == b"%PDF":
                            paper.pdf_path = pdf_path
                            db.session.commit()
                            downloaded = True
                            success_dl += 1
                            print(f"  ✓ Downloaded ({os.path.getsize(pdf_path)} bytes)")
                            break
                        else:
                            print(f"  ⚠ Not a PDF (header={head}), retrying...")
                            os.remove(pdf_path)
                    else:
                        print(f"  ⚠ File not created, retrying...")
                except Exception as e:
                    err_str = str(e)
                    if ("418" in err_str or "拦截" in err_str or "HTML" in err_str) and backoff_attempt < 3:
                        wait = COOKIE_REFRESH_BACKOFF[backoff_attempt]
                        print(f"  ⚠ Blocked (418/HTML), backing off {wait}s then refreshing cookies...")
                        time.sleep(wait)
                        try:
                            cookie_head, ua = get_cookie_and_ua(debug=False)
                            sess = make_session()
                            print(f"  ✓ Cookies refreshed")
                        except Exception as ce:
                            print(f"  ✗ Cookie refresh failed: {ce}")
                    else:
                        print(f"  ✗ Download failed: {e}")
                        break

            if not downloaded:
                fail_dl += 1

            delay = random.uniform(*PDF_DOWNLOAD_DELAY)
            print(f"  (waiting {delay:.0f}s)")
            time.sleep(delay)

        print(f"\nDownload results: {success_dl} success, {fail_dl} failed")

        # Rebuild list of papers with PDFs for figure extraction
        all_with_pdf = []
        for paper, doi, arnumber, existing_pdf in doi_map:
            if existing_pdf:
                all_with_pdf.append((paper, existing_pdf))
            elif arnumber:
                pdf_path = os.path.join("docs", f"{arnumber}.pdf")
                if os.path.exists(pdf_path):
                    all_with_pdf.append((paper, pdf_path))

        # Step 4: Extract figures
        print(f"\nStep 3/3: Extracting figures from {len(all_with_pdf)} papers...")
        success_fig = 0
        no_fig = 0
        errors = 0

        for i, (paper, pdf_path) in enumerate(all_with_pdf, 1):
            fig_filename = f"{paper.article_number}.png"
            fig_path = os.path.join(FIGURES_DIR, fig_filename)

            if paper.figure_path and os.path.exists(os.path.join(FIGURES_DIR, paper.figure_path)):
                continue  # already has figure

            print(f"[{i}/{len(all_with_pdf)}] {paper.title[:55]}...")

            try:
                found, caption = extract_best_figure(pdf_path, fig_path)
            except Exception as e:
                print(f"  ✗ Extraction error: {e}")
                errors += 1
                continue

            if not found:
                print(f"  - No valid figure")
                no_fig += 1
                continue

            print(f"  ✓ Figure ({os.path.getsize(fig_path)} bytes)")

            try:
                explanation = generate_figure_explanation(
                    client, model,
                    paper.title or "", paper.abstract or "", caption,
                )
                paper.figure_path = fig_filename
                paper.figure_explanation = explanation
                db.session.commit()
                success_fig += 1
            except Exception as e:
                paper.figure_path = fig_filename
                db.session.commit()
                success_fig += 1
                print(f"  ⚠ Figure saved but explanation failed: {e}")

            time.sleep(0.5)

        print(f"\n{'='*60}")
        print(f"DONE!")
        print(f"  PDF downloads: {success_dl} success, {fail_dl} failed")
        print(f"  Figures: {success_fig} extracted, {no_fig} no valid figure, {errors} errors")


if __name__ == "__main__":
    main()
