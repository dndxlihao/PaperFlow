import os
import re
import json
import uuid
import threading
from datetime import datetime, timezone

import pdfplumber
from flask import Blueprint, current_app, g, jsonify, request, send_file
from sqlalchemy import func, or_
from werkzeug.utils import secure_filename

from auth import token_required
from admin_utils import is_admin_user
from models import (
    Paper,
    PaperCardClick,
    PaperComment,
    PaperCommentLike,
    PaperEditRequest,
    PaperRating,
    PaperSourceClick,
    Friendship,
    UserDigest,
    User,
    UserPaper,
    db,
)
from getDoc import crawl_issue_by_pages
from crawl_arxiv import search_arxiv
from crawl_elsevier import search_elsevier
from pdf_download import download_pdf_by_article_with_report
from pdf_retry_service import record_pdf_download_outcome
from summarizer import (
    summarize_paper,
    extract_keywords_and_category,
    normalize_summary_html,
)

papers_bp = Blueprint("papers", __name__, url_prefix="/api")

CATEGORY_OTHER_LABEL = "其他"
CATEGORY_MERGE_THRESHOLD = 10
MENTION_PATTERN = re.compile(r"(?<![\w@])@([A-Za-z0-9_\u4e00-\u9fff\.-]{2,40})")
SUMMARY_SOURCE_PDF = "pdf_full_text"
SUMMARY_SOURCE_COMMUNITY = "community_edit"
SUMMARY_META_PATTERN = re.compile(r"^\s*<!--PF_SUMMARY_META:(\{.*?\})-->\s*", re.DOTALL)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIGURES_ROOT = os.path.abspath(os.path.join(REPO_ROOT, "figures"))
PENDING_EDIT_FIGURES_SUBDIR = "pending_edits"
PENDING_EDIT_FIGURES_DIR = os.path.join(FIGURES_ROOT, PENDING_EDIT_FIGURES_SUBDIR)
EDIT_IMAGE_MIME_TO_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
ALLOWED_EDIT_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_EDIT_IMAGE_BYTES = 8 * 1024 * 1024
USER_UPLOAD_PDF_MAX_BYTES = 60 * 1024 * 1024
USER_UPLOAD_FIGURES_SUBDIR = "user_uploads"
USER_UPLOAD_FIGURES_DIR = os.path.join(FIGURES_ROOT, USER_UPLOAD_FIGURES_SUBDIR)


def _pack_summary_payload(summary_html: str, source=None):
    clean = (summary_html or "").strip()
    if not clean:
        return clean
    if not source:
        return clean
    meta = json.dumps({"source": source}, ensure_ascii=False)
    return f"<!--PF_SUMMARY_META:{meta}-->\n{clean}"


def _public_paper_filter():
    return Paper.is_public_clause()


def _can_view_paper(paper: Paper, user) -> bool:
    if not paper:
        return False
    if (paper.content_origin or "system") != "user_upload":
        return True
    if (paper.creator_review_status or "approved") == "approved":
        return True
    if not user:
        return False
    if is_admin_user(user):
        return True
    return int(getattr(user, "id", 0) or 0) == int(paper.created_by_user_id or 0)


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


def _to_repo_relative(path: str):
    if not path:
        return path
    ap = os.path.abspath(path)
    try:
        rel = os.path.relpath(ap, REPO_ROOT)
    except Exception:
        return ap
    return rel if not rel.startswith("..") else ap


