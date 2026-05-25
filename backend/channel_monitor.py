import os
from datetime import date, datetime, timedelta, timezone

from getDoc import crawl_issue_by_pages, get_cookie_and_ua, get_pdf_doc, make_session
from models import (
    ChannelMonitorRecord,
    Paper,
    Recommendation,
    UserChannelSubscription,
    UserDigest,
    db,
)
from paper_filters import is_index_or_toc_content


CHANNEL_CATALOG = [
    {
        "key": "ieee-early-access",
        "name": "IEEE Early Access",
        "description": "监控 IEEE TPWRS / TSTE / TSG 三本期刊的 Early Access 更新，有新论文时推送主页卡片并发送站内信提醒。",
        "enabledByDefault": False,
    }
]

# Focus on the three journals requested by product scope.
IEEE_EARLY_ACCESS_SOURCES = [
    {"punumber": "59", "name": "IEEE Transactions on Power Systems"},
    {"punumber": "5165411", "name": "IEEE Transactions on Sustainable Energy"},
    {"punumber": "5165412", "name": "IEEE Transactions on Smart Grid"},
]

JOURNAL_ABBR = {
    "ieee transactions on power systems": "TPWRS",
    "ieee transactions on sustainable energy": "TSTE",
    "ieee transactions on smart grid": "TSG",
}
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIGURES_DIR = os.path.join(REPO_ROOT, "figures")


def channel_catalog_payload():
    return [dict(item) for item in CHANNEL_CATALOG]


def _to_repo_relative(path: str):
    if not path:
        return path
    ap = os.path.abspath(path)
    try:
        rel = os.path.relpath(ap, REPO_ROOT)
    except Exception:
        return ap
    return rel if not rel.startswith("..") else ap


def _resolve_pdf_path(article_number: str, paper_pdf_path: str | None, pdf_dir: str):
    candidates = []
    if article_number:
        candidates.append(os.path.join(pdf_dir, f"{article_number}.pdf"))
        candidates.append(os.path.join(REPO_ROOT, "backend", "docs", f"{article_number}.pdf"))
    if paper_pdf_path:
        if os.path.isabs(paper_pdf_path):
            candidates.append(paper_pdf_path)
        else:
            candidates.append(os.path.join(REPO_ROOT, paper_pdf_path))
            candidates.append(os.path.join(REPO_ROOT, "backend", paper_pdf_path))

    seen = set()
    for p in candidates:
        ap = os.path.abspath(p)
        if ap in seen:
            continue
        seen.add(ap)
        if os.path.exists(ap):
            return ap
    return None


def _extract_figure_for_paper(paper: Paper, pdf_dir: str):
    if not paper or paper.figure_path:
        return False

    arn = (paper.article_number or "").strip()
    if not arn:
        return False

    pdf_path = _resolve_pdf_path(arn, paper.pdf_path, pdf_dir)
    if not pdf_path or not os.path.exists(pdf_path):
        return False

    try:
        from extract_figures import extract_best_figure
    except Exception as e:
        print(f"[CHANNEL][WARN] cannot import figure extractor: {e}")
        return False

    os.makedirs(FIGURES_DIR, exist_ok=True)
    fig_name = f"{arn}.png"
    fig_path = os.path.join(FIGURES_DIR, fig_name)
    try:
        found, _ = extract_best_figure(pdf_path, fig_path)
        if not found:
            return False
        paper.figure_path = fig_name
        return True
    except Exception as e:
        print(f"[CHANNEL][WARN] figure extraction failed for {arn}: {e}")
        return False


def _download_ieee_pdf(arn: str, pdf_dir: str):
    out_path = os.path.join(pdf_dir, f"{arn}.pdf")
    if os.path.exists(out_path):
        return out_path

    cookie_head, ua = get_cookie_and_ua(debug=False)
    sess = make_session()
    get_pdf_doc(
        sess=sess,
        cookie_head=cookie_head,
        user_agent=ua or "Mozilla/5.0",
        pdf_number=arn,
        out_path=out_path,
        selenium_fallback=True,
    )
    return out_path if os.path.exists(out_path) else None


