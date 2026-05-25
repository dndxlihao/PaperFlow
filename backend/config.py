import os
from pathlib import Path

# Load .env file
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-in-production-32char!")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "mysql+pymysql://root@localhost:3306/paper_hub?charset=utf8mb4"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # DeepSeek API
    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    # Elsevier API (optional, used to improve ScienceDirect PDF access)
    ELSEVIER_API_KEY = os.environ.get("ELSEVIER_API_KEY", "")
    ELSEVIER_SELENIUM_FALLBACK = os.environ.get("ELSEVIER_SELENIUM_FALLBACK", "1") in {"1", "true", "True", "yes", "on"}
    ELSEVIER_SELENIUM_HEADLESS = os.environ.get("ELSEVIER_SELENIUM_HEADLESS", "1") in {"1", "true", "True", "yes", "on"}
    ELSEVIER_SELENIUM_USE_PROFILE = os.environ.get("ELSEVIER_SELENIUM_USE_PROFILE", "0") in {"1", "true", "True", "yes", "on"}
    ELSEVIER_SELENIUM_MANUAL_WAIT_SECONDS = int(os.environ.get("ELSEVIER_SELENIUM_MANUAL_WAIT_SECONDS", 0))
    ELSEVIER_SELENIUM_TIMEOUT = int(os.environ.get("ELSEVIER_SELENIUM_TIMEOUT", 180))
    ELSEVIER_SELENIUM_ATTACH_DEBUGGER = os.environ.get("ELSEVIER_SELENIUM_ATTACH_DEBUGGER", "0") in {"1", "true", "True", "yes", "on"}
    ELSEVIER_CHROME_DEBUGGER_ADDRESS = os.environ.get("ELSEVIER_CHROME_DEBUGGER_ADDRESS", "127.0.0.1:9222")
    ELSEVIER_SELENIUM_ALLOW_NEW_BROWSER_ON_ATTACH_FAIL = os.environ.get(
        "ELSEVIER_SELENIUM_ALLOW_NEW_BROWSER_ON_ATTACH_FAIL",
        "1",
    ) in {"1", "true", "True", "yes", "on"}
    ELSEVIER_SELENIUM_INTERACTIVE_VERIFY = os.environ.get(
        "ELSEVIER_SELENIUM_INTERACTIVE_VERIFY",
        "1",
    ) in {"1", "true", "True", "yes", "on"}
    ELSEVIER_SELENIUM_VERIFY_WAIT_SECONDS = int(os.environ.get("ELSEVIER_SELENIUM_VERIFY_WAIT_SECONDS", 300))

    # JWT
    JWT_EXPIRATION_HOURS = 72

    # PDF storage
    PDF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs")

    # Recommendation: how many papers per day
    RECOMMEND_COUNT = 10

    # Scheduler
    RECOMMEND_HOUR = 9  # Run at 9:00 AM daily
    RECOMMEND_MINUTE = 0
    RECOMMEND_WEEKLY_DAY = "mon"
    RECOMMEND_REALTIME_INTERVAL_MINUTES = 120
    CHANNEL_MONITOR_INTERVAL_MINUTES = int(os.environ.get("CHANNEL_MONITOR_INTERVAL_MINUTES", 60))
    CHANNEL_MONITOR_ROWS_PER_PAGE = int(os.environ.get("CHANNEL_MONITOR_ROWS_PER_PAGE", 12))
    KNOWLEDGE_INDEX_ENABLED = os.environ.get("KNOWLEDGE_INDEX_ENABLED", "1") in {"1", "true", "True", "yes", "on"}
    KNOWLEDGE_INDEX_WEEKLY_DAY = os.environ.get("KNOWLEDGE_INDEX_WEEKLY_DAY", "sun")
    KNOWLEDGE_INDEX_HOUR = int(os.environ.get("KNOWLEDGE_INDEX_HOUR", 4))
    KNOWLEDGE_INDEX_MINUTE = int(os.environ.get("KNOWLEDGE_INDEX_MINUTE", 30))
    KNOWLEDGE_TRENDS_ENABLED = os.environ.get("KNOWLEDGE_TRENDS_ENABLED", "1") in {"1", "true", "True", "yes", "on"}
    KNOWLEDGE_TRENDS_WEEKLY_DAY = os.environ.get("KNOWLEDGE_TRENDS_WEEKLY_DAY", "sun")
    KNOWLEDGE_TRENDS_HOUR = int(os.environ.get("KNOWLEDGE_TRENDS_HOUR", 5))
    KNOWLEDGE_TRENDS_MINUTE = int(os.environ.get("KNOWLEDGE_TRENDS_MINUTE", 0))
    PDF_RETRY_ENABLED = os.environ.get("PDF_RETRY_ENABLED", "1") in {"1", "true", "True", "yes", "on"}
    PDF_RETRY_INTERVAL_MINUTES = int(os.environ.get("PDF_RETRY_INTERVAL_MINUTES", 120))
    PDF_RETRY_BATCH_SIZE = int(os.environ.get("PDF_RETRY_BATCH_SIZE", 8))
    PDF_RETRY_MAX_ATTEMPTS = int(os.environ.get("PDF_RETRY_MAX_ATTEMPTS", 8))
    PDF_RETRY_BACKOFF_MINUTES = os.environ.get("PDF_RETRY_BACKOFF_MINUTES", "15,60,180,720,1440")

    # Biweekly digest schedule and analytics window.
    DIGEST_ENABLED = os.environ.get("DIGEST_ENABLED", "1") in {"1", "true", "True", "yes", "on"}
    DIGEST_LOOKBACK_DAYS = int(os.environ.get("DIGEST_LOOKBACK_DAYS", 14))
    DIGEST_INTERVAL_WEEKS = int(os.environ.get("DIGEST_INTERVAL_WEEKS", 2))
    DIGEST_ANCHOR_ISO_WEEK = int(os.environ.get("DIGEST_ANCHOR_ISO_WEEK", 2))
    DIGEST_CRON_DAY = os.environ.get("DIGEST_CRON_DAY", "sun")
    DIGEST_CRON_HOUR = int(os.environ.get("DIGEST_CRON_HOUR", 12))
    DIGEST_CRON_MINUTE = int(os.environ.get("DIGEST_CRON_MINUTE", 0))

    # Optional email channel for digest.
    DIGEST_EMAIL_ENABLED = os.environ.get("DIGEST_EMAIL_ENABLED", "0") in {"1", "true", "True", "yes", "on"}
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM_EMAIL = os.environ.get("SMTP_FROM_EMAIL", "")
    SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "1") in {"1", "true", "True", "yes", "on"}

    # Personalized recommendation scoring weights (tunable at runtime).
    RECSCORE_JOURNAL_MATCH_WEIGHT = float(os.environ.get("RECSCORE_JOURNAL_MATCH_WEIGHT", 4.0))
    RECSCORE_AREA_MATCH_WEIGHT = float(os.environ.get("RECSCORE_AREA_MATCH_WEIGHT", 2.0))
    RECSCORE_TEXT_MATCH_WEIGHT = float(os.environ.get("RECSCORE_TEXT_MATCH_WEIGHT", 1.4))
    RECSCORE_SUMMARY_BONUS = float(os.environ.get("RECSCORE_SUMMARY_BONUS", 0.3))

    RECSCORE_FAVORITE_BONUS = float(os.environ.get("RECSCORE_FAVORITE_BONUS", 0.6))
    RECSCORE_LIBRARY_PENALTY = float(os.environ.get("RECSCORE_LIBRARY_PENALTY", 0.25))
    RECSCORE_RATING_FACTOR = float(os.environ.get("RECSCORE_RATING_FACTOR", 0.85))
    RECSCORE_AVOID_CATEGORY_PENALTY = float(os.environ.get("RECSCORE_AVOID_CATEGORY_PENALTY", 1.8))
    RECSCORE_AREA_PREF_FACTOR = float(os.environ.get("RECSCORE_AREA_PREF_FACTOR", 0.45))
    RECSCORE_AREA_PREF_CAP = float(os.environ.get("RECSCORE_AREA_PREF_CAP", 2.6))
    RECSCORE_KEYWORD_PREF_FACTOR = float(os.environ.get("RECSCORE_KEYWORD_PREF_FACTOR", 0.22))
    RECSCORE_KEYWORD_PREF_CAP = float(os.environ.get("RECSCORE_KEYWORD_PREF_CAP", 1.8))

    RECSCORE_DAILY_FRESHNESS_WEIGHT = float(os.environ.get("RECSCORE_DAILY_FRESHNESS_WEIGHT", 1.0))
    RECSCORE_WEEKLY_FRESHNESS_WEIGHT = float(os.environ.get("RECSCORE_WEEKLY_FRESHNESS_WEIGHT", 0.6))
    RECSCORE_REALTIME_FRESHNESS_WEIGHT = float(os.environ.get("RECSCORE_REALTIME_FRESHNESS_WEIGHT", 1.5))

    RECSCORE_DAILY_SHUFFLE_WEIGHT = float(os.environ.get("RECSCORE_DAILY_SHUFFLE_WEIGHT", 0.25))
    RECSCORE_WEEKLY_SHUFFLE_WEIGHT = float(os.environ.get("RECSCORE_WEEKLY_SHUFFLE_WEIGHT", 0.18))
    RECSCORE_REALTIME_SHUFFLE_WEIGHT = float(os.environ.get("RECSCORE_REALTIME_SHUFFLE_WEIGHT", 0.35))

    RECSCORE_DAILY_CANDIDATE_LIMIT = int(os.environ.get("RECSCORE_DAILY_CANDIDATE_LIMIT", 1400))
    RECSCORE_WEEKLY_CANDIDATE_LIMIT = int(os.environ.get("RECSCORE_WEEKLY_CANDIDATE_LIMIT", 2400))
    RECSCORE_REALTIME_CANDIDATE_LIMIT = int(os.environ.get("RECSCORE_REALTIME_CANDIDATE_LIMIT", 900))

    RECSCORE_DAILY_FRESH_WINDOW_DAYS = int(os.environ.get("RECSCORE_DAILY_FRESH_WINDOW_DAYS", 10))
    RECSCORE_WEEKLY_FRESH_WINDOW_DAYS = int(os.environ.get("RECSCORE_WEEKLY_FRESH_WINDOW_DAYS", 30))
    RECSCORE_REALTIME_FRESH_WINDOW_DAYS = int(os.environ.get("RECSCORE_REALTIME_FRESH_WINDOW_DAYS", 3))

    RECSCORE_DAILY_FALLBACK_DAYS = int(os.environ.get("RECSCORE_DAILY_FALLBACK_DAYS", 10))
    RECSCORE_WEEKLY_FALLBACK_DAYS = int(os.environ.get("RECSCORE_WEEKLY_FALLBACK_DAYS", 21))
    RECSCORE_REALTIME_FALLBACK_DAYS = int(os.environ.get("RECSCORE_REALTIME_FALLBACK_DAYS", 3))

    # Personalized recommendation scoring weights (tunable at runtime).
    RECSCORE_JOURNAL_MATCH_WEIGHT = float(os.environ.get("RECSCORE_JOURNAL_MATCH_WEIGHT", 4.0))
    RECSCORE_AREA_MATCH_WEIGHT = float(os.environ.get("RECSCORE_AREA_MATCH_WEIGHT", 2.0))
    RECSCORE_TEXT_MATCH_WEIGHT = float(os.environ.get("RECSCORE_TEXT_MATCH_WEIGHT", 1.4))
    RECSCORE_SUMMARY_BONUS = float(os.environ.get("RECSCORE_SUMMARY_BONUS", 0.3))

    RECSCORE_FAVORITE_BONUS = float(os.environ.get("RECSCORE_FAVORITE_BONUS", 0.6))
    RECSCORE_LIBRARY_PENALTY = float(os.environ.get("RECSCORE_LIBRARY_PENALTY", 0.25))
    RECSCORE_RATING_FACTOR = float(os.environ.get("RECSCORE_RATING_FACTOR", 0.85))
    RECSCORE_AVOID_CATEGORY_PENALTY = float(os.environ.get("RECSCORE_AVOID_CATEGORY_PENALTY", 1.8))
    RECSCORE_AREA_PREF_FACTOR = float(os.environ.get("RECSCORE_AREA_PREF_FACTOR", 0.45))
    RECSCORE_AREA_PREF_CAP = float(os.environ.get("RECSCORE_AREA_PREF_CAP", 2.6))
    RECSCORE_KEYWORD_PREF_FACTOR = float(os.environ.get("RECSCORE_KEYWORD_PREF_FACTOR", 0.22))
    RECSCORE_KEYWORD_PREF_CAP = float(os.environ.get("RECSCORE_KEYWORD_PREF_CAP", 1.8))

    RECSCORE_DAILY_FRESHNESS_WEIGHT = float(os.environ.get("RECSCORE_DAILY_FRESHNESS_WEIGHT", 1.0))
    RECSCORE_WEEKLY_FRESHNESS_WEIGHT = float(os.environ.get("RECSCORE_WEEKLY_FRESHNESS_WEIGHT", 0.6))
    RECSCORE_REALTIME_FRESHNESS_WEIGHT = float(os.environ.get("RECSCORE_REALTIME_FRESHNESS_WEIGHT", 1.5))

    RECSCORE_DAILY_SHUFFLE_WEIGHT = float(os.environ.get("RECSCORE_DAILY_SHUFFLE_WEIGHT", 0.25))
    RECSCORE_WEEKLY_SHUFFLE_WEIGHT = float(os.environ.get("RECSCORE_WEEKLY_SHUFFLE_WEIGHT", 0.18))
    RECSCORE_REALTIME_SHUFFLE_WEIGHT = float(os.environ.get("RECSCORE_REALTIME_SHUFFLE_WEIGHT", 0.35))

    RECSCORE_DAILY_CANDIDATE_LIMIT = int(os.environ.get("RECSCORE_DAILY_CANDIDATE_LIMIT", 1400))
    RECSCORE_WEEKLY_CANDIDATE_LIMIT = int(os.environ.get("RECSCORE_WEEKLY_CANDIDATE_LIMIT", 2400))
    RECSCORE_REALTIME_CANDIDATE_LIMIT = int(os.environ.get("RECSCORE_REALTIME_CANDIDATE_LIMIT", 900))

    RECSCORE_DAILY_FRESH_WINDOW_DAYS = int(os.environ.get("RECSCORE_DAILY_FRESH_WINDOW_DAYS", 10))
    RECSCORE_WEEKLY_FRESH_WINDOW_DAYS = int(os.environ.get("RECSCORE_WEEKLY_FRESH_WINDOW_DAYS", 30))
    RECSCORE_REALTIME_FRESH_WINDOW_DAYS = int(os.environ.get("RECSCORE_REALTIME_FRESH_WINDOW_DAYS", 3))

    RECSCORE_DAILY_FALLBACK_DAYS = int(os.environ.get("RECSCORE_DAILY_FALLBACK_DAYS", 10))
    RECSCORE_WEEKLY_FALLBACK_DAYS = int(os.environ.get("RECSCORE_WEEKLY_FALLBACK_DAYS", 21))
    RECSCORE_REALTIME_FALLBACK_DAYS = int(os.environ.get("RECSCORE_REALTIME_FALLBACK_DAYS", 3))

    # Admin control
    # Comma-separated usernames/emails that can access admin endpoints.
    ADMIN_USERNAMES = os.environ.get("ADMIN_USERNAMES", "test")
    ADMIN_EMAILS = os.environ.get("ADMIN_EMAILS", "")