def _strip_html_to_plain_text(value: str):
    if not value:
        return ""
    text = str(value)
    text = text.replace("&nbsp;", " ").replace("&#160;", " ").replace("　", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _resolve_pdf_path(article_number: str, paper_pdf_path: str | None, pdf_dir: str):
    candidates = []
    if article_number:
        candidates.append(os.path.join(pdf_dir, f"{article_number}.pdf"))
        candidates.append(os.path.join(REPO_ROOT, "backend", "docs", f"{article_number}.pdf"))

    if paper_pdf_path:
        if os.path.isabs(paper_pdf_path):
            candidates.append(paper_pdf_path)
        else:
            candidates.append(os.path.join(REPO_ROOT, paper_pdf_path))
            candidates.append(os.path.join(REPO_ROOT, "backend", paper_pdf_path))

    seen = set()
    for path in candidates:
        ap = os.path.abspath(path)
        if ap in seen:
            continue
        seen.add(ap)
        if os.path.exists(ap):
            return ap
    return None


def _extract_text_from_pdf(pdf_path: str):
    chunks = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            txt = page.extract_text()
            if txt:
                chunks.append(txt)
    return "\n".join(chunks)


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
    return EDIT_IMAGE_MIME_TO_EXT.get(mime, "")


def _source_url_from_payload(data: dict):
    source_url = (
        (data.get("sourceUrl") or data.get("source_url") or data.get("sourceURL") or "").strip()
        if isinstance(data, dict) else ""
    )
    if source_url:
        return source_url

    doi = ((data.get("doi") if isinstance(data, dict) else "") or "").strip()
    pii = ((data.get("pii") if isinstance(data, dict) else "") or "").strip()
    if pii:
        return f"https://www.sciencedirect.com/science/article/pii/{pii}"
    if doi:
        return f"https://doi.org/{doi}"
    return ""


def _query_bool_arg(name: str, default: bool | None = False) -> bool | None:
    raw = request.args.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _query_int_arg(name: str, default: int | None = None) -> int | None:
    raw = request.args.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def _save_pending_edit_image(file_storage, article_number: str, user_id: int):
    ext = _resolve_image_extension(file_storage)
    if ext not in ALLOWED_EDIT_IMAGE_EXTENSIONS:
        raise ValueError("仅支持 png/jpg/jpeg/gif/webp 图片")

    file_storage.stream.seek(0, os.SEEK_END)
    size_bytes = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size_bytes > MAX_EDIT_IMAGE_BYTES:
        raise ValueError("图片文件不能超过 8MB")

    os.makedirs(PENDING_EDIT_FIGURES_DIR, exist_ok=True)
    safe_article = re.sub(r"[^A-Za-z0-9._-]+", "_", (article_number or "paper"))[:80]
    filename = f"edit_{safe_article}_{user_id}_{uuid.uuid4().hex[:10]}{ext}"
    abs_path = os.path.join(PENDING_EDIT_FIGURES_DIR, filename)
    file_storage.save(abs_path)
    rel_path = f"{PENDING_EDIT_FIGURES_SUBDIR}/{filename}"
    return rel_path


def _resolve_figure_abs_path(relative_path: str):
    if not relative_path:
        return None
    rel = str(relative_path).replace("\\", "/").lstrip("/")
    abs_path = os.path.abspath(os.path.join(FIGURES_ROOT, rel))
    figures_root = os.path.abspath(FIGURES_ROOT)
    if not (abs_path == figures_root or abs_path.startswith(figures_root + os.sep)):
        return None
    return abs_path


def _cleanup_pending_edit_figure(relative_path: str):
    if not relative_path:
        return
    clean = str(relative_path).replace("\\", "/").lstrip("/")
    if not clean.startswith(f"{PENDING_EDIT_FIGURES_SUBDIR}/"):
        return
    abs_path = _resolve_figure_abs_path(clean)
    if abs_path and os.path.exists(abs_path):
        try:
            os.remove(abs_path)
        except OSError:
            pass


def _get_aggregated_categories(min_count=CATEGORY_MERGE_THRESHOLD):
    results = db.session.query(
        Paper.category, func.count(Paper.id)
    ).filter(
        Paper.category.isnot(None),
        _public_paper_filter(),
    ).group_by(Paper.category).all()

    other_count = 0
    merged_names = []
    categories = []

    for cat, cnt in results:
        if not cat:
            continue
        if cat == CATEGORY_OTHER_LABEL:
            other_count += cnt
        elif cnt < min_count:
            other_count += cnt
            merged_names.append(cat)
        else:
            categories.append({"name": cat, "count": cnt})

    if other_count:
        categories.append({"name": CATEGORY_OTHER_LABEL, "count": other_count})

    categories.sort(key=lambda x: x["count"], reverse=True)
    return categories, merged_names


def _comment_author_payload(user):
    if not user:
        return None
    return {
        "id": user.id,
        "username": user.username,
        "displayName": user.display_name or user.username,
        "avatarUrl": user.avatar_url,
    }


def _comment_payload(comment, like_count_map=None, liked_comment_ids=None, current_user_id=None):
    like_count_map = like_count_map or {}
    liked_comment_ids = liked_comment_ids or set()
    return {
        "id": comment.id,
        "paperId": comment.paper_id,
        "parentId": comment.parent_id,
        "content": comment.content,
        "author": _comment_author_payload(comment.author),
        "likeCount": int(like_count_map.get(comment.id, 0)),
        "likedByMe": comment.id in liked_comment_ids,
        "isMine": bool(current_user_id and comment.user_id == current_user_id),
        "createdAt": comment.created_at.isoformat() if comment.created_at else None,
        "updatedAt": comment.updated_at.isoformat() if comment.updated_at else None,
        "replies": [],
    }


def _build_comment_tree(
    comments,
    like_count_map=None,
    liked_comment_ids=None,
    current_user_id=None,
    root_ids_order=None,
):
    like_count_map = like_count_map or {}
    liked_comment_ids = liked_comment_ids or set()

    payload_map = {}
    roots = []
    for comment in comments:
        payload_map[comment.id] = _comment_payload(
            comment,
            like_count_map,
            liked_comment_ids,
            current_user_id=current_user_id,
        )

    for comment in comments:
        item = payload_map[comment.id]
        if comment.parent_id and comment.parent_id in payload_map:
            payload_map[comment.parent_id]["replies"].append(item)
        else:
            roots.append(item)

    if root_ids_order:
        ordered = [payload_map[rid] for rid in root_ids_order if rid in payload_map]
        ordered_ids = {item["id"] for item in ordered}
        extras = [item for item in roots if item["id"] not in ordered_ids]
        roots = ordered + extras

    return roots


def _create_comment_notification(recipient_user_id, subject, content, article_number=None, keywords=None):
    now = datetime.now(timezone.utc)
    msg = UserDigest(
        user_id=recipient_user_id,
        period_start=now,
        period_end=now,
        subject=subject[:200],
        content=content[:4000],
        read_count=0,
        source_click_count=0,
        is_read=False,
    )
    if keywords:
        msg.keywords = keywords[:8]
    if article_number:
        msg.rec_article_numbers = [article_number]
    db.session.add(msg)


def _extract_mentioned_users(content: str):
    tokens = {token.strip() for token in MENTION_PATTERN.findall(content or "") if token.strip()}
    if not tokens:
        return []

    users = User.query.filter(
        or_(
            User.username.in_(tokens),
            User.display_name.in_(tokens),
        )
    ).all()

    matched = []
    for user in users:
        uname = (user.username or "").strip()
        dname = (user.display_name or "").strip()
        if uname in tokens or dname in tokens:
            matched.append(user)
    return matched


def _get_friend_user_ids(user_id: int):
    rows = Friendship.query.filter(
        Friendship.status == "accepted",
        or_(
            Friendship.user_id == user_id,
            Friendship.friend_id == user_id,
        ),
    ).all()
    friend_ids = set()
    for row in rows:
        if row.user_id == user_id:
            friend_ids.add(row.friend_id)
        elif row.friend_id == user_id:
            friend_ids.add(row.user_id)
    return friend_ids


def _validate_mention_users(content: str, actor_user_id: int):
    mentioned_users = _extract_mentioned_users(content)
    if not mentioned_users:
        return [], None

    friend_ids = _get_friend_user_ids(actor_user_id)
    blocked = [u for u in mentioned_users if u.id not in friend_ids and u.id != actor_user_id]
    if blocked:
        blocked_names = [u.display_name or u.username for u in blocked][:3]
        return mentioned_users, f"仅可 @ 好友，以下用户不是你的好友：{', '.join(blocked_names)}"
    return mentioned_users, None


def _sanitize_multiline_text(value, max_len=12000):
    text = (value or "")
    text = re.sub(r"\r\n?", "\n", str(text)).strip()
    if len(text) > max_len:
        text = text[:max_len]
    return text


def _parse_bool_text(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def _parse_person_list(raw_value):
    raw = (raw_value or "").strip()
    if not raw:
        return []
    chunks = re.split(r"[,;\n，；、]+", raw)
    out = []
    seen = set()
    for item in chunks:
        name = item.strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out[:40]


def _parse_keywords_list(raw_value):
    raw = (raw_value or "").strip()
    if not raw:
        return []
    chunks = re.split(r"[,;\n，；、]+", raw)
    out = []
    seen = set()
    for item in chunks:
        kw = item.strip()
        if not kw:
            continue
        key = kw.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(kw)
    return out[:12]


def _make_user_upload_article_number():
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"ugc_{ts}_{uuid.uuid4().hex[:8]}"


def _save_uploaded_pdf(file_storage, article_number: str, pdf_dir: str):
    if file_storage is None or not file_storage.filename:
        raise ValueError("请上传 PDF 文件")

    filename = secure_filename(file_storage.filename or "")
    ext = os.path.splitext(filename)[1].lower()
    if ext and ext != ".pdf":
        raise ValueError("仅支持 PDF 文件")

    # Validate size first.
    file_storage.stream.seek(0, os.SEEK_END)
    size_bytes = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size_bytes <= 0:
        raise ValueError("上传的 PDF 文件为空")
    if size_bytes > USER_UPLOAD_PDF_MAX_BYTES:
        raise ValueError("PDF 文件不能超过 60MB")

    os.makedirs(pdf_dir, exist_ok=True)
    abs_path = os.path.abspath(os.path.join(pdf_dir, f"{article_number}.pdf"))
    file_storage.save(abs_path)

    # Quick signature check.
    try:
        with open(abs_path, "rb") as f:
            header = f.read(4)
        if header != b"%PDF":
            os.remove(abs_path)
            raise ValueError("文件格式校验失败，请上传有效的 PDF")
    except ValueError:
        raise
    except Exception:
        if os.path.exists(abs_path):
            try:
                os.remove(abs_path)
            except OSError:
                pass
        raise ValueError("PDF 保存失败，请重试")

    return abs_path


def _process_user_uploaded_card(app, paper_id: int, article_number: str):
    with app.app_context():
        paper = db.session.get(Paper, int(paper_id))
        if not paper:
            return

        pdf_dir = app.config["PDF_DIR"]
        try:
            paper.processing_status = "processing"
            paper.processing_error = None
            db.session.commit()

            pdf_path = _resolve_pdf_path(article_number, paper.pdf_path, pdf_dir)
            if not pdf_path:
                raise ValueError("未找到已上传的 PDF 文件")

            full_text = _extract_text_from_pdf(pdf_path)
            if not full_text.strip():
                raise ValueError("PDF 文本提取为空，请检查文件是否可复制文本")

            summary = summarize_paper(
                title=paper.title or "",
                abstract=paper.abstract or "",
                full_text=full_text,
            )
            summary_html = normalize_summary_html(summary)
            paper.summary = _pack_summary_payload(summary_html, SUMMARY_SOURCE_PDF)
            paper.summary_generated_at = datetime.now(timezone.utc)
            paper.pdf_path = _to_repo_relative(pdf_path)

            if not paper.keywords_json or not paper.category:
                try:
                    info = extract_keywords_and_category(paper.title or "", paper.abstract or "")
                    if info.get("keywords"):
                        paper.keywords = info.get("keywords", [])
                    if info.get("category"):
                        paper.category = info.get("category") or "其他"
                except Exception:
                    pass

            # Extract first representative figure + explanation.
            try:
                from extract_figures import extract_best_figure, generate_figure_explanation
                from summarizer import get_client

                os.makedirs(USER_UPLOAD_FIGURES_DIR, exist_ok=True)
                figure_rel = f"{USER_UPLOAD_FIGURES_SUBDIR}/{article_number}.png"
                figure_abs = os.path.join(USER_UPLOAD_FIGURES_DIR, f"{article_number}.png")

                found, caption = extract_best_figure(pdf_path, figure_abs)
                if found:
                    paper.figure_path = figure_rel
                    try:
                        client = get_client()
                        model = app.config.get("DEEPSEEK_MODEL")
                        explanation = generate_figure_explanation(
                            client,
                            model,
                            paper.title or "",
                            paper.abstract or "",
                            caption,
                        )
                        if explanation:
                            paper.figure_explanation = normalize_summary_html(explanation)
                    except Exception:
                        # Keep the extracted figure even if explanation generation fails.
                        pass
            except Exception:
                # Keep summary generation success; figure extraction is best-effort.
                pass

            paper.processing_status = "ready"
            paper.processing_error = None
            db.session.commit()
        except Exception as e:
            paper.processing_status = "failed"
            paper.processing_error = str(e)[:2000]
            db.session.commit()


def _start_user_uploaded_card_worker(paper_id: int, article_number: str):
    worker = threading.Thread(
        target=_process_user_uploaded_card,
        args=(current_app._get_current_object(), int(paper_id), article_number),
        daemon=True,
    )
    worker.start()


def _resolve_paper_edit_request_type(has_summary, has_figure_text, has_figure_path):
    if not (has_summary or has_figure_text or has_figure_path):
        return "annotation"
    if has_summary and (has_figure_text or has_figure_path):
        return "mixed"
    if has_summary:
        return "summary"
    return "figure"


@papers_bp.route("/comments/mentionable-friends", methods=["GET"])
@token_required
def list_mentionable_friends():
    friend_ids = _get_friend_user_ids(g.current_user.id)
    if not friend_ids:
        return jsonify({"items": []})

    users = (
        User.query
        .filter(User.id.in_(friend_ids))
        .order_by(User.username.asc(), User.id.asc())
        .all()
    )
    items = [
        _comment_author_payload(user)
        for user in users
        if user
    ]
    return jsonify({"items": items})


# ─── IEEE crawl (existing, kept public) ─────────────────────────────────
@papers_bp.route("/ieee", methods=["GET"])
def get_ieee():
    punumber = request.args.get("punumber")
    isnumber = request.args.get("isnumber")
    if not punumber or not isnumber:
        return jsonify({"error": "Missing required parameters: punumber, isnumber"}), 400

    length = 25
    if "len" in request.args:
        try:
            length = int(request.args.get("len"))
        except ValueError:
            return jsonify({"error": "Invalid parameter: len must be an integer"}), 400

    sortType = request.args.get("sortType") or "paper-citations"

    try:
        start_page = int(request.args.get("start_page", 1))
        end_page = int(request.args.get("end_page", start_page))
    except ValueError:
        return jsonify({"error": "Invalid parameter: start_page/end_page must be integers"}), 400

    if start_page < 1 or end_page < 1 or end_page < start_page:
        return jsonify({"error": "Invalid page range"}), 400

    try:
        items = crawl_issue_by_pages(
            punumber=punumber,
            isnumber=isnumber,
            start_page=start_page,
            end_page=end_page,
            rows_per_page=length,
            sortType=sortType,
            download_pdf=False,
            attach_text=False,
        )
        return jsonify(items)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── PDF download (multi-source) ────────────────────────────────────────
@papers_bp.route("/pdf/<path:code>", methods=["GET"])
def get_pdf(code):
    pdf_dir = current_app.config["PDF_DIR"]
    file_path = os.path.join(pdf_dir, f"{code}.pdf")
    paper = Paper.query.filter_by(article_number=code).first()
    source_url = paper.source_url if paper else ""
    elsevier_api_key = current_app.config.get("ELSEVIER_API_KEY", "")
    force_browser = _query_bool_arg("browser", False)
    use_profile = _query_bool_arg("profile", False)
    headless = _query_bool_arg("headless", True)
    manual_wait = _query_int_arg("manual_wait", None)
    interactive_verify = _query_bool_arg("interactive_verify", None)
    verify_wait = _query_int_arg("verify_wait", None)
    attach_debugger = _query_bool_arg(
        "attach",
        bool(current_app.config.get("ELSEVIER_SELENIUM_ATTACH_DEBUGGER", False)),
    )
    debugger_address = (
        (request.args.get("debugger") or "").strip()
        or current_app.config.get("ELSEVIER_CHROME_DEBUGGER_ADDRESS")
    )

    if not os.path.exists(file_path):
        try:
            downloaded, report = download_pdf_by_article_with_report(
                article_number=code,
                out_dir=pdf_dir,
                source_url=source_url or "",
                elsevier_api_key=elsevier_api_key,
                elsevier_selenium_fallback=True if (force_browser or attach_debugger) else None,
                elsevier_selenium_use_profile=True if use_profile else None,
                elsevier_selenium_headless=headless if force_browser else None,
                elsevier_selenium_manual_wait_seconds=manual_wait if force_browser else None,
                elsevier_selenium_attach_debugger=attach_debugger,
                elsevier_selenium_debugger_address=debugger_address,
                elsevier_selenium_allow_new_browser_on_attach_fail=current_app.config.get(
                    "ELSEVIER_SELENIUM_ALLOW_NEW_BROWSER_ON_ATTACH_FAIL"
                ),
                elsevier_selenium_interactive_verify=interactive_verify,
                elsevier_selenium_verify_wait_seconds=verify_wait,
            )
            record_pdf_download_outcome(
                app=current_app,
                article_number=code,
                source_url=source_url or "",
                report=report,
                paper_id=paper.id if paper else None,
                enqueue_on_fail=True,
            )
            if downloaded and os.path.exists(downloaded):
                file_path = downloaded
                if paper and (not paper.pdf_path):
                    paper.pdf_path = _to_repo_relative(downloaded)
                    db.session.commit()
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    if not os.path.exists(file_path):
        return jsonify({"error": "PDF not found"}), 404

    return send_file(file_path, as_attachment=True)


@papers_bp.route("/papers/<article_number>/source-click", methods=["POST"])
@token_required
def track_source_click(article_number):
    paper = Paper.query.filter_by(article_number=article_number).first()
    if not paper:
        return jsonify({"error": "论文未找到"}), 404
    if not _can_view_paper(paper, g.current_user):
        return jsonify({"error": "该投稿正在审核中，暂不可查看"}), 403

    data = request.get_json(silent=True) or {}
    context = (data.get("context") or "").strip()[:50] or None

    row = PaperSourceClick(
        user_id=g.current_user.id,
        paper_id=paper.id,
        context=context,
    )
    db.session.add(row)
    db.session.commit()
    return jsonify({"ok": True})


@papers_bp.route("/papers/<article_number>/card-click", methods=["POST"])
@token_required
def track_card_click(article_number):
    paper = Paper.query.filter_by(article_number=article_number).first()
    if not paper:
        return jsonify({"error": "论文未找到"}), 404
    if not _can_view_paper(paper, g.current_user):
        return jsonify({"error": "该投稿正在审核中，暂不可查看"}), 403

    data = request.get_json(silent=True) or {}
    context = (data.get("context") or "").strip()[:50] or None

    row = PaperCardClick(
        user_id=g.current_user.id,
        paper_id=paper.id,
        context=context,
    )
    db.session.add(row)
    db.session.commit()
    return jsonify({"ok": True})


# ─── Import paper from IEEE into system DB ──────────────────────────────
@papers_bp.route("/papers/import", methods=["POST"])
@token_required
def import_paper():
    """Import a paper from IEEE data into the paper database."""
    data = request.get_json(silent=True) or {}
    article_number = str(data.get("articleNumber", "")).strip()
    if not article_number:
        return jsonify({"error": "articleNumber is required"}), 400

    # Check if paper already exists
    paper = Paper.query.filter_by(article_number=article_number).first()
    if not paper:
        paper = Paper(
            article_number=article_number,
            title=data.get("title", ""),
            abstract=data.get("abstract", ""),
            publication_date=data.get("publicationDate", ""),
            publication_title=data.get("publicationTitle", ""),
            download_count=data.get("downloadCount", 0),
            source_url=_source_url_from_payload(data),
        )
        if data.get("authors"):
            paper.authors = data["authors"]
        db.session.add(paper)
        db.session.commit()

        # Auto-generate keywords, category, and summary
        _auto_enrich_paper(paper)
    else:
        src = _source_url_from_payload(data)
        if src and not paper.source_url:
            paper.source_url = src
            db.session.commit()

    return jsonify(paper.to_dict()), 201


def _auto_enrich_paper(paper):
    """Auto-generate keywords, category, and summary for a paper."""
    try:
        if paper.abstract and (not paper.keywords_json or not paper.category):
            info = extract_keywords_and_category(paper.title or "", paper.abstract)
            paper.keywords = info.get("keywords", [])
            paper.category = info.get("category", "其他")
            db.session.commit()
    except Exception as e:
        current_app.logger.warning(f"Auto keywords/category failed for {paper.article_number}: {e}")

    # Summary is intentionally NOT auto-generated from abstract.
    # It must come from PDF full text via /api/papers/<article_number>/summary.


@papers_bp.route("/papers/upload-card", methods=["POST"])
@token_required
def upload_paper_card():
    """
    Creator workflow:
      - user uploads a PDF
      - system creates a paper card
      - background worker extracts figure + full-text summary
    """
    content_type = (request.content_type or "").lower()
    if not content_type.startswith("multipart/form-data"):
        return jsonify({"error": "请使用 multipart/form-data 上传 PDF"}), 400

    pdf_file = request.files.get("pdf")
    title = _sanitize_multiline_text(request.form.get("title"), max_len=500)
    abstract = _sanitize_multiline_text(request.form.get("abstract"), max_len=8000)
    publication_title = _sanitize_multiline_text(request.form.get("publicationTitle"), max_len=300) or "用户创作投稿"
    publication_date = _sanitize_multiline_text(request.form.get("publicationDate"), max_len=100)
    source_url = _sanitize_multiline_text(request.form.get("sourceUrl"), max_len=500)
    category = _sanitize_multiline_text(request.form.get("category"), max_len=100)
    add_to_library = _parse_bool_text(request.form.get("addToLibrary"), default=True)
    authors = _parse_person_list(request.form.get("authors"))
    keywords = _parse_keywords_list(request.form.get("keywords"))

    # Fallback title from filename when user leaves it empty.
    if not title and pdf_file and pdf_file.filename:
        title = os.path.splitext(secure_filename(pdf_file.filename))[0][:500]
    if not title:
        return jsonify({"error": "请填写论文标题"}), 400
    if not authors:
        return jsonify({"error": "请至少填写一位作者"}), 400

    article_number = ""
    for _ in range(8):
        candidate = _make_user_upload_article_number()
        if not Paper.query.filter_by(article_number=candidate).first():
            article_number = candidate
            break
    if not article_number:
        return jsonify({"error": "生成卡片编号失败，请重试"}), 500

    pdf_dir = current_app.config["PDF_DIR"]
    try:
        saved_pdf_abs = _save_uploaded_pdf(pdf_file, article_number=article_number, pdf_dir=pdf_dir)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "PDF 上传失败，请稍后重试"}), 500

    paper = Paper(
        article_number=article_number,
        title=title,
        abstract=abstract,
        publication_date=publication_date,
        publication_title=publication_title,
        source_url=source_url,
        pdf_path=_to_repo_relative(saved_pdf_abs),
        content_origin="user_upload",
        created_by_user_id=g.current_user.id,
        processing_status="pending",
        processing_error=None,
        creator_review_status="pending",
        creator_review_note=None,
        creator_reviewed_by=None,
        creator_reviewed_at=None,
    )
    if authors:
        paper.authors = authors
    if keywords:
        paper.keywords = keywords
    if category:
        paper.category = category

    db.session.add(paper)
    db.session.flush()

    if add_to_library:
        exists = UserPaper.query.filter_by(user_id=g.current_user.id, paper_id=paper.id).first()
        if not exists:
            db.session.add(UserPaper(user_id=g.current_user.id, paper_id=paper.id, notes=""))

    db.session.commit()
    _start_user_uploaded_card_worker(paper.id, article_number)

    return jsonify({
        "message": "上传成功，后台正在生成卡片内容。生成完成后将进入管理员审核。",
        "paper": paper.to_dict(),
    }), 201


