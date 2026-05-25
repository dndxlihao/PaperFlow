"""
Extract overview/framework figure from paper PDFs and generate AI explanations.
- Downloads missing arXiv PDFs
- Finds the best conceptual figure (preferring Figure 1 with caption)
- Validates images: rejects black, uniform, too small, or decoration images
- Smart cropping for vector-graphic figures (common in arXiv/conference papers)
- Generates AI explanation using figure caption + abstract (no guessing language)
"""
import io
import os
import re
import sys
import time
import fitz  # PyMuPDF
import numpy as np
from PIL import Image
from openai import OpenAI
from models import Paper, db
from crawl_arxiv import download_arxiv_pdf

FIGURES_DIR = os.path.join(os.path.dirname(__file__), "..", "figures")
PDF_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")

MIN_WIDTH = 200
MIN_HEIGHT = 150
MIN_AREA = 200 * 150

# Regex for Figure 1 captions
_FIG1_RE = re.compile(
    r'Fig(?:ure)?\.?\s*1[\.:]\s',
    re.IGNORECASE,
)
_FIG1_CAPTION_RE = re.compile(
    r'(Fig(?:ure)?\.?\s*1[\.:]\s*)([^\n]{10,200})',
    re.IGNORECASE,
)


def is_valid_image(img, lenient=False):
    """Check that the image is not mostly black, white, or uniform.
    lenient=True uses relaxed thresholds for rendered page crops."""
    arr = np.array(img.convert("RGB"))
    mean_val = float(arr.mean())
    std_val = float(arr.std())

    if mean_val < 15:       # mostly black
        return False
    if mean_val > 252:      # nearly pure white
        return False

    # Technical diagrams (black lines on white) have low std but are valid
    min_std = 10 if lenient else 15
    if std_val < min_std:
        return False

    # Check if image has enough non-black area
    gray = np.array(img.convert("L"))
    bright_ratio = (gray > 30).sum() / gray.size
    if bright_ratio < 0.10:
        return False

    return True


def is_text_heavy(img):
    """Check if an image is dominated by text rather than diagrams/plots.
    Returns True if the image appears to be mostly text."""
    gray = np.array(img.convert("L"))
    h, w = gray.shape
    if h < 30 or w < 30:
        return False

    binary = gray < 128
    # Count horizontal transitions per row (text has many small transitions)
    transitions = np.diff(binary.astype(np.int8), axis=1)
    trans_per_row = (transitions != 0).sum(axis=1)
    high_trans_rows = (trans_per_row > 30).sum()
    trans_ratio = high_trans_rows / h

    # Count rows with moderate dark pixel density (text-like)
    row_dark = binary.sum(axis=1)
    text_like_rows = ((row_dark > w * 0.03) & (row_dark < w * 0.5)).sum()
    text_ratio = text_like_rows / h

    return trans_ratio > 0.45 and text_ratio > 0.55


def find_figure_pages(doc):
    """Find pages that contain figure labels, returning {page_idx: caption_text}."""
    result = {}
    for i in range(min(len(doc), 10)):
        text = doc[i].get_text()
        m = _FIG1_CAPTION_RE.search(text)
        if m:
            result[i] = m.group(0).strip()
    return result


def _find_caption_block(page):
    """Find the text block containing Figure 1 caption. Returns (block, caption_text) or (None, None)."""
    blocks = page.get_text("blocks")
    for b in blocks:
        if b[6] == 0 and _FIG1_RE.search(b[4]):
            m = _FIG1_CAPTION_RE.search(b[4])
            caption = m.group(0).strip() if m else b[4].strip()[:100]
            return b, caption
    return None, None


