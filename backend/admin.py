import html as html_lib
import os
import re
import shutil
from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import func, or_
from datetime import datetime, timezone
import json

from auth import token_required
from admin_utils import admin_required, is_admin_user
from config import Config
from paper_filters import is_paper_index_or_toc
from summarizer import normalize_summary_html
from models import (
    User,
    Paper,
    PaperEditRequest,
    PaperComment,
    PaperCommentLike,
    UserPaper,
    PaperCardClick,
    PaperRating,
    PaperShare,
    Recommendation,
    PaperSourceClick,
    ChannelMonitorRecord,
    PaperPdfDownloadAttempt,
    PaperPdfRetryTask,
    UserChannelRequest,
    UserDigest,
    db,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")
SUMMARY_SOURCE_COMMUNITY = "community_edit"
SUMMARY_META_PATTERN = re.compile(r"^\s*<!--PF_SUMMARY_META:(\{.*?\})-->\s*", re.DOTALL)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIGURES_ROOT = os.path.abspath(os.path.join(REPO_ROOT, "figures"))
PENDING_EDIT_FIGURES_SUBDIR = "pending_edits"
COMMUNITY_EDIT_FIGURES_SUBDIR = "community_edits"

RECSCORE_KEYS = {
    "RECSCORE_JOURNAL_MATCH_WEIGHT": (float, 0.0, 50.0),
    "RECSCORE_AREA_MATCH_WEIGHT": (float, 0.0, 50.0),
    "RECSCORE_TEXT_MATCH_WEIGHT": (float, 0.0, 50.0),
    "RECSCORE_SUMMARY_BONUS": (float, 0.0, 20.0),
    "RECSCORE_FAVORITE_BONUS": (float, 0.0, 20.0),
    "RECSCORE_LIBRARY_PENALTY": (float, 0.0, 20.0),
    "RECSCORE_RATING_FACTOR": (float, 0.0, 20.0),
    "RECSCORE_AVOID_CATEGORY_PENALTY": (float, 0.0, 20.0),
    "RECSCORE_AREA_PREF_FACTOR": (float, 0.0, 20.0),
    "RECSCORE_AREA_PREF_CAP": (float, 0.0, 20.0),
    "RECSCORE_KEYWORD_PREF_FACTOR": (float, 0.0, 20.0),
    "RECSCORE_KEYWORD_PREF_CAP": (float, 0.0, 20.0),
    "RECSCORE_DAILY_FRESHNESS_WEIGHT": (float, 0.0, 20.0),
    "RECSCORE_WEEKLY_FRESHNESS_WEIGHT": (float, 0.0, 20.0),
    "RECSCORE_REALTIME_FRESHNESS_WEIGHT": (float, 0.0, 20.0),
    "RECSCORE_DAILY_SHUFFLE_WEIGHT": (float, 0.0, 5.0),
    "RECSCORE_WEEKLY_SHUFFLE_WEIGHT": (float, 0.0, 5.0),
    "RECSCORE_REALTIME_SHUFFLE_WEIGHT": (float, 0.0, 5.0),
}


def _pack_summary_payload(summary_html: str, source=None):
    clean = (summary_html or "").strip()
    if not clean:
        return clean
    if not source:
        return clean
    meta = json.dumps({"source": source}, ensure_ascii=False)
    return f"<!--PF_SUMMARY_META:{meta}-->\n{clean}"


def _unpack_summary_payload(summary_text: str):
    if not summary_text:
        return summary_text, None
    text = str(summary_text)
    match = SUMMARY_META_PATTERN.match(text)
    if not match:
        return text, None

    source = None
    try:
        source = json.loads(match.group(1)).get("source")
    except Exception:
        source = None

    return text[match.end():].lstrip(), source


def _apply_selected_text_patch(source_text: str, selected_text: str, suggestion_text: str):
    base = (source_text or "")
    selected = (selected_text or "").strip()
    suggestion = (suggestion_text or "").strip()
    if not base or not selected or not suggestion:
        return None

    replacement = html_lib.escape(suggestion, quote=False)

    idx = base.find(selected)
    if idx >= 0:
        return base[:idx] + replacement + base[idx + len(selected):]

    # Tolerate whitespace differences in selected snippet.
    tokens = [tok for tok in re.split(r"\s+", selected) if tok]
    if tokens:
        pattern = re.escape(tokens[0])
        for tok in tokens[1:]:
            pattern += r"(?:\s|&nbsp;|&#160;|　)+" + re.escape(tok)
        match = re.search(pattern, base)
        if match:
            return base[:match.start()] + replacement + base[match.end():]

    return None


def _weights_snapshot():
    # Keep this function simple/readable while avoiding exposing unrelated config.
    from flask import current_app

    out = {}
    for key in RECSCORE_KEYS:
        val = current_app.config.get(key)
        if isinstance(val, (int, float)):
            out[key] = float(val)
        else:
            try:
                out[key] = float(val)
            except Exception:
                out[key] = val
    return out


def _weights_default_snapshot():
    out = {}
    for key in RECSCORE_KEYS:
        val = getattr(Config, key, None)
        if isinstance(val, (int, float)):
            out[key] = float(val)
        else:
            try:
                out[key] = float(val)
            except Exception:
                out[key] = val
    return out


def _paper_brief(paper, click_count=0, card_click_count=0):
    source_click = int(click_count or 0)
    card_click = int(card_click_count or 0)
    engagement_score = round(source_click * 0.5 + card_click * 0.5, 2)
    return {
        "articleNumber": paper.article_number,
        "title": paper.title,
        "titleZh": paper.title_zh,
        "category": paper.category,
        "downloadCount": paper.download_count or 0,
        "clickCount": source_click,
        "cardClickCount": card_click,
        "engagementScore": engagement_score,
        "avgRating": paper.avg_rating(),
        "ratingCount": paper.rating_count(),
    }


def _creator_submission_payload(paper: Paper):
    creator = db.session.get(User, paper.created_by_user_id) if paper and paper.created_by_user_id else None
    d = paper.to_dict()
    d["creatorUsername"] = creator.username if creator else None
    d["creatorDisplayName"] = (creator.display_name if creator else None) or (creator.username if creator else None)
    d["creatorEmail"] = creator.email if creator else None
    return d


def _resolve_figure_abs_path(relative_path: str):
    if not relative_path:
        return None
    rel = str(relative_path).replace("\\", "/").lstrip("/")
    # Keep path inside figures root.
    abs_path = os.path.abspath(os.path.join(FIGURES_ROOT, rel))
    if not abs_path.startswith(FIGURES_ROOT):
        return None
    return abs_path


def _resolve_repo_abs_path(path_value: str):
    if not path_value:
        return None
    raw = str(path_value).strip()
    if not raw:
        return None
    abs_path = raw if os.path.isabs(raw) else os.path.abspath(os.path.join(REPO_ROOT, raw))
    root = os.path.abspath(REPO_ROOT)
    if abs_path == root or abs_path.startswith(root + os.sep):
        return abs_path
    return None


def _safe_remove_file(path_value: str):
    abs_path = _resolve_repo_abs_path(path_value)
    if not abs_path:
        return False
    if not os.path.isfile(abs_path):
        return False
    try:
        os.remove(abs_path)
        return True
    except OSError:
        return False


def _promote_pending_figure_path(proposed_path: str, article_number: str, req_id: int):
    if not proposed_path:
        return proposed_path
    clean = str(proposed_path).replace("\\", "/").lstrip("/")
    if not clean.startswith(f"{PENDING_EDIT_FIGURES_SUBDIR}/"):
        return clean

    src_abs = _resolve_figure_abs_path(clean)
    if not src_abs or not os.path.exists(src_abs):
        return clean

    ext = os.path.splitext(src_abs)[1].lower() or ".png"
    safe_article = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in (article_number or "paper"))[:80]
    final_name = f"{safe_article}_req{req_id}{ext}"
    final_rel = f"{COMMUNITY_EDIT_FIGURES_SUBDIR}/{final_name}"
    final_abs = _resolve_figure_abs_path(final_rel)
    if not final_abs:
        return clean

    os.makedirs(os.path.dirname(final_abs), exist_ok=True)
    shutil.copy2(src_abs, final_abs)
    return final_rel