@papers_bp.route("/papers/my-uploads", methods=["GET"])
@token_required
def list_my_uploaded_cards():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)

    q = (
        Paper.query
        .filter_by(created_by_user_id=g.current_user.id, content_origin="user_upload")
        .order_by(Paper.created_at.desc())
    )
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        "items": [p.to_dict() for p in pagination.items],
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
    })


@papers_bp.route("/papers/<article_number>/creator-publication", methods=["PATCH"])
@token_required
def update_creator_publication(article_number):
    paper = Paper.query.filter_by(article_number=article_number, content_origin="user_upload").first()
    if not paper:
        return jsonify({"error": "投稿卡片不存在"}), 404

    is_admin = is_admin_user(g.current_user)
    is_owner = int(paper.created_by_user_id or 0) == int(g.current_user.id or 0)
    if not (is_admin or is_owner):
        return jsonify({"error": "仅投稿作者或管理员可修改期刊信息"}), 403

    data = request.get_json(silent=True) or {}
    publication_title = _sanitize_multiline_text(data.get("publicationTitle"), max_len=300)
    publication_date = _sanitize_multiline_text(data.get("publicationDate"), max_len=100)
    source_url = _sanitize_multiline_text(data.get("sourceUrl"), max_len=500)

    if not any([publication_title, publication_date, source_url]):
        return jsonify({"error": "请至少填写一个需要更新的字段"}), 400

    if publication_title:
        paper.publication_title = publication_title
    if publication_date:
        paper.publication_date = publication_date
    if source_url:
        paper.source_url = source_url

    # Creator updates after acceptance should be re-reviewed before public listing.
    if is_owner and not is_admin:
        paper.creator_review_status = "pending"
        paper.creator_review_note = "作者更新了期刊信息，等待管理员复审"
        paper.creator_reviewed_by = None
        paper.creator_reviewed_at = None

    db.session.commit()
    return jsonify({
        "message": "期刊信息已更新并提交复审",
        "paper": paper.to_dict(),
    })


