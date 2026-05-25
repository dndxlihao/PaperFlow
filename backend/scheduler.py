from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timezone
import threading
from zoneinfo import ZoneInfo


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
scheduler = BackgroundScheduler(daemon=True, timezone=SHANGHAI_TZ)

_lock = threading.Lock()
_job_status = {
    "daily": {
        "strategy": "daily",
        "lastStartedAt": None,
        "lastFinishedAt": None,
        "lastDurationMs": None,
        "lastStatus": "never",
        "lastMessage": None,
        "lastResult": None,
    },
    "weekly": {
        "strategy": "weekly",
        "lastStartedAt": None,
        "lastFinishedAt": None,
        "lastDurationMs": None,
        "lastStatus": "never",
        "lastMessage": None,
        "lastResult": None,
    },
    "realtime": {
        "strategy": "realtime",
        "lastStartedAt": None,
        "lastFinishedAt": None,
        "lastDurationMs": None,
        "lastStatus": "never",
        "lastMessage": None,
        "lastResult": None,
    },
    "digest": {
        "strategy": "digest",
        "lastStartedAt": None,
        "lastFinishedAt": None,
        "lastDurationMs": None,
        "lastStatus": "never",
        "lastMessage": None,
        "lastResult": None,
    },
    "channel_monitor": {
        "strategy": "channel_monitor",
        "lastStartedAt": None,
        "lastFinishedAt": None,
        "lastDurationMs": None,
        "lastStatus": "never",
        "lastMessage": None,
        "lastResult": None,
    },
    "knowledge_index": {
        "strategy": "knowledge_index",
        "lastStartedAt": None,
        "lastFinishedAt": None,
        "lastDurationMs": None,
        "lastStatus": "never",
        "lastMessage": None,
        "lastResult": None,
    },
    "knowledge_trends": {
        "strategy": "knowledge_trends",
        "lastStartedAt": None,
        "lastFinishedAt": None,
        "lastDurationMs": None,
        "lastStatus": "never",
        "lastMessage": None,
        "lastResult": None,
    },
    "pdf_retry": {
        "strategy": "pdf_retry",
        "lastStartedAt": None,
        "lastFinishedAt": None,
        "lastDurationMs": None,
        "lastStatus": "never",
        "lastMessage": None,
        "lastResult": None,
    },
}


def _iso_now():
    return datetime.now(timezone.utc).isoformat()


def get_recommend_job_status():
    with _lock:
        return {
            "daily": dict(_job_status["daily"]),
            "weekly": dict(_job_status["weekly"]),
            "realtime": dict(_job_status["realtime"]),
            "digest": dict(_job_status["digest"]),
            "channel_monitor": dict(_job_status["channel_monitor"]),
            "knowledge_index": dict(_job_status["knowledge_index"]),
            "knowledge_trends": dict(_job_status["knowledge_trends"]),
            "pdf_retry": dict(_job_status["pdf_retry"]),
        }


def _run_update(app, strategy: str):
    from daily_update import run_daily_update
    started = datetime.now(timezone.utc)

    with _lock:
        st = _job_status.get(strategy)
        if st is not None:
            st["lastStartedAt"] = _iso_now()
            st["lastStatus"] = "running"
            st["lastMessage"] = None

    try:
        result = run_daily_update(app, strategy=strategy) or {}
        ended = datetime.now(timezone.utc)
        duration_ms = int((ended - started).total_seconds() * 1000)
        with _lock:
            st = _job_status.get(strategy)
            if st is not None:
                st["lastFinishedAt"] = ended.isoformat()
                st["lastDurationMs"] = duration_ms
                st["lastStatus"] = result.get("status", "ok")
                st["lastMessage"] = result.get("message")
                st["lastResult"] = result
    except Exception as e:
        ended = datetime.now(timezone.utc)
        duration_ms = int((ended - started).total_seconds() * 1000)
        with _lock:
            st = _job_status.get(strategy)
            if st is not None:
                st["lastFinishedAt"] = ended.isoformat()
                st["lastDurationMs"] = duration_ms
                st["lastStatus"] = "failed"
                st["lastMessage"] = str(e)
                st["lastResult"] = {"status": "failed", "message": str(e)}
        print(f"[SCHEDULER][{strategy}] Update failed: {e}")


