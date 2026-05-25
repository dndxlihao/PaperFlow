"""
Knowledge-base hybrid search (keyword + vector) & knowledge-graph endpoint.

Priority:
  1. Keyword hits in title / abstract / keywords  (SQL LIKE)
  2. Vector-similarity expansion via FAISS
Papers are merged, de-duplicated, and edges are built from
inter-paper cosine similarity + shared keywords.
"""

import json
import os
import re
import threading
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func, or_

from auth import token_required
from models import Paper, db

try:
    import faiss  # type: ignore
except Exception:
    faiss = None

knowledge_bp = Blueprint("knowledge", __name__, url_prefix="/api/knowledge")

EMBED_CACHE = os.path.join(os.path.dirname(__file__), "embeddings_cache.npz")
TRENDS_CACHE = os.path.join(os.path.dirname(__file__), "knowledge_trends_cache.json")
EMBED_CACHE_VERSION = 2
SUMMARY_META_PATTERN = re.compile(r"^\s*<!--PF_SUMMARY_META:(\{.*?\})-->\s*", re.DOTALL)
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
SPACE_PATTERN = re.compile(r"\s+")
EN_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9._+\-/]{1,}")
ZH_BLOCK_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,}")
PUB_YM_PATTERN = re.compile(r"((?:19|20)\d{2})\D{0,2}(1[0-2]|0?[1-9])")
YEAR_PATTERN = re.compile(r"((?:19|20)\d{2})")
ISSUE_PATTERNS = [
    re.compile(r"(?:issue|iss\.?|number|no\.?|nr\.?)\s*[:#]?\s*(\d{1,3})", re.IGNORECASE),
    re.compile(r"第\s*(\d{1,3})\s*期"),
    re.compile(r"\b(\d{1,3})\s*期\b"),
]
TOPIC_SPLIT_PATTERN = re.compile(r"[，,、;/；|]+")
TOPIC_TRIM_PATTERN = re.compile(r"^[\s\-\|·:：,/，;；_（）()【】\[\]<>《》\"'“”‘’]+|[\s\-\|·:：,/，;；_（）()【】\[\]<>《》\"'“”‘’]+$")
GENERIC_TOPIC_TOKENS = {
    "ai",
    "ml",
    "llm",
    "model",
    "models",
    "method",
    "methods",
    "approach",
    "framework",
    "study",
    "research",
    "analysis",
    "optimization",
    "algorithm",
    "algorithms",
    "应用",
    "方法",
    "模型",
    "研究",
    "分析",
    "算法",
    "优化",
    "系统",
    "框架",
    "实验",
}
ALGO_TOPIC_RULES = [
    (re.compile(r"(强化学习|reinforcement learning|\brl\b)", re.IGNORECASE), "强化学习"),
    (re.compile(r"(多智能体强化学习|multi[\s-]?agent[\s-]?reinforcement learning|marl)", re.IGNORECASE), "多智能体强化学习"),
    (re.compile(r"(扩散模型|diffusion model|ddpm|score[\s-]?based)", re.IGNORECASE), "扩散模型"),
    (re.compile(r"(图神经网络|graph neural network|\bgnn\b|\bgcn\b|\bgat\b)", re.IGNORECASE), "图神经网络"),
    (re.compile(r"(transformer|自注意力|attention)", re.IGNORECASE), "Transformer"),
    (re.compile(r"(大语言模型|large language model|\bllm\b|prompt)", re.IGNORECASE), "大语言模型"),
    (re.compile(r"(联邦学习|federated learning)", re.IGNORECASE), "联邦学习"),
    (re.compile(r"(元学习|meta[\s-]?learning)", re.IGNORECASE), "元学习"),
    (re.compile(r"(模型预测控制|model predictive control|\bmpc\b)", re.IGNORECASE), "模型预测控制"),
    (re.compile(r"(最优潮流|optimal power flow|\bopf\b)", re.IGNORECASE), "最优潮流"),
    (re.compile(r"(贝叶斯优化|bayesian optimization)", re.IGNORECASE), "贝叶斯优化"),
    (re.compile(r"(因果推断|causal inference)", re.IGNORECASE), "因果推断"),
    (re.compile(r"(知识图谱|knowledge graph)", re.IGNORECASE), "知识图谱"),
]
SUBFIELD_TOPIC_RULES = [
    (re.compile(r"(车网互动|\bv2g\b|vehicle[-\s]?to[-\s]?grid)", re.IGNORECASE), "车网互动"),
    (re.compile(r"(智能电网|smart grid)", re.IGNORECASE), "智能电网"),
    (re.compile(r"(微电网|microgrid)", re.IGNORECASE), "微电网"),
    (re.compile(r"(配电网|distribution network)", re.IGNORECASE), "配电网"),
    (re.compile(r"(状态估计|state estimation)", re.IGNORECASE), "状态估计"),
    (re.compile(r"(频率控制|frequency control)", re.IGNORECASE), "频率控制"),
    (re.compile(r"(经济调度|economic dispatch|unit commitment)", re.IGNORECASE), "经济调度"),
    (re.compile(r"(能源管理系统|energy management system|\bems\b)", re.IGNORECASE), "能源管理系统"),
    (re.compile(r"(暂态稳定|transient stability)", re.IGNORECASE), "暂态稳定"),
    (re.compile(r"(故障诊断|fault diagnosis)", re.IGNORECASE), "故障诊断"),
    (re.compile(r"(储能|energy storage|battery)", re.IGNORECASE), "储能系统"),
    (re.compile(r"(可再生能源|renewable energy|wind power|solar|photovoltaic)", re.IGNORECASE), "可再生能源"),
    (re.compile(r"(需求响应|demand response)", re.IGNORECASE), "需求响应"),
    (re.compile(r"(负荷预测|load forecasting|load prediction)", re.IGNORECASE), "负荷预测"),
    (re.compile(r"(电力市场|electricity market|power market)", re.IGNORECASE), "电力市场"),
    (re.compile(r"(电压控制|voltage control)", re.IGNORECASE), "电压控制"),
]
TOPIC_ALIAS_MAP = {
    "大模型": "大语言模型",
    "llm": "大语言模型",
    "large language model": "大语言模型",
    "reinforcement learning": "强化学习",
    "rl": "强化学习",
    "marl": "多智能体强化学习",
    "diffusion": "扩散模型",
    "diffusion model": "扩散模型",
    "graph neural network": "图神经网络",
    "gnn": "图神经网络",
    "gcn": "图神经网络",
    "gat": "图神经网络",
    "model predictive control": "模型预测控制",
    "mpc": "模型预测控制",
    "optimal power flow": "最优潮流",
    "opf": "最优潮流",
    "vehicle-to-grid": "车网互动",
    "v2g": "车网互动",
    "smart grid": "智能电网",
    "microgrid": "微电网",
    "distribution network": "配电网",
    "energy management system": "能源管理系统",
    "ems": "能源管理系统",
    "load forecasting": "负荷预测",
    "load prediction": "负荷预测",
}
LLM_SUBFIELD_RULES = [
    (re.compile(r"(rag|retrieval[-\s]?augmented generation|检索增强)", re.IGNORECASE), "RAG"),
    (re.compile(r"(agent|智能体|tool use|function call)", re.IGNORECASE), "智能体"),
    (re.compile(r"(prompt|提示工程)", re.IGNORECASE), "提示工程"),
    (re.compile(r"(lora|sft|instruction tuning|指令微调|微调)", re.IGNORECASE), "模型微调"),
    (re.compile(r"(quantization|量化|蒸馏|distillation|剪枝|compression)", re.IGNORECASE), "模型压缩"),
    (re.compile(r"(hallucination|幻觉|factuality|事实性)", re.IGNORECASE), "事实性对齐"),
    (re.compile(r"(multimodal|多模态|vision[-\s]?language)", re.IGNORECASE), "多模态"),
    (re.compile(r"(reasoning|推理|chain[-\s]?of[-\s]?thought)", re.IGNORECASE), "推理增强"),
]
KNOWN_ALGO_TOPICS = {name for _, name in ALGO_TOPIC_RULES}
KNOWN_SUBFIELD_TOPICS = {name for _, name in SUBFIELD_TOPIC_RULES}
CURRENT_YEAR = datetime.now(timezone.utc).year
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