def _auto_trim(img):
    """Trim whitespace borders from an image."""
    gray = np.array(img.convert("L"))
    h, w = gray.shape
    row_dark = (gray < 240).sum(axis=1)
    col_dark = (gray < 240).sum(axis=0)
    rows = np.where(row_dark > w * 0.005)[0]
    cols = np.where(col_dark > h * 0.005)[0]
    if len(rows) < 3 or len(cols) < 3:
        return img
    top = max(0, rows[0] - 5)
    bottom = min(h, rows[-1] + 5)
    left = max(0, cols[0] - 5)
    right = min(w, cols[-1] + 5)
    return img.crop((left, top, right, bottom))


def _trim_top_text(img):
    """Remove text paragraphs leaked into the top of a figure crop."""
    gray = np.array(img.convert("L"))
    h, w = gray.shape
    if h < 80:
        return img

    row_dark_ratio = (gray < 200).sum(axis=1) / w

    # Find whitespace gaps (nearly empty rows) in top 55%
    gap_threshold = 0.005
    in_gap = False
    gaps = []
    gap_start = 0
    cutoff = int(h * 0.55)
    for y in range(cutoff):
        if row_dark_ratio[y] < gap_threshold:
            if not in_gap:
                gap_start = y
                in_gap = True
        else:
            if in_gap and (y - gap_start) >= 4:
                gaps.append((gap_start, y))
            in_gap = False

    if not gaps:
        return img

    # Check each gap: if content above is text-heavy, trim it
    for gs, ge in gaps:
        above = gray[:gs]
        if above.shape[0] < 20:
            continue
        binary = above < 128
        trans = np.diff(binary.astype(np.int8), axis=1)
        trans_per_row = (trans != 0).sum(axis=1)
        hi_trans = (trans_per_row > 20).sum() / above.shape[0]
        if hi_trans > 0.5:
            return img.crop((0, ge, w, h))

    return img


def smart_crop_figure(doc, page_num):
    """Extract Figure 1 from a page using caption position and drawing bounds.
    Returns (img_pil, caption_text) or (None, None).
    Used for papers with vector graphics (no embedded raster images)."""
    page = doc[page_num]
    pw, ph = page.rect.width, page.rect.height

    cap_block, caption_text = _find_caption_block(page)
    if not cap_block:
        return None, None

    cap_rect = fitz.Rect(cap_block[0], cap_block[1], cap_block[2], cap_block[3])
    cap_top = cap_rect.y0

    # Determine column (two-column vs full-width layout)
    mid = pw / 2
    if cap_rect.x1 < mid + 20:
        col_left, col_right = 0, mid
    elif cap_rect.x0 > mid - 20:
        col_left, col_right = mid, pw
    else:
        col_left, col_right = 0, pw

    # Strategy 1: Use drawing/path bounding box to find figure region
    drawings = page.get_drawings()
    draw_rects = [d["rect"] for d in drawings
                  if d["rect"].width > 8 and d["rect"].height > 8]
    above_cap_draws = [r for r in draw_rects
                       if r.y0 < cap_top and r.y1 > cap_top - 350
                       and r.x0 >= col_left - 10 and r.x1 <= col_right + 10]

    if len(above_cap_draws) >= 3:
        fig_top = min(r.y0 for r in above_cap_draws)
        fig_bottom = max(r.y1 for r in above_cap_draws)
        # Ensure reasonable size and not too far from caption
        if fig_bottom > cap_top - 200:
            fig_bottom = cap_top - 2
        if cap_top - fig_top > 20:
            padding = 10
            clip = fitz.Rect(
                max(0, col_left),
                max(0, fig_top - padding),
                min(pw, col_right),
                min(ph, fig_bottom + padding),
            )
            scale = 2.5
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip)
            img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            img = _auto_trim(img)
            w, h = img.size
            if w >= 100 and h >= 60:
                return img, caption_text

    # Strategy 2: Crop region above caption with limited height
    max_height = min(250, ph * 0.5)
    fig_top = max(0, cap_top - max_height)
    fig_bottom = cap_top - 2
    if fig_bottom - fig_top < 40:
        return None, caption_text

    clip = fitz.Rect(
        max(0, col_left),
        fig_top,
        min(pw, col_right),
        fig_bottom,
    )
    scale = 2.5
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    img = _auto_trim(img)
    img = _trim_top_text(img)

    w, h = img.size
    if w < 100 or h < 60:
        return None, caption_text

    return img, caption_text