def _run_digest(app):
    from digest_service import run_biweekly_digest

    started = datetime.now(timezone.utc)
    with _lock:
        st = _job_status.get("digest")
        if st is not None:
            st["lastStartedAt"] = _iso_now()
            st["lastStatus"] = "running"
            st["lastMessage"] = None

    try:
        result = run_biweekly_digest() or {}
        ended = datetime.now(timezone.utc)
        duration_ms = int((ended - started).total_seconds() * 1000)
        with _lock:
            st = _job_status.get("digest")
            if st is not None:
                st["lastFinishedAt"] = ended.isoformat()
                st["lastDurationMs"] = duration_ms
                st["lastStatus"] = result.get("status", "ok")
                st["lastMessage"] = result.get("message")
                st["lastResult"] = result
    except Exception as e:
        ended = datetime.now(timezone.utc)
        duration_ms = int((ended - started).total_seconds() * 1000)
        with _lock:
            st = _job_status.get("digest")
            if st is not None:
                st["lastFinishedAt"] = ended.isoformat()
                st["lastDurationMs"] = duration_ms
                st["lastStatus"] = "failed"
                st["lastMessage"] = str(e)
                st["lastResult"] = {"status": "failed", "message": str(e)}
        print(f"[SCHEDULER][digest] Run failed: {e}")


def _run_channel_monitor(app):
    from channel_monitor import run_ieee_early_access_monitor

    started = datetime.now(timezone.utc)
    with _lock:
        st = _job_status.get("channel_monitor")
        if st is not None:
            st["lastStartedAt"] = _iso_now()
            st["lastStatus"] = "running"
            st["lastMessage"] = None

    try:
        result = run_ieee_early_access_monitor(app) or {}
        ended = datetime.now(timezone.utc)
        duration_ms = int((ended - started).total_seconds() * 1000)
        with _lock:
            st = _job_status.get("channel_monitor")
            if st is not None:
                st["lastFinishedAt"] = ended.isoformat()
                st["lastDurationMs"] = duration_ms
                st["lastStatus"] = result.get("status", "ok")
                st["lastMessage"] = result.get("message")
                st["lastResult"] = result
    except Exception as e:
        ended = datetime.now(timezone.utc)
        duration_ms = int((ended - started).total_seconds() * 1000)
        with _lock:
            st = _job_status.get("channel_monitor")
            if st is not None:
                st["lastFinishedAt"] = ended.isoformat()
                st["lastDurationMs"] = duration_ms
                st["lastStatus"] = "failed"
                st["lastMessage"] = str(e)
                st["lastResult"] = {"status": "failed", "message": str(e)}
        print(f"[SCHEDULER][channel_monitor] Run failed: {e}")


def _run_knowledge_index(app):
    from knowledge import build_index

    started = datetime.now(timezone.utc)
    with _lock:
        st = _job_status.get("knowledge_index")
        if st is not None:
            st["lastStartedAt"] = _iso_now()
            st["lastStatus"] = "running"
            st["lastMessage"] = None

    try:
        paper_count = int(build_index(app) or 0)
        ended = datetime.now(timezone.utc)
        duration_ms = int((ended - started).total_seconds() * 1000)
        result = {
            "status": "ok",
            "message": f"索引重建完成，共 {paper_count} 篇",
            "paperCount": paper_count,
        }
        with _lock:
            st = _job_status.get("knowledge_index")
            if st is not None:
                st["lastFinishedAt"] = ended.isoformat()
                st["lastDurationMs"] = duration_ms
                st["lastStatus"] = "ok"
                st["lastMessage"] = result["message"]
                st["lastResult"] = result
    except Exception as e:
        ended = datetime.now(timezone.utc)
        duration_ms = int((ended - started).total_seconds() * 1000)
        with _lock:
            st = _job_status.get("knowledge_index")
            if st is not None:
                st["lastFinishedAt"] = ended.isoformat()
                st["lastDurationMs"] = duration_ms
                st["lastStatus"] = "failed"
                st["lastMessage"] = str(e)
                st["lastResult"] = {"status": "failed", "message": str(e)}
        print(f"[SCHEDULER][knowledge_index] Rebuild failed: {e}")