# Module-level singletons
_index = None
_paper_ids = None       # np array of paper.id, aligned with _embeddings rows
_embeddings = None      # np float32 L2-normalised
_id_to_idx = None       # dict  paper_id -> row index in _embeddings
_model = None
_build_lock = threading.Lock()
_cache_meta = {
    "cacheVersion": EMBED_CACHE_VERSION,
    "paperCount": 0,
    "maxPaperId": 0,
    "builtAt": None,
}
_trends_lock = threading.Lock()
_trends_cache = None
_trends_cache_meta = {
    "months": 12,
    "top": 6,
    "experts": 5,
    "generatedAt": None,
}


def _normalize_l2(vectors: np.ndarray):
    if vectors is None:
        return
    if faiss is not None:
        faiss.normalize_L2(vectors)
        return
    if vectors.ndim != 2 or vectors.shape[0] == 0:
        return
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    vectors /= norms


class _NumpyInnerProductIndex:
    def __init__(self, dim: int):
        self.dim = int(dim)
        self._emb = np.empty((0, self.dim), dtype="float32")

    @property
    def ntotal(self) -> int:
        return int(self._emb.shape[0])

    def add(self, emb: np.ndarray):
        arr = np.asarray(emb, dtype="float32")
        if arr.ndim != 2:
            raise ValueError("embeddings must be a 2D array")
        if arr.shape[1] != self.dim:
            raise ValueError("embedding dimension mismatch")
        if arr.shape[0] == 0:
            return
        self._emb = np.vstack([self._emb, arr]).astype("float32", copy=False)

    def search(self, q_vec: np.ndarray, k: int):
        q = np.asarray(q_vec, dtype="float32")
        if q.ndim != 2 or q.shape[0] == 0:
            return (
                np.empty((0, 0), dtype="float32"),
                np.empty((0, 0), dtype="int64"),
            )
        if self.ntotal == 0:
            scores = np.full((q.shape[0], 0), -1.0, dtype="float32")
            idxs = np.full((q.shape[0], 0), -1, dtype="int64")
            return scores, idxs

        k = max(1, min(int(k), self.ntotal))
        all_scores = np.matmul(q, self._emb.T)
        part = np.argpartition(-all_scores, kth=k - 1, axis=1)[:, :k]
        part_scores = np.take_along_axis(all_scores, part, axis=1)
        order = np.argsort(-part_scores, axis=1)
        sorted_idx = np.take_along_axis(part, order, axis=1).astype("int64")
        sorted_scores = np.take_along_axis(part_scores, order, axis=1).astype("float32")
        return sorted_scores, sorted_idx


def _new_ip_index(dim: int):
    if faiss is not None:
        return faiss.IndexFlatIP(dim)
    return _NumpyInnerProductIndex(dim)


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    return _model


def _paper_text(p):
    clean_summary = ""
    if p.summary:
        text = str(p.summary)
        m = SUMMARY_META_PATTERN.match(text)
        clean_summary = text[m.end():].lstrip() if m else text
        clean_summary = SPACE_PATTERN.sub(" ", HTML_TAG_PATTERN.sub(" ", clean_summary)).strip()

    clean_figure_expl = ""
    if p.figure_explanation:
        clean_figure_expl = SPACE_PATTERN.sub(
            " ",
            HTML_TAG_PATTERN.sub(" ", str(p.figure_explanation)),
        ).strip()

    kw_text = ""
    try:
        kws = p.keywords or []
        if kws:
            kw_text = " ".join([str(x) for x in kws if x])
    except Exception:
        kw_text = ""

    parts = []
    if p.title:
        parts.extend([p.title, p.title, p.title])
    if p.title_zh:
        parts.extend([p.title_zh, p.title_zh, p.title_zh])
    if kw_text:
        parts.extend([kw_text, kw_text])
    if p.category:
        parts.extend([p.category, p.category])
    if p.abstract:
        parts.append(str(p.abstract)[:1400])
    if clean_summary:
        parts.append(clean_summary[:1600])
    if clean_figure_expl:
        parts.append(clean_figure_expl[:700])
    return " ".join(parts)


def _norm_text(value: str):
    if not value:
        return ""
    text = str(value).lower()
    text = HTML_TAG_PATTERN.sub(" ", text)
    text = SPACE_PATTERN.sub(" ", text).strip()
    return text


