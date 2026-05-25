"""
Generate English abstracts for papers that are missing them,
using DeepSeek API based on paper title, journal, authors, etc.
"""
import sys
import time
from openai import OpenAI
from app import create_app
from models import db, Paper

ABSTRACT_PROMPT = (
    "You are an expert academic researcher. Based on the following paper metadata, "
    "write a plausible and professional English abstract (150-250 words) for this paper. "
    "The abstract should follow standard academic structure: background/motivation, "
    "methodology, key results, and conclusions. "
    "Output ONLY the abstract text, nothing else."
)


def generate_abstract(client, model, paper):
    """Generate an abstract for a single paper using DeepSeek."""
    parts = [f"Title: {paper.title}"]
    if paper.publication_title:
        parts.append(f"Journal: {paper.publication_title}")
    if paper.authors_json:
        parts.append(f"Authors: {paper.authors_json}")
    if paper.publication_date:
        parts.append(f"Publication Date: {paper.publication_date}")
    if paper.keywords_json:
        parts.append(f"Keywords: {paper.keywords_json}")

    user_prompt = "\n".join(parts)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": ABSTRACT_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.4,
        max_tokens=500,
    )
    return response.choices[0].message.content.strip()


def main():
    app = create_app()
    with app.app_context():
        client = OpenAI(
            api_key=app.config["DEEPSEEK_API_KEY"],
            base_url=app.config["DEEPSEEK_BASE_URL"],
        )
        model = app.config["DEEPSEEK_MODEL"]

        papers = Paper.query.filter(
            (Paper.abstract == None) | (Paper.abstract == "")
        ).all()

        print(f"Found {len(papers)} papers missing abstracts.")
        if not papers:
            print("Nothing to do.")
            return

        success = 0
        fail = 0
        for i, paper in enumerate(papers, 1):
            try:
                abstract = generate_abstract(client, model, paper)
                paper.abstract = abstract
                db.session.commit()
                success += 1
                print(f"[{i}/{len(papers)}] ✓ {paper.title[:60]}...")
            except Exception as e:
                db.session.rollback()
                fail += 1
                print(f"[{i}/{len(papers)}] ✗ {paper.title[:60]}... Error: {e}")
            # Small delay to avoid rate limits
            if i < len(papers):
                time.sleep(0.5)

        print(f"\nDone! Success: {success}, Failed: {fail}")


if __name__ == "__main__":
    main()
