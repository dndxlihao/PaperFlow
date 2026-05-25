import os
import time

from openai import OpenAI

from app import create_app
from models import Paper, Recommendation, db
from extract_figures import (
    FIGURES_DIR,
    PDF_DIR,
    extract_best_figure,
    generate_figure_explanation,
)
from crawl_arxiv import download_arxiv_pdf


def main(limit=300):
    os.makedirs(FIGURES_DIR, exist_ok=True)
    os.makedirs(PDF_DIR, exist_ok=True)

    app = create_app()
    with app.app_context():
        client = OpenAI(
            api_key=app.config["DEEPSEEK_API_KEY"],
            base_url=app.config["DEEPSEEK_BASE_URL"],
        )
        model = app.config["DEEPSEEK_MODEL"]

        recs = Recommendation.query.order_by(
            Recommendation.recommended_date.desc(),
            Recommendation.id.desc(),
        ).limit(2000).all()

        seen = set()
        targets = []
        for r in recs:
            p = r.paper
            if not p or p.id in seen:
                continue
            seen.add(p.id)
            if p.figure_path:
                continue
            targets.append(p)
            if len(targets) >= limit:
                break

        print(f"Recent recommendation papers needing figure: {len(targets)}", flush=True)

        ok = 0
        no_pdf = 0
        no_fig = 0
        err = 0

        for i, paper in enumerate(targets, 1):
            arn = paper.article_number
            fig_filename = f"{arn}.png"
            fig_path = os.path.join(FIGURES_DIR, fig_filename)

            # resolve PDF path
            pdf_path = None
            if paper.pdf_path and os.path.exists(paper.pdf_path):
                pdf_path = paper.pdf_path
            else:
                expected = os.path.join(PDF_DIR, f"{arn}.pdf")
                if os.path.exists(expected):
                    pdf_path = expected
                elif arn.startswith("arxiv_"):
                    try:
                        pdf_path = download_arxiv_pdf(arn, out_dir=PDF_DIR)
                        paper.pdf_path = pdf_path
                        db.session.commit()
                    except Exception:
                        pdf_path = None

            if not pdf_path or not os.path.exists(pdf_path):
                no_pdf += 1
                continue

            try:
                found, caption = extract_best_figure(pdf_path, fig_path)
            except Exception:
                err += 1
                continue

            if not found:
                no_fig += 1
                continue

            try:
                explanation = generate_figure_explanation(
                    client,
                    model,
                    paper.title or "",
                    paper.abstract or "",
                    caption,
                )
                paper.figure_explanation = explanation
            except Exception:
                pass

            paper.figure_path = fig_filename
            db.session.commit()
            ok += 1

            if i % 20 == 0:
                print(f"[{i}/{len(targets)}] ok={ok} no_pdf={no_pdf} no_fig={no_fig} err={err}", flush=True)

            time.sleep(0.4)

        print(f"Done. ok={ok} no_pdf={no_pdf} no_fig={no_fig} err={err}", flush=True)


if __name__ == "__main__":
    main()
