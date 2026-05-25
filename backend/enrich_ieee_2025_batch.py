import json
import re
import time
import requests
import httpx
from openai import OpenAI

from app import create_app
from models import Paper, db

TARGET_JOURNALS = [
    "IEEE Transactions on Smart Grid",
    "IEEE Transactions on Industrial Informatics",
    "IEEE Transactions on Power Electronics",
    "IEEE Transactions on Industrial Electronics",
    "IEEE Transactions on Sustainable Energy",
    "IEEE Transactions on Power Systems",
]

SYSTEM = '''你是一位专业的学术论文分析专家。请根据提供的论文标题和摘要，输出以下内容，用JSON格式返回：

{
  "keywords": ["3-4个中文关键词"],
  "category": "论文所属类别（如：电力系统、电力电子、智能电网、可再生能源、工业控制等）",
  "title_zh": "论文标题的中文翻译",
  "summary": "600-1000字的中文论文深度解读HTML"
}

summary格式要求：
1. 段落标题用 <h4>标题</h4>，段落用 <p>内容</p>，首行缩进
2. 重要术语用 <b class=\"term\">术语</b>，关键结论用 <b class=\"conclusion\">结论</b>
3. 结构：研究背景与动机、核心方法、关键创新、实验与结论、意义与展望
4. 不要使用Markdown语法

只返回JSON，不要其它内容。'''


def doi_from_article_number(article_number):
    if not article_number or not article_number.startswith("crossref_"):
        return ""
    raw = article_number[len("crossref_"):]
    m = re.match(r"(10\.\d{4,9})_(.*)", raw)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    return ""


def fetch_abstract(doi):
    if not doi:
        return None
    try:
        r = requests.get(
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=abstract",
            timeout=20,
            headers={"User-Agent": "PaperFlow/1.0"},
        )
        if r.status_code == 200:
            a = r.json().get("abstract")
            if a and len(a) > 20:
                return a
    except Exception:
        pass

    try:
        r = requests.get(
            f"https://api.openalex.org/works/doi:{doi}",
            timeout=20,
            headers={"User-Agent": "PaperFlow/1.0 (mailto:paperflow@research.edu)"},
        )
        if r.status_code == 200:
            inv = r.json().get("abstract_inverted_index")
            if inv:
                words = {}
                for w, pos_list in inv.items():
                    for p in pos_list:
                        words[p] = w
                a = " ".join(words[i] for i in sorted(words))
                if len(a) > 20:
                    return a
    except Exception:
        pass

    return None


def enrich_one(client, model, title, abstract):
    text = abstract or title
    if len((text or "").strip()) < 10:
        text = title
    resp = client.chat.completions.create(
        model=model,
        temperature=0.3,
        max_tokens=2500,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"论文标题：{title}\n\n摘要：{(text or '')[:2000]}"},
        ],
    )
    raw = resp.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if "```" in raw:
            raw = raw[:raw.rindex("```")]
    if "{" in raw:
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
    return json.loads(raw)


def main(batch_size=40, sleep_sec=0.2):
    app = create_app()
    http_client = httpx.Client(timeout=httpx.Timeout(90.0, connect=15.0))

    with app.app_context():
        client = OpenAI(
            api_key=app.config["DEEPSEEK_API_KEY"],
            base_url=app.config["DEEPSEEK_BASE_URL"],
            http_client=http_client,
        )
        model = app.config["DEEPSEEK_MODEL"]

        total = Paper.query.filter(
            Paper.publication_title.in_(TARGET_JOURNALS),
            Paper.publication_date.like("2025%"),
            (Paper.summary.is_(None)) | (Paper.summary == ""),
        ).count()
        print(f"Total target papers to enrich: {total}", flush=True)

        ok = 0
        fail = 0
        processed = 0

        while True:
            papers = Paper.query.filter(
                Paper.publication_title.in_(TARGET_JOURNALS),
                Paper.publication_date.like("2025%"),
                (Paper.summary.is_(None)) | (Paper.summary == ""),
            ).order_by(Paper.id).limit(batch_size).all()

            if not papers:
                break

            for p in papers:
                processed += 1
                try:
                    if not p.abstract or len((p.abstract or "").strip()) < 20:
                        doi = doi_from_article_number(p.article_number or "")
                        a = fetch_abstract(doi)
                        if a:
                            p.abstract = a

                    info = enrich_one(client, model, p.title or "", p.abstract)
                    p.summary = info.get("summary", "")
                    if not p.keywords_json:
                        kw = info.get("keywords", [])
                        p.keywords_json = json.dumps(kw, ensure_ascii=False) if kw else None
                    if not p.category:
                        p.category = info.get("category", "其他")
                    if not p.title_zh:
                        p.title_zh = info.get("title_zh", "")

                    db.session.commit()
                    ok += 1
                except Exception as e:
                    db.session.rollback()
                    fail += 1
                    if fail <= 10 or processed % 50 == 0:
                        print(f"ERR [{processed}] {p.article_number}: {type(e).__name__}: {str(e)[:160]}", flush=True)

                if processed % 20 == 0:
                    remaining = Paper.query.filter(
                        Paper.publication_title.in_(TARGET_JOURNALS),
                        Paper.publication_date.like("2025%"),
                        (Paper.summary.is_(None)) | (Paper.summary == ""),
                    ).count()
                    print(f"Progress processed={processed} ok={ok} fail={fail} remaining={remaining}", flush=True)

                time.sleep(sleep_sec)

            db.session.expire_all()

        remaining = Paper.query.filter(
            Paper.publication_title.in_(TARGET_JOURNALS),
            Paper.publication_date.like("2025%"),
            (Paper.summary.is_(None)) | (Paper.summary == ""),
        ).count()
        print(f"Done. ok={ok} fail={fail} remaining={remaining}", flush=True)


if __name__ == "__main__":
    main()