@papers_bp.route("/papers/<article_number>/creator-resubmit", methods=["POST"])
@token_required
def resubmit_creator_paper(article_number):
    paper = Paper.query.filter_by(article_number=article_number, content_origin="user_upload").first()
    if not paper:
        return jsonify({"error": "投稿卡片不存在"}), 404
    if int(paper.created_by_user_id or 0) != int(g.current_user.id or 0):
        return jsonify({"error": "仅投稿作者可重新提交审核"}), 403
    if (paper.creator_review_status or "approved") != "rejected":
        return jsonify({"error": "仅驳回状态可重新提交"}), 400

    paper.creator_review_status = "pending"
    paper.creator_review_note = "作者已重新提交审核"
    paper.creator_reviewed_by = None
    paper.creator_reviewed_at = None
    db.session.commit()
    return jsonify({
        "message": "已重新提交审核",
        "paper": paper.to_dict(),
    })


@papers_bp.route("/papers/<article_number>/creator-withdraw", methods=["POST"])
@token_required
def withdraw_creator_paper(article_number):
    paper = Paper.query.filter_by(article_number=article_number, content_origin="user_upload").first()
    if not paper:
        return jsonify({"error": "投稿卡片不存在"}), 404
    if int(paper.created_by_user_id or 0) != int(g.current_user.id or 0):
        return jsonify({"error": "仅投稿作者可撤回"}), 403
    if (paper.creator_review_status or "approved") != "pending":
        return jsonify({"error": "仅待审核状态可撤回"}), 400

    paper.creator_review_status = "withdrawn"
    paper.creator_review_note = "作者已撤回投稿"
    paper.creator_reviewed_by = None
    paper.creator_reviewed_at = None
    db.session.commit()
    return jsonify({
        "message": "已撤回投稿",
        "paper": paper.to_dict(),
    })


