import functools
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import func, or_
from werkzeug.utils import secure_filename

from admin_utils import is_admin_user
from models import (
    Friendship,
    GroupChat,
    GroupChatMember,
    GroupChatMessage,
    PaperComment,
    PaperCommentLike,
    Paper,
    PaperEditRequest,
    PaperRating,
    PaperCardClick,
    PaperShare,
    PaperSourceClick,
    ScholarRating,
    User,
    UserChannelRequest,
    UserChannelSubscription,
    UserDigest,
    UserPaper,
    UserPreference,
    db,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

ALLOWED_AVATAR_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
AVATAR_MIME_TO_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def _avatar_storage_dir():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pic", "avatars"))


def _remove_local_avatar(avatar_url: str | None):
    if not avatar_url or not avatar_url.startswith("/api/avatars/"):
        return
    filename = avatar_url.rsplit("/", 1)[-1]
    path = os.path.join(_avatar_storage_dir(), filename)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _user_payload(user: User):
    d = user.to_dict()
    d["isAdmin"] = is_admin_user(user)
    return d


def _clean_profile_bio(value, max_len=2000):
    text = str(value or "").strip()
    if len(text) > max_len:
        return None, f"个人简介不能超过{max_len}个字符"
    return text or None, None


def _parse_profile_research_areas(raw, max_items=20, max_len=40):
    if raw is None:
        return []

    if isinstance(raw, list):
        candidates = [str(x).strip() for x in raw]
    else:
        text = str(raw).strip()
        if not text:
            return []
        parts = re.split(r"[,\n;/，；、]+", text)
        candidates = [p.strip() for p in parts]

    result = []
    seen = set()
    for item in candidates:
        if not item:
            continue
        cleaned = item[:max_len]
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
        if len(result) >= max_items:
            break
    return result


def _resolve_avatar_extension(file_storage) -> str:
    """Resolve image extension from original filename first, then MIME type fallback."""
    raw_name = (file_storage.filename or "").strip()
    ext = os.path.splitext(raw_name)[1].lower()
    if ext:
        return ext

    # Some non-ASCII filenames become "png/jpg" after secure_filename without dot.
    safe_name = secure_filename(raw_name)
    safe_base, safe_ext = os.path.splitext(safe_name.lower())
    if safe_ext:
        return safe_ext
    if safe_base in {"png", "jpg", "jpeg", "gif", "webp"}:
        return f".{safe_base}"

    mime = (file_storage.mimetype or "").lower()
    return AVATAR_MIME_TO_EXT.get(mime, "")


def token_required(f):
    """Decorator that validates JWT and sets g.current_user."""

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        token = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        if not token:
            return jsonify({"error": "缺少认证令牌"}), 401
        try:
            payload = jwt.decode(
                token, current_app.config["SECRET_KEY"], algorithms=["HS256"]
            )
            user = db.session.get(User, payload["user_id"])
            if user is None:
                return jsonify({"error": "用户不存在"}), 401
            g.current_user = user
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "令牌已过期"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "无效令牌"}), 401
        return f(*args, **kwargs)

    return wrapper