@admin_bp.route("/overview", methods=["GET"])
@token_required
@admin_required
def overview():
    user_count = User.query.count()
    # Keep paper total consistent with system-library homepage (public-visible cards only).
    paper_count = Paper.query.filter(Paper.is_public_clause()).count()
    library_count = UserPaper.query.count()
    rating_count = PaperRating.query.count()
    share_count = PaperShare.query.count()
    rec_days = db.session.query(func.count(func.distinct(Recommendation.recommended_date))).scalar() or 0

    total_source_clicks = db.session.query(func.count(PaperSourceClick.id)).scalar() or 0

    top_categories = (
        db.session.query(Paper.category, func.count(Paper.id).label("cnt"))
        .filter(Paper.category.isnot(None), Paper.category != "", Paper.is_public_clause())
        .group_by(Paper.category)
        .order_by(func.count(Paper.id).desc())
        .limit(8)
        .all()
    )

    return jsonify({
        "users": user_count,
        "papers": paper_count,
        "libraryItems": library_count,
        "ratings": rating_count,
        "shares": share_count,
        "recommendationDays": rec_days,
        # Keep totalDownloads for backward compatibility with old frontend code.
        "totalDownloads": int(total_source_clicks),
        "totalSourceClicks": int(total_source_clicks),
        "topCategories": [{"name": c or "未分类", "count": int(n)} for c, n in top_categories],
    })


