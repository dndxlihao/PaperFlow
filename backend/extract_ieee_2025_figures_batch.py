import os
import re
import time
import random
import requests

from openai import OpenAI

from app import create_app
from models import Paper, db
from getDoc import get_cookie_and_ua, get_pdf_doc, make_session
from extract_figures import extract_best_figure, generate_figure_explanation, FIGURES_DIR, PDF_DIR

TARGET_JOURNALS = [
    "IEEE Transactions on Smart Grid",
    "IEEE Transactions on Industrial Informatics",
    "IEEE Transactions on Power Electronics",
    "IEEE Transactions on Industrial Electronics",
    "IEEE Transactions on Sustainable Energy",
    "IEEE Transactions on Power Systems",
]


def parse_doi(article_number):
    if not article_number or not article_number.startswith("crossref_"):
        return ""
    raw = article_number[len("crossref_"):]
    m = re.match(r"(10\.\d{4,9})_(.*)", raw)
    if not m:
        return ""
    return f"{m.group(1)}/{m.group(2)}"


def resolve_arnumber(paper):
    src = paper.source_url or ""
    m = re.search(r"/document/(\d+)", src)
    if m:
        return m.group(1)

    doi = parse_doi(paper.article_number)
    if not doi:
        return None

    try:
        r = requests.get(
            f"https://doi.org/{doi}",
            allow_redirects=True,
            timeout=25,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        final_url = r.url or ""
        m2 = re.search(r"/document/(\d+)", final_url)
        if m2:
            if not paper.source_url:
                paper.source_url = final_url
                db.session.commit()
            return m2.group(1)
    except Exception:
        return None

    return None


def _process_batch(app, client, model, limit_per_run):
    """Process one figure batch and return batch stats."""
    print("Getting IEEE cookies...", flush=True)
    cookie_head, ua = get_cookie_and_ua(debug=False)
    sess = make_session()

    papers = Paper.query.filter(
        Paper.publication_title.in_(TARGET_JOURNALS),
        Paper.publication_date.like("2025%"),
        (Paper.figure_path.is_(None)) | (Paper.figure_path == ""),
    ).order_by(Paper.id).limit(limit_per_run).all()

    ok = 0
    no_pdf = 0
    no_fig = 0
    dl_fail = 0
    err = 0

    for i, p in enumerate(papers, 1):
        arnumber = resolve_arnumber(p)
        if not arnumber:
            no_pdf += 1
            if i % 10 == 0:
                print(f"[{i}/{len(papers)}] no arnumber: {p.article_number}", flush=True)
            continue

        pdf_path = os.path.join(PDF_DIR, f"{arnumber}.pdf")
        fig_filename = f"{p.article_number}.png"
        fig_path = os.path.join(FIGURES_DIR, fig_filename)

        if not os.path.exists(pdf_path):
            downloaded = False
            for _ in range(3):
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
                            if f.read(4) == b"%PDF":
                                downloaded = True
                                break
                        os.remove(pdf_path)
                except Exception:
                    pass
                time.sleep(random.uniform(3, 8))

            if not downloaded:
                dl_fail += 1
                continue

        p.pdf_path = pdf_path

        try:
            found, caption = extract_best_figure(pdf_path, fig_path)
        except Exception:
            db.session.commit()
            err += 1
            continue

        if not found:
            no_fig += 1
            db.session.commit()
            continue

        try:
            explanation = generate_figure_explanation(
                client,
                model,
                p.title or "",
                p.abstract or "",
                caption,
            )
            p.figure_explanation = explanation
        except Exception:
            pass

        p.figure_path = fig_filename
        db.session.commit()
        ok += 1

        if i % 10 == 0:
            print(
                f"[{i}/{len(papers)}] ok={ok} dl_fail={dl_fail} no_pdf={no_pdf} no_fig={no_fig} err={err}",
                flush=True,
            )
        time.sleep(random.uniform(1.0, 2.5))

    print(
        f"Done batch. ok={ok} dl_fail={dl_fail} no_pdf={no_pdf} no_fig={no_fig} err={err}",
        flush=True,
    )
    return {
        "processed": len(papers),
        "ok": ok,
        "no_pdf": no_pdf,
        "no_fig": no_fig,
        "dl_fail": dl_fail,
        "err": err,
    }


def main(limit_per_run=120, max_idle_rounds=3):
    os.makedirs(FIGURES_DIR, exist_ok=True)
    os.makedirs(PDF_DIR, exist_ok=True)

    app = create_app()
    with app.app_context():
        client = OpenAI(
            api_key=app.config["DEEPSEEK_API_KEY"],
            base_url=app.config["DEEPSEEK_BASE_URL"],
        )
        model = app.config["DEEPSEEK_MODEL"]

        total_remaining = Paper.query.filter(
            Paper.publication_title.in_(TARGET_JOURNALS),
            Paper.publication_date.like("2025%"),
            (Paper.figure_path.is_(None)) | (Paper.figure_path == ""),
        ).count()
        print(f"Total target papers missing figure: {total_remaining}", flush=True)

        if total_remaining == 0:
            print("Nothing to do.", flush=True)
            return

        idle_rounds = 0
        round_no = 0
        while True:
            remaining = Paper.query.filter(
                Paper.publication_title.in_(TARGET_JOURNALS),
                Paper.publication_date.like("2025%"),
                (Paper.figure_path.is_(None)) | (Paper.figure_path == ""),
            ).count()
            print(f"Remaining before round {round_no + 1}: {remaining}", flush=True)
            if remaining == 0:
                print("All done.", flush=True)
                break

            stats = _process_batch(app, client, model, limit_per_run)
            round_no += 1

            if stats["ok"] == 0:
                idle_rounds += 1
            else:
                idle_rounds = 0

            if idle_rounds >= max_idle_rounds:
                print("Stopping after repeated idle rounds with no successful figure extraction.", flush=True)
                break

            time.sleep(8)


if __name__ == "__main__":
    main()