def _create_token(user: User) -> str:
    payload = {
        "user_id": user.id,
        "exp": datetime.now(timezone.utc)
        + timedelta(hours=current_app.config["JWT_EXPIRATION_HOURS"]),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    journals = data.get("journals") or []
    research_areas = data.get("researchAreas") or []
    recommend_frequency = "daily"

    if not username or not email or not password:
        return jsonify({"error": "用户名、邮箱和密码不能为空"}), 400
    if len(password) < 6:
        return jsonify({"error": "密码长度至少6位"}), 400

    if User.query.filter((User.username == username) | (User.email == email)).first():
        return jsonify({"error": "用户名或邮箱已被注册"}), 409

    user = User(username=username, email=email)
    user.set_password(password)
    db.session.add(user)

    # Support onboarding preferences at sign-up time.
    if isinstance(journals, list) or isinstance(research_areas, list):
        pref = UserPreference(user=user)
        if isinstance(journals, list):
            pref.journals = [str(x).strip() for x in journals if str(x).strip()][:30]
        if isinstance(research_areas, list):
            pref.research_areas = [str(x).strip() for x in research_areas if str(x).strip()][:30]
        pref.recommend_frequency = recommend_frequency
        db.session.add(pref)

    db.session.commit()

    token = _create_token(user)
    return jsonify({"token": token, "user": _user_payload(user)}), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"error": "用户名和密码不能为空"}), 400

    login_key = username.lower()
    candidates = (
        User.query.filter(
            or_(
                func.lower(User.username) == login_key,
                func.lower(User.email) == login_key,
                func.lower(User.display_name) == login_key,
            )
        )
        .limit(20)
        .all()
    )

    user = next((u for u in candidates if u.check_password(password)), None)

    if user is None:
        return jsonify({"error": "用户名或密码错误"}), 401

    token = _create_token(user)
    return jsonify({"token": token, "user": _user_payload(user)})


@auth_bp.route("/me", methods=["GET"])
@token_required
def me():
    return jsonify(_user_payload(g.current_user))


@auth_bp.route("/me", methods=["PATCH"])
@token_required
def update_me():
    data = request.get_json(silent=True) or {}
    user = g.current_user

    if "username" in data:
        username = (data.get("username") or "").strip()
        if not username:
            return jsonify({"error": "账号名不能为空"}), 400
        if len(username) > 80:
            return jsonify({"error": "账号名长度不能超过80个字符"}), 400
        if username != user.username:
            exists = User.query.filter(User.username == username, User.id != user.id).first()
            if exists:
                return jsonify({"error": "该账号名已被占用"}), 409
            user.username = username

    if "displayName" in data:
        display_name = (data.get("displayName") or "").strip()
        if display_name and len(display_name) > 80:
            return jsonify({"error": "昵称长度不能超过80个字符"}), 400
        user.display_name = display_name or None

    if "bio" in data or "profileBio" in data:
        raw_bio = data.get("bio", data.get("profileBio"))
        bio, bio_err = _clean_profile_bio(raw_bio)
        if bio_err:
            return jsonify({"error": bio_err}), 400
        user.profile_bio = bio

    if "profileResearchAreas" in data or "profile_research_areas" in data:
        raw_areas = data.get("profileResearchAreas", data.get("profile_research_areas"))
        user.profile_research_areas = _parse_profile_research_areas(raw_areas)

    db.session.commit()
    return jsonify(_user_payload(user))


@auth_bp.route("/avatar", methods=["POST"])
@token_required
def upload_avatar():
    file = request.files.get("avatar")
    if file is None or not file.filename:
        return jsonify({"error": "请选择头像文件"}), 400

    ext = _resolve_avatar_extension(file)
    if ext not in ALLOWED_AVATAR_EXTENSIONS:
        return jsonify({"error": "仅支持 png/jpg/jpeg/gif/webp 图片"}), 400

    # 5MB safety cap for avatar uploads.
    file.stream.seek(0, os.SEEK_END)
    size_bytes = file.stream.tell()
    file.stream.seek(0)
    if size_bytes > 5 * 1024 * 1024:
        return jsonify({"error": "头像文件不能超过 5MB"}), 400

    os.makedirs(_avatar_storage_dir(), exist_ok=True)
    filename = f"user_{g.current_user.id}_{uuid.uuid4().hex}{ext}"
    path = os.path.join(_avatar_storage_dir(), filename)
    file.save(path)

    _remove_local_avatar(g.current_user.avatar_url)
    g.current_user.avatar_url = f"/api/avatars/{filename}"
    db.session.commit()
    return jsonify(_user_payload(g.current_user))


@auth_bp.route("/password", methods=["PUT"])
@token_required
def change_password():
    data = request.get_json(silent=True) or {}
    current_password = data.get("currentPassword") or ""
    new_password = data.get("newPassword") or ""

    if not current_password or not new_password:
        return jsonify({"error": "当前密码和新密码不能为空"}), 400
    if not g.current_user.check_password(current_password):
        return jsonify({"error": "当前密码错误"}), 400
    if len(new_password) < 6:
        return jsonify({"error": "新密码长度至少6位"}), 400

    g.current_user.set_password(new_password)
    db.session.commit()
    return jsonify({"ok": True})


