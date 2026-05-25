from flask import Blueprint, g, jsonify, request
from sqlalchemy import or_, and_

from auth import token_required
from models import db, User, Friendship, Paper, GroupChat, GroupChatMember, GroupChatMessage

groups_bp = Blueprint("groups", __name__, url_prefix="/api/groups")


def _is_friend(uid, other_id):
    return Friendship.query.filter(
        Friendship.status == "accepted",
        or_(
            and_(Friendship.user_id == uid, Friendship.friend_id == other_id),
            and_(Friendship.user_id == other_id, Friendship.friend_id == uid),
        )
    ).first() is not None


def _is_member(group_id, user_id):
    return GroupChatMember.query.filter_by(group_id=group_id, user_id=user_id).first()


# ---------- Create Group ----------
@groups_bp.route("", methods=["POST"])
@token_required
def create_group():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    member_ids = data.get("memberIds", [])

    if not name:
        return jsonify({"error": "群聊名称不能为空"}), 400
    if len(name) > 50:
        return jsonify({"error": "群聊名称过长"}), 400

    uid = g.current_user.id
    group = GroupChat(name=name, creator_id=uid)
    db.session.add(group)
    db.session.flush()

    # Add creator as member
    db.session.add(GroupChatMember(group_id=group.id, user_id=uid, role="creator"))

    # Add friends as members
    for mid in member_ids:
        if mid == uid:
            continue
        if _is_friend(uid, mid):
            db.session.add(GroupChatMember(group_id=group.id, user_id=mid, role="member"))

    db.session.commit()
    return jsonify(group.to_dict()), 201


# ---------- List My Groups ----------
@groups_bp.route("", methods=["GET"])
@token_required
def list_groups():
    uid = g.current_user.id
    memberships = GroupChatMember.query.filter_by(user_id=uid).all()
    groups = []
    for m in memberships:
        d = m.group.to_dict()
        d["myRole"] = m.role
        # Include last message preview
        last_msg = GroupChatMessage.query.filter_by(group_id=m.group_id)\
            .order_by(GroupChatMessage.created_at.desc()).first()
        if last_msg:
            d["lastMessage"] = {
                "content": last_msg.content[:50] if last_msg.content else "分享了一篇论文",
                "username": last_msg.sender.username if last_msg.sender else None,
                "createdAt": last_msg.created_at.isoformat() if last_msg.created_at else None,
            }
        groups.append(d)
    return jsonify(groups)


# ---------- Group Detail ----------
@groups_bp.route("/<int:group_id>", methods=["GET"])
@token_required
def group_detail(group_id):
    group = db.session.get(GroupChat, group_id)
    if not group:
        return jsonify({"error": "群聊不存在"}), 404
    if not _is_member(group_id, g.current_user.id):
        return jsonify({"error": "您不是该群成员"}), 403

    d = group.to_dict()
    d["members"] = [m.to_dict() for m in group.members]
    return jsonify(d)


# ---------- Add Members ----------
@groups_bp.route("/<int:group_id>/members", methods=["POST"])
@token_required
def add_members(group_id):
    group = db.session.get(GroupChat, group_id)
    if not group:
        return jsonify({"error": "群聊不存在"}), 404
    if not _is_member(group_id, g.current_user.id):
        return jsonify({"error": "您不是该群成员"}), 403

    data = request.get_json(silent=True) or {}
    member_ids = data.get("memberIds", [])
    uid = g.current_user.id
    added = 0

    for mid in member_ids:
        if mid == uid:
            continue
        if _is_friend(uid, mid) and not _is_member(group_id, mid):
            db.session.add(GroupChatMember(group_id=group_id, user_id=mid, role="member"))
            added += 1

    db.session.commit()
    return jsonify({"added": added})


# ---------- Leave / Remove Member ----------
@groups_bp.route("/<int:group_id>/members/<int:user_id>", methods=["DELETE"])
@token_required
def remove_member(group_id, user_id):
    group = db.session.get(GroupChat, group_id)
    if not group:
        return jsonify({"error": "群聊不存在"}), 404

    uid = g.current_user.id
    # Can remove self (leave) or creator can remove others
    if user_id != uid and group.creator_id != uid:
        return jsonify({"error": "无权操作"}), 403

    member = _is_member(group_id, user_id)
    if not member:
        return jsonify({"error": "该用户不在群中"}), 404

    db.session.delete(member)
    db.session.commit()
    return jsonify({"ok": True})


# ---------- Delete Group ----------
@groups_bp.route("/<int:group_id>", methods=["DELETE"])
@token_required
def delete_group(group_id):
    group = db.session.get(GroupChat, group_id)
    if not group:
        return jsonify({"error": "群聊不存在"}), 404
    if group.creator_id != g.current_user.id:
        return jsonify({"error": "只有群主可以解散群聊"}), 403

    db.session.delete(group)
    db.session.commit()
    return jsonify({"ok": True})


# ---------- Get Messages ----------
@groups_bp.route("/<int:group_id>/messages", methods=["GET"])
@token_required
def get_messages(group_id):
    group = db.session.get(GroupChat, group_id)
    if not group:
        return jsonify({"error": "群聊不存在"}), 404
    if not _is_member(group_id, g.current_user.id):
        return jsonify({"error": "您不是该群成员"}), 403

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    per_page = min(per_page, 100)

    q = GroupChatMessage.query.filter_by(group_id=group_id)\
        .order_by(GroupChatMessage.created_at.desc())
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    items.reverse()  # chronological order

    return jsonify({"total": total, "items": [m.to_dict() for m in items]})


# ---------- Send Message ----------
@groups_bp.route("/<int:group_id>/messages", methods=["POST"])
@token_required
def send_message(group_id):
    group = db.session.get(GroupChat, group_id)
    if not group:
        return jsonify({"error": "群聊不存在"}), 404
    if not _is_member(group_id, g.current_user.id):
        return jsonify({"error": "您不是该群成员"}), 403

    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    message_type = data.get("messageType", "text")
    article_number = data.get("articleNumber")

    if message_type == "paper_share":
        if not article_number:
            return jsonify({"error": "缺少论文信息"}), 400
        paper = Paper.query.filter_by(article_number=article_number).first()
        if not paper:
            return jsonify({"error": "论文不存在"}), 404
        msg = GroupChatMessage(
            group_id=group_id,
            user_id=g.current_user.id,
            content=content[:500] if content else None,
            message_type="paper_share",
            paper_id=paper.id,
        )
    else:
        if not content:
            return jsonify({"error": "消息不能为空"}), 400
        msg = GroupChatMessage(
            group_id=group_id,
            user_id=g.current_user.id,
            content=content[:2000],
            message_type="text",
        )

    db.session.add(msg)
    db.session.commit()
    return jsonify(msg.to_dict()), 201