def _extract_query_terms(query: str, limit: int = 24):
    text = (query or "").strip()
    if not text:
        return []

    out = []
    seen = set()

    def _add(term: str):
        t = (term or "").strip().lower()
        if len(t) < 2:
            return
        if t not in seen:
            seen.add(t)
            out.append(t)

    _add(text)
    lowered = text.lower()

    for tok in EN_TOKEN_PATTERN.findall(lowered):
        _add(tok)

    for block in ZH_BLOCK_PATTERN.findall(text):
        _add(block)
        if len(block) >= 4:
            for i in range(min(len(block) - 1, 10)):
                _add(block[i:i + 2])

    return out[:limit]


def _lexical_score(paper: Paper, query_text: str, terms):
    title = _norm_text(paper.title or "")
    title_zh = _norm_text(paper.title_zh or "")
    abstract = _norm_text((paper.abstract or "")[:1600])
    kw = _norm_text(" ".join([str(x) for x in (paper.keywords or []) if x]))
    category = _norm_text(paper.category or "")
    summary_raw = ""
    if paper.summary:
        text = str(paper.summary)
        m = SUMMARY_META_PATTERN.match(text)
        summary_raw = text[m.end():].lstrip() if m else text
    summary = _norm_text(summary_raw[:1800])
    full_text = " ".join([title, title_zh, abstract, kw, category, summary]).strip()

    query_norm = _norm_text(query_text or "")
    if not full_text:
        return {
            "score": 0.0,
            "exactTitleHit": False,
            "exactTextHit": False,
            "titleHits": 0,
            "fullHits": 0,
            "keywordHits": 0,
            "categoryHits": 0,
            "matchedTerms": [],
            "matchedTitleTerms": [],
        }

    exact_title_hit = bool(query_norm) and (query_norm in title or query_norm in title_zh)
    exact_text_hit = bool(query_norm) and (query_norm in full_text)

    if terms:
        title_hits = 0
        full_hits = 0
        kw_hits = 0
        cat_hits = 0
        matched_terms = []
        matched_title_terms = []
        for t in terms:
            in_title = t in title or t in title_zh
            in_full = t in full_text
            in_kw = t in kw
            in_cat = t in category
            if in_title:
                title_hits += 1
                matched_title_terms.append(t)
            if in_full:
                full_hits += 1
                matched_terms.append(t)
            if in_kw:
                kw_hits += 1
            if in_cat:
                cat_hits += 1
        title_cov = title_hits / len(terms)
        full_cov = full_hits / len(terms)
        kw_cov = kw_hits / len(terms)
        cat_cov = cat_hits / len(terms)
    else:
        title_cov = 0.0
        full_cov = 0.0
        kw_cov = 0.0
        cat_cov = 0.0
        title_hits = 0
        full_hits = 0
        kw_hits = 0
        cat_hits = 0
        matched_terms = []
        matched_title_terms = []

    lexical = (
        0.45 * full_cov
        + 0.28 * title_cov
        + 0.14 * kw_cov
        + 0.06 * cat_cov
        + (0.07 if exact_text_hit else 0.0)
        + (0.08 if exact_title_hit else 0.0)
    )
    lexical = max(0.0, min(1.0, lexical))
    return {
        "score": lexical,
        "exactTitleHit": exact_title_hit,
        "exactTextHit": exact_text_hit,
        "titleHits": title_hits,
        "fullHits": full_hits,
        "keywordHits": kw_hits,
        "categoryHits": cat_hits,
        "matchedTerms": matched_terms[:12],
        "matchedTitleTerms": matched_title_terms[:12],
    }


def _parse_pub_year_month(paper: Paper):
    text = (paper.publication_date or "").strip()
    if text:
        m = PUB_YM_PATTERN.search(text)
        if m:
            try:
                year = int(m.group(1))
                month = int(m.group(2))
                if 1 <= month <= 12:
                    return year, month
            except Exception:
                pass

    # 热点趋势只基于论文发表时间，不再回退到入库时间(created_at)。
    return None


def _month_key(year: int, month: int):
    return f"{year:04d}-{month:02d}"


def _month_sequence(months: int = 12):
    now = datetime.now(SHANGHAI_TZ).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    seq = []
    cursor = now - timedelta(days=32 * (months - 1))
    cursor = cursor.replace(day=1)
    while len(seq) < months:
        seq.append((cursor.year, cursor.month))
        if cursor.month == 12:
            cursor = cursor.replace(year=cursor.year + 1, month=1)
        else:
            cursor = cursor.replace(month=cursor.month + 1)
    return seq


def _build_relevance_reasons(is_kw: bool, vec_score: float, lexical_info: dict):
    reasons = []
    if lexical_info.get("exactTitleHit"):
        reasons.append("标题精确命中")
    elif lexical_info.get("titleHits", 0) > 0:
        reasons.append(f"标题词命中 {lexical_info['titleHits']} 项")

    if is_kw:
        if lexical_info.get("keywordHits", 0) > 0:
            reasons.append(f"关键词匹配 {lexical_info['keywordHits']} 项")
        else:
            reasons.append("关键词检索命中")

    if lexical_info.get("categoryHits", 0) > 0:
        reasons.append("研究方向标签匹配")

    if vec_score >= 0.86:
        reasons.append(f"语义高度相似 ({vec_score:.2f})")
    elif vec_score >= 0.75:
        reasons.append(f"语义相似 ({vec_score:.2f})")

    if not reasons:
        reasons.append("语义相似度召回")
    return reasons[:4]


def _normalize_journal_name(value: str):
    if not value:
        return ""
    text = SPACE_PATTERN.sub(" ", str(value)).strip()
    if not text:
        return ""
    return text


def _is_arxiv_paper(article_number: str, publication_title: str):
    arn = (article_number or "").strip().lower()
    pub = (publication_title or "").strip().lower()
    return arn.startswith("arxiv_") or ("arxiv" in pub)


def _extract_year_for_stats(publication_date: str, publication_title: str):
    for text in (publication_date or "", publication_title or ""):
        m = YEAR_PATTERN.search(text)
        if m:
            try:
                year = int(m.group(1))
                if 1900 <= year <= CURRENT_YEAR + 1:
                    return year
            except Exception:
                continue
    return None