def render_page_figure(doc, page_num, fig_pages):
    """Render a page to image and crop the figure area (last-resort fallback)."""
    page = doc[page_num]
    mat = fitz.Matrix(2, 2)
    pix = page.get_pixmap(matrix=mat)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    img = img.convert("RGB")

    w, h = img.size
    top = int(h * 0.15)
    bottom = int(h * 0.85)
    left = int(w * 0.05)
    right = int(w * 0.95)
    cropped = img.crop((left, top, right, bottom))

    if not is_valid_image(cropped, lenient=True):
        return None

    return cropped


def extract_best_figure(pdf_path, out_path):
    """
    Extract the best overview/conceptual figure from a PDF.
    Returns (found: bool, caption: str or None).
    Strategy:
      1) Try extracting embedded raster images (scored by size/page/caption)
      2) Smart-crop vector figures using caption position + drawing bounds
      3) Last-resort page rendering (only if not text-heavy)
    """
    doc = fitz.open(pdf_path)

    # Find pages with "Figure 1" label and caption
    fig_pages = find_figure_pages(doc)
    caption = None
    if fig_pages:
        caption = list(fig_pages.values())[0]

    candidates = []  # (score, page_num, img_pil)
    has_large_embedded = False

    for page_num in range(min(len(doc), 10)):
        page = doc[page_num]
        images = page.get_images(full=True)

        for img_info in images:
            xref = img_info[0]
            try:
                img_data = doc.extract_image(xref)
                if not img_data:
                    continue
                img_bytes = img_data["image"]
                img = Image.open(io.BytesIO(img_bytes))
                img = img.convert("RGB")
            except Exception:
                continue

            w, h = img.size

            if w < MIN_WIDTH or h < MIN_HEIGHT or w * h < MIN_AREA:
                continue

            aspect = w / h
            if aspect > 5 or aspect < 0.15:
                continue

            if not is_valid_image(img):
                continue

            has_large_embedded = True

            score = 0
            area = w * h
            score += area / 100000

            if page_num in fig_pages:
                score += 50

            if 1 <= page_num <= 2:
                score += 10
            elif page_num <= 4:
                score += 5

            if page_num == 0:
                score -= 5

            if 0.5 <= aspect <= 2.5:
                score += 5

            # Reject text-heavy images to avoid selecting PDF page snapshots.
            if is_text_heavy(img):
                continue

            candidates.append((score, page_num, img))

    # Smart-crop fallback: use caption position for vector-graphic figures
    if not has_large_embedded:
        for pg in sorted(fig_pages.keys()):
            cropped, cap_text = smart_crop_figure(doc, pg)
            if cropped and not is_text_heavy(cropped):
                w, h = cropped.size
                score = 40
                score += 20
                candidates.append((score, pg, cropped))
                if cap_text and not caption:
                    caption = cap_text
                break

    doc.close()

    if not candidates:
        return False, None

    candidates.sort(key=lambda x: x[0], reverse=True)
    best_score, best_page, best_img = candidates[0]
    best_img.save(out_path, format="PNG")
    return True, caption