def _run_knowledge_trends(app):
    from knowledge import build_trends_cache

    started = datetime.now(timezone.utc)
    with _lock:
        st = _job_status.get("knowledge_trends")
        if st is not None:
            st["lastStartedAt"] = _iso_now()
            st["lastStatus"] = "running"
            st["lastMessage"] = None

    try:
        payload = build_trends_cache(app, months=12, top_n=6, experts_per_category=5) or {}
        cat_count = int(len(payload.get("categories") or []))
        ended = datetime.now(timezone.utc)
        duration_ms = int((ended - started).total_seconds() * 1000)
        result = {
            "status": "ok",
            "message": f"热点方向快照已刷新，共 {cat_count} 个方向",
            "categoryCount": cat_count,
            "generatedAt": payload.get("generatedAt"),
        }
        with _lock:
            st = _job_status.get("knowledge_trends")
            if st is not None:
                st["lastFinishedAt"] = ended.isoformat()
                st["lastDurationMs"] = duration_ms
                st["lastStatus"] = "ok"
                st["lastMessage"] = result["message"]
                st["lastResult"] = result
    except Exception as e:
        ended = datetime.now(timezone.utc)
        duration_ms = int((ended - started).total_seconds() * 1000)
        with _lock:
            st = _job_status.get("knowledge_trends")
            if st is not None:
                st["lastFinishedAt"] = ended.isoformat()
                st["lastDurationMs"] = duration_ms
                st["lastStatus"] = "failed"
                st["lastMessage"] = str(e)
                st["lastResult"] = {"status": "failed", "message": str(e)}
        print(f"[SCHEDULER][knowledge_trends] Refresh failed: {e}")


def _run_pdf_retry(app):
    from pdf_retry_service import run_pdf_retry_batch

    started = datetime.now(timezone.utc)
    with _lock:
        st = _job_status.get("pdf_retry")
        if st is not None:
            st["lastStartedAt"] = _iso_now()
            st["lastStatus"] = "running"
            st["lastMessage"] = None

    try:
        result = run_pdf_retry_batch(app) or {}
        ended = datetime.now(timezone.utc)
        duration_ms = int((ended - started).total_seconds() * 1000)
        message = (
            f"PDF重试完成：picked={int(result.get('picked', 0))}, "
            f"success={int(result.get('success', 0))}, failed={int(result.get('failed', 0))}"
        )
        with _lock:
            st = _job_status.get("pdf_retry")
            if st is not None:
                st["lastFinishedAt"] = ended.isoformat()
                st["lastDurationMs"] = duration_ms
                st["lastStatus"] = "ok"
                st["lastMessage"] = message
                st["lastResult"] = result
    except Exception as e:
        ended = datetime.now(timezone.utc)
        duration_ms = int((ended - started).total_seconds() * 1000)
        with _lock:
            st = _job_status.get("pdf_retry")
            if st is not None:
                st["lastFinishedAt"] = ended.isoformat()
                st["lastDurationMs"] = duration_ms
                st["lastStatus"] = "failed"
                st["lastMessage"] = str(e)
                st["lastResult"] = {"status": "failed", "message": str(e)}
        print(f"[SCHEDULER][pdf_retry] Run failed: {e}")


