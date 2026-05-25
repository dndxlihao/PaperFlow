import os
import json
import random
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pdfplumber
from flask import Blueprint, current_app, g, jsonify, request

from auth import token_required
from channel_monitor import (
    channel_catalog_payload,
    get_user_channel_updates,
    run_ieee_early_access_monitor,
)
from models import (
    Paper,
    PaperRating,
    Recommendation,
    UserChannelRequest,
    UserChannelSubscription,
    UserDigest,
    UserPaper,
    UserPreference,
    db,
)
from getDoc import crawl_issue_by_pages
from pdf_download import download_pdf_by_article_with_report
from pdf_retry_service import record_pdf_download_outcome
from paper_filters import is_paper_index_or_toc
from summarizer import summarize_paper

recommend_bp = Blueprint("recommend", __name__, url_prefix="/api/recommend")
SUMMARY_SOURCE_PDF = "pdf_full_text"
SUMMARY_META_PATTERN = re.compile(r"^\s*<!--PF_SUMMARY_META:(\{.*?\})-->\s*", re.DOTALL)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _valid_channel_keys():
    return {item["key"] for item in channel_catalog_payload()}


def _norm_title(title: str) -> str:
    return "".join((title or "").strip().lower().split())


def _norm_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def _pack_summary_payload(summary_html: str, source: str):
    clean = (summary_html or "").strip()
    if not clean:
        return clean
    meta = json.dumps({"source": source}, ensure_ascii=False)
    return f"<!--PF_SUMMARY_META:{meta}-->\n{clean}"


def _is_public_paper(paper: Paper) -> bool:
    if not paper:
        return False
    if (paper.content_origin or "system") != "user_upload":
        return True
    return (paper.creator_review_status or "approved") == "approved"


def _unpack_summary_payload(summary_text: str):
    if not summary_text:
        return summary_text, None
    text = str(summary_text)
    match = SUMMARY_META_PATTERN.match(text)
    if not match:
        return text, None
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
    for p in candidates:
        ap = os.path.abspath(p)
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


def _clean_list(values, limit=30):
    if not isinstance(values, list):
        return []
    out = []
    seen = set()
    for v in values:
        item = str(v).strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _parse_excluded_article_numbers(raw: str):
    if not raw:
        return set()
    out = set()
    for item in raw.split(","):
        v = (item or "").strip()
        if v:
            out.add(v)
    return out


def _expand_journal_terms(terms):
    alias = {
        "tsg": ["ieee transactions on smart grid", "transactions on smart grid", "smart grid"],
        "tste": ["ieee transactions on sustainable energy", "transactions on sustainable energy", "sustainable energy"],
        "tpwrs": ["ieee transactions on power systems", "transactions on power systems", "power systems"],
        "tpes": ["ieee transactions on power electronics", "transactions on power electronics", "power electronics"],
        "tpel": ["ieee transactions on power electronics", "transactions on power electronics", "power electronics"],
        "tie": ["ieee transactions on industrial electronics", "transactions on industrial electronics", "industrial electronics"],
        "tpwrd": ["ieee transactions on power delivery", "transactions on power delivery", "power delivery"],
        "tii": ["ieee transactions on industrial informatics", "transactions on industrial informatics", "industrial informatics"],
    }
    expanded = []
    for term in terms:
        t = _norm_text(term)
        if not t:
            continue
        expanded.append(t)
        if t.startswith("ieee "):
            expanded.append(t[5:].strip())
        for abbr, variants in alias.items():
            if re.search(rf"\b{re.escape(abbr)}\b", t):
                expanded.extend(variants)
        expanded.extend(alias.get(t, []))
    # preserve order, drop dupes
    result = []
    seen = set()
    for t in expanded:
        if t in seen:
            continue
        seen.add(t)
        result.append(t)
    return result