def generate_figure_explanation(client, model, title, abstract, caption=None):
    """Generate explanation for the figure using caption + abstract."""
    caption_part = ""
    if caption:
        caption_part = f"图片标注/说明文字：{caption}\n"

    prompt = (
        f"论文标题：{title}\n"
        f"摘要：{abstract[:600]}\n"
        f"{caption_part}\n"
        "请用中文概括这篇论文的核心方法框架（150-200字）。要求：\n"
        "1. 直接描述方法的主要模块、数据流向和关键技术步骤\n"
        "2. 语气确定，不要用'可能''大概''很可能是'等猜测性表达\n"
        "3. 不要说'根据标题和摘要'，直接输出内容\n"
        "4. 重点描述系统如何运作，而非论文贡献"
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "你是学术论文方法论分析专家。直接、确定地描述论文方法框架。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=500,
    )
    return response.choices[0].message.content.strip()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                        help="Re-extract all figures, even those already processed")
    args = parser.parse_args()

    os.makedirs(FIGURES_DIR, exist_ok=True)
    os.makedirs(PDF_DIR, exist_ok=True)

    from app import create_app
    app = create_app()
    with app.app_context():
        client = OpenAI(
            api_key=app.config["DEEPSEEK_API_KEY"],
            base_url=app.config["DEEPSEEK_BASE_URL"],
        )
        model = app.config["DEEPSEEK_MODEL"]

        if args.force:
            # Clear old figure data for re-extraction
            papers = Paper.query.all()
            for p in papers:
                p.figure_path = None
                p.figure_explanation = None
            db.session.commit()
            print("Cleared all existing figure data.")
        else:
            papers = Paper.query.filter(
                (Paper.figure_path == None) | (Paper.figure_path == "")
            ).all()

        print(f"Processing {len(papers)} papers...")

        success = 0
        no_pdf = 0
        no_fig = 0
        errors = 0

        for i, paper in enumerate(papers, 1):
            arn = paper.article_number
            fig_filename = f"{arn}.png"
            fig_path = os.path.join(FIGURES_DIR, fig_filename)

            # Step 1: Ensure PDF exists
            pdf_path = None
            if paper.pdf_path and os.path.exists(paper.pdf_path):
                pdf_path = paper.pdf_path
            else:
                expected = os.path.join(PDF_DIR, f"{arn}.pdf")
                if os.path.exists(expected):
                    pdf_path = expected
                elif arn.startswith("arxiv_"):
                    print(f"[{i}/{len(papers)}] Downloading PDF for {arn}...")
                    try:
                        pdf_path = download_arxiv_pdf(arn, out_dir=PDF_DIR)
                        paper.pdf_path = pdf_path
                        db.session.commit()
                        time.sleep(1)
                    except Exception as e:
                        print(f"  ✗ PDF download failed: {e}")
                        errors += 1
                        continue

            if not pdf_path or not os.path.exists(pdf_path):
                print(f"[{i}/{len(papers)}] No PDF for {arn}")
                no_pdf += 1
                continue

            # Step 2: Extract best figure
            print(f"[{i}/{len(papers)}] Extracting from {arn}...")
            try:
                found, caption = extract_best_figure(pdf_path, fig_path)
            except Exception as e:
                print(f"  ✗ Extraction error: {e}")
                errors += 1
                continue

            if not found:
                print(f"  - No valid figure found, skipping")
                no_fig += 1
                continue

            fig_size = os.path.getsize(fig_path)
            print(f"  ✓ Figure saved ({fig_size} bytes)"
                  + (f" caption: {caption[:60]}..." if caption else ""))

            # Step 3: Generate AI explanation
            try:
                explanation = generate_figure_explanation(
                    client, model,
                    paper.title or "",
                    paper.abstract or "",
                    caption
                )
                paper.figure_path = fig_filename
                paper.figure_explanation = explanation
                db.session.commit()
                success += 1
                print(f"  ✓ Explanation ({len(explanation)} chars)")
            except Exception as e:
                paper.figure_path = fig_filename
                db.session.commit()
                success += 1
                print(f"  ⚠ Figure saved but explanation failed: {e}")

            time.sleep(0.5)

        print(f"\nDone! Success: {success}, No PDF: {no_pdf}, "
              f"No valid figure: {no_fig}, Errors: {errors}")


if __name__ == "__main__":
    main()
