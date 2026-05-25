"""
Academic Genealogy (学术族谱) API.

Mines author data from existing Paper records to build scholar graphs:
- Nodes: scholars (authors) with paper counts and research areas
- Edges: co-authorship relationships (weighted by shared papers)

API:
  GET  /api/scholars/hot-keywords          -> popular research keywords
  POST /api/scholars/graph   { "query": "...", "topK": 60 }
  POST /api/scholars/search-author { "name": "taoqian" }
  GET  /api/scholars/detail/<name>
"""

import json
import re
from collections import Counter, defaultdict

from flask import Blueprint, jsonify, request
from sqlalchemy import and_, or_

from flask import g
from auth import token_required
from models import Paper, ScholarRating, db
from sqlalchemy import func

scholars_bp = Blueprint("scholars", __name__, url_prefix="/api/scholars")


def _parse_authors(paper):
    """Return list of author name strings from a Paper."""
    if paper.authors_json:
        try:
            authors = json.loads(paper.authors_json)
            if isinstance(authors, list):
                return [a.strip() for a in authors if isinstance(a, str) and a.strip()]
        except (json.JSONDecodeError, TypeError):
            pass
    return []


def _parse_keywords(paper):
    if paper.keywords_json:
        try:
            kws = json.loads(paper.keywords_json)
            if isinstance(kws, list):
                return [k.strip() for k in kws if isinstance(k, str) and k.strip()]
        except (json.JSONDecodeError, TypeError):
            pass
    return []


def _normalize_name(name):
    """Normalize a name for fuzzy matching: lowercase, remove spaces/punctuation."""
    return re.sub(r'[^a-z\u4e00-\u9fff]', '', name.lower())


def _name_matches(query_norm, author_name):
    """
    Check if a normalized query matches an author name.
    Handles:
      - "Tao Qian" matches "taoqian", "qiantao", "Tao Qian"
      - "qiantao" matches "Tao Qian"
    Strict: requires full-name match, not substring.
    """
    author_norm = _normalize_name(author_name)
    if not author_norm or not query_norm:
        return False
    # Exact normalized match
    if query_norm == author_norm:
        return True
    # Split author name into parts, check if concatenation in either order matches
    parts = re.findall(r'[a-z\u4e00-\u9fff]+', author_name.lower())
    if len(parts) >= 2:
        # Try all 2-part permutations: "firstname+lastname" and "lastname+firstname"
        for i in range(len(parts)):
            for j in range(len(parts)):
                if i != j:
                    combined = parts[i] + parts[j]
                    if query_norm == combined:
                        return True
    # Also split the query and check if it matches the author parts
    # e.g. query="tao qian" (norm list ["tao","qian"]) vs author "Qian Tao"
    query_parts = re.findall(r'[a-z\u4e00-\u9fff]+', query_norm)
    if len(query_parts) >= 2 and len(parts) >= 2:
        if set(query_parts) == set(parts):
            return True
    return False


def _build_scholar_graph(papers, top_k_scholars=60):
    """
    Given a list of Paper objects, build a scholar co-authorship graph.

    Returns (nodes, edges) where:
      nodes: list of { id, name, paperCount, categories, keywords, papers }
      edges: list of { source, target, weight, sharedPapers }
    """
    # 1. Collect per-author stats
    author_papers = defaultdict(list)    # author_name -> [paper]
    author_categories = defaultdict(Counter)
    author_keywords = defaultdict(Counter)

    for p in papers:
        authors = _parse_authors(p)
        kws = _parse_keywords(p)
        cat = p.category or "未分类"
        for a in authors:
            author_papers[a].append(p)
            author_categories[a][cat] += 1
            for k in kws:
                author_keywords[a][k] += 1

    # 2. Rank authors by paper count, take top_k
    ranked = sorted(author_papers.keys(), key=lambda a: len(author_papers[a]), reverse=True)
    top_authors = set(ranked[:top_k_scholars])

    # 3. Build nodes
    nodes = []
    for name in ranked[:top_k_scholars]:
        plist = author_papers[name]
        cats = author_categories[name]
        top_cat = cats.most_common(1)[0][0] if cats else None
        top_kws = [k for k, _ in author_keywords[name].most_common(5)]
        paper_titles = [{"title": p.title, "articleNumber": p.article_number,
                         "year": p.publication_date} for p in plist[:10]]
        nodes.append({
            "id": name,
            "name": name,
            "paperCount": len(plist),
            "category": top_cat,
            "keywords": top_kws,
            "papers": paper_titles,
        })

    # 4. Build co-authorship edges
    coauthor_count = defaultdict(int)     # (a, b) -> shared paper count
    coauthor_papers = defaultdict(list)   # (a, b) -> [paper_title]

    for p in papers:
        authors = [a for a in _parse_authors(p) if a in top_authors]
        for i in range(len(authors)):
            for j in range(i + 1, len(authors)):
                a, b = tuple(sorted([authors[i], authors[j]]))
                coauthor_count[(a, b)] += 1
                if len(coauthor_papers[(a, b)]) < 5:
                    coauthor_papers[(a, b)].append(p.title or "")

    edges = []
    for (a, b), count in coauthor_count.items():
        edges.append({
            "source": a,
            "target": b,
            "weight": count,
            "sharedPapers": coauthor_papers[(a, b)],
        })

    return nodes, edges