@auth_bp.route("/users/<int:user_id>/profile", methods=["GET"])
@token_required
def get_user_profile(user_id):
    target_user = db.session.get(User, user_id)
    if not target_user:
        return jsonify({"error": "用户不存在"}), 404

    viewer = g.current_user
    is_me = int(viewer.id or 0) == int(target_user.id or 0)

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 8, type=int)
    page = max(1, page)
    per_page = max(1, min(per_page, 20))

    q = (
        Paper.query
        .filter(Paper.created_by_user_id == target_user.id)
        .filter(Paper.is_public_clause())
    )
    q = q.order_by(Paper.created_at.desc(), Paper.id.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)

    profile = {
        "id": target_user.id,
        "username": target_user.username,
        "displayName": target_user.display_name or target_user.username,
        "avatarUrl": target_user.avatar_url,
        "bio": target_user.profile_bio or "",
        "researchAreas": target_user.profile_research_areas,
        "createdAt": target_user.created_at.isoformat() if target_user.created_at else None,
        "isMe": is_me,
    }

    return jsonify({
        "profile": profile,
        "papers": {
            "items": [item.to_dict() for item in pagination.items],
            "total": pagination.total,
            "page": pagination.page,
            "pages": pagination.pages,
            "perPage": per_page,
        },
    })


@auth_bp.route("/me", methods=["DELETE"])
@token_required
def delete_me():
    user = g.current_user
    user_id = user.id

    created_group_ids = [
        row.id for row in GroupChat.query.filter_by(creator_id=user_id).all()
    ]
    if created_group_ids:
        GroupChatMessage.query.filter(GroupChatMessage.group_id.in_(created_group_ids)).delete(
            synchronize_session=False
        )
        GroupChatMember.query.filter(GroupChatMember.group_id.in_(created_group_ids)).delete(
            synchronize_session=False
        )
        GroupChat.query.filter(GroupChat.id.in_(created_group_ids)).delete(
            synchronize_session=False
        )

    GroupChatMessage.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    GroupChatMember.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    PaperShare.query.filter(
        or_(PaperShare.from_user_id == user_id, PaperShare.to_user_id == user_id)
    ).delete(synchronize_session=False)
    Friendship.query.filter(
        or_(Friendship.user_id == user_id, Friendship.friend_id == user_id)
    ).delete(synchronize_session=False)
    UserPaper.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    PaperRating.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    PaperCardClick.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    PaperSourceClick.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    comment_ids = [row[0] for row in db.session.query(PaperComment.id).filter_by(user_id=user_id).all()]
    if comment_ids:
        PaperComment.query.filter(PaperComment.parent_id.in_(comment_ids)).update(
            {"parent_id": None},
            synchronize_session=False,
        )
        PaperCommentLike.query.filter(PaperCommentLike.comment_id.in_(comment_ids)).delete(
            synchronize_session=False
        )
    PaperCommentLike.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    PaperComment.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    UserDigest.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    ScholarRating.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    UserChannelSubscription.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    UserChannelRequest.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    UserChannelRequest.query.filter_by(reviewed_by=user_id).update(
        {"reviewed_by": None},
        synchronize_session=False,
    )
    PaperEditRequest.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    PaperEditRequest.query.filter_by(reviewed_by=user_id).update(
        {"reviewed_by": None},
        synchronize_session=False,
    )
    Paper.query.filter_by(created_by_user_id=user_id).update(
        {"created_by_user_id": None},
        synchronize_session=False,
    )
    Paper.query.filter_by(creator_reviewed_by=user_id).update(
        {"creator_reviewed_by": None},
        synchronize_session=False,
    )
    UserPreference.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    db.session.delete(user)
    db.session.commit()
    return jsonify({"ok": True})
