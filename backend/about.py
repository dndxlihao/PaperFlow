import os
import uuid

from flask import Blueprint, g, jsonify, request
from werkzeug.utils import secure_filename

from admin_utils import is_admin_user
from auth import token_required
from models import AboutPageConfig, db

about_bp = Blueprint("about", __name__, url_prefix="/api/about")
ABOUT_EDITOR_USERNAME = "Manager1"
LEGACY_HERO_SUBTITLES = {
    "面向能源与智能系统研究场景，构建“检索、阅读、推荐、互动”一体化的学术协同平台。",
    "面向跨学科科研与技术创新场景，构建“检索、阅读、推荐、互动”一体化的开放学术协同平台。",
}
DEFAULT_HERO_SUBTITLE = "面向跨学科科研与技术创新场景，构建检索、阅读、推荐、互动一体化的开放学术协同平台。"

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MIME_TO_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def _about_assets_dir():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pic", "about"))


def _is_about_editor(user) -> bool:
    if not user:
        return False
    if not is_admin_user(user):
        return False
    target = ABOUT_EDITOR_USERNAME.strip().lower()
    username = (user.username or "").strip().lower()
    display_name = (getattr(user, "display_name", None) or "").strip().lower()
    return username == target or display_name == target


def _clean_text(value, max_len=4000):
    if value is None:
        return ""
    return str(value).strip()[:max_len]


def _default_content():
    return {
        "hero": {
            "badge": "About PaperFlow",
            "title": "关于我们",
            "subtitle": DEFAULT_HERO_SUBTITLE,
        },
        "projectBackground": [
            "PaperFlow 起步于电力与能源交叉方向的文献痛点：论文数量增长快、跨源检索分散、阅读沉淀难复用。平台将 IEEE、arXiv、Elsevier 等来源聚合到统一入口，并结合 AI 摘要与偏好推荐，帮助用户缩短从“发现文献”到“形成研究判断”的路径。",
            "随着自动化科研范式逐步成为主流，我们希望提供一个自由、开放、可持续沉淀的学术交流窗口。用户能够围绕论文进行评论、回复、评分与分享，让研究想法更快被讨论、被验证、被延展。",
            "在科研传播层面，平台同样有助于稿件推广和同行快速审阅：研究者可以更高效地触达目标读者，同行可以在结构化信息与互动反馈中快速理解论文价值，从而形成更高质量的学术协作闭环。",
        ],
        "lead": {
            "name": "总负责人（待完善）",
            "avatarUrl": "",
            "role": "总体统筹、产品方向与学术协同",
            "experience": "负责平台战略规划、跨团队协作与关键项目推进，持续优化学术产品体验与社区生态建设。",
        },
        "teams": [
            {
                "id": "team-product",
                "title": "产品与学术运营组",
                "description": "负责产品路线、学术需求调研与专题栏目规划。",
                "members": [],
            },
            {
                "id": "team-algo",
                "title": "推荐算法组",
                "description": "负责个性化推荐策略、评分权重与反馈闭环优化。",
                "members": [],
            },
            {
                "id": "team-engineering",
                "title": "平台工程组",
                "description": "负责数据抓取、服务稳定性、性能与安全保障。",
                "members": [],
            },
        ],
        "versionUpdates": [
            {"version": "v1.3", "date": "2026-05", "updates": "新增论文评论区、回复与点赞；支持互动消息提醒。"},
            {"version": "v1.2", "date": "2026-04", "updates": "上线双周阅读简报、专栏订阅提醒、管理员推荐权重调节。"},
            {"version": "v1.1", "date": "2026-03", "updates": "个性化推荐增强，支持研究方向偏好与实时刷新策略。"},
            {"version": "v1.0", "date": "2026-02", "updates": "完成论文搜索、AI 总结、论文库和基础社交分享功能。"},
        ],
    }