# ─── User's paper library ──────────────────────────────────────────────
@papers_bp.route("/library", methods=["GET"])
@token_required
def list_library():
    """List papers in current user's library."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    per_page = min(per_page, 100)

    q = UserPaper.query.filter_by(user_id=g.current_user.id).order_by(UserPaper.added_at.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    items = [up.to_dict() for up in pagination.items]

    return jsonify({
        "items": items,
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
    })


@papers_bp.route("/library", methods=["POST"])
@token_required
def add_to_library():
    """Add a paper to the user's personal library."""
    data = request.get_json(silent=True) or {}
    article_number = str(data.get("articleNumber", "")).strip()
    if not article_number:
        return jsonify({"error": "articleNumber is required"}), 400

    paper = Paper.query.filter_by(article_number=article_number).first()
    if not paper:
        # Auto-import paper
        paper = Paper(
            article_number=article_number,
            title=data.get("title", ""),
            abstract=data.get("abstract", ""),
            publication_date=data.get("publicationDate", ""),
            publication_title=data.get("publicationTitle", ""),
            download_count=data.get("downloadCount", 0),
            source_url=_source_url_from_payload(data),
        )
        if data.get("authors"):
            paper.authors = data["authors"]
        db.session.add(paper)
        db.session.flush()
    else:
        src = _source_url_from_payload(data)
        if src and not paper.source_url:
            paper.source_url = src

    up = UserPaper(
        user_id=g.current_user.id,
        paper_id=paper.id,
        notes=data.get("notes", ""),
    )
    db.session.add(up)
    db.session.commit()
    return jsonify(up.to_dict()), 201


@papers_bp.route("/library/<int:user_paper_id>", methods=["DELETE"])
@token_required
def remove_from_library(user_paper_id):
    up = UserPaper.query.filter_by(id=user_paper_id, user_id=g.current_user.id).first()
    if not up:
        return jsonify({"error": "未找到该论文"}), 404
    db.session.delete(up)
    db.session.commit()
    return jsonify({"message": "已移除"})


@papers_bp.route("/library/<int:user_paper_id>", methods=["PATCH"])
@token_required
def update_library_paper(user_paper_id):
    up = UserPaper.query.filter_by(id=user_paper_id, user_id=g.current_user.id).first()
    if not up:
        return jsonify({"error": "未找到该论文"}), 404

    data = request.get_json(silent=True) or {}
    if "notes" in data:
        up.notes = data["notes"]
    if "isFavorite" in data:
        up.is_favorite = bool(data["isFavorite"])
    db.session.commit()
    return jsonify(up.to_dict())


# ─── Paper summary ─────────────────────────────────────────────────────
@papers_bp.route("/papers/<article_number>", methods=["GET"])
@token_required
def get_paper_detail(article_number):
    paper = Paper.query.filter_by(article_number=article_number).first()
    if not paper:
        return jsonify({"error": "论文未找到"}), 404
    if not _can_view_paper(paper, g.current_user):
        return jsonify({"error": "该投稿正在审核中，暂不可查看"}), 403
    return jsonify(paper.to_dict())


@papers_bp.route("/papers/<article_number>/summary", methods=["GET"])
@token_required
def get_summary(article_number):
    paper = Paper.query.filter_by(article_number=article_number).first()
    if not paper:
        return jsonify({"error": "论文未找到"}), 404
    if not _can_view_paper(paper, g.current_user):
        return jsonify({"error": "该投稿正在审核中，暂不可查看"}), 403

    if paper.summary:
        clean_summary, summary_source = _unpack_summary_payload(paper.summary)
        return jsonify({
            "articleNumber": paper.article_number,
            "title": paper.title,
            "summary": normalize_summary_html(clean_summary),
            "summarySource": summary_source or "unknown",
            "generatedAt": paper.summary_generated_at.isoformat() if paper.summary_generated_at else None,
        })

    return jsonify({"error": "该论文尚未生成总结，请先调用 POST 生成"}), 404