def _expand_area_terms(terms):
    alias = {
        "电力系统": ["电力系统", "电网", "smart grid", "power system", "power systems", "grid"],
        "新能源": ["新能源", "可再生能源", "renewable", "renewables", "wind", "solar", "clean energy"],
        "储能": ["储能", "储能系统", "energy storage", "battery", "bess"],
        "智能电网": ["智能电网", "smart grid", "grid intelligence"],
        "电力电子": ["电力电子", "power electronics", "converter", "inverter"],
        "机器学习": ["机器学习", "machine learning", "deep learning", "neural network", "transformer", "强化学习"],
    }
    expanded = []
    for term in terms:
        raw = str(term or "").strip()
        if not raw:
            continue
        expanded.append(_norm_text(raw))
        for k, variants in alias.items():
            if _norm_text(k) == _norm_text(raw):
                expanded.extend([_norm_text(v) for v in variants if _norm_text(v)])
                break

    result = []
    seen = set()
    for t in expanded:
        if not t or t in seen:
            continue
        seen.add(t)
        result.append(t)
    return result


def _journal_match_score(publication_text: str, raw_journals, expanded_journals):
    pub = _norm_text(publication_text or "")
    if not pub:
        return 0.0

    # Direct phrase match from user-selected journal string has highest confidence.
    for raw in raw_journals:
        r = _norm_text(raw)
        if not r:
            continue
        # "Energy" should target the journal "Energy", not every title that contains energy.
        if r == "energy":
            if pub == "energy":
                return 2.0
            continue
        if r in pub:
            return 2.0

    for t in expanded_journals:
        if t and t in pub:
            return 1.0
    return 0.0


def _area_match_score(category_text: str, keyword_text: str, combined_text: str, expanded_areas):
    if not expanded_areas:
        return 0.0
    cat = _norm_text(category_text or "")
    kw = _norm_text(keyword_text or "")
    comb = _norm_text(combined_text or "")
    hits = 0
    for area in expanded_areas:
        if not area:
            continue
        if (cat and area in cat) or (kw and area in kw) or (comb and area in comb):
            hits += 1
    return float(hits)


def _build_area_profiles(raw_terms):
    profiles = []
    seen = set()
    for raw in raw_terms or []:
        name = str(raw or "").strip()
        if not name:
            continue
        key = _norm_text(name)
        if key in seen:
            continue
        seen.add(key)
        terms = _expand_area_terms([name]) or [key]
        profiles.append({
            "name": name,
            "key": key,
            "terms": terms,
        })
    return profiles


def _match_area_profile(category_text: str, keyword_text: str, combined_text: str, profile: dict):
    cat = _norm_text(category_text or "")
    kw = _norm_text(keyword_text or "")
    comb = _norm_text(combined_text or "")
    for term in profile.get("terms", []):
        t = _norm_text(term)
        if not t:
            continue
        if (cat and t in cat) or (kw and t in kw) or (comb and t in comb):
            return True
    return False


def _frequency_profile(freq: str):
    f = (freq or "daily").strip().lower()

    def _cfg_i(name, default):
        try:
            return int(current_app.config.get(name, default))
        except Exception:
            return int(default)

    def _cfg_f(name, default):
        try:
            return float(current_app.config.get(name, default))
        except Exception:
            return float(default)

    if f == "weekly":
        return {
            "candidate_limit": _cfg_i("RECSCORE_WEEKLY_CANDIDATE_LIMIT", 2400),
            "fresh_window_days": _cfg_i("RECSCORE_WEEKLY_FRESH_WINDOW_DAYS", 30),
            "freshness_weight": _cfg_f("RECSCORE_WEEKLY_FRESHNESS_WEIGHT", 0.6),
            "shuffle_weight": _cfg_f("RECSCORE_WEEKLY_SHUFFLE_WEIGHT", 0.18),
            "fallback_days": _cfg_i("RECSCORE_WEEKLY_FALLBACK_DAYS", 21),
        }
    if f == "realtime":
        return {
            "candidate_limit": _cfg_i("RECSCORE_REALTIME_CANDIDATE_LIMIT", 900),
            "fresh_window_days": _cfg_i("RECSCORE_REALTIME_FRESH_WINDOW_DAYS", 3),
            "freshness_weight": _cfg_f("RECSCORE_REALTIME_FRESHNESS_WEIGHT", 1.5),
            "shuffle_weight": _cfg_f("RECSCORE_REALTIME_SHUFFLE_WEIGHT", 0.35),
            "fallback_days": _cfg_i("RECSCORE_REALTIME_FALLBACK_DAYS", 3),
        }
    return {
        "candidate_limit": _cfg_i("RECSCORE_DAILY_CANDIDATE_LIMIT", 1400),
        "fresh_window_days": _cfg_i("RECSCORE_DAILY_FRESH_WINDOW_DAYS", 10),
        "freshness_weight": _cfg_f("RECSCORE_DAILY_FRESHNESS_WEIGHT", 1.0),
        "shuffle_weight": _cfg_f("RECSCORE_DAILY_SHUFFLE_WEIGHT", 0.25),
        "fallback_days": _cfg_i("RECSCORE_DAILY_FALLBACK_DAYS", 10),
    }


