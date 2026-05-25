import os
import time
import random
import requests
import pdfplumber
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def make_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

def _build_options(headless: bool, download_dir: str | None = None) -> Options:
    opts = Options()

    if headless:
        opts.add_argument("--headless=new")

    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,800")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    if download_dir is not None:
        prefs = {
            "download.default_directory": os.path.abspath(download_dir),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True, 
        }
        opts.add_experimental_option("prefs", prefs)

    return opts

def _open_and_get_cookies_and_ua(headless: bool, timeout: int = 60, debug: bool = False) -> tuple[str, str]:
    driver = webdriver.Chrome(options=_build_options(headless))
    try:
        url = "https://ieeexplore.ieee.org/search/searchresult.jsp?newsearch=true&queryText=sys"
        driver.get(url)

        wait = WebDriverWait(driver, timeout)
        wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
        wait.until(lambda d: len(d.get_cookies()) > 0)

        ua = driver.execute_script("return navigator.userAgent;") or ""

        if debug:
            print("CURRENT_URL =", driver.current_url)
            print("TITLE =", driver.title)
            print("UA =", ua)
            print("COOKIE_COUNT =", len(driver.get_cookies()))

        cookies = driver.get_cookies()
        cookie_header = "".join([f"{c['name']}={c['value']};" for c in cookies])
        return cookie_header, ua
    finally:
        driver.quit()

def get_cookie_and_ua(debug: bool = False) -> tuple[str, str]:
    try:
        return _open_and_get_cookies_and_ua(headless=True, timeout=60, debug=debug)
    except Exception as e:
        print("[WARN] headless 获取 cookie/ua 失败，回退到非 headless：", repr(e))
        return _open_and_get_cookies_and_ua(headless=False, timeout=90, debug=debug)

def get_pdf_links_by_issue(
    sess: requests.Session,
    cookie_head: str,
    user_agent: str,
    punumber: str,
    isnumber: str,
    page_number: int = 1,
    rows_per_page: int = 25,
    sortType: str = "paper-citations",
):
    url = "https://ieeexplore.ieee.org/rest/search"
    data = {
        "punumber": punumber,
        "isnumber": isnumber,
        "sortType": sortType,
        "pageNumber": page_number,
        "rowsPerPage": rows_per_page,
        "returnType": "SEARCH",
        "returnFacets": ["ALL"],
    }

    referer = f"https://ieeexplore.ieee.org/xpl/tocresult.jsp?isnumber={isnumber}&punumber={punumber}"
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://ieeexplore.ieee.org",
        "Referer": referer,
        "Cookie": cookie_head,
        "Connection": "keep-alive",
    }

    response = sess.post(url, json=data, headers=headers, timeout=(15, 90))
    if response.status_code != 200:
        snippet = (response.text or "")[:300]
        raise Exception(f"请求失败，状态码: {response.status_code}, body前300字: {snippet!r}")

    result_dict = response.json()
    records = result_dict.get("records", []) or []

    pdf_result = []
    for record in records:
        article_num = record.get("articleNumber", None)
        pdf_item = {
            "articleNumber": article_num,
            "articleTitle": record.get("articleTitle", None),
            "authors": [a.get("preferredName", None) for a in record.get("authors", []) if isinstance(a, dict)]
            if record.get("authors") is not None
            else "None",
            "publicationDate": record.get("publicationDate", None),
            "downloadCount": record.get("downloadCount", None),
            "displayPublicationTitle": record.get("displayPublicationTitle", None),
            "publicationTitle": record.get("publicationTitle", None),
            "pdfLink": f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={article_num}"
            if article_num
            else None,
            "abstract": record.get("abstract", None),
        }
        pdf_result.append(pdf_item)
    return pdf_result

def get_pdf_links_by_issue_pages(
    sess: requests.Session,
    cookie_head: str,
    user_agent: str,
    punumber: str,
    isnumber: str,
    start_page: int = 1,
    end_page: int = 1,
    rows_per_page: int = 25,
    sortType: str = "paper-citations",
    sleep_between_pages: float = 1.0,
):
    all_items = []
    for p in range(start_page, end_page + 1):
        items = get_pdf_links_by_issue(
            sess=sess,
            cookie_head=cookie_head,
            user_agent=user_agent,
            punumber=punumber,
            isnumber=isnumber,
            page_number=p,
            rows_per_page=rows_per_page,
            sortType=sortType,
        )
        print(f"[INFO] page {p}: {len(items)} items")
        all_items.extend(items)
        time.sleep(sleep_between_pages)
    return all_items