@scholars_bp.route("/hot-keywords", methods=["GET"])
@token_required
def hot_keywords():
    """Return popular research keywords/categories from the paper DB."""
    papers = Paper.query.filter(Paper.keywords_json.isnot(None)).all()
    kw_counter = Counter()
    cat_counter = Counter()
    for p in papers:
        for k in _parse_keywords(p):
            kw_counter[k] += 1
        if p.category:
            cat_counter[p.category] += 1

    # Top categories + top keywords, deduplicated
    hot = []
    seen = set()
    for name, count in cat_counter.most_common(12):
        key = name.strip()
        if key and key not in seen:
            hot.append({"label": key, "count": count, "type": "category"})
            seen.add(key)
    for name, count in kw_counter.most_common(40):
        key = name.strip()
        if key and key not in seen and len(hot) < 20:
            hot.append({"label": key, "count": count, "type": "keyword"})
            seen.add(key)

    return jsonify({"keywords": hot})


@scholars_bp.route("/graph", methods=["POST"])
@token_required
def scholar_graph():
    """
    Build a scholar co-authorship graph for papers matching a query.
    Body: { "query": "search terms", "topK": 60 }

    Also supports author search: if query looks like a person name
    (detected by fuzzy matching), find papers by that author.
    """
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    top_k = min(int(data.get("topK", 60)), 120)

    if not query:
        return jsonify({"error": "query is required"}), 400

    # 1. Try topic/keyword search
    terms = [t.strip() for t in query.split() if t.strip()]
    filters = []
    for t in terms:
        like = f"%{t}%"
        filters.append(or_(
            Paper.title.ilike(like),
            Paper.abstract.ilike(like),
            Paper.keywords_json.ilike(like),
            Paper.category.ilike(like),
        ))
    papers = Paper.query.filter(*filters).all() if filters else []

    # 2. Also try fuzzy author name search and merge results
    query_norm = _normalize_name(query)
    if query_norm and len(query_norm) >= 3:
        # Generate SQL filters for possible name parts
        # e.g., "qiantao" -> try all splits: ("q","iantao"), ("qi","antao"), ...
        # Also try original terms as author name parts
        author_sql_filters = []
        # If multi-word, each word might be part of a name
        if len(terms) <= 3:
            for t in terms:
                author_sql_filters.append(Paper.authors_json.ilike(f"%{t}%"))

        # For single concatenated word, try 2-part splits (min 2 chars each)
        if len(terms) == 1 and len(query_norm) >= 4:
            for i in range(2, len(query_norm) - 1):
                part1, part2 = query_norm[:i], query_norm[i:]
                if len(part1) >= 2 and len(part2) >= 2:
                    author_sql_filters.append(
                        and_(
                            Paper.authors_json.ilike(f"%{part1}%"),
                            Paper.authors_json.ilike(f"%{part2}%"),
                        )
                    )

        if author_sql_filters:
            candidates = Paper.query.filter(
                Paper.authors_json.isnot(None),
                or_(*author_sql_filters)
            ).all()
            paper_ids_already = {p.id for p in papers}
            for p in candidates:
                if p.id in paper_ids_already:
                    continue
                authors = _parse_authors(p)
                for a in authors:
                    if _name_matches(query_norm, a):
                        papers.append(p)
                        paper_ids_already.add(p.id)
                        break

    if not papers:
        return jsonify({"nodes": [], "edges": [], "paperCount": 0})

    nodes, edges = _build_scholar_graph(papers, top_k_scholars=top_k)

    return jsonify({
        "nodes": nodes,
        "edges": edges,
        "paperCount": len(papers),
    })


