from flask import Blueprint, g, jsonify, request
from sqlalchemy import or_, and_

from auth import token_required
from models import db, User, Friendship, PaperShare, Paper, UserDigest

friends_bp = Blueprint("friends", __name__, url_prefix="/api/friends")


def _attach_recommended_papers(digests):
    article_numbers = []
    seen = set()
    for digest in digests:
        for article_number in digest.rec_article_numbers:
            if article_number and article_number not in seen:
                seen.add(article_number)
                article_numbers.append(article_number)

    if not article_numbers:
        return [digest.to_dict() for digest in digests]

    papers = Paper.query.filter(Paper.article_number.in_(article_numbers)).all()
    paper_map = {paper.article_number: paper.to_dict(include_summary=False) for paper in papers}

    payload = []
    for digest in digests:
        item = digest.to_dict()
        item["recommendedPapers"] = [
            paper_map[article_number]
            for article_number in digest.rec_article_numbers
            if article_number in paper_map
        ]
        payload.append(item)
    return payload


# ---------- Friend Search ----------
@friends_bp.route("/search", methods=["GET"])
@token_required
def search_users():
    """Search users by username (for adding friends)."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 1:
        return jsonify([])
    users = User.query.filter(
        User.username.ilike(f"%{q}%"),
        User.id != g.current_user.id,
    ).limit(20).all()
    # Attach friendship status
    results = []
    for u in users:
        fs = Friendship.query.filter(
            or_(
                and_(Friendship.user_id == g.current_user.id, Friendship.friend_id == u.id),
                and_(Friendship.user_id == u.id, Friendship.friend_id == g.current_user.id),
            )
        ).first()
        d = u.to_dict()
        d["friendshipStatus"] = fs.status if fs else None
        d["friendshipId"] = fs.id if fs else None
        results.append(d)
    return jsonify(results)


# ---------- Send Friend Request ----------
@friends_bp.route("/request", methods=["POST"])
@token_required
def send_friend_request():
    data = request.get_json(silent=True) or {}
    friend_id = data.get("friendId")
    if not friend_id or friend_id == g.current_user.id:
        return jsonify({"error": "无效的用户"}), 400

    friend = db.session.get(User, friend_id)
    if not friend:
        return jsonify({"error": "用户不存在"}), 404

    existing = Friendship.query.filter(
        or_(
            and_(Friendship.user_id == g.current_user.id, Friendship.friend_id == friend_id),
            and_(Friendship.user_id == friend_id, Friendship.friend_id == g.current_user.id),
        )
    ).first()
    if existing:
        if existing.status == "accepted":
            return jsonify({"error": "已经是好友了"}), 409
        if existing.status == "pending":
            return jsonify({"error": "已发送过请求"}), 409
        # If rejected, allow re-request
        existing.status = "pending"
        existing.user_id = g.current_user.id
        existing.friend_id = friend_id
        db.session.commit()
        return jsonify(existing.to_dict()), 200

    fs = Friendship(user_id=g.current_user.id, friend_id=friend_id, status="pending")
    db.session.add(fs)
    db.session.commit()
    return jsonify(fs.to_dict()), 201


# ---------- Pending Requests (received) ----------
@friends_bp.route("/requests", methods=["GET"])
@token_required
def pending_requests():
    reqs = Friendship.query.filter_by(
        friend_id=g.current_user.id, status="pending"
    ).order_by(Friendship.created_at.desc()).all()
    return jsonify([r.to_dict() for r in reqs])


# ---------- Accept / Reject ----------
@friends_bp.route("/requests/<int:req_id>", methods=["PUT"])
@token_required
def handle_request(req_id):
    fs = db.session.get(Friendship, req_id)
    if not fs or fs.friend_id != g.current_user.id:
        return jsonify({"error": "请求不存在"}), 404

    data = request.get_json(silent=True) or {}
    action = data.get("action")
    if action == "accept":
        fs.status = "accepted"
    elif action == "reject":
        fs.status = "rejected"
    else:
        return jsonify({"error": "无效操作"}), 400

    db.session.commit()
    return jsonify(fs.to_dict())


# ---------- My Friends List ----------
@friends_bp.route("", methods=["GET"])
@token_required
def list_friends():
    uid = g.current_user.id
    friendships = Friendship.query.filter(
        Friendship.status == "accepted",
        or_(Friendship.user_id == uid, Friendship.friend_id == uid),
    ).all()
    friends = []
    for fs in friendships:
        friend_user = fs.receiver if fs.user_id == uid else fs.requester
        d = friend_user.to_dict()
        d["friendshipId"] = fs.id
        friends.append(d)
    return jsonify(friends)


# ---------- Remove Friend ----------
@friends_bp.route("/<int:fs_id>", methods=["DELETE"])
@token_required
def remove_friend(fs_id):
    fs = db.session.get(Friendship, fs_id)
    if not fs:
        return jsonify({"error": "不存在"}), 404
    uid = g.current_user.id
    if fs.user_id != uid and fs.friend_id != uid:
        return jsonify({"error": "无权操作"}), 403
    db.session.delete(fs)
    db.session.commit()
    return jsonify({"ok": True})


# ========== Paper Sharing ==========

@friends_bp.route("/share", methods=["POST"])
@token_required
def share_paper():
    """Share a paper to one or more friends."""
    data = request.get_json(silent=True) or {}
    article_number = data.get("articleNumber")
    friend_ids = data.get("friendIds", [])
    message = (data.get("message") or "").strip()

    if not article_number or not friend_ids:
        return jsonify({"error": "参数不完整"}), 400

    paper = Paper.query.filter_by(article_number=article_number).first()
    if not paper:
        return jsonify({"error": "论文不存在"}), 404

    uid = g.current_user.id
    created = []
    for fid in friend_ids:
        # Verify friendship
        is_friend = Friendship.query.filter(
            Friendship.status == "accepted",
            or_(
                and_(Friendship.user_id == uid, Friendship.friend_id == fid),
                and_(Friendship.user_id == fid, Friendship.friend_id == uid),
            )
        ).first()
        if not is_friend:
            continue
        share = PaperShare(
            from_user_id=uid,
            to_user_id=fid,
            paper_id=paper.id,
            message=message[:500] if message else None,
        )
        db.session.add(share)
        created.append(share)

    db.session.commit()
    return jsonify({"shared": len(created)}), 201


# ---------- My Received Shares (inbox) ----------
@friends_bp.route("/shares/inbox", methods=["GET"])
@token_required
def shares_inbox():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    q = PaperShare.query.filter_by(to_user_id=g.current_user.id)\
        .order_by(PaperShare.created_at.desc())
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    return jsonify({"total": total, "items": [s.to_dict() for s in items]})


# ---------- Mark share as read ----------
@friends_bp.route("/shares/<int:share_id>/read", methods=["PUT"])
@token_required
def mark_read(share_id):
    s = db.session.get(PaperShare, share_id)
    if not s or s.to_user_id != g.current_user.id:
        return jsonify({"error": "不存在"}), 404
    s.is_read = True
    db.session.commit()
    return jsonify({"ok": True})


# ---------- Unread count ----------
@friends_bp.route("/shares/unread-count", methods=["GET"])
@token_required
def unread_count():
    count = PaperShare.query.filter_by(
        to_user_id=g.current_user.id, is_read=False
    ).count()
    digest_unread = UserDigest.query.filter_by(
        user_id=g.current_user.id, is_read=False
    ).count()
    pending = Friendship.query.filter_by(
        friend_id=g.current_user.id, status="pending"
    ).count()
    return jsonify({
        "unreadShares": count,
        "unreadDigests": digest_unread,
        "pendingRequests": pending,
        "totalUnread": count + digest_unread + pending,
    })


@friends_bp.route("/digests/inbox", methods=["GET"])
@token_required
def digests_inbox():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    q = UserDigest.query.filter_by(user_id=g.current_user.id)\
        .order_by(UserDigest.created_at.desc())
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    return jsonify({"total": total, "items": _attach_recommended_papers(items)})


@friends_bp.route("/digests/<int:digest_id>/read", methods=["PUT"])
@token_required
def mark_digest_read(digest_id):
    d = db.session.get(UserDigest, digest_id)
    if not d or d.user_id != g.current_user.id:
        return jsonify({"error": "不存在"}), 404
    d.is_read = True
    db.session.commit()
    return jsonify({"ok": True})


@friends_bp.route("/digests/<int:digest_id>", methods=["DELETE"])
@token_required
def delete_digest(digest_id):
    d = db.session.get(UserDigest, digest_id)
    if not d or d.user_id != g.current_user.id:
        return jsonify({"error": "不存在"}), 404
    db.session.delete(d)
    db.session.commit()
    return jsonify({"ok": True})


@friends_bp.route("/shares/<int:share_id>", methods=["DELETE"])
@token_required
def delete_share(share_id):
    s = db.session.get(PaperShare, share_id)
    if not s or s.to_user_id != g.current_user.id:
        return jsonify({"error": "不存在"}), 404
    db.session.delete(s)
    db.session.commit()
    return jsonify({"ok": True})


@friends_bp.route("/digests/trigger", methods=["POST"])
@token_required
def trigger_my_digest():
    """Manual trigger for testing: create digest for current cycle immediately."""
    from digest_service import run_biweekly_digest

    result = run_biweekly_digest(force=True, user_ids=[g.current_user.id])
    return jsonify(result)
