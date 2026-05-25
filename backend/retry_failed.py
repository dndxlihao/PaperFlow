"""Retry downloading the 6 IEEE papers that failed with 502 errors."""
import os
import re
import sys
import time
import random

from app import create_app
from models import Paper, db
from getDoc import get_cookie_and_ua, get_pdf_doc, make_session
from extract_figures import extract_best_figure, generate_figure_explanation, FIGURES_DIR, PDF_DIR
from openai import OpenAI
from download_ieee_figures import JOURNAL_ISSUES, crawl_issue_papers, doi_from_article_number

FAILED_ARNUMBERS = {'11223218', '11237166', '11193880', '11237071', '11129975', '11142946'}


def main():
    os.makedirs(FIGURES_DIR, exist_ok=True)
    os.makedirs(PDF_DIR, exist_ok=True)

    app = create_app()
    with app.app_context():
        client = OpenAI(
            api_key=app.config['DEEPSEEK_API_KEY'],
            base_url=app.config['DEEPSEEK_BASE_URL'],
        )
        model = app.config['DEEPSEEK_MODEL']

        # Build DOI -> DB paper mapping (only papers without figures)
        db_papers = Paper.query.filter(
            Paper.article_number.like('crossref_10.1109%'),
            (Paper.figure_path == None) | (Paper.figure_path == ''),
        ).all()
        doi_to_paper = {}
        for p in db_papers:
            doi = doi_from_article_number(p.article_number)
            if doi:
                doi_to_paper[doi.lower()] = p

        print(f'Papers without figures: {len(doi_to_paper)}')

        # Get cookies
        print('Getting fresh cookies...')
        cookie_head, ua = get_cookie_and_ua(debug=True)
        sess = make_session()

        # Crawl issues to find DOI->arnumber mapping for the 6 failed papers
        targets = {}  # arnumber -> paper
        for journal_name, info in JOURNAL_ISSUES.items():
            pun = info['punumber']
            for isnumber, vol, iss in info['issues']:
                print(f'Crawling {journal_name} vol={vol} iss={iss}...')
                issue_papers = crawl_issue_papers(sess, cookie_head, ua, pun, isnumber)
                for ip in issue_papers:
                    if ip['arnumber'] in FAILED_ARNUMBERS and ip['doi'] in doi_to_paper:
                        targets[ip['arnumber']] = doi_to_paper[ip['doi']]
                        print(f'  FOUND: {ip["arnumber"]} -> {ip["doi"]}')
                time.sleep(2)
            if len(targets) == len(FAILED_ARNUMBERS):
                break

        print(f'\nMatched {len(targets)}/{len(FAILED_ARNUMBERS)} failed papers')

        # Download missing PDFs
        print('\nDownloading missing PDFs...')
        for arn, paper in targets.items():
            pdf_path = os.path.join('docs', f'{arn}.pdf')
            if os.path.exists(pdf_path):
                with open(pdf_path, 'rb') as f:
                    head = f.read(4)
                if head == b'%PDF':
                    print(f'  {arn}: valid PDF exists ({os.path.getsize(pdf_path)} bytes)')
                    continue
                else:
                    os.remove(pdf_path)

            print(f'  {arn}: downloading...')
            for attempt in range(3):
                try:
                    get_pdf_doc(
                        sess=sess,
                        cookie_head=cookie_head,
                        user_agent=ua,
                        pdf_number=arn,
                        selenium_fallback=False,
                    )
                    if os.path.exists(pdf_path):
                        with open(pdf_path, 'rb') as f:
                            h = f.read(4)
                        if h == b'%PDF':
                            print(f'    OK ({os.path.getsize(pdf_path)} bytes)')
                            break
                        else:
                            print(f'    Not valid PDF, retrying...')
                            os.remove(pdf_path)
                except Exception as e:
                    print(f'    Attempt {attempt+1}/3: {e}')
                time.sleep(15)
            else:
                print(f'    FAILED after 3 attempts')
            time.sleep(random.uniform(20, 35))

        # Extract figures and generate explanations
        print('\nExtracting figures...')
        success = 0
        for arn, paper in targets.items():
            pdf_path = os.path.join('docs', f'{arn}.pdf')
            fig_filename = f'{paper.article_number}.png'
            fig_path = os.path.join(FIGURES_DIR, fig_filename)
            if not os.path.exists(pdf_path):
                print(f'  {arn}: no PDF, skip')
                continue

            paper.pdf_path = pdf_path
            print(f'  {arn}: {paper.title[:55]}...')
            try:
                found, caption = extract_best_figure(pdf_path, fig_path)
            except Exception as e:
                print(f'    Extract error: {e}')
                db.session.commit()
                continue

            if not found:
                print(f'    No valid figure')
                db.session.commit()
                continue

            print(f'    Figure: {os.path.getsize(fig_path)} bytes')
            try:
                explanation = generate_figure_explanation(
                    client, model,
                    paper.title or '', paper.abstract or '', caption,
                )
                paper.figure_path = fig_filename
                paper.figure_explanation = explanation
                db.session.commit()
                success += 1
                print(f'    Explanation: {len(explanation)} chars')
            except Exception as e:
                paper.figure_path = fig_filename
                db.session.commit()
                success += 1
                print(f'    Figure saved, explanation failed: {e}')
            time.sleep(1)

        print(f'\nDone! {success}/{len(targets)} succeeded.')


if __name__ == '__main__':
    main()