def _upsert_ieee_paper(item, pdf_dir):
    arn = str(item.get("articleNumber") or "").strip()
    if not arn:
        return None, False

    title = (item.get("articleTitle") or "").strip()
    abstract = item.get("abstract") or ""
    if is_index_or_toc_content(title, abstract):
        return None, False

    paper = Paper.query.filter_by(article_number=arn).first()
    created = False

    if not paper:
        paper = Paper(
            article_number=arn,
            title=title,
            abstract=abstract,
            publication_date=item.get("publicationDate") or "",
            publication_title=item.get("publicationTitle") or item.get("displayPublicationTitle") or "IEEE",
            download_count=item.get("downloadCount") or 0,
            source_url=f"https://ieeexplore.ieee.org/document/{arn}",
        )
        authors = item.get("authors") or []
        if isinstance(authors, list):
            paper.authors = authors
        db.session.add(paper)
        db.session.flush()
        created = True
    else:
        # Refresh key metadata for existing papers when upstream has newer values.
        if title and not paper.title:
            paper.title = title
        if abstract and not paper.abstract:
            paper.abstract = abstract
        if not paper.publication_title:
            paper.publication_title = item.get("publicationTitle") or item.get("displayPublicationTitle") or "IEEE"
        if not paper.publication_date:
            paper.publication_date = item.get("publicationDate") or ""
        if (item.get("downloadCount") or 0) > (paper.download_count or 0):
            paper.download_count = item.get("downloadCount") or paper.download_count
        if not paper.source_url:
            paper.source_url = f"https://ieeexplore.ieee.org/document/{arn}"
        if isinstance(item.get("authors"), list) and (not paper.authors):
            paper.authors = item.get("authors")

    existing_pdf = _resolve_pdf_path(arn, paper.pdf_path, pdf_dir)
    if not existing_pdf:
        try:
            pdf_path = _download_ieee_pdf(arn, pdf_dir)
            if pdf_path:
                paper.pdf_path = _to_repo_relative(pdf_path)
        except Exception:
            pass

    return paper, created


def _create_subscription_alerts(channel_key: str, new_papers):
    subs = UserChannelSubscription.query.filter_by(channel_key=channel_key, enabled=True).all()
    if not subs:
        return 0

    article_numbers = [p.article_number for p in new_papers if p and p.article_number][:8]
    if not article_numbers:
        return 0

    paper_titles = [p.title or p.article_number for p in new_papers[:5]]
    title_lines = "\n".join([f"- {t}" for t in paper_titles])

    journals = []
    seen = set()
    for p in new_papers:
        pub = (p.publication_title or "").strip().lower()
        abbr = JOURNAL_ABBR.get(pub)
        if abbr and abbr not in seen:
            seen.add(abbr)
            journals.append(abbr)
    journal_text = "/".join(journals) if journals else "TPWRS/TSTE/TSG"

    now = datetime.now(timezone.utc)
    sent = 0
    for sub in subs:
        digest = UserDigest(
            user_id=sub.user_id,
            period_start=now,
            period_end=now,
            subject=f"IEEE {journal_text} Early Access 更新：新增 {len(new_papers)} 篇",
            content=(
                f"你订阅的 IEEE {journal_text} Early Access 有新论文更新。\n"
                f"本次新增 {len(new_papers)} 篇，建议尽快查看：\n"
                f"{title_lines}\n\n"
                "点击下方建议阅读卡片可直达论文详情。"
            ),
            read_count=0,
            source_click_count=0,
            is_read=False,
        )
        digest.rec_article_numbers = article_numbers
        digest.keywords = ["IEEE", "Early Access", "订阅提醒"]
        db.session.add(digest)
        sent += 1

    return sent


