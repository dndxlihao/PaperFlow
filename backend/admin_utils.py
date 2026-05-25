import functools

from flask import current_app, g, jsonify


def _parse_csv(raw: str):
    if not raw:
        return set()
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def is_admin_user(user) -> bool:
    if not user:
        return False

    usernames = _parse_csv(current_app.config.get("ADMIN_USERNAMES", ""))
    emails = _parse_csv(current_app.config.get("ADMIN_EMAILS", ""))

    uname = (user.username or "").strip().lower()
    email = (user.email or "").strip().lower()
    return uname in usernames or email in emails


def admin_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        user = getattr(g, "current_user", None)
        if not is_admin_user(user):
            return jsonify({"error": "需要管理员权限"}), 403
        return f(*args, **kwargs)

    return wrapper