def _score_weights():
    def _cfg_f(name, default):
        try:
            return float(current_app.config.get(name, default))
        except Exception:
            return float(default)

    return {
        "journal": _cfg_f("RECSCORE_JOURNAL_MATCH_WEIGHT", 4.0),
        "area": _cfg_f("RECSCORE_AREA_MATCH_WEIGHT", 2.0),
        "text": _cfg_f("RECSCORE_TEXT_MATCH_WEIGHT", 1.4),
        "summary": _cfg_f("RECSCORE_SUMMARY_BONUS", 0.3),
        "favorite": _cfg_f("RECSCORE_FAVORITE_BONUS", 0.6),
        "library_penalty": _cfg_f("RECSCORE_LIBRARY_PENALTY", 0.25),
        "rating_factor": _cfg_f("RECSCORE_RATING_FACTOR", 0.85),
        "avoid_category_penalty": _cfg_f("RECSCORE_AVOID_CATEGORY_PENALTY", 1.8),
        "area_pref_factor": _cfg_f("RECSCORE_AREA_PREF_FACTOR", 0.45),
        "area_pref_cap": _cfg_f("RECSCORE_AREA_PREF_CAP", 2.6),
        "keyword_pref_factor": _cfg_f("RECSCORE_KEYWORD_PREF_FACTOR", 0.22),
        "keyword_pref_cap": _cfg_f("RECSCORE_KEYWORD_PREF_CAP", 1.8),
    }


def _build_user_history_profile(user_id: int):
    library_rows = UserPaper.query.filter_by(user_id=user_id).all()
    rating_rows = PaperRating.query.filter_by(user_id=user_id).all()

    favorite_ids = {r.paper_id for r in library_rows if r.is_favorite}
    library_ids = {r.paper_id for r in library_rows}
    rating_map = {r.paper_id: r.score for r in rating_rows}

    liked_ids = set(favorite_ids)
    disliked_ids = set()
    for pid, score in rating_map.items():
        if score >= 4:
            liked_ids.add(pid)
        elif score <= 2:
            disliked_ids.add(pid)

    liked_papers = []
    if liked_ids:
        liked_papers = Paper.query.filter(Paper.id.in_(liked_ids)).all()

    disliked_papers = []
    if disliked_ids:
        disliked_papers = Paper.query.filter(Paper.id.in_(disliked_ids)).all()

    area_pref = Counter()
    keyword_pref = Counter()
    for p in liked_papers:
        cat = _norm_text(p.category or "")
        if cat:
            area_pref[cat] += 1
        for kw in (p.keywords or [])[:8]:
            token = _norm_text(kw)
            if token:
                keyword_pref[token] += 1

    area_avoid = set()
    for p in disliked_papers:
        cat = _norm_text(p.category or "")
        if cat:
            area_avoid.add(cat)

    return {
        "library_ids": library_ids,
        "favorite_ids": favorite_ids,
        "rating_map": rating_map,
        "area_pref": area_pref,
        "keyword_pref": keyword_pref,
        "area_avoid": area_avoid,
    }


def _upsert_preference(user_id: int, data: dict):
    pref = UserPreference.query.filter_by(user_id=user_id).first()
    if not pref:
        pref = UserPreference(user_id=user_id)
        db.session.add(pref)

    journals = _clean_list(data.get("journals") or [])
    research_areas = _clean_list(data.get("researchAreas") or [])
    pref.journals = journals
    pref.research_areas = research_areas
    # Product decision: personalized feed is fixed to daily cadence.
    pref.recommend_frequency = "daily"
    db.session.commit()
    return pref

