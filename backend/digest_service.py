from __future__ import annotations

import smtplib
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.header import Header

from flask import current_app

from models import Paper, PaperSourceClick, User, UserDigest, UserPaper, db


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _window(now: datetime | None = None, days: int = 14):
    now_utc = _to_utc(now or datetime.now(timezone.utc))
    # Align end boundary to next whole second so second-precision DB timestamps
    # generated in the current second are not dropped by the '< end' filter.
    end = now_utc.replace(microsecond=0) + timedelta(seconds=1)
    start = end - timedelta(days=days)
    return start, end


def _email_enabled() -> bool:
    return bool(current_app.config.get("DIGEST_EMAIL_ENABLED", False))


def _send_digest_email(to_email: str, subject: str, content: str) -> bool:
    host = current_app.config.get("SMTP_HOST", "")
    port = int(current_app.config.get("SMTP_PORT", 587))
    user = current_app.config.get("SMTP_USER", "")
    password = current_app.config.get("SMTP_PASSWORD", "")
    from_email = current_app.config.get("SMTP_FROM_EMAIL", user)
    use_tls = bool(current_app.config.get("SMTP_USE_TLS", True))

    if not host or not from_email:
        return False

    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = from_email
    msg["To"] = to_email

    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            if use_tls:
                server.starttls()
            if user and password:
                server.login(user, password)
            server.sendmail(from_email, [to_email], msg.as_string())
        return True
    except Exception as e:
        print(f"[DIGEST][EMAIL] send failed for {to_email}: {e}")
        return False


def _build_digest_payload(user_id: int, start: datetime, end: datetime):
    reads = (
        UserPaper.query.filter(
            UserPaper.user_id == user_id,
            UserPaper.added_at >= start,
            UserPaper.added_at <= end,
        )
        .order_by(UserPaper.added_at.desc())
        .all()
    )

    clicks = (
        PaperSourceClick.query.filter(
            PaperSourceClick.user_id == user_id,
            PaperSourceClick.clicked_at >= start,
            PaperSourceClick.clicked_at <= end,
        )
        .order_by(PaperSourceClick.clicked_at.desc())
        .all()
    )

    read_papers = [r.paper for r in reads if r.paper]
    read_ids = {p.id for p in read_papers if p and p.id}

    kw_counter = Counter()
    cat_counter = Counter()
    for p in read_papers:
        for kw in (p.keywords or [])[:8]:
            token = (kw or "").strip()
            if token:
                kw_counter[token] += 1
        cat = (p.category or "").strip()
        if cat:
            cat_counter[cat] += 1

    top_keywords = [k for k, _ in kw_counter.most_common(8)]
    top_categories = [c for c, _ in cat_counter.most_common(3)]

    clicked_numbers = []
    seen_clicked = set()
    for c in clicks:
        if not c.paper:
            continue
        arn = c.paper.article_number
        if arn and arn not in seen_clicked:
            seen_clicked.add(arn)
            clicked_numbers.append(arn)

    rec_q = Paper.query.order_by(Paper.created_at.desc(), Paper.id.desc())
    if top_categories:
        rec_q = rec_q.filter(Paper.category.in_(top_categories))
    candidates = rec_q.limit(60).all()

    rec_article_numbers = []
    rec_titles = []
    for p in candidates:
        if p.id in read_ids:
            continue
        arn = p.article_number
        if not arn or arn in rec_article_numbers:
            continue
        rec_article_numbers.append(arn)
        rec_titles.append(p.title_zh or p.title or arn)
        if len(rec_article_numbers) >= 5:
            break

    read_titles = [p.title_zh or p.title or p.article_number for p in read_papers[:8]]
    clicked_titles = []
    seen_click_title = set()
    for c in clicks:
        if not c.paper:
            continue
        t = c.paper.title_zh or c.paper.title or c.paper.article_number
        if t and t not in seen_click_title:
            seen_click_title.add(t)
            clicked_titles.append(t)
        if len(clicked_titles) >= 5:
            break

    period_text = f"{start.date().isoformat()} 至 {end.date().isoformat()}"
    keywords_text = "、".join(top_keywords[:6]) if top_keywords else "暂无明显关键词"
    categories_text = "、".join(top_categories) if top_categories else "暂无明显方向"

    lines = [
        f"双周阅读简报（{period_text}）",
        "",
        f"你这段时间加入论文库 {len(read_papers)} 篇。",
    ]

    if read_titles:
        lines.append("已阅读/收藏代表文献：")
        for t in read_titles[:5]:
            lines.append(f"- {t}")

    lines.extend([
        "",
        f"阅读关键词画像：{keywords_text}",
        f"关注方向：{categories_text}",
        "",
        f"点击原文链接 {len(clicks)} 次。",
    ])

    if clicked_titles:
        lines.append("你近期重点查看原文的文献：")
        for t in clicked_titles:
            lines.append(f"- {t}")

    lines.extend([
        "",
        "本期总结：你近期阅读集中在上述关键词与方向，建议继续在相邻主题中扩展，保持方向连续性与主题多样性平衡。",
        "",
        "相似文献推荐（建议阅读）：",
    ])

    if rec_titles:
        for t in rec_titles:
            lines.append(f"- {t}")
    else:
        lines.append("- 暂无新推荐，可稍后再看")

    content = "\n".join(lines)
    subject = f"PaperFlow 双周阅读简报 | {start.date().isoformat()} - {end.date().isoformat()}"

    return {
        "subject": subject,
        "content": content,
        "keywords": top_keywords,
        "clicked_article_numbers": clicked_numbers[:20],
        "rec_article_numbers": rec_article_numbers,
        "read_count": len(read_papers),
        "source_click_count": len(clicks),
    }


