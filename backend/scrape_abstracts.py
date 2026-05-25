"""
从 ScienceDirect 页面批量抓取缺失的论文摘要。
使用 Selenium + stealth + BeautifulSoup 绕过反爬并可靠解析。
"""
import json
import re
import sys
import time
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium_stealth import stealth

from app import create_app
from models import Paper, db


def make_driver():
    opts = Options()
    opts.add_argument('--headless=new')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-blink-features=AutomationControlled')
    opts.add_argument('--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    driver = webdriver.Chrome(options=opts)
    stealth(driver, languages=['en-US', 'en'], vendor='Google Inc.', platform='MacIntel',
            webgl_vendor='Intel Inc.', renderer='Intel Iris OpenGL Engine', fix_hairline=True)
    return driver


def get_sd_url(paper):
    """从 source_url 中提取 PII，构造 ScienceDirect 文章页面 URL"""
    url = paper.source_url or ''
    m = re.search(r'/pii/([A-Za-z0-9]+)', url)
    if m:
        pii = m.group(1)
        return f'https://www.sciencedirect.com/science/article/pii/{pii}'
    arn = paper.article_number or ''
    if arn.startswith('crossref_'):
        doi_raw = arn[9:]
        m2 = re.match(r'(10\.\d{4,9})_(.*)', doi_raw)
        if m2:
            doi = f'{m2.group(1)}/{m2.group(2)}'
            return f'https://doi.org/{doi}'
    return None


def scrape_abstract(driver, url):
    """从 ScienceDirect 页面抓取 Abstract 文本（BeautifulSoup 解析更可靠）"""
    driver.get(url)
    time.sleep(6)
    try:
        driver.execute_script("window.scrollTo(0, 500)")
        time.sleep(1)
    except Exception:
        pass

    soup = BeautifulSoup(driver.page_source, 'html.parser')

    # 方法1: 找 div.abstract 中 heading 为 "Abstract" 的段落
    for div in soup.select('div.abstract'):
        h = div.find(['h2', 'h3'])
        if not h:
            continue
        heading = h.get_text(strip=True).lower()
        if 'abstract' not in heading or 'graphical' in heading:
            continue
        # 获取段落文本
        paras = div.find_all('p')
        text = ' '.join(p.get_text(strip=True) for p in paras if len(p.get_text(strip=True)) > 30)
        if text and len(text) > 50:
            return text
        # 回退：去掉标题的所有文本
        full = div.get_text(separator=' ', strip=True)
        heading_text = h.get_text(strip=True)
        abstract = full.replace(heading_text, '', 1).strip()
        if len(abstract) > 50:
            return abstract

    # 方法2: 找 id 含 "abs0005" 的 div（ScienceDirect 标准 abstract id）
    abs_div = soup.find('div', id='abs0005')
    if abs_div:
        text = abs_div.get_text(separator=' ', strip=True)
        if text.lower().startswith('abstract'):
            text = text[8:].strip()
        if len(text) > 50:
            return text

    # 方法3: JSON-LD description
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict) and data.get('description'):
                desc = data['description']
                if len(desc) > 80:
                    return desc
        except Exception:
            pass

    return None


def main():
    app = create_app()
    with app.app_context():
        papers = Paper.query.filter(
            (Paper.abstract.is_(None)) | (Paper.abstract == '')
        ).order_by(Paper.id).all()

        total = len(papers)
        print(f'共 {total} 篇论文缺少摘要')
        if total == 0:
            return

        driver = make_driver()
        success = 0
        fail = 0

        try:
            for i, p in enumerate(papers, 1):
                title = (p.title or '').strip()
                # 跳过无意义条目
                if not title or title in ('Table of Contents', 'Blank Page',
                                          'IEEE Transactions on Smart Grid Information for Authors'):
                    print(f'[{i}/{total}] 跳过（无意义条目）: {title}')
                    continue

                url = get_sd_url(p)
                if not url:
                    print(f'[{i}/{total}] 跳过（无URL）: {title[:50]}')
                    fail += 1
                    continue

                print(f'[{i}/{total}] {title[:60]}...')
                try:
                    abstract = scrape_abstract(driver, url)
                    if abstract:
                        p.abstract = abstract
                        db.session.commit()
                        success += 1
                        print(f'  ✓ 获取成功 ({len(abstract)} chars)')
                    else:
                        fail += 1
                        print(f'  ✗ 页面无摘要')
                except Exception as e:
                    fail += 1
                    print(f'  ✗ 错误: {e}')

                # 每20篇重启浏览器，防止内存泄漏
                if i % 20 == 0:
                    driver.quit()
                    print('  [重启浏览器]')
                    time.sleep(3)
                    driver = make_driver()
                else:
                    time.sleep(3)  # 间隔3秒避免被封

        finally:
            driver.quit()

        print(f'\n完成！成功: {success}, 失败: {fail}, 总计: {total}')


if __name__ == '__main__':
    main()