def _extract_issue_for_stats(publication_date: str, publication_title: str):
    for text in (publication_date or "", publication_title or ""):
        if not text:
            continue
        for pattern in ISSUE_PATTERNS:
            m = pattern.search(text)
            if not m:
                continue
            try:
                value = int(m.group(1))
            except Exception:
                continue
            if 1 <= value <= 999:
                return str(value)

    # Fallback: use month as issue-like bucket when explicit issue is unavailable.
    m = PUB_YM_PATTERN.search(publication_date or "")
    if m:
        try:
            month = int(m.group(2))
            if 1 <= month <= 12:
                return f"M{month:02d}"
        except Exception:
            pass
    return None


def _build_publication_stats_payload():
    papers = Paper.query.filter(Paper.is_public_clause()).all()
    journals = {}
    non_arxiv_total = 0

    for p in papers:
        arn = p.article_number or ""
        pub_title = p.publication_title or ""
        if _is_arxiv_paper(arn, pub_title):
            continue

        journal = _normalize_journal_name(pub_title)
        if not journal:
            continue

        non_arxiv_total += 1
        year = _extract_year_for_stats(p.publication_date or "", pub_title)
        issue = _extract_issue_for_stats(p.publication_date or "", pub_title)

        item = journals.get(journal)
        if not item:
            item = {
                "journal": journal,
                "paperCount": 0,
                "years": {},
                "unknownYearCount": 0,
                "issueSampleCount": 0,
            }
            journals[journal] = item

        item["paperCount"] += 1
        if year is None:
            item["unknownYearCount"] += 1
            continue

        year_key = str(year)
        year_bucket = item["years"].get(year_key)
        if not year_bucket:
            year_bucket = {
                "year": year,
                "paperCount": 0,
                "issues": {},
                "unknownIssueCount": 0,
            }
            item["years"][year_key] = year_bucket

        year_bucket["paperCount"] += 1
        if issue:
            year_bucket["issues"][issue] = year_bucket["issues"].get(issue, 0) + 1
            item["issueSampleCount"] += 1
        else:
            year_bucket["unknownIssueCount"] += 1

    journal_items = []
    for journal_name, data in journals.items():
        years = []
        for year_key, year_data in data["years"].items():
            issue_items = [
                {"issue": issue, "paperCount": int(cnt)}
                for issue, cnt in year_data["issues"].items()
            ]
            issue_items.sort(
                key=lambda x: (
                    0 if str(x["issue"]).startswith("M") else 1,
                    int(str(x["issue"])[1:]) if str(x["issue"]).startswith("M") else int(x["issue"]),
                )
            )
            years.append({
                "year": int(year_data["year"]),
                "paperCount": int(year_data["paperCount"]),
                "issues": issue_items,
                "unknownIssueCount": int(year_data["unknownIssueCount"]),
            })

        years.sort(key=lambda x: x["year"], reverse=True)
        journal_items.append({
            "journal": journal_name,
            "paperCount": int(data["paperCount"]),
            "yearCount": len(years),
            "issueSampleCount": int(data["issueSampleCount"]),
            "unknownYearCount": int(data["unknownYearCount"]),
            "years": years,
        })

    journal_items.sort(
        key=lambda x: (x["paperCount"], x["issueSampleCount"], x["journal"].lower()),
        reverse=True,
    )

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "totalPapersNonArxiv": int(non_arxiv_total),
        "totalJournals": int(len(journal_items)),
        "journals": journal_items,
    }


def _normalize_topic_label(text: str):
    if not text:
        return ""
    label = TOPIC_TRIM_PATTERN.sub("", SPACE_PATTERN.sub(" ", str(text)).strip())
    if len(label) < 2:
        return ""
    if re.fullmatch(r"[\d\W_]+", label):
        return ""
    low = label.lower()
    if low in GENERIC_TOPIC_TOKENS:
        return ""
    if len(label) > 46:
        label = label[:46].rstrip(" .,:;，；")
    return label


def _is_too_broad_topic(label: str):
    low = (label or "").strip().lower()
    if not low:
        return True
    if low in GENERIC_TOPIC_TOKENS:
        return True
    if len(low) <= 2:
        return True
    # 过于通用的“某某系统/某某模型”不直接作为热点子方向
    if low.endswith("系统") and len(low) <= 4:
        return True
    if low.endswith("模型") and len(low) <= 4:
        return True
    return False


def _extract_by_rules(text: str, rules, max_items: int = 5):
    if not text:
        return []
    out = []
    seen = set()
    for pattern, mapped in rules:
        if pattern.search(text):
            key = mapped.lower()
            if key not in seen:
                seen.add(key)
                out.append(mapped)
            if len(out) >= max_items:
                break
    return out


def _canonicalize_topic_token(token: str):
    t = _normalize_topic_label(token)
    if not t:
        return ""
    low = t.lower()
    mapped = TOPIC_ALIAS_MAP.get(low) or TOPIC_ALIAS_MAP.get(t)
    if mapped:
        return mapped
    return t


def _canonicalize_topic_label(label: str):
    if not label:
        return ""
    raw = str(label).replace("•", "·")
    parts = [p for p in re.split(r"\s*[·]\s*", raw) if p]
    normalized = []
    seen = set()
    for part in parts:
        c = _canonicalize_topic_token(part)
        if not c:
            continue
        key = c.lower()
        if key not in seen:
            seen.add(key)
            normalized.append(c)
    if not normalized:
        return ""
    if len(normalized) == 1:
        return normalized[0]
    return " · ".join(normalized[:3])


def _topic_family_key(topic: str):
    t = _canonicalize_topic_label(topic)
    if not t:
        return ""
    algo_hits = _extract_by_rules(t, ALGO_TOPIC_RULES, max_items=1)
    subfield_hits = _extract_by_rules(t, SUBFIELD_TOPIC_RULES, max_items=1)
    llm_sub_hits = _extract_by_rules(t, LLM_SUBFIELD_RULES, max_items=1)

    algo = algo_hits[0] if algo_hits else ""
    subfield = subfield_hits[0] if subfield_hits else ""
    llm_sub = llm_sub_hits[0] if llm_sub_hits else ""

    # 若是“大语言模型 · 某子方向”，按子方向聚合，避免“LLM”与“LLM·RAG”重复占位。
    if algo == "大语言模型" and llm_sub:
        return f"llm-sub:{llm_sub}"
    if subfield and algo:
        return f"pair:{subfield}|{algo}"
    if algo:
        return f"algo:{algo}"
    if subfield:
        return f"sf:{subfield}"
    return f"plain:{t}"