def run_biweekly_digest(now: datetime | None = None, force: bool = False, user_ids=None):
    enabled = bool(current_app.config.get("DIGEST_ENABLED", True))
    if not enabled and not force:
        return {"status": "skipped", "message": "digest disabled"}

    start, end = _window(now=now, days=int(current_app.config.get("DIGEST_LOOKBACK_DAYS", 14)))

    # Biweekly gate: execute only every 2nd ISO week by default.
    interval_weeks = max(1, int(current_app.config.get("DIGEST_INTERVAL_WEEKS", 2)))
    anchor_week = int(current_app.config.get("DIGEST_ANCHOR_ISO_WEEK", 2))
    this_week = end.isocalendar().week
    should_run = ((this_week - anchor_week) % interval_weeks) == 0
    if not should_run and not force:
        return {
            "status": "skipped",
            "message": f"week {this_week} not on biweekly cadence",
            "start": start.isoformat(),
            "end": end.isoformat(),
        }

    q = User.query
    if user_ids:
        q = q.filter(User.id.in_(list(user_ids)))
    users = q.all()
    created = 0
    emailed = 0

    for u in users:
        exists = (
            UserDigest.query.filter(
                UserDigest.user_id == u.id,
                UserDigest.period_start == start,
                UserDigest.period_end == end,
            )
            .first()
        )
        if exists and not force:
            continue

        payload = _build_digest_payload(u.id, start, end)
        d = exists or UserDigest(user_id=u.id, period_start=start, period_end=end)
        d.subject = payload["subject"]
        d.content = payload["content"]
        d.keywords = payload["keywords"]
        d.clicked_article_numbers = payload["clicked_article_numbers"]
        d.rec_article_numbers = payload["rec_article_numbers"]
        d.read_count = payload["read_count"]
        d.source_click_count = payload["source_click_count"]
        d.is_read = False
        if not exists:
            db.session.add(d)
            created += 1

        if _email_enabled() and u.email:
            ok = _send_digest_email(u.email, d.subject, d.content)
            if ok:
                d.email_sent_at = datetime.now(timezone.utc)
                emailed += 1

    db.session.commit()

    return {
        "status": "ok",
        "message": f"created {created} digests, emailed {emailed}",
        "created": created,
        "emailed": emailed,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