@admin_bp.route("/review-pending-count", methods=["GET"])
@token_required
@admin_required
def review_pending_count():
    pending_channel = UserChannelRequest.query.filter_by(status="pending").count()
    pending_paper_edits = PaperEditRequest.query.filter_by(status="pending").count()
    pending_pdf_retry = PaperPdfRetryTask.query.filter_by(status="pending").count()
    pending_creator_submissions = Paper.query.filter_by(
        content_origin="user_upload",
        creator_review_status="pending",
    ).count()
    return jsonify({
        "pendingChannelRequests": int(pending_channel),
        "pendingPaperEdits": int(pending_paper_edits),
        "pendingPdfRetryTasks": int(pending_pdf_retry),
        "pendingCreatorSubmissions": int(pending_creator_submissions),
        "totalPendingReviews": int(
            pending_channel + pending_paper_edits + pending_pdf_retry + pending_creator_submissions
        ),
    })


@admin_bp.route("/creator-submissions", methods=["GET"])
@token_required
@admin_required
def list_creator_submissions():
    status = (request.args.get("status") or "").strip().lower()
    keyword = (request.args.get("keyword") or "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)

    q = Paper.query.filter(Paper.content_origin == "user_upload")
    if status in {"pending", "approved", "rejected"}:
        q = q.filter(Paper.creator_review_status == status)

    if keyword:
        like = f"%{keyword}%"
        creator_ids = [
            u.id
            for u in User.query.filter(
                or_(User.username.ilike(like), User.display_name.ilike(like), User.email.ilike(like))
            ).all()
        ]
        creator_match = Paper.created_by_user_id.in_(creator_ids) if creator_ids else (Paper.id == -1)
        q = q.filter(
            or_(
                Paper.article_number.ilike(like),
                Paper.title.ilike(like),
                Paper.publication_title.ilike(like),
                creator_match,
            )
        )

    q = q.order_by(Paper.created_at.desc(), Paper.id.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        "items": [_creator_submission_payload(item) for item in pagination.items],
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
    })