@scholars_bp.route("/detail/<path:name>", methods=["GET"])
@token_required
def scholar_detail(name):
    """
    Get detailed info for a single scholar (all their papers in DB).
    Supports fuzzy name matching.
    """
    name = name.strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    query_norm = _normalize_name(name)

    # Always use normalized fuzzy aggregation so different name formats
    # (e.g. "huqinran", "Hu Qinran", "Qinran Hu") map to one scholar profile.
    sql_filters = [Paper.authors_json.ilike(f"%{name}%")]
    parts = name.split()
    for part in parts:
        if len(part) >= 2:
            sql_filters.append(Paper.authors_json.ilike(f"%{part}%"))
    if len(parts) == 1 and len(query_norm) >= 4:
        for i in range(2, len(query_norm) - 1):
            p1, p2 = query_norm[:i], query_norm[i:]
            if len(p1) >= 2 and len(p2) >= 2:
                sql_filters.append(
                    and_(
                        Paper.authors_json.ilike(f"%{p1}%"),
                        Paper.authors_json.ilike(f"%{p2}%"),
                    )
                )

    matched = []
    matched_ids = set()
    matched_aliases = Counter()
    if sql_filters:
        candidates = Paper.query.filter(
            Paper.authors_json.isnot(None),
            or_(*sql_filters)
        ).all()
        for p in candidates:
            authors = _parse_authors(p)
            hit_alias = None
            for a in authors:
                if _name_matches(query_norm, a):
                    hit_alias = a
                    break
            if hit_alias and p.id not in matched_ids:
                matched.append(p)
                matched_ids.add(p.id)
                matched_aliases[hit_alias] += 1

    real_name = matched_aliases.most_common(1)[0][0] if matched_aliases else name

    if not matched:
        return jsonify({"error": "scholar not found"}), 404

    # Build coauthors list using real_name
    coauthor_count = Counter()
    categories = Counter()
    keywords = Counter()

    for p in matched:
        authors = _parse_authors(p)
        for a in authors:
            if not _name_matches(query_norm, a):
                coauthor_count[a] += 1
        if p.category:
            categories[p.category] += 1
        for k in _parse_keywords(p):
            keywords[k] += 1

    paper_list = [{
        "articleNumber": p.article_number,
        "title": p.title,
        "titleZh": p.title_zh,
        "year": p.publication_date,
        "category": p.category,
        "figurePath": p.figure_path,
    } for p in sorted(matched, key=lambda x: x.publication_date or "", reverse=True)]

    coauthors = [{"name": a, "count": c} for a, c in coauthor_count.most_common(20)]

    # Scholar rating stats
    avg_row = db.session.query(func.avg(ScholarRating.score)).filter_by(scholar_name=real_name).scalar()
    rating_count = db.session.query(func.count(ScholarRating.id)).filter_by(scholar_name=real_name).scalar()

    return jsonify({
        "name": real_name,
        "paperCount": len(matched),
        "papers": paper_list,
        "coauthors": coauthors,
        "categories": [{"name": c, "count": n} for c, n in categories.most_common()],
        "keywords": [{"name": k, "count": n} for k, n in keywords.most_common(10)],
        "avgRating": round(float(avg_row), 1) if avg_row else 0,
        "ratingCount": rating_count or 0,
    })


# ── Scholar rating ──────────────────────────────────────────────────

def _scholar_rating_info(scholar_name, user_id=None):
    avg_row = db.session.query(func.avg(ScholarRating.score)).filter_by(scholar_name=scholar_name).scalar()
    cnt = db.session.query(func.count(ScholarRating.id)).filter_by(scholar_name=scholar_name).scalar()
    my_score = 0
    if user_id:
        r = ScholarRating.query.filter_by(user_id=user_id, scholar_name=scholar_name).first()
        if r:
            my_score = r.score
    return {
        "myScore": my_score,
        "avgRating": round(float(avg_row), 1) if avg_row else 0,
        "ratingCount": cnt or 0,
    }


@scholars_bp.route("/rate", methods=["POST"])
@token_required
def rate_scholar():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    score = data.get("score")
    if not name or not isinstance(score, (int, float)) or not (1 <= int(score) <= 5):
        return jsonify({"error": "name and score (1-5) required"}), 400
    score = int(score)
    user_id = g.current_user.id

    rating = ScholarRating.query.filter_by(user_id=user_id, scholar_name=name).first()
    if rating:
        rating.score = score
    else:
        rating = ScholarRating(user_id=user_id, scholar_name=name, score=score)
        db.session.add(rating)
    db.session.commit()

    info = _scholar_rating_info(name, user_id)
    info["score"] = score
    return jsonify(info)


@scholars_bp.route("/rate/<path:name>", methods=["GET"])
@token_required
def get_scholar_rating(name):
    name = name.strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    return jsonify(_scholar_rating_info(name, g.current_user.id))