# Default IEEE sources for recommendation crawling
DEFAULT_SOURCES = [
    {"punumber": "59", "name": "IEEE Transactions on Power Systems"},
    {"punumber": "61", "name": "IEEE Transactions on Power Electronics"},
    {"punumber": "60", "name": "IEEE Transactions on Power Delivery"},
    {"punumber": "41", "name": "IEEE Transactions on Industrial Electronics"},
    {"punumber": "28", "name": "IEEE Transactions on Energy Conversion"},
    {"punumber": "5165411", "name": "IEEE Transactions on Sustainable Energy"},
]


def run_daily_recommendation(app):
    """Run inside scheduler context: crawl top papers and generate summaries."""
    with app.app_context():
        today = date.today()

        # Skip if already recommended today
        existing = Recommendation.query.filter_by(recommended_date=today).count()
        if existing >= app.config["RECOMMEND_COUNT"]:
            print(f"[RECOMMEND] Already have {existing} recommendations for {today}, skipping.")
            return

        count_needed = app.config["RECOMMEND_COUNT"] - existing

        # Pick random sources to crawl
        sources = random.sample(DEFAULT_SOURCES, min(len(DEFAULT_SOURCES), 3))

        candidate_papers = []
        for source in sources:
            try:
                items = crawl_issue_by_pages(
                    punumber=source["punumber"],
                    isnumber="",  # Latest issue
                    start_page=1,
                    end_page=1,
                    rows_per_page=10,
                    sortType="paper-citations",
                    download_pdf=False,
                    attach_text=False,
                )
                candidate_papers.extend(items)
            except Exception as e:
                print(f"[RECOMMEND][WARN] Failed to crawl {source['name']}: {e}")
                continue

        if not candidate_papers:
            print("[RECOMMEND] No candidates found.")
            return

        # Deduplicate and pick top N
        seen = set()
        unique_candidates = []
        for item in candidate_papers:
            arn = item.get("articleNumber")
            if arn and arn not in seen:
                seen.add(arn)
                unique_candidates.append(item)

        selected = unique_candidates[:count_needed]

        for item in selected:
            arn = str(item.get("articleNumber", ""))
            if not arn:
                continue

            # Ensure paper in DB
            paper = Paper.query.filter_by(article_number=arn).first()
            if not paper:
                paper = Paper(
                    article_number=arn,
                    title=item.get("articleTitle", ""),
                    abstract=item.get("abstract", ""),
                    publication_date=item.get("publicationDate", ""),
                    publication_title=item.get("publicationTitle") or item.get("displayPublicationTitle", ""),
                    download_count=item.get("downloadCount", 0),
                )
                authors = item.get("authors", [])
                if isinstance(authors, list):
                    paper.authors = authors
                db.session.add(paper)
                db.session.flush()

            # Generate summary if not exists
            _, summary_source = _unpack_summary_payload(paper.summary or "")
            if summary_source != SUMMARY_SOURCE_PDF:
                try:
                    pdf_dir = app.config["PDF_DIR"]
                    pdf_path = _resolve_pdf_path(arn, paper.pdf_path, pdf_dir)
                    if not pdf_path:
                        downloaded, report = download_pdf_by_article_with_report(
                            article_number=arn,
                            out_dir=pdf_dir,
                            source_url=paper.source_url or "",
                            elsevier_api_key=app.config.get("ELSEVIER_API_KEY", ""),
                            elsevier_selenium_attach_debugger=app.config.get("ELSEVIER_SELENIUM_ATTACH_DEBUGGER"),
                            elsevier_selenium_debugger_address=app.config.get("ELSEVIER_CHROME_DEBUGGER_ADDRESS"),
                            elsevier_selenium_allow_new_browser_on_attach_fail=app.config.get(
                                "ELSEVIER_SELENIUM_ALLOW_NEW_BROWSER_ON_ATTACH_FAIL"
                            ),
                        )
                        record_pdf_download_outcome(
                            app=app,
                            article_number=arn,
                            source_url=paper.source_url or "",
                            report=report,
                            paper_id=paper.id,
                            enqueue_on_fail=True,
                        )
                        if downloaded and os.path.exists(downloaded):
                            paper.pdf_path = _to_repo_relative(downloaded)
                        pdf_path = _resolve_pdf_path(arn, paper.pdf_path, pdf_dir)
                    if not pdf_path:
                        raise RuntimeError("PDF not found after download")

                    full_text = _extract_text_from_pdf(pdf_path)
                    if not full_text.strip():
                        raise RuntimeError("PDF extracted text is empty")

                    summary = summarize_paper(
                        title=paper.title or "",
                        abstract=paper.abstract or "",
                        full_text=full_text,
                    )
                    paper.summary = _pack_summary_payload(summary, SUMMARY_SOURCE_PDF)
                    paper.summary_generated_at = datetime.now(timezone.utc)
                    paper.pdf_path = _to_repo_relative(pdf_path)
                    summary_source = SUMMARY_SOURCE_PDF
                except Exception as e:
                    print(f"[RECOMMEND][WARN] Summary failed for {arn}: {e}")

            if summary_source != SUMMARY_SOURCE_PDF:
                print(f"[RECOMMEND][SKIP] {arn} has no PDF full-text summary, skip recommendation.")
                continue

            # Create recommendation: do not recommend the same paper repeatedly.
            exists = Recommendation.query.filter_by(paper_id=paper.id).first()
            if not exists:
                rec = Recommendation(paper_id=paper.id, recommended_date=today)
                db.session.add(rec)

        db.session.commit()
        print(f"[RECOMMEND] Created {len(selected)} recommendations for {today}.")


