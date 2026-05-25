import re

# Keep patterns conservative to avoid filtering normal research papers.
_EN_PATTERNS = [
    re.compile(r"table\s+of\s+contents", re.IGNORECASE),
    re.compile(r"^contents$", re.IGNORECASE),
    re.compile(r"^issue\s+contents$", re.IGNORECASE),
    re.compile(r"^front\s+matter$", re.IGNORECASE),
    re.compile(r"^masthead$", re.IGNORECASE),
    re.compile(r"^editorial\s+board$", re.IGNORECASE),
    re.compile(r"^in\s+this\s+issue$", re.IGNORECASE),
    re.compile(r"^cover(\s+page)?$", re.IGNORECASE),
    re.compile(r"^(erratum|corrigendum)\b", re.IGNORECASE),
    re.compile(r"^call\s+for\s+papers?$", re.IGNORECASE),
]

_ZH_PATTERNS = [
    re.compile(r"目录"),
    re.compile(r"目次"),
    re.compile(r"卷首语"),
    re.compile(r"编者按"),
    re.compile(r"征稿启事"),
]


def is_index_or_toc_content(title: str, abstract: str = "") -> bool:
    text = (title or "").strip()
    if not text:
        return False

    lower_text = text.lower()
    for p in _EN_PATTERNS:
        if p.search(lower_text):
            return True

    for p in _ZH_PATTERNS:
        if p.search(text):
            return True

    # A few sites include explicit tag words in abstract for non-research pages.
    abs_text = (abstract or "").strip().lower()
    if abs_text and ("table of contents" in abs_text or "issue contents" in abs_text):
        return True

    return False


def is_paper_index_or_toc(paper) -> bool:
    if paper is None:
        return False
    return is_index_or_toc_content(getattr(paper, "title", ""), getattr(paper, "abstract", ""))