@papers_bp.route("/papers/<article_number>/summary", methods=["POST"])
@token_required
def generate_summary(article_number):
    """Download PDF (if needed), extract text, call DeepSeek to summarize."""
    paper = Paper.query.filter_by(article_number=article_number).first()
    if not paper:
        return jsonify({"error": "论文未找到，请先导入"}), 404
    if not _can_view_paper(paper, g.current_user):
        return jsonify({"error": "该投稿正在审核中，暂不可操作"}), 403

    # Download PDF if not available
    pdf_dir = current_app.config["PDF_DIR"]
    pdf_path = _resolve_pdf_path(article_number, paper.pdf_path, pdf_dir)

    if not pdf_path:
        try:
            downloaded, report = download_pdf_by_article_with_report(
                article_number=article_number,
                out_dir=pdf_dir,
                source_url=paper.source_url or "",
                elsevier_api_key=current_app.config.get("ELSEVIER_API_KEY", ""),
                elsevier_selenium_attach_debugger=current_app.config.get("ELSEVIER_SELENIUM_ATTACH_DEBUGGER"),
                elsevier_selenium_debugger_address=current_app.config.get("ELSEVIER_CHROME_DEBUGGER_ADDRESS"),
                elsevier_selenium_allow_new_browser_on_attach_fail=current_app.config.get(
                    "ELSEVIER_SELENIUM_ALLOW_NEW_BROWSER_ON_ATTACH_FAIL"
                ),
            )
            record_pdf_download_outcome(
                app=current_app,
                article_number=article_number,
                source_url=paper.source_url or "",
                report=report,
                paper_id=paper.id,
                enqueue_on_fail=True,
            )
            if downloaded and os.path.exists(downloaded):
                paper.pdf_path = _to_repo_relative(downloaded)
        except Exception as e:
            current_app.logger.warning(f"PDF download failed for {article_number}: {e}")
        pdf_path = _resolve_pdf_path(article_number, paper.pdf_path, pdf_dir)

    if not pdf_path:
        return jsonify({
            "error": "未能获取 PDF 全文，本次已停止仅摘要总结。请稍后重试，或确认该论文 PDF 可下载。",
            "needFullText": True,
        }), 422

    try:
        full_text = _extract_text_from_pdf(pdf_path)
    except Exception as e:
        current_app.logger.warning(f"PDF text extraction failed for {article_number}: {e}")
        full_text = ""

    if not full_text.strip():
        return jsonify({
            "error": "PDF 已找到，但未能提取到有效全文文本，暂不生成摘要总结。",
            "needFullText": True,
        }), 422

    try:
        summary = summarize_paper(
            title=paper.title or "",
            abstract=paper.abstract or "",
            full_text=full_text,
        )
    except Exception as e:
        return jsonify({"error": f"LLM总结生成失败: {e}"}), 500

    summary_html = normalize_summary_html(summary)
    paper.summary = _pack_summary_payload(summary_html, SUMMARY_SOURCE_PDF)
    paper.summary_generated_at = datetime.now(timezone.utc)
    paper.pdf_path = _to_repo_relative(pdf_path)

    # Also extract keywords/category if not already set
    if not paper.keywords_json or not paper.category:
        try:
            info = extract_keywords_and_category(paper.title or "", paper.abstract or "")
            paper.keywords = info.get("keywords", [])
            paper.category = info.get("category", "其他")
        except Exception:
            pass

    db.session.commit()

    return jsonify({
        "articleNumber": paper.article_number,
        "title": paper.title,
        "summary": summary_html,
        "summarySource": SUMMARY_SOURCE_PDF,
        "generatedAt": paper.summary_generated_at.isoformat(),
    })


@papers_bp.route("/papers/<article_number>/edit-requests", methods=["GET"])
@token_required
def list_paper_edit_requests(article_number):
    paper = Paper.query.filter_by(article_number=article_number).first()
    if not paper:
        return jsonify({"error": "论文未找到"}), 404
    if not _can_view_paper(paper, g.current_user):
        return jsonify({"error": "该投稿正在审核中，暂不可查看"}), 403

    status = (request.args.get("status") or "").strip().lower()
    limit = min(request.args.get("limit", 50, type=int), 120)

    q = PaperEditRequest.query.filter_by(paper_id=paper.id)
    if status in {"pending", "approved", "rejected", "withdrawn"}:
        q = q.filter_by(status=status)

    rows = (
        q.order_by(PaperEditRequest.created_at.desc(), PaperEditRequest.id.desc())
        .limit(limit)
        .all()
    )
    return jsonify({
        "articleNumber": paper.article_number,
        "paperTitle": paper.title,
        "items": [row.to_dict() for row in rows],
    })


@papers_bp.route("/papers/<article_number>/edit-requests/<int:req_id>", methods=["DELETE"])
@token_required
def withdraw_paper_edit_request(article_number, req_id):
    paper = Paper.query.filter_by(article_number=article_number).first()
    if not paper:
        return jsonify({"error": "论文未找到"}), 404
    if not _can_view_paper(paper, g.current_user):
        return jsonify({"error": "该投稿正在审核中，暂不可查看"}), 403

    req = PaperEditRequest.query.filter_by(id=req_id, paper_id=paper.id).first()
    if not req:
        return jsonify({"error": "编辑申请不存在"}), 404

    if req.user_id != g.current_user.id:
        return jsonify({"error": "仅可撤销自己提交的编辑申请"}), 403

    if req.status != "pending":
        return jsonify({"error": "仅可撤销待审核申请"}), 400

    _cleanup_pending_edit_figure(req.proposed_figure_path or "")
    req.status = "withdrawn"

    db.session.commit()
    return jsonify({
        "message": "编辑申请已撤销",
        "item": req.to_dict(),
    })


@papers_bp.route("/papers/<article_number>/edit-requests", methods=["POST"])
@token_required
def create_paper_edit_request(article_number):
    paper = Paper.query.filter_by(article_number=article_number).first()
    if not paper:
        return jsonify({"error": "论文未找到"}), 404
    if not _can_view_paper(paper, g.current_user):
        return jsonify({"error": "该投稿正在审核中，暂不可查看"}), 403

    is_multipart = (request.content_type or "").lower().startswith("multipart/form-data")
    data = request.form if is_multipart else (request.get_json(silent=True) or {})

    reason = _sanitize_multiline_text(data.get("reason"), max_len=2000)
    target_field = _sanitize_multiline_text(data.get("targetField"), max_len=40)
    selected_text = _sanitize_multiline_text(data.get("selectedText"), max_len=2000)
    suggestion_text = _sanitize_multiline_text(data.get("suggestion"), max_len=4000)
    proposed_summary_raw = _sanitize_multiline_text(data.get("summary"), max_len=30000)
    proposed_figure_expl = _sanitize_multiline_text(data.get("figureExplanation"), max_len=12000)
    proposed_figure_path = _sanitize_multiline_text(data.get("figurePath"), max_len=500)

    if is_multipart:
        image_file = request.files.get("figureImage")
        if image_file is not None and image_file.filename:
            try:
                proposed_figure_path = _save_pending_edit_image(
                    image_file,
                    article_number=article_number,
                    user_id=g.current_user.id,
                )
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
            except Exception:
                return jsonify({"error": "图片上传失败，请稍后重试"}), 500
            if not target_field:
                target_field = "figurePath"

    current_summary, _ = _unpack_summary_payload(paper.summary or "")
    current_summary = (current_summary or "").strip()
    current_figure_expl = (paper.figure_explanation or "").strip()
    current_figure_path = (paper.figure_path or "").strip()

    proposed_summary = normalize_summary_html(proposed_summary_raw) if proposed_summary_raw else ""

    changed_summary = bool(proposed_summary) and proposed_summary.strip() != current_summary
    changed_figure_expl = bool(proposed_figure_expl) and proposed_figure_expl != current_figure_expl
    changed_figure_path = bool(proposed_figure_path) and proposed_figure_path != current_figure_path
    has_annotation = bool(suggestion_text)

    # If user mainly submits annotation suggestions, avoid treating formatting-only
    # textarea echoes as a full summary overwrite.
    if changed_summary and has_annotation and (target_field or "").strip() == "summary" and selected_text:
        if _strip_html_to_plain_text(proposed_summary) == _strip_html_to_plain_text(current_summary):
            changed_summary = False

    if changed_figure_expl and has_annotation and (target_field or "").strip() == "figureExplanation" and selected_text:
        if _strip_html_to_plain_text(proposed_figure_expl) == _strip_html_to_plain_text(current_figure_expl):
            changed_figure_expl = False

    if not (changed_summary or changed_figure_expl or changed_figure_path or has_annotation):
        return jsonify({"error": "未检测到有效修改或修改建议，请填写内容后再提交"}), 400

    if not reason and not suggestion_text and not (changed_summary or changed_figure_expl or changed_figure_path):
        return jsonify({"error": "请填写修改建议或补充说明，便于管理员审核"}), 400
    reason_for_review = reason or suggestion_text or "用户提交了卡片内容修订"

    req = PaperEditRequest(
        paper_id=paper.id,
        user_id=g.current_user.id,
        reason=reason_for_review,
        request_type=_resolve_paper_edit_request_type(changed_summary, changed_figure_expl, changed_figure_path),
        target_field=target_field or None,
        selected_text=selected_text or None,
        suggestion_text=suggestion_text or None,
        original_summary=current_summary or None,
        original_figure_explanation=current_figure_expl or None,
        original_figure_path=current_figure_path or None,
        proposed_summary=proposed_summary if changed_summary else None,
        proposed_figure_explanation=proposed_figure_expl if changed_figure_expl else None,
        proposed_figure_path=proposed_figure_path if changed_figure_path else None,
        status="pending",
    )
    db.session.add(req)
    db.session.commit()

    return jsonify({
        "message": "编辑申请已提交，等待管理员审核",
        "item": req.to_dict(),
    }), 201