@recommend_bp.route("", methods=["GET"])
@token_required
def get_recommendations():
    """Get recommendations. Optionally filter by date."""
    date_str = request.args.get("date")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    q = Recommendation.query
    if date_str:
        try:
            target_date = date.fromisoformat(date_str)
            q = q.filter_by(recommended_date=target_date)
        except ValueError:
            return jsonify({"error": "Invalid date format, use YYYY-MM-DD"}), 400
    
    q = q.order_by(Recommendation.recommended_date.desc(), Recommendation.id.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)

    # Deduplicate by normalized title to avoid repeated cards for the same paper.
    seen_titles = set()
    deduped_items = []
    for r in pagination.items:
        if is_paper_index_or_toc(r.paper):
            continue
        title_key = _norm_title((r.paper.title_zh or r.paper.title or ""))
        if title_key and title_key in seen_titles:
            continue
        if title_key:
            seen_titles.add(title_key)
        deduped_items.append(r.to_dict())

    return jsonify({
        "items": deduped_items,
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
    })


@recommend_bp.route("/trigger", methods=["POST"])
@token_required
def trigger_recommendation():
    """Manually trigger a frequency-specific update run."""
    try:
        from daily_update import run_daily_update
        strategy = (request.args.get("strategy") or "daily").strip().lower()
        if strategy not in {"daily", "weekly", "realtime"}:
            strategy = "daily"
        result = run_daily_update(current_app._get_current_object(), strategy=strategy) or {}
        added = int(result.get("added", 0) or 0)
        return jsonify({
            "message": f"{strategy} 推荐更新已完成（新增 {added} 条）",
            "result": result,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@recommend_bp.route("/dates", methods=["GET"])
@token_required
def get_recommendation_dates():
    """Get list of dates that have recommendations."""
    rows = (
        db.session.query(Recommendation.recommended_date)
        .distinct()
        .order_by(Recommendation.recommended_date.desc())
        .limit(30)
        .all()
    )
    dates = [r[0].isoformat() for r in rows]
    return jsonify(dates)


@recommend_bp.route("/preferences", methods=["GET"])
@token_required
def get_preferences():
    pref = UserPreference.query.filter_by(user_id=g.current_user.id).first()
    if not pref:
        return jsonify({
            "journals": [],
            "researchAreas": [],
            "recommendFrequency": "daily",
        })
    payload = pref.to_dict()
    payload["recommendFrequency"] = "daily"
    return jsonify(payload)


@recommend_bp.route("/preferences", methods=["PUT"])
@token_required
def update_preferences():
    data = request.get_json(silent=True) or {}
    pref = _upsert_preference(g.current_user.id, data)
    return jsonify(pref.to_dict())


@recommend_bp.route("/personalized", methods=["GET"])
@token_required
def get_personalized_recommendations():
    per_page = request.args.get("per_page", 10, type=int)
    per_page = max(1, min(per_page, 50))
    seed = request.args.get("seed", type=int)
    excluded_article_numbers = _parse_excluded_article_numbers(
        request.args.get("exclude_article_numbers", "")
    )
    if seed is None:
        # Keep recommendations fresh between visits; each request gets a new random seed unless caller sets one.
        seed = int(datetime.now(timezone.utc).timestamp() * 1000000)

    pref = UserPreference.query.filter_by(user_id=g.current_user.id).first()
    if pref and pref.recommend_frequency != "daily":
        pref.recommend_frequency = "daily"
        db.session.commit()

    journals_raw = pref.journals if pref else []
    journals = _expand_journal_terms(journals_raw)
    area_profiles = _build_area_profiles(pref.research_areas if pref else [])
    areas = []
    for profile in area_profiles:
        areas.extend(profile["terms"])
    areas = list(dict.fromkeys([_norm_text(a) for a in areas if _norm_text(a)]))
    freq_profile = _frequency_profile("daily")
    weights = _score_weights()
    history = _build_user_history_profile(g.current_user.id)
    has_journal_pref = len(journals_raw) > 0
    has_area_pref = len(area_profiles) > 0

    pref_payload = (
        pref.to_dict()
        if pref
        else {
            "journals": [],
            "researchAreas": [],
            "recommendFrequency": "daily",
        }
    )
    pref_payload["recommendFrequency"] = "daily"

    def _calc_tier(journal_hit: bool, area_hit: bool):
        # Strict priority:
        # 1) journal+area both match
        # 2) journal-only match
        # 3) area-only match (other journals allowed when preferred journal is exhausted)
        # 4) others
        if has_journal_pref and has_area_pref:
            if journal_hit and area_hit:
                return 0
            if journal_hit:
                return 1
            if area_hit:
                return 2
            return 3
        if has_journal_pref:
            return 0 if journal_hit else 1
        if has_area_pref:
            return 0 if area_hit else 1
        return 2

    def _paper_features(paper):
        pub = paper.publication_title or ""
        keywords_text = " ".join(paper.keywords or [])
        combined_text = " ".join([paper.title or "", paper.abstract or "", keywords_text, paper.category or ""])
        journal_score = _journal_match_score(pub, journals_raw, journals) if has_journal_pref else 0.0
        area_score = _area_match_score(paper.category or "", keywords_text, combined_text, areas) if has_area_pref else 0.0
        return journal_score, area_score, keywords_text, combined_text

    candidate_limit = int(freq_profile["candidate_limit"])
    # Journal preference needs a broader pool, otherwise older but relevant journal papers
    # may be excluded by a strict recent-only limit.
    if has_journal_pref:
        candidate_limit = max(candidate_limit, 8000)
    papers = (
        Paper.query.filter(Paper.is_public_clause()).order_by(Paper.created_at.desc(), Paper.id.desc())
        .limit(candidate_limit)
        .all()
    )
    scored = []
    now = datetime.now(timezone.utc)
    for paper in papers:
        if is_paper_index_or_toc(paper):
            continue
        if paper.article_number in excluded_article_numbers:
            continue

        journal_score, area_score, keywords_text, combined_text = _paper_features(paper)
        matched_area_keys = []
        if has_area_pref:
            for profile in area_profiles:
                if _match_area_profile(paper.category or "", keywords_text, combined_text, profile):
                    matched_area_keys.append(profile["key"])
        journal_hit = journal_score > 0
        area_hit = area_score > 0
        tier = _calc_tier(journal_hit, area_hit)

        category = _norm_text(paper.category or "")
        combined = _norm_text(combined_text)

        score = 0.0

        if journal_score > 0:
            score += weights["journal"] * journal_score
        if area_score > 0:
            score += weights["area"] * min(area_score, 2.0)
            score += weights["text"] * min(area_score, 2.0)

        if paper.summary:
            score += weights["summary"]

        # Daily freshness boost.
        if paper.created_at:
            created_at = paper.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            age_days = max(0.0, (now - created_at).total_seconds() / 86400.0)
            fresh_window = float(freq_profile["fresh_window_days"])
            freshness = max(0.0, 1.0 - (age_days / fresh_window))
            score += freshness * float(freq_profile["freshness_weight"])

        # User history: favorites/ratings shape long-term profile and stabilize ranking.
        if paper.id in history["favorite_ids"]:
            score += weights["favorite"]
        if paper.id in history["library_ids"]:
            score -= weights["library_penalty"]

        rating = history["rating_map"].get(paper.id)
        if rating is not None:
            score += (float(rating) - 3.0) * weights["rating_factor"]

        if category in history["area_avoid"]:
            score -= weights["avoid_category_penalty"]

        for area, cnt in history["area_pref"].most_common(8):
            if not area:
                continue
            if category and (area in category or category in area):
                score += min(weights["area_pref_cap"], weights["area_pref_factor"] * cnt)

        for kw, cnt in history["keyword_pref"].most_common(16):
            if kw and kw in combined:
                score += min(weights["keyword_pref_cap"], weights["keyword_pref_factor"] * cnt)

        # Add visible diversity so cards are not fixed every visit.
        rand = random.Random(f"{seed}:{paper.article_number}").random()
        score += rand * max(float(freq_profile["shuffle_weight"]), 0.45)

        scored.append((tier, score, paper, matched_area_keys))

    scored.sort(key=lambda x: (x[0], -x[1]))

    items = []
    seen_titles = set()
    seen_article_numbers = set()
    selected_area_keys = [p["key"] for p in area_profiles]

    def _append_paper_obj(paper_obj):
        title_key = _norm_title(paper_obj.title_zh or paper_obj.title or "")
        if title_key and title_key in seen_titles:
            return False
        if paper_obj.article_number in seen_article_numbers:
            return False
        if title_key:
            seen_titles.add(title_key)
        seen_article_numbers.add(paper_obj.article_number)
        items.append(paper_obj.to_dict())
        return True

    if has_area_pref and len(selected_area_keys) >= 2:
        area_buckets = {k: [] for k in selected_area_keys}
        spill = []
        for rec in scored:
            matched_keys = rec[3]
            matched_in_selected = [k for k in matched_keys if k in area_buckets]
            if not matched_in_selected:
                spill.append(rec)
                continue
            # balance bucket sizes to avoid one dominant direction occupying the top cards
            target_key = min(matched_in_selected, key=lambda k: len(area_buckets[k]))
            area_buckets[target_key].append(rec)

        progressed = True
        while len(items) < per_page and progressed:
            progressed = False
            for key in selected_area_keys:
                bucket = area_buckets.get(key) or []
                while bucket:
                    tier, score, paper, _ = bucket.pop(0)
                    if _append_paper_obj(paper):
                        progressed = True
                        break
                if len(items) >= per_page:
                    break

        if len(items) < per_page:
            for tier, score, paper, _ in spill:
                if _append_paper_obj(paper) and len(items) >= per_page:
                    break
        if len(items) < per_page:
            for tier, score, paper, _ in scored:
                if _append_paper_obj(paper) and len(items) >= per_page:
                    break
    else:
        for _, _, paper, _ in scored:
            if _append_paper_obj(paper) and len(items) >= per_page:
                break

    if len(items) < per_page:
        recent_cutoff = date.today() - timedelta(days=int(freq_profile["fallback_days"]))
        recs = (
            Recommendation.query.filter(Recommendation.recommended_date >= recent_cutoff)
            .order_by(Recommendation.recommended_date.desc(), Recommendation.id.desc())
            .limit(per_page * 3)
            .all()
        )
        for rec in recs:
            paper = rec.paper
            if not paper:
                continue
            if not _is_public_paper(paper):
                continue
            if is_paper_index_or_toc(paper):
                continue
            if paper.article_number in excluded_article_numbers:
                continue
            if paper.article_number in seen_article_numbers:
                continue

            journal_score, area_score, _, _ = _paper_features(paper)
            tier = _calc_tier(journal_score > 0, area_score > 0)
            if has_area_pref and has_journal_pref and tier > 2:
                continue

            if _append_paper_obj(paper) and len(items) >= per_page:
                break

    # Final fallback: when recommendation table is sparse, still provide cards.
    if len(items) == 0:
        latest = (
            Paper.query.filter(Paper.is_public_clause()).order_by(Paper.created_at.desc(), Paper.id.desc())
            .limit(per_page)
            .all()
        )
        for p in latest:
            if is_paper_index_or_toc(p):
                continue
            if p.article_number in excluded_article_numbers:
                continue
            if p.article_number in seen_article_numbers:
                continue
            if _append_paper_obj(p) and len(items) >= per_page:
                break

    return jsonify({
        "items": items,
        "seed": seed,
        "preferences": pref_payload,
    })


@recommend_bp.route("/channels/catalog", methods=["GET"])
@token_required
def get_channel_catalog():
    return jsonify({"items": channel_catalog_payload()})


@recommend_bp.route("/channels/updates", methods=["GET"])
@token_required
def get_channel_updates():
    limit = request.args.get("limit", 8, type=int)
    days = request.args.get("days", 30, type=int)
    items = get_user_channel_updates(g.current_user.id, limit=limit, days=days)
    return jsonify({"items": items})


@recommend_bp.route("/channels/monitor/trigger", methods=["POST"])
@token_required
def trigger_channel_monitor():
    result = run_ieee_early_access_monitor(current_app._get_current_object()) or {}
    return jsonify({
        "message": "IEEE Early Access 监控任务已执行",
        "result": result,
    })


@recommend_bp.route("/channels/subscriptions", methods=["GET"])
@token_required
def get_channel_subscriptions():
    catalog = channel_catalog_payload()
    rows = UserChannelSubscription.query.filter_by(user_id=g.current_user.id).all()
    status_map = {r.channel_key: bool(r.enabled) for r in rows}

    items = []
    for item in catalog:
        d = dict(item)
        d["enabled"] = bool(status_map.get(item["key"], item.get("enabledByDefault", False)))
        items.append(d)
    return jsonify({"items": items})


@recommend_bp.route("/channels/subscriptions", methods=["PUT"])
@token_required
def update_channel_subscriptions():
    data = request.get_json(silent=True) or {}
    enabled_keys = data.get("enabledChannelKeys")
    if not isinstance(enabled_keys, list):
        return jsonify({"error": "enabledChannelKeys 必须是数组"}), 400

    valid_keys = _valid_channel_keys()
    normalized = {str(x).strip() for x in enabled_keys if str(x).strip()}
    invalid = [k for k in normalized if k not in valid_keys]
    if invalid:
        return jsonify({"error": f"无效专栏键: {', '.join(invalid)}"}), 400

    existing = UserChannelSubscription.query.filter_by(user_id=g.current_user.id).all()
    existing_map = {row.channel_key: row for row in existing}

    for key in valid_keys:
        row = existing_map.get(key)
        enabled = key in normalized
        if row is None:
            row = UserChannelSubscription(user_id=g.current_user.id, channel_key=key, enabled=enabled)
            db.session.add(row)
        else:
            row.enabled = enabled

    db.session.commit()
    return get_channel_subscriptions()


@recommend_bp.route("/channels/requests", methods=["POST"])
@token_required
def create_channel_request():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    detail = (data.get("detail") or "").strip()

    if len(title) < 2:
        return jsonify({"error": "需求标题至少2个字符"}), 400
    if len(title) > 200:
        return jsonify({"error": "需求标题不能超过200个字符"}), 400
    if len(detail) > 3000:
        return jsonify({"error": "需求说明不能超过3000个字符"}), 400

    req = UserChannelRequest(
        user_id=g.current_user.id,
        title=title,
        detail=detail or None,
        status="pending",
    )
    db.session.add(req)

    now = datetime.now(timezone.utc)
    ack = UserDigest(
        user_id=g.current_user.id,
        period_start=now,
        period_end=now,
        subject="专栏需求提交成功，已进入审核",
        content=(
            "我们已收到你的专栏/期刊更新需求。\n"
            "该需求将进入管理员审核流程，预计 48 小时内反馈结果。\n"
            "你可以在首页“我的需求进度”中查看处理状态。"
        ),
        read_count=0,
        source_click_count=0,
        is_read=False,
    )
    ack.keywords = ["需求审核", "48小时反馈"]
    db.session.add(ack)

    db.session.commit()
    return jsonify(req.to_dict()), 201


@recommend_bp.route("/channels/requests/mine", methods=["GET"])
@token_required
def list_my_channel_requests():
    rows = (
        UserChannelRequest.query
        .filter_by(user_id=g.current_user.id)
        .order_by(UserChannelRequest.created_at.desc())
        .limit(50)
        .all()
    )
    return jsonify({"items": [r.to_dict() for r in rows]})