@admin_bp.route("/creator-submissions/<int:paper_id>/review", methods=["PUT"])
@token_required
@admin_required
def review_creator_submission(paper_id):
    paper = db.session.get(Paper, paper_id)
    if not paper or (paper.content_origin or "system") != "user_upload":
        return jsonify({"error": "投稿记录不存在"}), 404

    if (paper.creator_review_status or "approved") != "pending":
        return jsonify({"error": "当前状态不可审核，请刷新后重试"}), 400

    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip().lower()
    note = (data.get("note") or "").strip()
    if action not in {"approve", "reject"}:
        return jsonify({"error": "action 必须是 approve 或 reject"}), 400

    now = datetime.now(timezone.utc)
    paper.creator_review_status = "approved" if action == "approve" else "rejected"
    paper.creator_review_note = note[:2000] if note else None
    paper.creator_reviewed_by = g.current_user.id
    paper.creator_reviewed_at = now

    if paper.created_by_user_id:
        subject = "你的创作者投稿已审核通过" if action == "approve" else "你的创作者投稿未通过审核"
        content = (
            f"论文：{paper.title or paper.article_number}\n"
            f"审核结果：{'通过' if action == 'approve' else '驳回'}\n"
            f"审核备注：{paper.creator_review_note or '无'}"
        )
        msg = UserDigest(
            user_id=paper.created_by_user_id,
            period_start=now,
            period_end=now,
            subject=subject,
            content=content,
            read_count=0,
            source_click_count=0,
            is_read=False,
        )
        msg.keywords = ["创作者投稿", "审核结果", paper.creator_review_status]
        if paper.article_number:
            msg.rec_article_numbers = [paper.article_number]
        db.session.add(msg)

    db.session.commit()
    return jsonify(_creator_submission_payload(paper))


@admin_bp.route("/pdf-retry/summary", methods=["GET"])
@token_required
@admin_required
def pdf_retry_summary():
    pending = PaperPdfRetryTask.query.filter_by(status="pending").count()
    running = PaperPdfRetryTask.query.filter_by(status="running").count()
    success = PaperPdfRetryTask.query.filter_by(status="success").count()
    failed = PaperPdfRetryTask.query.filter_by(status="failed").count()

    limit = min(max(request.args.get("limit", 20, type=int), 1), 100)
    recent = (
        PaperPdfDownloadAttempt.query
        .order_by(PaperPdfDownloadAttempt.created_at.desc(), PaperPdfDownloadAttempt.id.desc())
        .limit(limit)
        .all()
    )
    return jsonify({
        "pending": int(pending),
        "running": int(running),
        "success": int(success),
        "failed": int(failed),
        "recentAttempts": [row.to_dict() for row in recent],
    })


@admin_bp.route("/pdf-retry/run", methods=["POST"])
@token_required
@admin_required
def run_pdf_retry_now():
    from pdf_retry_service import run_pdf_retry_batch

    data = request.get_json(silent=True) or {}
    limit = data.get("limit")
    force_browser = bool(data.get("forceBrowser", False))
    interactive_verify = data.get("interactiveVerify")
    verify_wait_seconds = data.get("verifyWaitSeconds")
    result = run_pdf_retry_batch(
        current_app,
        limit=limit,
        force_browser=force_browser,
        interactive_verify=interactive_verify,
        verify_wait_seconds=verify_wait_seconds,
    )
    return jsonify({"ok": True, **result})