def get_user_channel_updates(user_id: int, limit: int = 10, days: int = 30):
    limit = max(1, min(int(limit or 10), 50))
    days = max(1, min(int(days or 30), 365))

    enabled_keys = [
        row.channel_key
        for row in UserChannelSubscription.query.filter_by(user_id=user_id, enabled=True).all()
    ]
    if not enabled_keys:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        ChannelMonitorRecord.query
        .filter(ChannelMonitorRecord.channel_key.in_(enabled_keys))
        .filter(ChannelMonitorRecord.first_seen_at >= cutoff)
        .order_by(ChannelMonitorRecord.first_seen_at.desc(), ChannelMonitorRecord.id.desc())
        .limit(limit * 3)
        .all()
    )

    name_map = {item["key"]: item["name"] for item in CHANNEL_CATALOG}
    items = []
    seen = set()
    for row in rows:
        paper = row.paper
        if not paper:
            continue
        arn = paper.article_number
        if not arn or arn in seen:
            continue
        seen.add(arn)
        items.append({
            "channelKey": row.channel_key,
            "channelName": name_map.get(row.channel_key, row.channel_key),
            "articleNumber": arn,
            "firstSeenAt": row.first_seen_at.isoformat() if row.first_seen_at else None,
            "paper": paper.to_dict(include_summary=False),
        })
        if len(items) >= limit:
            break
    return items


def run_ieee_early_access_monitor(app):
    with app.app_context():
        today = date.today()
        rows_per_page = int(app.config.get("CHANNEL_MONITOR_ROWS_PER_PAGE", 12))
        pdf_dir = app.config["PDF_DIR"]
        os.makedirs(pdf_dir, exist_ok=True)
        os.makedirs(FIGURES_DIR, exist_ok=True)

        candidates = []
        for source in IEEE_EARLY_ACCESS_SOURCES:
            try:
                items = crawl_issue_by_pages(
                    punumber=source["punumber"],
                    isnumber="",
                    start_page=1,
                    end_page=1,
                    rows_per_page=rows_per_page,
                    sortType="newest",
                    download_pdf=False,
                    attach_text=False,
                )
                candidates.extend(items)
            except Exception as e:
                print(f"[CHANNEL][WARN] crawl failed for {source['name']}: {e}")

        if not candidates:
            return {
                "status": "ok",
                "added": 0,
                "notifiedUsers": 0,
                "emailedUsers": 0,
                "message": "no candidates",
            }

        seen = set()
        unique_items = []
        for item in candidates:
            arn = str(item.get("articleNumber") or "").strip()
            if not arn or arn in seen:
                continue
            seen.add(arn)
            unique_items.append(item)

        new_papers = []
        extracted_figures = 0
        for item in unique_items:
            paper, _created = _upsert_ieee_paper(item, pdf_dir)
            if not paper:
                continue

            arn = (paper.article_number or "").strip()
            if not arn:
                continue

            seen_row = ChannelMonitorRecord.query.filter_by(
                channel_key="ieee-early-access",
                article_number=arn,
            ).first()
            is_new_hit = seen_row is None
            if seen_row is None:
                seen_row = ChannelMonitorRecord(
                    channel_key="ieee-early-access",
                    article_number=arn,
                    paper_id=paper.id,
                    first_seen_at=datetime.now(timezone.utc),
                    last_seen_at=datetime.now(timezone.utc),
                )
                db.session.add(seen_row)
            else:
                seen_row.last_seen_at = datetime.now(timezone.utc)
                if not seen_row.paper_id:
                    seen_row.paper_id = paper.id

            if is_new_hit:
                # Ensure newly monitored papers can appear in homepage recommendation streams.
                rec_exists = Recommendation.query.filter_by(paper_id=paper.id, recommended_date=today).first()
                if not rec_exists:
                    db.session.add(Recommendation(paper_id=paper.id, recommended_date=today))

                if _extract_figure_for_paper(paper, pdf_dir):
                    extracted_figures += 1
                new_papers.append(paper)

        notified_users = 0
        emailed_users = 0
        if new_papers:
            notified_users = _create_subscription_alerts(
                "ieee-early-access",
                new_papers,
            )

        db.session.commit()
        return {
            "status": "ok",
            "added": len(new_papers),
            "notifiedUsers": notified_users,
            "emailedUsers": emailed_users,
            "figureExtracted": extracted_figures,
            "message": (
                f"new papers={len(new_papers)}, "
                f"notified users={notified_users}, emailed users={emailed_users}, "
                f"figure extracted={extracted_figures}"
            ),
        }