def _normalize_content(payload):
    content = _default_content()
    src = payload if isinstance(payload, dict) else {}

    hero = src.get("hero") if isinstance(src.get("hero"), dict) else {}
    content["hero"]["badge"] = _clean_text(hero.get("badge") or content["hero"]["badge"], 100)
    content["hero"]["title"] = _clean_text(hero.get("title") or content["hero"]["title"], 100)
    content["hero"]["subtitle"] = _clean_text(hero.get("subtitle") or content["hero"]["subtitle"], 300)
    if content["hero"]["subtitle"] in LEGACY_HERO_SUBTITLES:
        content["hero"]["subtitle"] = DEFAULT_HERO_SUBTITLE

    raw_bg = src.get("projectBackground")
    if isinstance(raw_bg, list):
        paragraphs = [_clean_text(p, 1600) for p in raw_bg if _clean_text(p, 1600)]
        if paragraphs:
            content["projectBackground"] = paragraphs[:8]

    lead = src.get("lead") if isinstance(src.get("lead"), dict) else {}
    content["lead"]["name"] = _clean_text(lead.get("name") or content["lead"]["name"], 120)
    content["lead"]["avatarUrl"] = _clean_text(lead.get("avatarUrl") or content["lead"]["avatarUrl"], 500)
    content["lead"]["role"] = _clean_text(lead.get("role") or content["lead"]["role"], 200)
    content["lead"]["experience"] = _clean_text(lead.get("experience") or content["lead"]["experience"], 3000)

    raw_teams = src.get("teams")
    if isinstance(raw_teams, list) and raw_teams:
        teams = []
        for idx, item in enumerate(raw_teams[:8]):
            if not isinstance(item, dict):
                continue
            team_id = _clean_text(item.get("id") or f"team-{idx+1}", 80)
            team_title = _clean_text(item.get("title"), 120)
            team_desc = _clean_text(item.get("description"), 500)
            if not team_title:
                continue
            members = []
            raw_members = item.get("members")
            if isinstance(raw_members, list):
                for member in raw_members[:30]:
                    if not isinstance(member, dict):
                        continue
                    m_name = _clean_text(member.get("name"), 100)
                    m_role = _clean_text(member.get("role"), 160)
                    m_bio = _clean_text(member.get("bio"), 1000)
                    if not m_name and not m_role and not m_bio:
                        continue
                    members.append({"name": m_name, "role": m_role, "bio": m_bio})
            teams.append(
                {
                    "id": team_id or f"team-{idx+1}",
                    "title": team_title,
                    "description": team_desc,
                    "members": members,
                }
            )
        if teams:
            content["teams"] = teams

    raw_versions = src.get("versionUpdates")
    if isinstance(raw_versions, list) and raw_versions:
        updates = []
        for item in raw_versions[:30]:
            if not isinstance(item, dict):
                continue
            version = _clean_text(item.get("version"), 40)
            date = _clean_text(item.get("date"), 20)
            desc = _clean_text(item.get("updates"), 1200)
            if not version and not date and not desc:
                continue
            updates.append({"version": version, "date": date, "updates": desc})
        if updates:
            content["versionUpdates"] = updates

    return content


def _get_or_create_config():
    config = AboutPageConfig.query.order_by(AboutPageConfig.id.asc()).first()
    if config is None:
        config = AboutPageConfig()
        config.data = _default_content()
        db.session.add(config)
        db.session.commit()
    return config


def _resolve_image_extension(file_storage) -> str:
    raw_name = (file_storage.filename or "").strip()
    ext = os.path.splitext(raw_name)[1].lower()
    if ext:
        return ext
    safe_name = secure_filename(raw_name)
    safe_base, safe_ext = os.path.splitext(safe_name.lower())
    if safe_ext:
        return safe_ext
    if safe_base in {"png", "jpg", "jpeg", "gif", "webp"}:
        return f".{safe_base}"
    mime = (file_storage.mimetype or "").lower()
    return MIME_TO_EXT.get(mime, "")


@about_bp.route("/content", methods=["GET"])
@token_required
def get_about_content():
    config = _get_or_create_config()
    return jsonify(
        {
            "content": _normalize_content(config.data),
            "canEdit": _is_about_editor(g.current_user),
            "updatedBy": config.updated_by_username,
            "updatedAt": config.updated_at.isoformat() if config.updated_at else None,
        }
    )


@about_bp.route("/content", methods=["PATCH"])
@token_required
def update_about_content():
    if not _is_about_editor(g.current_user):
        return jsonify({"error": f"仅 {ABOUT_EDITOR_USERNAME} 管理员可编辑（按账号名或昵称判断）"}), 403

    data = request.get_json(silent=True) or {}
    content = data.get("content")
    if not isinstance(content, dict):
        return jsonify({"error": "content 必须为对象"}), 400

    config = _get_or_create_config()
    config.data = _normalize_content(content)
    config.updated_by_username = g.current_user.username
    db.session.commit()
    return jsonify(
        {
            "content": config.data,
            "canEdit": True,
            "updatedBy": config.updated_by_username,
            "updatedAt": config.updated_at.isoformat() if config.updated_at else None,
        }
    )


@about_bp.route("/leader-avatar", methods=["POST"])
@token_required
def upload_about_leader_avatar():
    if not _is_about_editor(g.current_user):
        return jsonify({"error": f"仅 {ABOUT_EDITOR_USERNAME} 管理员可编辑（按账号名或昵称判断）"}), 403

    file = request.files.get("avatar")
    if file is None or not file.filename:
        return jsonify({"error": "请选择头像文件"}), 400

    ext = _resolve_image_extension(file)
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return jsonify({"error": "仅支持 png/jpg/jpeg/gif/webp 图片"}), 400

    file.stream.seek(0, os.SEEK_END)
    size_bytes = file.stream.tell()
    file.stream.seek(0)
    if size_bytes > 5 * 1024 * 1024:
        return jsonify({"error": "头像文件不能超过 5MB"}), 400

    os.makedirs(_about_assets_dir(), exist_ok=True)
    filename = f"about_lead_{uuid.uuid4().hex}{ext}"
    file.save(os.path.join(_about_assets_dir(), filename))

    return jsonify({"avatarUrl": f"/api/about-assets/{filename}"})