@admin_bp.route("/popular-papers", methods=["GET"])
@token_required
@admin_required
def popular_papers():
    limit = min(request.args.get("limit", 20, type=int), 100)
    source_click_counts = (
        db.session.query(
            PaperSourceClick.paper_id.label("paper_id"),
            func.count(PaperSourceClick.id).label("click_count"),
        )
        .group_by(PaperSourceClick.paper_id)
        .subquery()
    )
    card_click_counts = (
        db.session.query(
            PaperCardClick.paper_id.label("paper_id"),
            func.count(PaperCardClick.id).label("card_click_count"),
        )
        .group_by(PaperCardClick.paper_id)
        .subquery()
    )
    source_click_expr = func.coalesce(source_click_counts.c.click_count, 0)
    card_click_expr = func.coalesce(card_click_counts.c.card_click_count, 0)
    engagement_score_expr = (source_click_expr * 0.5 + card_click_expr * 0.5).label("engagement_score")

    rows = (
        db.session.query(
            Paper,
            source_click_expr.label("click_count"),
            card_click_expr.label("card_click_count"),
            engagement_score_expr,
        )
        .outerjoin(source_click_counts, Paper.id == source_click_counts.c.paper_id)
        .outerjoin(card_click_counts, Paper.id == card_click_counts.c.paper_id)
        .filter(Paper.is_public_clause())
        .order_by(
            engagement_score_expr.desc(),
            source_click_expr.desc(),
            card_click_expr.desc(),
            Paper.created_at.desc(),
        )
        .limit(limit * 5)
        .all()
    )

    filtered = []
    for paper, click_count, card_click_count, _ in rows:
        if is_paper_index_or_toc(paper):
            continue
        filtered.append(_paper_brief(paper, click_count, card_click_count))
        if len(filtered) >= limit:
            break

    return jsonify({
        "items": filtered
    })


@admin_bp.route("/users", methods=["GET"])
@token_required
@admin_required
def list_users():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    keyword = (request.args.get("keyword") or "").strip()

    q = User.query
    if keyword:
        like = f"%{keyword}%"
        q = q.filter((User.username.ilike(like)) | (User.email.ilike(like)))

    q = q.order_by(User.created_at.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)

    user_ids = [u.id for u in pagination.items]
    if not user_ids:
        return jsonify({"items": [], "total": pagination.total, "page": pagination.page, "pages": pagination.pages})

    lib_counts = dict(
        db.session.query(UserPaper.user_id, func.count(UserPaper.id))
        .filter(UserPaper.user_id.in_(user_ids))
        .group_by(UserPaper.user_id)
        .all()
    )
    rating_counts = dict(
        db.session.query(PaperRating.user_id, func.count(PaperRating.id))
        .filter(PaperRating.user_id.in_(user_ids))
        .group_by(PaperRating.user_id)
        .all()
    )
    share_counts = dict(
        db.session.query(PaperShare.from_user_id, func.count(PaperShare.id))
        .filter(PaperShare.from_user_id.in_(user_ids))
        .group_by(PaperShare.from_user_id)
        .all()
    )

    items = []
    for u in pagination.items:
        d = u.to_dict()
        d["isAdmin"] = is_admin_user(u)
        d["libraryCount"] = int(lib_counts.get(u.id, 0))
        d["ratingCount"] = int(rating_counts.get(u.id, 0))
        d["shareCount"] = int(share_counts.get(u.id, 0))
        items.append(d)

    return jsonify({
        "items": items,
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
    })


@admin_bp.route("/users/<int:user_id>", methods=["PATCH"])
@token_required
@admin_required
def update_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "用户不存在"}), 404

    data = request.get_json(silent=True) or {}
    new_username = (data.get("username") or "").strip()
    new_email = (data.get("email") or "").strip()

    if new_username and new_username != user.username:
        exists = User.query.filter(User.username == new_username, User.id != user.id).first()
        if exists:
            return jsonify({"error": "用户名已存在"}), 409
        user.username = new_username

    if new_email and new_email != user.email:
        exists = User.query.filter(User.email == new_email, User.id != user.id).first()
        if exists:
            return jsonify({"error": "邮箱已存在"}), 409
        user.email = new_email

    db.session.commit()
    d = user.to_dict()
    d["isAdmin"] = is_admin_user(user)
    return jsonify(d)