def download_pdf_via_selenium(
    pdf_url: str,
    out_path: str,
    headless: bool = False,
    timeout: int = 120,
    debug: bool = False,
):
    download_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(download_dir, exist_ok=True)

    if os.path.exists(out_path):
        os.remove(out_path)

    driver = webdriver.Chrome(options=_build_options(headless=headless, download_dir=download_dir))
    try:
        driver.get(pdf_url)

        start = time.time()
        while time.time() - start < timeout:
            pdfs = [f for f in os.listdir(download_dir) if f.lower().endswith(".pdf")]
            crds = [f for f in os.listdir(download_dir) if f.lower().endswith(".crdownload")]

            if debug:
                if int(time.time() - start) % 5 == 0:
                    print("[DEBUG] downloading... pdfs=", pdfs, "crdownload=", crds)

            if not crds and pdfs:
                newest = max((os.path.join(download_dir, f) for f in pdfs), key=os.path.getmtime)
                os.replace(newest, out_path)
                return True

            time.sleep(1)

        return False
    finally:
        driver.quit()

def get_pdf_doc(
    sess: requests.Session,
    cookie_head: str,
    user_agent: str,
    pdf_number: str,
    timeout: int = 180,
    retries: int = 3,
    selenium_fallback: bool = True,
):
    pdf_url = f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={pdf_number}"
    referer = f"https://ieeexplore.ieee.org/document/{pdf_number}"

    headers = {
        "User-Agent": user_agent,
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Cookie": cookie_head,
        "Referer": referer,
    }

    os.makedirs("docs", exist_ok=True)
    out_path = f"docs/{pdf_number}.pdf"

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            with sess.get(pdf_url, headers=headers, stream=True, timeout=(30, timeout)) as r:
                r.raise_for_status()

                ctype = (r.headers.get("Content-Type") or "").lower()

                if "text/html" in ctype:
                    body_head = r.content[:200]
                    raise RuntimeError(f"被拦截/返回HTML，Content-Type={ctype}, 前200字节={body_head!r}")

                with open(out_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 128):
                        if chunk:
                            f.write(chunk)
                            
            with open(out_path, "rb") as f:
                head = f.read(4)
            if head != b"%PDF":
                raise RuntimeError(f"保存的文件不像 PDF（文件头={head!r}），可能仍被拦截")

            print(f"[OK] PDF 下载成功: {out_path}")
            return pdf_number

        except Exception as e:
            last_err = e
            print(f"[WARN] 第 {attempt}/{retries} 次下载失败: {repr(e)}")
            time.sleep(2 * attempt + random.uniform(0.5, 1.5))
            if selenium_fallback and attempt == retries:
                print(f"[INFO] requests 多次失败，尝试 Selenium fallback 下载: {pdf_number}")
                ok = download_pdf_via_selenium(pdf_url=pdf_url, out_path=out_path, headless=False, timeout=120)
                if ok:
                    print(f"[OK] Selenium fallback 下载成功: {out_path}")
                    return pdf_number
                else:
                    print(f"[ERROR] Selenium fallback 也失败: {pdf_number}")

    raise last_err

def pdf_ocr(doc_path: str) -> str:
    text = ""
    with pdfplumber.open(f"docs/{doc_path}.pdf") as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            text += page_text if page_text else ""
    return text

def crawl_issue_by_pages(
    punumber: str,
    isnumber: str,
    start_page: int = 1,
    end_page: int = 1,
    rows_per_page: int = 25,
    sortType: str = "paper-citations",
    download_pdf: bool = False,
    attach_text: bool = False,
    sleep_between_downloads: float = 2.0,
    debug_selenium: bool = False,
):
    cookie_head, ua = get_cookie_and_ua(debug=debug_selenium)
    ua = ua or "Mozilla/5.0"
    sess = make_session()

    items = get_pdf_links_by_issue_pages(
        sess=sess,
        cookie_head=cookie_head,
        user_agent=ua,
        punumber=punumber,
        isnumber=isnumber,
        start_page=start_page,
        end_page=end_page,
        rows_per_page=rows_per_page,
        sortType=sortType,
    )

    if not download_pdf:
        return items

    for idx, it in enumerate(items, start=1):
        arn = it.get("articleNumber")
        if not arn:
            continue
        time.sleep(sleep_between_downloads + random.uniform(0.3, 1.2))

        try:
            get_pdf_doc(sess=sess, cookie_head=cookie_head, user_agent=ua, pdf_number=str(arn))
            if attach_text:
                it["content"] = pdf_ocr(str(arn))
        except Exception as e:
            print("[ERROR] 文档下载异常:", arn, e)
            time.sleep(5 + random.uniform(1, 3))

        if idx % 10 == 0:
            print(f"[INFO] progress: {idx}/{len(items)}")

    return items

def down_pdf(code: str):
    cookie_head, ua = get_cookie_and_ua(debug=False)
    sess = make_session()
    get_pdf_doc(sess=sess, cookie_head=cookie_head, user_agent=ua or "Mozilla/5.0", pdf_number=code)

if __name__ == "__main__":
    punumber = "59"
    isnumber = "11345511"

    items = crawl_issue_by_pages(
        punumber=punumber,
        isnumber=isnumber,
        start_page=2,
        end_page=3,     
        rows_per_page=25,
        download_pdf=True,
        attach_text=False,
        sleep_between_downloads=2.0,
        debug_selenium=False,
    )
    print(f"\nTOTAL items fetched = {len(items)}")
    print(items[:2])