def _topic_specificity_score(topic: str, parent_category: str):
    score = 0.0
    t = topic or ""
    if "·" in t:
        score += 2.4
    if len(t) >= 6:
        score += 0.8
    if re.search(r"[A-Z]{2,}", t) or re.search(r"[a-z]{4,}", t):
        score += 0.6
    if parent_category and parent_category in t and len(t) > len(parent_category):
        score += 0.9
    if _extract_by_rules(t, ALGO_TOPIC_RULES, max_items=1):
        score += 1.2
    if _extract_by_rules(t, SUBFIELD_TOPIC_RULES, max_items=1):
        score += 0.6
    return score


def _topic_candidates_from_paper(paper: Paper):
    category = _canonicalize_topic_label(paper.category or "") or "未分类"
    seen = set()
    topics = []

    def _push(topic: str):
        t = _canonicalize_topic_label(topic)
        if not t:
            return
        key = t.lower()
        if key in seen:
            return
        seen.add(key)
        topics.append(t)

    raw_keywords = []
    try:
        raw_keywords = [str(k).strip() for k in (paper.keywords or []) if k and str(k).strip()]
    except Exception:
        raw_keywords = []

    text_blob = " ".join([
        str(paper.title or ""),
        str(paper.title_zh or ""),
        str(paper.abstract or "")[:1800],
        " ".join(raw_keywords),
        str(paper.category or ""),
    ])
    algo_hits = _extract_by_rules(text_blob, ALGO_TOPIC_RULES, max_items=5)
    subfield_hits = _extract_by_rules(text_blob, SUBFIELD_TOPIC_RULES, max_items=5)
    llm_sub_hits = _extract_by_rules(text_blob, LLM_SUBFIELD_RULES, max_items=5)

    # LLM场景进一步细化：优先“ 大语言模型 · 子方向 ”
    if "大语言模型" in algo_hits:
        for llm_sub in llm_sub_hits[:4]:
            _push(f"大语言模型 · {llm_sub}")

    refined_keywords = []
    for kw in raw_keywords:
        for part in TOPIC_SPLIT_PATTERN.split(kw):
            norm = _canonicalize_topic_label(part)
            if not norm or _is_too_broad_topic(norm):
                continue
            refined_keywords.append(norm)

    # 优先生成“子领域 · 算法”组合热点，避免宽泛标签。
    for sf in subfield_hits[:3]:
        for algo in algo_hits[:3]:
            _push(f"{sf} · {algo}")

    for algo in algo_hits[:4]:
        _push(algo)
        if category and category != "未分类":
            cat_low = category.lower()
            algo_low = algo.lower()
            if (cat_low not in algo_low) and (algo_low not in cat_low):
                _push(f"{category} · {algo}")

    for sf in subfield_hits[:4]:
        _push(sf)

    for kw in refined_keywords[:10]:
        low = kw.lower()
        is_specific = (
            ("·" in kw)
            or (len(kw) >= 5)
            or bool(re.search(r"[A-Za-z]{3,}", kw))
            or bool(_extract_by_rules(low, ALGO_TOPIC_RULES, max_items=1))
            or bool(_extract_by_rules(low, SUBFIELD_TOPIC_RULES, max_items=1))
        )
        if not is_specific:
            continue
        _push(kw)
        if category and category != "未分类":
            cat_low = category.lower()
            kw_low = kw.lower()
            if (cat_low not in kw_low) and (kw_low not in cat_low):
                _push(f"{category} · {kw}")

    # 没有细粒度关键词时，仅在类目本身不宽泛时回落
    if not topics and category and not _is_too_broad_topic(category):
        _push(category)

    return topics, category