@admin_bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
@token_required
@admin_required
def reset_password(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "用户不存在"}), 404

    data = request.get_json(silent=True) or {}
    new_password = data.get("newPassword") or ""
    if len(new_password) < 6:
        return jsonify({"error": "密码长度至少6位"}), 400

    user.set_password(new_password)
    db.session.commit()
    return jsonify({"ok": True})


@admin_bp.route("/preferences", methods=["GET"])
@token_required
@admin_required
def user_preferences():
    limit = min(request.args.get("limit", 10, type=int), 30)

    library_cats = (
        db.session.query(Paper.category, func.count(UserPaper.id).label("cnt"))
        .join(UserPaper, UserPaper.paper_id == Paper.id)
        .filter(Paper.category.isnot(None), Paper.category != "")
        .group_by(Paper.category)
        .order_by(func.count(UserPaper.id).desc())
        .limit(limit)
        .all()
    )

    rating_cats = (
        db.session.query(Paper.category, func.count(PaperRating.id).label("cnt"))
        .join(PaperRating, PaperRating.paper_id == Paper.id)
        .filter(Paper.category.isnot(None), Paper.category != "")
        .group_by(Paper.category)
        .order_by(func.count(PaperRating.id).desc())
        .limit(limit)
        .all()
    )

    active_users = (
        db.session.query(User.id, User.username, func.count(UserPaper.id).label("cnt"))
        .outerjoin(UserPaper, UserPaper.user_id == User.id)
        .group_by(User.id, User.username)
        .order_by(func.count(UserPaper.id).desc())
        .limit(limit)
        .all()
    )

    return jsonify({
        "libraryCategories": [{"name": c or "未分类", "count": int(n)} for c, n in library_cats],
        "ratingCategories": [{"name": c or "未分类", "count": int(n)} for c, n in rating_cats],
        "activeUsers": [{"userId": uid, "username": uname, "libraryCount": int(cnt)} for uid, uname, cnt in active_users],
    })


@admin_bp.route("/recommend/jobs", methods=["GET"])
@token_required
@admin_required
def recommend_jobs_status():
    from scheduler import get_recommend_job_status

    return jsonify(get_recommend_job_status())


@admin_bp.route("/recommend/weights", methods=["GET"])
@token_required
@admin_required
def get_recommend_weights():
    return jsonify(_weights_snapshot())


@admin_bp.route("/recommend/weights/defaults", methods=["GET"])
@token_required
@admin_required
def get_recommend_weights_defaults():
    return jsonify(_weights_default_snapshot())


@admin_bp.route("/recommend/weights", methods=["PATCH"])
@token_required
@admin_required
def update_recommend_weights():
    from flask import current_app

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "请求体必须是JSON对象"}), 400

    updates = {}
    for key, raw in data.items():
        if key not in RECSCORE_KEYS:
            return jsonify({"error": f"不支持的权重键: {key}"}), 400

        caster, min_v, max_v = RECSCORE_KEYS[key]
        try:
            val = caster(raw)
        except Exception:
            return jsonify({"error": f"{key} 取值类型不正确"}), 400

        if val < min_v or val > max_v:
            return jsonify({"error": f"{key} 超出范围 [{min_v}, {max_v}]"}), 400

        current_app.config[key] = val
        updates[key] = float(val)

    return jsonify({
        "updated": updates,
        "weights": _weights_snapshot(),
        "note": "权重已在线生效（当前进程）。重启后会恢复到配置/环境变量中的值。",
    })


@admin_bp.route("/channel-requests", methods=["GET"])
@token_required
@admin_required
def list_channel_requests():
    status = (request.args.get("status") or "").strip().lower()
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)

    q = UserChannelRequest.query
    if status in {"pending", "approved", "rejected"}:
        q = q.filter_by(status=status)

    q = q.order_by(UserChannelRequest.created_at.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        "items": [item.to_dict() for item in pagination.items],
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
    })