# ─── All papers (admin-like browse) ────────────────────────────────────
@papers_bp.route("/papers", methods=["GET"])
@token_required
def list_papers():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    per_page = min(per_page, 100)
    keyword = request.args.get("keyword", "").strip()

    is_admin = is_admin_user(g.current_user)
    q = Paper.query
    if not is_admin:
        q = q.filter(
            or_(
                _public_paper_filter(),
                Paper.created_by_user_id == g.current_user.id,
            )
        )
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            Paper.title.ilike(like)
            | Paper.abstract.ilike(like)
            | Paper.article_number.ilike(like)
        )

    q = q.order_by(Paper.created_at.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "items": [p.to_dict() for p in pagination.items],
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
    })


# ─── arXiv search ───────────────────────────────────────────────────────
@papers_bp.route("/arxiv", methods=["GET"])
@token_required
def search_arxiv_api():
    query = request.args.get("query", "").strip()
    category = request.args.get("category", "").strip()
    max_results = request.args.get("max_results", 25, type=int)
    sort_by = request.args.get("sort_by", "submittedDate")

    if not query and not category:
        return jsonify({"error": "请提供 query 或 category 参数"}), 400

    try:
        items = search_arxiv(
            query=query,
            category=category,
            max_results=min(max_results, 100),
            sort_by=sort_by,
        )
        return jsonify(items)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Elsevier search ────────────────────────────────────────────────────
@papers_bp.route("/elsevier", methods=["GET"])
@token_required
def search_elsevier_api():
    query = request.args.get("query", "").strip()
    max_results = request.args.get("max_results", 25, type=int)

    if not query:
        return jsonify({"error": "请提供 query 参数"}), 400

    api_key = current_app.config.get("ELSEVIER_API_KEY", "")

    try:
        items = search_elsevier(
            query=query,
            api_key=api_key,
            max_results=min(max_results, 50),
        )
        return jsonify(items)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── System paper library (all papers with category filtering) ──────────
@papers_bp.route("/system-library", methods=["GET"])
@token_required
def system_library():
    """Browse all papers in the system, with optional category and keyword filters."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    per_page = min(per_page, 100)
    category = request.args.get("category", "").strip()
    keyword = request.args.get("keyword", "").strip()

    q = Paper.query.filter(_public_paper_filter())
    if category:
        _, merged_names = _get_aggregated_categories()
        if category == CATEGORY_OTHER_LABEL:
            other_categories = merged_names + [CATEGORY_OTHER_LABEL]
            q = q.filter(Paper.category.in_(other_categories))
        else:
            q = q.filter(Paper.category == category)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(Paper.title.ilike(like) | Paper.abstract.ilike(like))

    q = q.order_by(Paper.created_at.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "items": [p.to_dict() for p in pagination.items],
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
    })


@papers_bp.route("/categories", methods=["GET"])
@token_required
def list_categories():
    """Get all distinct categories with paper counts."""
    categories, _ = _get_aggregated_categories()
    return jsonify(categories)


# ─── Paper rating ───────────────────────────────────────────────────────
@papers_bp.route("/papers/<article_number>/rate", methods=["POST"])
@token_required
def rate_paper(article_number):
    """Rate a paper (1-5). Updates existing rating if already rated."""
    paper = Paper.query.filter_by(article_number=article_number).first()
    if not paper:
        return jsonify({"error": "论文未找到"}), 404
    if not _can_view_paper(paper, g.current_user):
        return jsonify({"error": "该投稿正在审核中，暂不可查看"}), 403

    data = request.get_json(silent=True) or {}
    score = data.get("score")
    if not score or not isinstance(score, int) or score < 1 or score > 5:
        return jsonify({"error": "评分需为 1-5 的整数"}), 400

    rating = PaperRating.query.filter_by(
        user_id=g.current_user.id, paper_id=paper.id
    ).first()

    if rating:
        rating.score = score
    else:
        rating = PaperRating(
            user_id=g.current_user.id,
            paper_id=paper.id,
            score=score,
        )
        db.session.add(rating)

    db.session.commit()
    return jsonify({
        "score": rating.score,
        "avgRating": paper.avg_rating(),
        "ratingCount": paper.rating_count(),
    })


@papers_bp.route("/papers/<article_number>/rate", methods=["GET"])
@token_required
def get_my_rating(article_number):
    """Get the current user's rating for a paper."""
    paper = Paper.query.filter_by(article_number=article_number).first()
    if not paper:
        return jsonify({"error": "论文未找到"}), 404
    if not _can_view_paper(paper, g.current_user):
        return jsonify({"error": "该投稿正在审核中，暂不可查看"}), 403

    rating = PaperRating.query.filter_by(
        user_id=g.current_user.id, paper_id=paper.id
    ).first()

    return jsonify({
        "myScore": rating.score if rating else None,
        "avgRating": paper.avg_rating(),
        "ratingCount": paper.rating_count(),
    })


@papers_bp.route("/stats", methods=["GET"])
@token_required
def get_stats():
    """Global stats for the dashboard."""
    total_papers = Paper.query.filter(_public_paper_filter()).count()
    summary_count = Paper.query.filter(
        _public_paper_filter(),
        Paper.summary.isnot(None), Paper.summary != ""
    ).count()
    return jsonify({
        "totalPapers": total_papers,
        "summaryCount": summary_count,
    })


# ─── Paper comments ──────────────────────────────────────────────────────
@papers_bp.route("/papers/<article_number>/comments", methods=["GET"])
@token_required
def get_paper_comments(article_number):
    paper = Paper.query.filter_by(article_number=article_number).first()
    if not paper:
        return jsonify({"error": "论文未找到"}), 404
    if not _can_view_paper(paper, g.current_user):
        return jsonify({"error": "该投稿正在审核中，暂不可查看"}), 403

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 8, type=int)
    page = max(1, page)
    per_page = max(1, min(per_page, 20))

    root_q = (
        PaperComment.query
        .filter_by(paper_id=paper.id, parent_id=None)
        .order_by(PaperComment.created_at.desc(), PaperComment.id.desc())
    )
    root_pagination = root_q.paginate(page=page, per_page=per_page, error_out=False)
    root_ids_order = [c.id for c in root_pagination.items]

    all_comments = (
        PaperComment.query
        .filter_by(paper_id=paper.id)
        .order_by(PaperComment.created_at.asc(), PaperComment.id.asc())
        .all()
    )
    total_count = len(all_comments)

    comment_ids = []
    comments = []
    if root_ids_order:
        children_map = {}
        comment_map = {}
        for comment in all_comments:
            comment_map[comment.id] = comment
            children_map.setdefault(comment.parent_id, []).append(comment)

        selected_ids = set()
        stack = list(root_ids_order)
        while stack:
            current_id = stack.pop()
            if current_id in selected_ids:
                continue
            selected_ids.add(current_id)
            for child in children_map.get(current_id, []):
                if child.id not in selected_ids:
                    stack.append(child.id)

        comments = [c for c in all_comments if c.id in selected_ids]
        comment_ids = [c.id for c in comments]

    like_count_map = {}
    liked_comment_ids = set()
    if comment_ids:
        like_rows = (
            db.session.query(PaperCommentLike.comment_id, func.count(PaperCommentLike.id))
            .filter(PaperCommentLike.comment_id.in_(comment_ids))
            .group_by(PaperCommentLike.comment_id)
            .all()
        )
        like_count_map = {cid: cnt for cid, cnt in like_rows}

        liked_rows = (
            PaperCommentLike.query
            .filter(
                PaperCommentLike.comment_id.in_(comment_ids),
                PaperCommentLike.user_id == g.current_user.id,
            )
            .all()
        )
        liked_comment_ids = {row.comment_id for row in liked_rows}

    items = _build_comment_tree(
        comments,
        like_count_map,
        liked_comment_ids,
        current_user_id=g.current_user.id,
        root_ids_order=root_ids_order,
    )
    return jsonify({
        "items": items,
        "totalCount": total_count,
        "rootCount": root_pagination.total,
        "page": root_pagination.page,
        "pages": root_pagination.pages,
        "perPage": per_page,
        "hasMore": root_pagination.page < root_pagination.pages,
    })


