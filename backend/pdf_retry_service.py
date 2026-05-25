from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_

from models import Paper, PaperPdfDownloadAttempt, PaperPdfRetryTask, db
from pdf_download import download_pdf_by_article_with_report

NON_RETRYABLE_REASON_CODES = {
    "invalid_article_number",
    "unsupported_source",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _int_or_default(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _backoff_schedule_minutes(app) -> list[int]:
    raw = (app.config.get("PDF_RETRY_BACKOFF_MINUTES") or "15,60,180,720,1440").strip()
    out = []
    for seg in raw.split(","):
        seg = seg.strip()
        if not seg:
            continue
        try:
            num = int(seg)
        except ValueError:
            continue
        if num > 0:
            out.append(num)
    return out or [15, 60, 180, 720, 1440]


def _next_delay_minutes(app, attempt_count: int) -> int:
    seq = _backoff_schedule_minutes(app)
    idx = max(0, attempt_count - 1)
    if idx >= len(seq):
        idx = len(seq) - 1
    return int(seq[idx])


def _get_or_create_task(article_number: str) -> PaperPdfRetryTask:
    task = PaperPdfRetryTask.query.filter_by(article_number=article_number).first()
    if task:
        return task
    task = PaperPdfRetryTask(article_number=article_number)
    db.session.add(task)
    return task


def _resolve_paper(article_number: str, paper_id: int | None):
    if paper_id:
        row = db.session.get(Paper, int(paper_id))
        if row:
            return row
    return Paper.query.filter_by(article_number=article_number).first()


def record_pdf_download_outcome(
    app,
    article_number: str,
    source_url: str = "",
    report: dict | None = None,
    paper_id: int | None = None,
    enqueue_on_fail: bool = True,
) -> dict:
    """
    Persist one PDF download attempt and update retry queue state.
    Should be called inside Flask app context.
    """
    report = report or {}
    now = _utc_now()
    arn = (article_number or "").strip()
    if not arn:
        return {"ok": False, "message": "empty article_number"}

    paper = _resolve_paper(arn, paper_id)
    success = bool(report.get("success"))
    reason_code = (report.get("reasonCode") or "").strip() or None
    reason_message = (report.get("reasonMessage") or "").strip() or None
    provider = (report.get("provider") or "").strip() or None
    path = (report.get("path") or "").strip() or None

    attempt = PaperPdfDownloadAttempt(
        paper_id=paper.id if paper else paper_id,
        article_number=arn,
        source=provider,
        source_url=(source_url or "").strip() or None,
        success=success,
        reason_code=reason_code,
        reason_message=reason_message,
        downloaded_path=path,
        created_at=now,
    )
    meta = report.get("meta")
    if isinstance(meta, dict):
        attempt.details = meta
    else:
        attempt.details = {}
    db.session.add(attempt)

    task = _get_or_create_task(arn)
    task.paper_id = (paper.id if paper else paper_id) or task.paper_id
    task.source = provider or task.source
    task.source_url = (source_url or "").strip() or task.source_url
    task.last_attempt_at = now
    task.last_reason_code = reason_code
    task.last_reason_message = reason_message
    if path:
        task.last_downloaded_path = path

    if success:
        task.status = "success"
        task.next_retry_at = None
        task.last_success_at = now
        db.session.commit()
        return {"ok": True, "status": "success", "taskStatus": task.status}

    # Failed
    retryable = enqueue_on_fail and (reason_code not in NON_RETRYABLE_REASON_CODES)
    max_attempts = max(1, _int_or_default(app.config.get("PDF_RETRY_MAX_ATTEMPTS"), 8))
    task.attempt_count = int(task.attempt_count or 0) + 1

    if retryable and task.attempt_count < max_attempts:
        task.status = "pending"
        delay = _next_delay_minutes(app, int(task.attempt_count))
        task.next_retry_at = now + timedelta(minutes=delay)
    elif retryable and task.attempt_count >= max_attempts:
        task.status = "failed"
        task.next_retry_at = None
        task.last_reason_code = task.last_reason_code or "max_retry_reached"
        if not task.last_reason_message:
            task.last_reason_message = f"Max retry attempts reached: {max_attempts}"
    else:
        task.status = "failed"
        task.next_retry_at = None

    db.session.commit()
    return {"ok": True, "status": "failed", "taskStatus": task.status}


def run_pdf_retry_batch(
    app,
    limit: int | None = None,
    force_browser: bool = False,
    interactive_verify: bool | None = None,
    verify_wait_seconds: int | None = None,
) -> dict:
    """
    Run retry queue once. Called by scheduler or admin endpoint.
    """
    now = _utc_now()
    run_limit = max(1, _int_or_default(limit, _int_or_default(app.config.get("PDF_RETRY_BATCH_SIZE"), 8)))
    max_attempts = max(1, _int_or_default(app.config.get("PDF_RETRY_MAX_ATTEMPTS"), 8))
    interactive_verify_flag = (
        app.config.get("ELSEVIER_SELENIUM_INTERACTIVE_VERIFY")
        if interactive_verify is None else bool(interactive_verify)
    )
    verify_wait_seconds_value = (
        app.config.get("ELSEVIER_SELENIUM_VERIFY_WAIT_SECONDS")
        if verify_wait_seconds is None else verify_wait_seconds
    )

    rows = (
        PaperPdfRetryTask.query
        .filter(
            PaperPdfRetryTask.status.in_(["pending", "failed"]),
            or_(PaperPdfRetryTask.next_retry_at.is_(None), PaperPdfRetryTask.next_retry_at <= now),
            PaperPdfRetryTask.attempt_count < max_attempts,
        )
        .order_by(
            PaperPdfRetryTask.next_retry_at.is_(None).desc(),
            PaperPdfRetryTask.next_retry_at.asc(),
            PaperPdfRetryTask.updated_at.asc(),
        )
        .limit(run_limit)
        .all()
    )

    stats = {"picked": len(rows), "success": 0, "failed": 0, "items": []}
    for task in rows:
        task.status = "running"
        task.last_attempt_at = now
        db.session.commit()

        path, report = download_pdf_by_article_with_report(
            article_number=task.article_number,
            out_dir=app.config["PDF_DIR"],
            source_url=task.source_url or "",
            elsevier_api_key=app.config.get("ELSEVIER_API_KEY", ""),
            elsevier_selenium_fallback=True if force_browser else None,
            elsevier_selenium_headless=app.config.get("ELSEVIER_SELENIUM_HEADLESS"),
            elsevier_selenium_use_profile=app.config.get("ELSEVIER_SELENIUM_USE_PROFILE"),
            elsevier_selenium_manual_wait_seconds=app.config.get("ELSEVIER_SELENIUM_MANUAL_WAIT_SECONDS"),
            elsevier_selenium_attach_debugger=app.config.get("ELSEVIER_SELENIUM_ATTACH_DEBUGGER"),
            elsevier_selenium_debugger_address=app.config.get("ELSEVIER_CHROME_DEBUGGER_ADDRESS"),
            elsevier_selenium_allow_new_browser_on_attach_fail=app.config.get(
                "ELSEVIER_SELENIUM_ALLOW_NEW_BROWSER_ON_ATTACH_FAIL"
            ),
            elsevier_selenium_interactive_verify=interactive_verify_flag,
            elsevier_selenium_verify_wait_seconds=verify_wait_seconds_value,
        )

        outcome = record_pdf_download_outcome(
            app=app,
            article_number=task.article_number,
            source_url=task.source_url or "",
            report=report,
            paper_id=task.paper_id,
            enqueue_on_fail=True,
        )

        if path:
            stats["success"] += 1
        else:
            stats["failed"] += 1

        stats["items"].append({
            "articleNumber": task.article_number,
            "path": path,
            "success": bool(path),
            "taskStatus": outcome.get("taskStatus"),
            "reasonCode": report.get("reasonCode"),
            "reasonMessage": report.get("reasonMessage"),
        })

    return stats