@admin_bp.route("/channel-requests/<int:req_id>/review", methods=["PUT"])
@token_required
@admin_required
def review_channel_request(req_id):
    req = db.session.get(UserChannelRequest, req_id)
    if not req:
        return jsonify({"error": "需求不存在"}), 404

    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip().lower()
    note = (data.get("note") or "").strip()

    if action not in {"approve", "reject"}:
        return jsonify({"error": "action 必须是 approve 或 reject"}), 400

    req.status = "approved" if action == "approve" else "rejected"
    req.admin_note = note[:500] if note else None
    req.reviewed_by = g.current_user.id
    req.reviewed_at = datetime.now(timezone.utc)

    now = datetime.now(timezone.utc)
    subject = "你的专栏需求已审核通过" if req.status == "approved" else "你的专栏需求未通过本次审核"
    content = (
        f"需求标题：{req.title}\n"
        f"审核结果：{'已采纳' if req.status == 'approved' else '未采纳'}\n"
        f"审核备注：{req.admin_note or '无'}"
    )
    msg = UserDigest(
        user_id=req.user_id,
        period_start=now,
        period_end=now,
        subject=subject,
        content=content,
        read_count=0,
        source_click_count=0,
        is_read=False,
    )
    msg.keywords = ["需求审核", req.status]
    db.session.add(msg)

    db.session.commit()
    return jsonify(req.to_dict())


@admin_bp.route("/paper-edit-requests", methods=["GET"])
@token_required
@admin_required
def list_paper_edit_requests():
    status = (request.args.get("status") or "").strip().lower()
    keyword = (request.args.get("keyword") or "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)

    q = PaperEditRequest.query.join(Paper, PaperEditRequest.paper_id == Paper.id).join(
        User, PaperEditRequest.user_id == User.id
    )
    if status in {"pending", "approved", "rejected", "withdrawn"}:
        q = q.filter(PaperEditRequest.status == status)

    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            or_(
                Paper.article_number.ilike(like),
                Paper.title.ilike(like),
                User.username.ilike(like),
            )
        )

    q = q.order_by(PaperEditRequest.created_at.desc(), PaperEditRequest.id.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        "items": [item.to_dict() for item in pagination.items],
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
    })


@admin_bp.route("/paper-edit-requests/<int:req_id>/review", methods=["PUT"])
@token_required
@admin_required
def review_paper_edit_request(req_id):
    req = db.session.get(PaperEditRequest, req_id)
    if not req:
        return jsonify({"error": "编辑申请不存在"}), 404
    if req.status != "pending":
        return jsonify({"error": "该申请已审核，不能重复操作"}), 400

    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip().lower()
    note = (data.get("note") or "").strip()
    if action not in {"approve", "reject"}:
        return jsonify({"error": "action 必须是 approve 或 reject"}), 400

    now = datetime.now(timezone.utc)
    req.status = "approved" if action == "approve" else "rejected"
    req.admin_note = note[:500] if note else None
    req.reviewed_by = g.current_user.id
    req.reviewed_at = now

    if req.status == "approved":
        paper = req.paper
        if paper:
            current_summary, _ = _unpack_summary_payload(paper.summary or "")
            patched_summary = None
            if req.target_field == "summary" and req.selected_text and req.suggestion_text:
                patched_summary = _apply_selected_text_patch(
                    current_summary or "",
                    req.selected_text,
                    req.suggestion_text,
                )

            if patched_summary:
                normalized_summary = normalize_summary_html(patched_summary)
                paper.summary = _pack_summary_payload(normalized_summary, SUMMARY_SOURCE_COMMUNITY)
                paper.summary_generated_at = now
            elif req.proposed_summary:
                normalized_summary = normalize_summary_html(req.proposed_summary)
                paper.summary = _pack_summary_payload(normalized_summary, SUMMARY_SOURCE_COMMUNITY)
                paper.summary_generated_at = now

            patched_figure_explanation = None
            if req.target_field == "figureExplanation" and req.selected_text and req.suggestion_text:
                patched_figure_explanation = _apply_selected_text_patch(
                    paper.figure_explanation or "",
                    req.selected_text,
                    req.suggestion_text,
                )
            if patched_figure_explanation:
                paper.figure_explanation = patched_figure_explanation
            elif req.proposed_figure_explanation:
                paper.figure_explanation = req.proposed_figure_explanation

            if req.proposed_figure_path:
                final_figure_path = _promote_pending_figure_path(
                    req.proposed_figure_path,
                    article_number=paper.article_number if paper else "",
                    req_id=req.id,
                )
                req.proposed_figure_path = final_figure_path
                paper.figure_path = final_figure_path

    subject = "你的卡片编辑申请已审核通过" if req.status == "approved" else "你的卡片编辑申请未通过审核"
    content = (
        f"论文：{(req.paper.title if req.paper else '') or (req.paper.article_number if req.paper else '')}\n"
        f"申请类型：{req.request_type}\n"
        f"审核结果：{'已通过' if req.status == 'approved' else '未通过'}\n"
        f"审核备注：{req.admin_note or '无'}"
    )
    digest = UserDigest(
        user_id=req.user_id,
        period_start=now,
        period_end=now,
        subject=subject,
        content=content,
        read_count=0,
        source_click_count=0,
        is_read=False,
    )
    digest.keywords = ["卡片编辑", req.status]
    if req.paper and req.paper.article_number:
        digest.rec_article_numbers = [req.paper.article_number]
    db.session.add(digest)

    db.session.commit()
    return jsonify(req.to_dict())


