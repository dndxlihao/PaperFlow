import os
import json
import re
import html
from openai import OpenAI
from flask import current_app


def get_client() -> OpenAI:
    return OpenAI(
        api_key=current_app.config["DEEPSEEK_API_KEY"],
        base_url=current_app.config["DEEPSEEK_BASE_URL"],
        timeout=120,
    )


SYSTEM_PROMPT = (
    "你是一位专业的学术论文分析专家。请根据提供的论文信息撰写一篇600-1000字的中文论文总结。\n\n"
    "输出要求（严格遵循）：\n"
    "1. 直接输出正文，不要使用任何 Markdown 语法（不要用 #、**、*、- 等标记）\n"
    "2. 使用以下 HTML 标签来格式化：\n"
    "   - 段落标题用 <h4>标题</h4>\n"
    "   - 普通段落用 <p>内容</p>，每段开头要有两个全角空格（首行缩进）\n"
    "   - 重要术语、模型名称用 <b class=\"term\">术语</b>（会显示为红色加粗）\n"
    "   - 关键结论用 <b class=\"conclusion\">结论内容</b>（会显示为红色加粗）\n"
    "   - 数字和指标用 <b>数值</b>\n\n"
    "3. 内容结构：\n"
    "   <h4>研究背景与动机</h4>\n"
    "   <p>　　正文...</p>\n"
    "   <h4>核心方法</h4>\n"
    "   <p>　　正文...</p>\n"
    "   <h4>关键创新</h4>\n"
    "   <p>　　正文...</p>\n"
    "   <h4>实验与结论</h4>\n"
    "   <p>　　正文...</p>\n"
    "   <h4>意义与展望</h4>\n"
    "   <p>　　正文...</p>\n\n"
    "请确保内容专业、连贯，重要术语和结论使用 class=\"term\" 或 class=\"conclusion\" 标记。"
)

KEYWORDS_PROMPT = (
    "请根据以下论文标题和摘要，返回一个JSON对象，包含：\n"
    '1. "keywords": 3-4个中文关键词的数组\n'
    '2. "category": 论文所属的一个主类别（从以下选项中选一个最匹配的）：\n'
    "   大模型, 强化学习, 计算机视觉, 自然语言处理, 图神经网络, 生成模型, "
    "   多模态, 推荐系统, 知识图谱, 联邦学习, 优化理论, 自监督学习, "
    "   对比学习, 迁移学习, 数据挖掘, 机器人学, 语音处理, 生物信息学, "
    "   信号处理, 电力系统, 新能源与储能, 电动汽车与充电, 智能电网, "
    "   建筑能效与暖通, 电池技术, 综合能源系统, 氢能与燃料电池, "
    "   可再生能源, 电力市场与交易, 能源管理与优化\n\n"
    "注意：尽量选择具体的类别，避免使用\"其他\"。\n"
    "只返回JSON，不要其他文字。例如：\n"
    '{"keywords": ["大语言模型", "知识蒸馏", "推理加速"], "category": "大模型"}'
)


def summarize_paper(title: str, abstract: str, full_text: str) -> str:
    """Use DeepSeek to generate a 600-1000 word Chinese summary of the paper."""
    client = get_client()

    max_text_len = 12000
    if len(full_text) > max_text_len:
        full_text = full_text[:max_text_len] + "\n...[文本过长，已截断]"

    user_prompt = f"论文标题：{title}\n\n摘要：{abstract}\n\n正文内容：\n{full_text}"

    response = client.chat.completions.create(
        model=current_app.config["DEEPSEEK_MODEL"],
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=2000,
    )

    raw = response.choices[0].message.content.strip()
    return normalize_summary_html(raw)


def summarize_from_abstract(title: str, abstract: str) -> str:
    """Fallback: generate summary from title + abstract only (no PDF needed)."""
    client = get_client()

    user_prompt = (
        f"论文标题：{title}\n\n摘要：{abstract}\n\n"
        "重要要求：\n"
        "1. 目前仅有标题和摘要信息（无全文PDF），请严格基于摘要中明确提及的内容进行解读\n"
        "2. 不要编造摘要中未提到的具体实验数据、数值结果或对比基线\n"
        "3. 如果摘要提到了实验结果但未给出具体数字，可以概括性描述但不要虚构具体百分比\n"
        "4. 核心方法部分重点描述摘要中提到的技术路线和关键创新\n"
        "5. 请撰写600-1000字的中文深度解读"
    )

    response = client.chat.completions.create(
        model=current_app.config["DEEPSEEK_MODEL"],
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=2000,
    )

    raw = response.choices[0].message.content.strip()
    return normalize_summary_html(raw)


def _render_inline_text(text: str) -> str:
    safe = html.escape(text, quote=False)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
    safe = re.sub(r"__(.+?)__", r"<b>\1</b>", safe)
    safe = re.sub(r"`([^`]+)`", r"\1", safe)
    return safe


def normalize_summary_html(raw: str) -> str:
    """Normalize model output to stable HTML blocks for frontend rendering.

    Handles accidental Markdown output (e.g. #, **bold**) and enforces
    first-line indentation for every paragraph.
    """
    if not raw:
        return ""

    text = str(raw).replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"^```(?:html|markdown|md)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    if not text:
        return ""

    # Convert Markdown headings to h4 blocks.
    text = re.sub(
        r"(?m)^\s{0,3}#{1,6}\s+(.+?)\s*$",
        lambda m: f"<h4>{m.group(1).strip()}</h4>",
        text,
    )

    has_html = bool(re.search(r"</?(h[1-6]|p|b|strong|ul|ol|li|br)\b", text, flags=re.IGNORECASE))

    if has_html:
        # Convert Markdown bold markers when mixed into HTML output.
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

        def _indent_p(match):
            inner = (match.group(1) or "").strip()
            if not inner:
                return "<p></p>"
            if inner.startswith("　　") or inner.startswith("&emsp;&emsp;") or inner.startswith("&nbsp;&nbsp;"):
                return f"<p>{inner}</p>"
            return f"<p>　　{inner}</p>"

        text = re.sub(r"<p>\s*([\s\S]*?)\s*</p>", _indent_p, text, flags=re.IGNORECASE)
        return text.strip()

    blocks = []
    for part in re.split(r"\n\s*\n", text):
        lines = [ln.strip() for ln in part.split("\n") if ln.strip()]
        if not lines:
            continue
        merged = re.sub(r"\s+", " ", " ".join(lines)).strip()
        if not merged:
            continue
        blocks.append(f"<p>　　{_render_inline_text(merged)}</p>")

    return "\n".join(blocks).strip()


def extract_keywords_and_category(title: str, abstract: str) -> dict:
    """Extract 3-4 keywords and a category from paper title + abstract."""
    client = get_client()

    user_prompt = f"论文标题：{title}\n\n摘要：{abstract}"

    response = client.chat.completions.create(
        model=current_app.config["DEEPSEEK_MODEL"],
        messages=[
            {"role": "system", "content": KEYWORDS_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=200,
    )

    text = response.choices[0].message.content.strip()
    # Try to parse JSON from response
    try:
        # Find JSON in response
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except (json.JSONDecodeError, AttributeError):
        pass
    return {"keywords": [], "category": "其他"}