@papers_bp.route("/papers/<article_number>/comments", methods=["POST"])
@token_required
def create_paper_comment(article_number):
    paper = Paper.query.filter_by(article_number=article_number).first()
    if not paper:
        return jsonify({"error": "论文未找到"}), 404
    if not _can_view_paper(paper, g.current_user):
        return jsonify({"error": "该投稿正在审核中，暂不可查看"}), 403

    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    parent_id_raw = data.get("parentId")

    if not content:
        return jsonify({"error": "评论内容不能为空"}), 400
    if len(content) > 1500:
        return jsonify({"error": "评论内容不能超过1500字符"}), 400

    mention_users, mention_error = _validate_mention_users(content, g.current_user.id)
    if mention_error:
        return jsonify({"error": mention_error}), 400

    parent_id = None
    if parent_id_raw is not None and str(parent_id_raw).strip() != "":
        try:
            parent_id = int(parent_id_raw)
        except (TypeError, ValueError):
            return jsonify({"error": "parentId 必须为整数"}), 400
        parent = db.session.get(PaperComment, parent_id)
        if not parent or parent.paper_id != paper.id:
            return jsonify({"error": "回复目标评论不存在"}), 404

    comment = PaperComment(
        paper_id=paper.id,
        user_id=g.current_user.id,
        parent_id=parent_id,
        content=content,
    )
    db.session.add(comment)

    actor_name = g.current_user.display_name or g.current_user.username
    paper_title = (paper.title_zh or paper.title or paper.article_number or "论文").strip()
    notified_user_ids = set()

    if parent_id:
        parent = db.session.get(PaperComment, parent_id)
        if parent and parent.user_id != g.current_user.id:
            _create_comment_notification(
                recipient_user_id=parent.user_id,
                subject="你的评论收到了回复",
                content=(
                    f"{actor_name} 回复了你在《{paper_title}》下的评论：\n"
                    f"{content[:280]}"
                ),
                article_number=paper.article_number,
                keywords=["评论互动", "回复"],
            )
            notified_user_ids.add(parent.user_id)

    # Mention notification: only mentionable friends are allowed.
    for user in mention_users:
        if user.id == g.current_user.id or user.id in notified_user_ids:
            continue
        _create_comment_notification(
            recipient_user_id=user.id,
            subject="你在评论中被提及",
            content=(
                f"{actor_name} 在《{paper_title}》的评论里 @了你：\n"
                f"{content[:280]}"
            ),
            article_number=paper.article_number,
            keywords=["评论互动", "@提及"],
        )
        notified_user_ids.add(user.id)

    db.session.commit()

    total_count = PaperComment.query.filter_by(paper_id=paper.id).count()
    return jsonify({
        "item": _comment_payload(
            comment,
            {comment.id: 0},
            set(),
            current_user_id=g.current_user.id,
        ),
        "totalCount": total_count,
    }), 201


@papers_bp.route("/comments/<int:comment_id>", methods=["PATCH"])
@token_required
def update_paper_comment(comment_id):
    comment = db.session.get(PaperComment, comment_id)
    if not comment:
        return jsonify({"error": "评论不存在"}), 404
    if comment.user_id != g.current_user.id:
        return jsonify({"error": "无权编辑该评论"}), 403

    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "评论内容不能为空"}), 400
    if len(content) > 1500:
        return jsonify({"error": "评论内容不能超过1500字符"}), 400

    _, mention_error = _validate_mention_users(content, g.current_user.id)
    if mention_error:
        return jsonify({"error": mention_error}), 400

    comment.content = content
    db.session.commit()
    return jsonify({
        "item": _comment_payload(
            comment,
            like_count_map={comment.id: PaperCommentLike.query.filter_by(comment_id=comment.id).count()},
            liked_comment_ids={comment.id} if PaperCommentLike.query.filter_by(
                comment_id=comment.id,
                user_id=g.current_user.id,
            ).first() else set(),
            current_user_id=g.current_user.id,
        )
    })


@papers_bp.route("/comments/<int:comment_id>", methods=["DELETE"])
@token_required
def delete_paper_comment(comment_id):
    comment = db.session.get(PaperComment, comment_id)
    if not comment:
        return jsonify({"error": "评论不存在"}), 404
    if comment.user_id != g.current_user.id:
        return jsonify({"error": "无权删除该评论"}), 403

    paper_id = comment.paper_id
    parent_id = comment.parent_id

    # Keep child replies by reparenting to deleted comment's parent.
    PaperComment.query.filter_by(parent_id=comment.id).update(
        {"parent_id": parent_id},
        synchronize_session=False,
    )
    PaperCommentLike.query.filter_by(comment_id=comment.id).delete(synchronize_session=False)
    db.session.delete(comment)
    db.session.commit()

    total_count = PaperComment.query.filter_by(paper_id=paper_id).count()
    return jsonify({
        "ok": True,
        "totalCount": total_count,
    })


@papers_bp.route("/comments/<int:comment_id>/like", methods=["POST"])
@token_required
def toggle_comment_like(comment_id):
    comment = db.session.get(PaperComment, comment_id)
    if not comment:
        return jsonify({"error": "评论不存在"}), 404

    existing = PaperCommentLike.query.filter_by(
        comment_id=comment_id,
        user_id=g.current_user.id,
    ).first()

    if existing:
        db.session.delete(existing)
        liked = False
    else:
        db.session.add(PaperCommentLike(comment_id=comment_id, user_id=g.current_user.id))
        liked = True

        if comment.user_id != g.current_user.id:
            actor_name = g.current_user.display_name or g.current_user.username
            paper = comment.paper
            paper_title = (
                (paper.title_zh or paper.title or paper.article_number)
                if paper else "论文"
            )
            _create_comment_notification(
                recipient_user_id=comment.user_id,
                subject="你的评论收到了点赞",
                content=(
                    f"{actor_name} 点赞了你在《{paper_title}》下的评论。\n"
                    f"评论内容：{(comment.content or '')[:280]}"
                ),
                article_number=paper.article_number if paper else None,
                keywords=["评论互动", "点赞"],
            )

    db.session.commit()
    like_count = PaperCommentLike.query.filter_by(comment_id=comment_id).count()
    return jsonify({
        "commentId": comment_id,
        "liked": liked,
        "likeCount": like_count,
    })