def _build_trending_payload(months: int = 12, top_n: int = 6, experts_per_category: int = 5):
    papers = Paper.query.filter(Paper.is_public_clause()).all()
    month_seq = _month_sequence(months=months)
    month_keys = [_month_key(y, m) for y, m in month_seq]
    month_idx = {mk: i for i, mk in enumerate(month_keys)}

    topic_counts = defaultdict(lambda: [0] * len(month_keys))
    topic_parent_category = {}
    topic_paper_ids = defaultdict(set)
    topic_author_counts = defaultdict(Counter)
    topic_family_author_counts = defaultdict(Counter)
    topic_author_year_bounds = defaultdict(dict)  # {topic: {author: [min_year, max_year]}}
    topic_specificity = defaultdict(float)

    for p in papers:
        topics, parent_category = _topic_candidates_from_paper(p)
        if not topics:
            continue

        try:
            authors = [a.strip() for a in (p.authors or []) if a and str(a).strip()]
        except Exception:
            authors = []

        ym = _parse_pub_year_month(p)
        idx = None
        if ym:
            mk = _month_key(ym[0], ym[1])
            idx = month_idx.get(mk)

        # 专家统计按“全量论文”累计（不局限于近12个月窗口），趋势曲线仍仅统计窗口内。
        for topic in topics:
            if topic not in topic_parent_category:
                topic_parent_category[topic] = parent_category or "未分类"
            topic_specificity[topic] = max(
                topic_specificity[topic],
                _topic_specificity_score(topic, topic_parent_category.get(topic, "")),
            )

            if idx is not None:
                topic_counts[topic][idx] += 1
                topic_paper_ids[topic].add(int(p.id))

            family_key = _topic_family_key(topic)
            for author in authors:
                if len(author) < 2:
                    continue
                topic_author_counts[topic][author] += 1
                if family_key:
                    topic_family_author_counts[family_key][author] += 1
                bounds = topic_author_year_bounds[topic].get(author)
                if ym:
                    if not bounds:
                        topic_author_year_bounds[topic][author] = [ym[0], ym[0]]
                    else:
                        bounds[0] = min(bounds[0], ym[0])
                        bounds[1] = max(bounds[1], ym[0])

    # Rank sub-topics by recent activity + growth + specificity.
    ranked = []
    for topic, series in topic_counts.items():
        if not any(series):
            continue
        has_algo = bool(_extract_by_rules(topic, ALGO_TOPIC_RULES, max_items=1))
        has_subfield = bool(_extract_by_rules(topic, SUBFIELD_TOPIC_RULES, max_items=1))
        if ("·" not in topic) and (not has_algo) and (not has_subfield):
            continue
        total = sum(series)
        if total < 2:
            # 单篇波动噪声太大，不作为热点方向
            continue
        if ("·" not in topic) and has_subfield and (not has_algo) and total < 4:
            # 仅有子领域且样本太少时，容易过宽泛
            continue
        recent = sum(series[-3:]) if len(series) >= 3 else sum(series)
        prev = sum(series[-6:-3]) if len(series) >= 6 else 0
        growth = recent - prev
        growth_rate = (growth / prev) if prev > 0 else (1.0 if recent > 0 else 0.0)
        specificity = topic_specificity.get(topic, 0.0)
        paper_span = len(topic_paper_ids.get(topic, set()))
        # 强化“细化方向”的得分，同时保留热度和增长趋势。
        score = recent * 1.0 + growth * 0.4 + paper_span * 0.08 + specificity * 0.9
        ranked.append((score, topic, series, recent, prev, growth, growth_rate, total, paper_span, specificity))

    ranked.sort(key=lambda x: x[0], reverse=True)

    # 去重与多样化：避免同一主题家族重复上榜（如“大模型·大语言模型”与“大语言模型”）。
    algo_has_pair_topic = set()
    for row in ranked:
        topic = row[1]
        algo_hits = _extract_by_rules(topic, ALGO_TOPIC_RULES, max_items=1)
        if ("·" in topic) and algo_hits:
            algo_has_pair_topic.add(algo_hits[0])

    selected_ranked = []
    used_family = set()
    for row in ranked:
        topic = row[1]
        family = _topic_family_key(topic)
        if not family or family in used_family:
            continue

        algo_hits = _extract_by_rules(topic, ALGO_TOPIC_RULES, max_items=1)
        algo = algo_hits[0] if algo_hits else ""
        if algo and ("·" not in topic) and (algo in algo_has_pair_topic):
            # 已有“子领域·算法”时，抑制仅算法的宽泛条目
            continue

        used_family.add(family)
        selected_ranked.append(row)
        if len(selected_ranked) >= top_n:
            break

    ranked = selected_ranked

    categories = []
    for _, topic, series, recent, prev, growth, growth_rate, total, paper_span, specificity in ranked:
        experts = []
        counter = topic_author_counts.get(topic, Counter())
        family_key = _topic_family_key(topic)
        family_counter = topic_family_author_counts.get(family_key, Counter()) if family_key else Counter()

        candidate_names = set([name for name, _ in counter.most_common(50)])
        candidate_names.update([name for name, _ in family_counter.most_common(50)])
        for name in candidate_names:
            cnt = int(counter.get(name, 0))
            fam_cnt = int(family_counter.get(name, 0))
            if cnt <= 0 and fam_cnt <= 0:
                continue
            bounds = topic_author_year_bounds.get(topic, {}).get(name) or [CURRENT_YEAR, CURRENT_YEAR]
            first_year, last_year = bounds
            seniority_years = max(1, CURRENT_YEAR - first_year + 1)
            active_recency = max(0, CURRENT_YEAR - last_year)
            # 专题内产出 + 家族内产出（避免子方向过细导致数量偏小）
            expert_score = cnt * 1.35 + fam_cnt * 0.55 + seniority_years * 0.16 - active_recency * 0.05
            experts.append({
                "name": name,
                "paperCount": int(max(cnt, fam_cnt)),
                "topicPaperCount": int(cnt),
                "familyPaperCount": int(fam_cnt),
                "firstYear": int(first_year),
                "lastYear": int(last_year),
                "seniorityYears": int(seniority_years),
                "score": round(expert_score, 3),
            })

        experts.sort(key=lambda x: (x["score"], x["paperCount"]), reverse=True)
        categories.append({
            "topic": topic,
            "category": topic,
            "parentCategory": topic_parent_category.get(topic, "未分类"),
            "searchQuery": topic,
            "series": series,
            "recent3m": int(recent),
            "prev3m": int(prev),
            "growth3m": int(growth),
            "growthRate3m": round(float(growth_rate), 4),
            "totalInWindow": int(total),
            "paperSpan": int(paper_span),
            "specificity": round(float(specificity), 3),
            "topExperts": experts[:experts_per_category],
        })

    return {
        "months": month_keys,
        "categories": categories,
        "paperCountTotal": int(len(papers)),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }


def _load_trends_cache_file():
    if not os.path.exists(TRENDS_CACHE):
        return None
    try:
        with open(TRENDS_CACHE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            return None
        if "categories" not in payload or "months" not in payload:
            return None
        return payload
    except Exception:
        return None


def _save_trends_cache_file(payload: dict):
    os.makedirs(os.path.dirname(TRENDS_CACHE), exist_ok=True)
    with open(TRENDS_CACHE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def build_trends_cache(app, months: int = 12, top_n: int = 6, experts_per_category: int = 5):
    """Build and persist trends payload cache. Used by weekly scheduler job."""
    global _trends_cache, _trends_cache_meta

    def _build():
        payload = _build_trending_payload(
            months=months,
            top_n=top_n,
            experts_per_category=experts_per_category,
        )
        payload["_cacheMeta"] = {
            "months": int(months),
            "top": int(top_n),
            "experts": int(experts_per_category),
            "generatedAt": payload.get("generatedAt"),
        }
        return payload

    with _trends_lock:
        if app is not None:
            with app.app_context():
                payload = _build()
        else:
            payload = _build()

        _trends_cache = payload
        _trends_cache_meta = dict(payload.get("_cacheMeta") or {})
        _save_trends_cache_file(payload)
        return payload


def get_trends_cached(app, months: int = 12, top_n: int = 6, experts_per_category: int = 5, force_refresh: bool = False):
    """
    Return cached trends for default parameters.
    For non-default parameter combinations or force_refresh, compute fresh payload.
    """
    global _trends_cache, _trends_cache_meta

    params_match_default = int(months) == 12 and int(top_n) == 6 and int(experts_per_category) == 5
    if force_refresh:
        return build_trends_cache(app, months=months, top_n=top_n, experts_per_category=experts_per_category)

    if not params_match_default:
        # Custom queries are generated on demand and not persisted.
        if app is not None:
            with app.app_context():
                return _build_trending_payload(
                    months=months,
                    top_n=top_n,
                    experts_per_category=experts_per_category,
                )
        return _build_trending_payload(
            months=months,
            top_n=top_n,
            experts_per_category=experts_per_category,
        )

    with _trends_lock:
        if _trends_cache and isinstance(_trends_cache, dict) and _trends_cache.get("categories") is not None:
            return dict(_trends_cache)

        file_payload = _load_trends_cache_file()
        if file_payload:
            _trends_cache = file_payload
            _trends_cache_meta = dict(file_payload.get("_cacheMeta") or {})
            return dict(file_payload)

    # Cold start fallback: build once
    return build_trends_cache(app, months=months, top_n=top_n, experts_per_category=experts_per_category)


def build_index(app):
    global _index, _paper_ids, _embeddings, _id_to_idx, _cache_meta

    with _build_lock:
        with app.app_context():
            papers = Paper.query.filter(Paper.is_public_clause()).all()
            texts, ids = [], []
            max_pid = 0
            for p in papers:
                if p.id and p.id > max_pid:
                    max_pid = int(p.id)
                t = _paper_text(p)
                if t.strip():
                    texts.append(t)
                    ids.append(p.id)
            if not texts:
                _index = None
                _paper_ids = np.array([], dtype="int64")
                _embeddings = None
                _id_to_idx = {}
                _cache_meta = {
                    "cacheVersion": EMBED_CACHE_VERSION,
                    "paperCount": 0,
                    "maxPaperId": max_pid,
                    "builtAt": datetime.now(timezone.utc).isoformat(),
                }
                return 0

            model = _get_model()
            emb = model.encode(texts, show_progress_bar=True, batch_size=64)
            emb = np.array(emb, dtype="float32")
            _normalize_l2(emb)

            dim = emb.shape[1]
            index = _new_ip_index(dim)
            index.add(emb)

            _index = index
            _paper_ids = np.array(ids)
            _embeddings = emb
            _id_to_idx = {pid: i for i, pid in enumerate(ids)}
            _cache_meta = {
                "cacheVersion": EMBED_CACHE_VERSION,
                "paperCount": int(len(ids)),
                "maxPaperId": int(max_pid),
                "builtAt": datetime.now(timezone.utc).isoformat(),
            }
            np.savez(
                EMBED_CACHE,
                embeddings=emb,
                paper_ids=_paper_ids,
                paper_count=np.array([_cache_meta["paperCount"]], dtype="int64"),
                max_paper_id=np.array([_cache_meta["maxPaperId"]], dtype="int64"),
                built_at=np.array([_cache_meta["builtAt"]], dtype="U64"),
                cache_version=np.array([EMBED_CACHE_VERSION], dtype="int64"),
            )
            return len(ids)


def _ensure_index(app):
    global _index, _paper_ids, _embeddings, _id_to_idx, _cache_meta

    if _index is not None:
        return

    if os.path.exists(EMBED_CACHE):
        data = np.load(EMBED_CACHE)
        emb = data["embeddings"]
        _paper_ids = data["paper_ids"]
        _embeddings = emb
        _id_to_idx = {int(pid): i for i, pid in enumerate(_paper_ids)}
        dim = emb.shape[1]
        _index = _new_ip_index(dim)
        _index.add(emb)
        cache_version = int(data["cache_version"][0]) if "cache_version" in data else 1
        paper_count = int(data["paper_count"][0]) if "paper_count" in data else int(len(_paper_ids))
        max_paper_id = int(data["max_paper_id"][0]) if "max_paper_id" in data else int(np.max(_paper_ids) if len(_paper_ids) else 0)
        built_at = str(data["built_at"][0]) if "built_at" in data else None
        _cache_meta = {
            "cacheVersion": cache_version,
            "paperCount": paper_count,
            "maxPaperId": max_paper_id,
            "builtAt": built_at,
        }
    else:
        build_index(app)


def _cosine_sim(id_a, id_b):
    """Return cosine similarity between two papers (by id)."""
    if _embeddings is None or _id_to_idx is None:
        return 0.0
    ia = _id_to_idx.get(int(id_a))
    ib = _id_to_idx.get(int(id_b))
    if ia is None or ib is None:
        return 0.0
    return float(np.dot(_embeddings[ia], _embeddings[ib]))


# ── Endpoints ───────────────────────────────────────────────────────────


@knowledge_bp.route("/search", methods=["POST"])
@token_required
def search():
    data = request.get_json(silent=True) or {}
    query = data.get("query", "").strip()
    try:
        top_k = int(data.get("topK", 40))
    except (TypeError, ValueError):
        top_k = 40
    top_k = min(max(top_k, 1), 100)

    if not query:
        return jsonify({"error": "请输入搜索关键词"}), 400

    _ensure_index(current_app._get_current_object())
    query_terms = _extract_query_terms(query)

    # ── Step 1: keyword search in DB ────────────────────────────────
    like_conditions = []
    base_like = f"%{query}%"
    like_conditions.extend([
        Paper.title.ilike(base_like),
        Paper.title_zh.ilike(base_like),
        Paper.abstract.ilike(base_like),
        Paper.keywords_json.ilike(base_like),
        Paper.category.ilike(base_like),
    ])
    for term in query_terms[:10]:
        term_like = f"%{term}%"
        like_conditions.extend([
            Paper.title.ilike(term_like),
            Paper.title_zh.ilike(term_like),
            Paper.abstract.ilike(term_like),
            Paper.keywords_json.ilike(term_like),
            Paper.category.ilike(term_like),
        ])

    kw_papers = Paper.query.filter(Paper.is_public_clause(), or_(*like_conditions)).limit(top_k * 4).all()
    kw_ids = {p.id for p in kw_papers}

    # ── Step 2: vector search (expand beyond keyword hits) ──────────
    vec_ids_scores = {}
    if _index is not None and _index.ntotal > 0:
        model = _get_model()
        q_vec = model.encode([query])
        q_vec = np.array(q_vec, dtype="float32")
        _normalize_l2(q_vec)
        k = min(max(top_k * 4, 60), _index.ntotal)
        scores, indices = _index.search(q_vec, k)
        for idx, sc in zip(indices[0], scores[0]):
            if idx < 0:
                continue
            pid = int(_paper_ids[idx])
            vec_ids_scores[pid] = max(vec_ids_scores.get(pid, -1.0), float(sc))

    # ── Step 3: merge & score ───────────────────────────────────────
    all_ids = kw_ids | set(vec_ids_scores.keys())
    if not all_ids:
        return jsonify({"nodes": [], "edges": [], "query": query, "meta": {"terms": query_terms}})
    papers = Paper.query.filter(Paper.is_public_clause(), Paper.id.in_(all_ids)).all()
    paper_map = {p.id: p for p in papers}

    nodes = []
    for pid in all_ids:
        p = paper_map.get(pid)
        if not p:
            continue
        vec_raw = vec_ids_scores.get(pid, -1.0)
        vec_sc = max(0.0, min(1.0, (vec_raw + 1.0) / 2.0))
        is_kw = pid in kw_ids
        lexical_info = _lexical_score(p, query, query_terms)
        lexical_sc = lexical_info["score"]
        exact_title_hit = lexical_info["exactTitleHit"]
        exact_text_hit = lexical_info["exactTextHit"]
        combined = 0.62 * vec_sc + 0.38 * lexical_sc
        boost = 0.0
        if is_kw:
            boost += 0.04
        if exact_title_hit:
            boost += 0.06
        if exact_text_hit:
            boost += 0.03
        combined = max(0.0, min(1.0, combined + boost))

        min_keep_score = 0.26
        if combined < min_keep_score and lexical_sc < 0.12 and not is_kw:
            continue
        d = p.to_dict(include_summary=False)
        d["score"] = round(combined, 3)
        d["semanticScore"] = round(vec_sc, 3)
        d["lexicalScore"] = round(lexical_sc, 3)
        d["exactTitleHit"] = exact_title_hit
        d["matchedTerms"] = lexical_info.get("matchedTerms", [])
        d["titleMatchedTerms"] = lexical_info.get("matchedTitleTerms", [])
        d["relevance"] = {
            "semantic": round(vec_sc, 3),
            "lexical": round(lexical_sc, 3),
            "boost": round(boost, 3),
            "keywordHit": bool(is_kw),
            "exactTitleHit": bool(exact_title_hit),
            "exactTextHit": bool(exact_text_hit),
            "fullTermHits": int(lexical_info.get("fullHits", 0)),
            "titleTermHits": int(lexical_info.get("titleHits", 0)),
            "keywordTermHits": int(lexical_info.get("keywordHits", 0)),
            "categoryTermHits": int(lexical_info.get("categoryHits", 0)),
        }
        d["relevanceReasons"] = _build_relevance_reasons(is_kw, vec_sc, lexical_info)
        d["keywordHit"] = is_kw
        d["_pid"] = pid
        nodes.append(d)

    # Sort by blended score, then lexical confidence.
    nodes.sort(
        key=lambda x: (
            x.get("score", 0),
            x.get("exactTitleHit", False),
            x.get("lexicalScore", 0),
            x.get("semanticScore", 0),
        ),
        reverse=True,
    )
    nodes = nodes[:top_k]

    # ── Step 4: build edges from cosine similarity between papers ───
    edges = []
    SIM_THRESHOLD = 0.62 if len(nodes) > 18 else 0.58
    node_pids = [n["_pid"] for n in nodes]

    for i in range(len(nodes)):
        kw1 = set(nodes[i].get("keywords") or [])
        for j in range(i + 1, len(nodes)):
            sim = _cosine_sim(node_pids[i], node_pids[j])
            kw2 = set(nodes[j].get("keywords") or [])
            shared_kw = kw1 & kw2
            shared_kw_count = len(shared_kw)
            if sim >= SIM_THRESHOLD or (shared_kw_count >= 2 and sim >= 0.45):
                label_parts = list(shared_kw)[:3]
                if not label_parts and sim >= SIM_THRESHOLD:
                    label_parts = [f"相似度 {sim:.0%}"]
                edges.append({
                    "source": nodes[i]["articleNumber"],
                    "target": nodes[j]["articleNumber"],
                    "similarity": round(sim, 3),
                    "sharedKeywords": list(shared_kw),
                    "label": " · ".join(label_parts),
                    "weight": round(sim * 2.8 + shared_kw_count * 0.7, 2),
                })

    # Clean internal fields
    for n in nodes:
        n.pop("_pid", None)

    return jsonify({
        "nodes": nodes,
        "edges": edges,
        "query": query,
        "meta": {
            "terms": query_terms,
            "simThreshold": SIM_THRESHOLD,
        },
    })


@knowledge_bp.route("/build-index", methods=["POST"])
@token_required
def rebuild_index():
    count = build_index(current_app._get_current_object())
    return jsonify({"message": f"索引已重建，共 {count} 篇论文"})


@knowledge_bp.route("/status", methods=["GET"])
@token_required
def index_status():
    _ensure_index(current_app._get_current_object())
    ready = _index is not None and _index.ntotal > 0
    cached = os.path.exists(EMBED_CACHE)
    indexed_count = int(_index.ntotal) if _index else 0
    db_count = int(Paper.query.filter(Paper.is_public_clause()).count())
    db_max_id = db.session.query(func.max(Paper.id)).filter(Paper.is_public_clause()).scalar() if db_count else 0
    db_max_id = int(db_max_id or 0)
    stale = bool(
        int(_cache_meta.get("cacheVersion", 1)) < EMBED_CACHE_VERSION
        or
        _cache_meta.get("paperCount", 0) != db_count
        or _cache_meta.get("maxPaperId", 0) != db_max_id
    )
    return jsonify({
        "ready": ready,
        "cached": cached,
        "paperCount": indexed_count,
        "dbPaperCount": db_count,
        "cachePaperCount": int(_cache_meta.get("paperCount", 0)),
        "stale": stale,
        "builtAt": _cache_meta.get("builtAt"),
        "cacheVersion": int(_cache_meta.get("cacheVersion", 1)),
    })


@knowledge_bp.route("/trends", methods=["GET"])
@token_required
def knowledge_trends():
    try:
        months = int(request.args.get("months", 12))
    except (TypeError, ValueError):
        months = 12
    try:
        top_n = int(request.args.get("top", 6))
    except (TypeError, ValueError):
        top_n = 6
    try:
        experts_per_category = int(request.args.get("experts", 5))
    except (TypeError, ValueError):
        experts_per_category = 5

    months = min(max(months, 6), 24)
    top_n = min(max(top_n, 3), 10)
    experts_per_category = min(max(experts_per_category, 3), 8)
    refresh = str(request.args.get("refresh", "")).strip().lower() in {"1", "true", "yes", "on"}
    payload = get_trends_cached(
        current_app._get_current_object(),
        months=months,
        top_n=top_n,
        experts_per_category=experts_per_category,
        force_refresh=refresh,
    )
    return jsonify(payload)


@knowledge_bp.route("/publication-stats", methods=["GET"])
@token_required
def publication_stats():
    payload = _build_publication_stats_payload()
    return jsonify(payload)