def init_scheduler(app):
    """Initialize frequency-aware recommendation update scheduler."""

    hour = app.config.get("RECOMMEND_HOUR", 9)
    minute = app.config.get("RECOMMEND_MINUTE", 0)
    weekly_day = app.config.get("RECOMMEND_WEEKLY_DAY", "mon")
    realtime_minutes = max(15, int(app.config.get("RECOMMEND_REALTIME_INTERVAL_MINUTES", 120)))
    digest_day = app.config.get("DIGEST_CRON_DAY", "sun")
    digest_hour = int(app.config.get("DIGEST_CRON_HOUR", 12))
    digest_minute = int(app.config.get("DIGEST_CRON_MINUTE", 0))
    channel_monitor_interval_minutes = max(
        30, int(app.config.get("CHANNEL_MONITOR_INTERVAL_MINUTES", 180))
    )
    knowledge_index_enabled = bool(app.config.get("KNOWLEDGE_INDEX_ENABLED", True))
    knowledge_index_day = app.config.get("KNOWLEDGE_INDEX_WEEKLY_DAY", "sun")
    knowledge_index_hour = int(app.config.get("KNOWLEDGE_INDEX_HOUR", 4))
    knowledge_index_minute = int(app.config.get("KNOWLEDGE_INDEX_MINUTE", 30))
    knowledge_trends_enabled = bool(app.config.get("KNOWLEDGE_TRENDS_ENABLED", True))
    knowledge_trends_day = app.config.get("KNOWLEDGE_TRENDS_WEEKLY_DAY", "sun")
    knowledge_trends_hour = int(app.config.get("KNOWLEDGE_TRENDS_HOUR", 5))
    knowledge_trends_minute = int(app.config.get("KNOWLEDGE_TRENDS_MINUTE", 0))
    pdf_retry_enabled = bool(app.config.get("PDF_RETRY_ENABLED", True))
    pdf_retry_interval_minutes = max(15, int(app.config.get("PDF_RETRY_INTERVAL_MINUTES", 120)))

    scheduler.add_job(
        func=_run_update,
        args=[app, "daily"],
        trigger="cron",
        hour=hour,
        minute=minute,
        timezone=SHANGHAI_TZ,
        id="recommend_daily_update",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        func=_run_update,
        args=[app, "weekly"],
        trigger="cron",
        day_of_week=weekly_day,
        hour=hour,
        minute=(minute + 15) % 60,
        timezone=SHANGHAI_TZ,
        id="recommend_weekly_update",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    scheduler.add_job(
        func=_run_update,
        args=[app, "realtime"],
        trigger="interval",
        minutes=realtime_minutes,
        id="recommend_realtime_update",
        replace_existing=True,
        misfire_grace_time=900,
    )

    scheduler.add_job(
        func=_run_digest,
        args=[app],
        trigger="cron",
        day_of_week=digest_day,
        hour=digest_hour,
        minute=digest_minute,
        timezone=SHANGHAI_TZ,
        id="biweekly_digest_job",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    scheduler.add_job(
        func=_run_channel_monitor,
        args=[app],
        trigger="interval",
        minutes=channel_monitor_interval_minutes,
        id="channel_monitor_job",
        replace_existing=True,
        misfire_grace_time=1800,
    )

    if knowledge_index_enabled:
        scheduler.add_job(
            func=_run_knowledge_index,
            args=[app],
            trigger="cron",
            day_of_week=knowledge_index_day,
            hour=knowledge_index_hour,
            minute=knowledge_index_minute,
            timezone=SHANGHAI_TZ,
            id="knowledge_index_weekly_rebuild",
            replace_existing=True,
            misfire_grace_time=7200,
        )

    if knowledge_trends_enabled:
        scheduler.add_job(
            func=_run_knowledge_trends,
            args=[app],
            trigger="cron",
            day_of_week=knowledge_trends_day,
            hour=knowledge_trends_hour,
            minute=knowledge_trends_minute,
            timezone=SHANGHAI_TZ,
            id="knowledge_trends_weekly_refresh",
            replace_existing=True,
            misfire_grace_time=7200,
        )

    if pdf_retry_enabled:
        scheduler.add_job(
            func=_run_pdf_retry,
            args=[app],
            trigger="interval",
            minutes=pdf_retry_interval_minutes,
            id="pdf_retry_job",
            replace_existing=True,
            misfire_grace_time=1800,
        )

    scheduler.start()
    knowledge_part = (
        f", knowledge_index({knowledge_index_day})@{knowledge_index_hour:02d}:{knowledge_index_minute:02d} Asia/Shanghai"
        if knowledge_index_enabled
        else ", knowledge_index disabled"
    )
    trends_part = (
        f", knowledge_trends({knowledge_trends_day})@{knowledge_trends_hour:02d}:{knowledge_trends_minute:02d} Asia/Shanghai"
        if knowledge_trends_enabled
        else ", knowledge_trends disabled"
    )
    retry_part = (
        f", pdf_retry every {pdf_retry_interval_minutes}m"
        if pdf_retry_enabled
        else ", pdf_retry disabled"
    )
    print(
        "[SCHEDULER] Updates enabled: "
        f"daily@{hour:02d}:{minute:02d} Asia/Shanghai, "
        f"weekly({weekly_day})@{hour:02d}:{(minute + 15) % 60:02d} Asia/Shanghai, "
        f"realtime every {realtime_minutes}m, "
        f"digest({digest_day})@{digest_hour:02d}:{digest_minute:02d} Asia/Shanghai biweekly, "
        f"channel_monitor every {channel_monitor_interval_minutes}m"
        f"{knowledge_part}"
        f"{trends_part}"
        f"{retry_part}"
    )