@admin_bp.route("/papers/<article_number>", methods=["DELETE"])
@token_required
@admin_required
def delete_system_paper(article_number):
    paper = Paper.query.filter_by(article_number=article_number).first()
    if not paper:
        return jsonify({"error": "论文不存在"}), 404

    paper_id = int(paper.id)
    paper_title = paper.title or paper.article_number
    pdf_path = paper.pdf_path
    figure_path = paper.figure_path

    # Cleanup pending edit images (best effort).
    edit_rows = PaperEditRequest.query.filter_by(paper_id=paper_id).all()
    for row in edit_rows:
        if row and row.proposed_figure_path:
            abs_path = _resolve_figure_abs_path(row.proposed_figure_path)
            if abs_path and os.path.exists(abs_path):
                try:
                    os.remove(abs_path)
                except OSError:
                    pass

    comment_ids = [
        row[0]
        for row in db.session.query(PaperComment.id).filter_by(paper_id=paper_id).all()
    ]
    if comment_ids:
        PaperCommentLike.query.filter(
            PaperCommentLike.comment_id.in_(comment_ids)
        ).delete(synchronize_session=False)
    PaperComment.query.filter_by(paper_id=paper_id).delete(synchronize_session=False)

    PaperEditRequest.query.filter_by(paper_id=paper_id).delete(synchronize_session=False)
    UserPaper.query.filter_by(paper_id=paper_id).delete(synchronize_session=False)
    Recommendation.query.filter_by(paper_id=paper_id).delete(synchronize_session=False)
    PaperRating.query.filter_by(paper_id=paper_id).delete(synchronize_session=False)
    PaperShare.query.filter_by(paper_id=paper_id).delete(synchronize_session=False)
    PaperSourceClick.query.filter_by(paper_id=paper_id).delete(synchronize_session=False)
    PaperCardClick.query.filter_by(paper_id=paper_id).delete(synchronize_session=False)
    PaperPdfDownloadAttempt.query.filter_by(paper_id=paper_id).delete(synchronize_session=False)
    PaperPdfRetryTask.query.filter_by(paper_id=paper_id).delete(synchronize_session=False)
    ChannelMonitorRecord.query.filter_by(paper_id=paper_id).delete(synchronize_session=False)

    db.session.delete(paper)
    db.session.commit()

    _safe_remove_file(pdf_path)
    _safe_remove_file(figure_path)

    return jsonify({
        "message": "论文卡片已删除",
        "articleNumber": article_number,
        "paperTitle": paper_title,
    })
