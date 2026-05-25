"""Batch-enrich crossref papers: keywords, category, summary, Chinese title in ONE API call."""
import json, time, sys, httpx
from openai import OpenAI
from app import create_app
from models import Paper, db

SYSTEM = '''你是一位专业的学术论文分析专家。请根据提供的论文标题和摘要，输出以下内容，用JSON格式返回：

{
  "keywords": ["3-4个中文关键词"],
  "category": "论文所属类别（如：电力系统、电力电子、智能电网、可再生能源、工业控制等）",
  "title_zh": "论文标题的中文翻译",
  "summary": "600-1000字的中文论文深度解读HTML"
}

summary格式要求：
1. 段落标题用 <h4>标题</h4>，段落用 <p>内容</p>，首行缩进
2. 重要术语用 <b class=\\"term\\">术语</b>，关键结论用 <b class=\\"conclusion\\">结论</b>
3. 结构：研究背景与动机、核心方法、关键创新、实验与结论、意义与展望
4. 不要使用Markdown语法

只返回JSON，不要其它内容。'''

def enrich_one(client, model, title, abstract):
    text = abstract or title
    if len((text or '').strip()) < 10:
        text = title
    resp = client.chat.completions.create(
        model=model, temperature=0.3, max_tokens=2500,
        messages=[
            {'role': 'system', 'content': SYSTEM},
            {'role': 'user', 'content': f'论文标题：{title}\n\n摘要：{(text or "")[:2000]}'}
        ],
    )
    raw = resp.choices[0].message.content.strip()
    # Extract JSON
    if raw.startswith('```'):
        raw = raw.split('\n', 1)[1] if '\n' in raw else raw[3:]
        if '```' in raw:
            raw = raw[:raw.rindex('```')]
    if '{' in raw:
        raw = raw[raw.index('{'):raw.rindex('}') + 1]
    return json.loads(raw)


def main():
    app = create_app()
    http_client = httpx.Client(timeout=httpx.Timeout(90.0, connect=15.0))
    ok = fail = 0
    batch_size = 50

    with app.app_context():
        client = OpenAI(
            api_key=app.config['DEEPSEEK_API_KEY'],
            base_url=app.config['DEEPSEEK_BASE_URL'],
            http_client=http_client,
        )
        model = app.config['DEEPSEEK_MODEL']

        total = Paper.query.filter(
            Paper.article_number.like('crossref_%'),
            ((Paper.summary == None) | (Paper.summary == ''))
        ).count()
        print(f'Total to enrich: {total}', flush=True)

        processed = 0
        while True:
            papers = Paper.query.filter(
                Paper.article_number.like('crossref_%'),
                ((Paper.summary == None) | (Paper.summary == ''))
            ).order_by(Paper.id).limit(batch_size).all()

            if not papers:
                break

            for p in papers:
                processed += 1
                try:
                    info = enrich_one(client, model, p.title or '', p.abstract)
                    p.summary = info.get('summary', '')
                    if not p.keywords_json:
                        kw = info.get('keywords', [])
                        p.keywords_json = json.dumps(kw, ensure_ascii=False) if kw else None
                    if not p.category:
                        p.category = info.get('category', '其他')
                    if not p.title_zh:
                        p.title_zh = info.get('title_zh', '')
                    db.session.commit()
                    ok += 1
                except Exception as e:
                    db.session.rollback()
                    fail += 1
                    if fail <= 5 or processed % 50 == 0:
                        print(f'  ERR [{processed}]: {type(e).__name__}: {str(e)[:120]}', flush=True)

                if processed % 20 == 0:
                    print(f'  [{processed}/{total}] ok={ok} fail={fail}', flush=True)
                time.sleep(0.2)

            db.session.expire_all()

        remaining = Paper.query.filter(
            Paper.article_number.like('crossref_%'),
            ((Paper.summary == None) | (Paper.summary == ''))
        ).count()
        print(f'\nDone! ok={ok}, fail={fail}, remaining={remaining}', flush=True)


if __name__ == '__main__':
    main()
