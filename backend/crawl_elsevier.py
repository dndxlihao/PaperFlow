"""
Elsevier / ScienceDirect paper crawler.
Uses the Elsevier ScienceDirect search API and Scopus API.
For public access without API key, we use the ScienceDirect search scraping approach.
"""

import os
import re
import time
import urllib.parse
import requests


SCOPUS_SEARCH_URL = "https://api.elsevier.com/content/search/scopus"
SCIENCEDIRECT_SEARCH_URL = "https://api.elsevier.com/content/search/sciencedirect"
UNPAYWALL_API = "https://api.unpaywall.org/v2"
CROSSREF_WORKS_API = "https://api.crossref.org/works"

DOI_CODE_PATTERN = re.compile(r"^(10\.\d{4,9})_(.+)$", re.IGNORECASE)
DOI_IN_TEXT_PATTERN = re.compile(r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.IGNORECASE)
PII_IN_URL_PATTERN = re.compile(r"/pii/([A-Za-z0-9]+)", re.IGNORECASE)
ABS_URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)
RELATIVE_PDF_PATTERN = re.compile(r"(/science/article/pii/[A-Za-z0-9]+/(?:pdf|pdfft)[^\"'<>\\s]*)", re.IGNORECASE)
ABS_PDF_PATTERN = re.compile(r"(https?://[^\"'<>\\s]+(?:\\.pdf(?:\\?|$)|/pdf(?:\\?|$)|/pdfft[^\"'<>\\s]*))", re.IGNORECASE)
EMAIL_CONTACT = "paperflow@example.com"
HUMAN_VERIFICATION_URL_MARKERS = (
    "captcha",
    "challenge",
    "cf_chl",
    "turnstile",
    "verify",
)
HUMAN_VERIFICATION_TITLE_MARKERS = (
    "just a moment",
    "attention required",
    "verify you are human",
    "human verification",
    "captcha",
)
HUMAN_VERIFICATION_TEXT_MARKERS = (
    "verify you are human",
    "human verification",
    "please verify",
    "press and hold",
    "security check",
    "enter the characters",
    "i am not a robot",
    "hcaptcha",
    "g-recaptcha",
    "cloudflare",
    "cf-challenge",
    "challenge-platform",
    "访问验证",
    "人机验证",
    "安全验证",
    "验证码",
)


def _is_pdf_bytes(payload: bytes) -> bool:
    return bool(payload and payload[:4] == b"%PDF")


def _is_valid_pdf_file(path: str) -> bool:
    try:
        if not os.path.exists(path) or os.path.getsize(path) < 2048:
            return False
        with open(path, "rb") as f:
            return _is_pdf_bytes(f.read(4))
    except Exception:
        return False


def _normalize_doi(value: str) -> str:
    if not value:
        return ""
    text = str(value).strip()
    text = text.replace("https://doi.org/", "").replace("http://doi.org/", "")
    text = text.replace("https://dx.doi.org/", "").replace("http://dx.doi.org/", "")
    return text.strip()


def extract_doi_from_article_number(article_number: str) -> str:
    arn = (article_number or "").strip()
    if not arn:
        return ""

    if arn.startswith("crossref_"):
        raw = arn[len("crossref_"):]
    elif arn.startswith("elsevier_"):
        raw = arn[len("elsevier_"):]
    else:
        raw = arn

    raw = urllib.parse.unquote(raw).strip()
    if raw.lower().startswith("10.") and "/" in raw:
        return _normalize_doi(raw)

    m = DOI_CODE_PATTERN.match(raw)
    if m:
        return _normalize_doi(f"{m.group(1)}/{m.group(2)}")
    return ""


def extract_pii_from_article_number(article_number: str) -> str:
    arn = (article_number or "").strip()
    if not arn.startswith("elsevier_"):
        return ""
    raw = urllib.parse.unquote(arn[len("elsevier_"):]).strip()
    if not raw:
        return ""
    if raw.lower().startswith("10."):
        return ""
    # Typical PII starts with S and is alnum (sometimes with X).
    if re.fullmatch(r"[A-Za-z0-9]{8,30}", raw):
        return raw
    return ""


def _extract_pii_from_url(url: str) -> str:
    if not url:
        return ""
    m = PII_IN_URL_PATTERN.search(url)
    return m.group(1) if m else ""


def _safe_get(sess: requests.Session, url: str, **kwargs):
    try:
        return sess.get(url, **kwargs)
    except Exception:
        return None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def _env_str(name: str, default: str = "") -> str:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = str(raw).strip()
    return value if value else default


def _discover_local_chrome_profile_dir() -> str:
    candidates = [
        os.environ.get("ELSEVIER_CHROME_USER_DATA_DIR", "").strip(),
        os.path.expanduser("~/Library/Application Support/Google/Chrome"),
        os.path.expanduser("~/.config/google-chrome"),
        os.path.expanduser("~/AppData/Local/Google/Chrome/User Data"),
    ]
    for path in candidates:
        if path and os.path.isdir(path):
            return path
    return ""


def _wait_for_new_pdf(download_dir: str, baseline_files: set[str], timeout: int) -> str:
    started = time.time()
    while time.time() - started < timeout:
        try:
            all_files = os.listdir(download_dir)
        except OSError:
            return ""

        new_pdfs = [
            os.path.join(download_dir, name)
            for name in all_files
            if name.lower().endswith(".pdf") and name not in baseline_files
        ]
        active = [name for name in all_files if name.lower().endswith(".crdownload")]

        # Only accept finished and valid PDF.
        if new_pdfs and not active:
            new_pdfs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            for path in new_pdfs:
                if _is_valid_pdf_file(path):
                    return path

        time.sleep(1)
    return ""


def _collect_pdf_links_from_browser(driver) -> list[str]:
    try:
        links = driver.execute_script(
            """
            const out = new Set();
            const push = (u) => {
              if (!u || typeof u !== "string") return;
              const s = u.trim();
              if (!s) return;
              const low = s.toLowerCase();
              if (low.includes("/pdf") || low.includes("/pdfft") || low.endsWith(".pdf")) {
                out.add(s);
              }
            };

            document.querySelectorAll("a[href]").forEach((el) => push(el.getAttribute("href")));
            document.querySelectorAll("[data-href]").forEach((el) => push(el.getAttribute("data-href")));
            document.querySelectorAll("[data-pdf-url]").forEach((el) => push(el.getAttribute("data-pdf-url")));

            const html = document.documentElement ? document.documentElement.outerHTML : "";
            const rel = html.match(/\\/science\\/article\\/pii\\/[A-Za-z0-9]+\\/(?:pdf|pdfft)[^"'<>\\s]*/gi) || [];
            const abs = html.match(/https?:\\/\\/[^"'<>\\s]+(?:\\.pdf(?:\\?|$)|\\/pdf(?:\\?|$)|\\/pdfft[^"'<>\\s]*)/gi) || [];
            rel.forEach(push);
            abs.forEach(push);
            return Array.from(out);
            """
        )
        return [x for x in (links or []) if isinstance(x, str) and x.strip()]
    except Exception:
        return []


def _detect_human_verification(driver) -> tuple[bool, str]:
    title = ""
    url = ""
    body_text = ""
    page_html = ""

    try:
        title = (driver.title or "").strip().lower()
    except Exception:
        title = ""
    try:
        url = (driver.current_url or "").strip().lower()
    except Exception:
        url = ""

    try:
        body_text = (
            driver.execute_script(
                "return (document.body && document.body.innerText) ? document.body.innerText.slice(0, 12000) : '';"
            )
            or ""
        )
        body_text = str(body_text).lower()
    except Exception:
        body_text = ""

    for marker in HUMAN_VERIFICATION_URL_MARKERS:
        if marker in url:
            return True, f"url:{marker}"

    for marker in HUMAN_VERIFICATION_TITLE_MARKERS:
        if marker in title:
            return True, f"title:{marker}"

    for marker in HUMAN_VERIFICATION_TEXT_MARKERS:
        if marker in body_text:
            return True, f"text:{marker}"

    # Fall back to tiny html signature match if innerText is not enough.
    try:
        page_html = (driver.page_source or "")[:30000].lower()
    except Exception:
        page_html = ""
    for marker in ("cf-turnstile", "g-recaptcha", "hcaptcha", "challenge-platform"):
        if marker in page_html:
            return True, f"html:{marker}"

    return False, ""


def _wait_for_human_verification_pass(driver, wait_seconds: int) -> tuple[bool, str]:
    timeout = max(5, int(wait_seconds or 0))
    deadline = time.time() + timeout
    last_hint = ""
    while time.time() < deadline:
        blocked, hint = _detect_human_verification(driver)
        if not blocked:
            return True, last_hint
        if hint:
            last_hint = hint
        time.sleep(1.5)
    return False, last_hint


def _download_elsevier_pdf_via_selenium(
    out_path: str,
    candidate_html_urls: list[str],
    candidate_pdf_urls: list[str],
    timeout: int = 180,
    headless: bool = True,
    use_profile: bool = False,
    manual_wait_seconds: int = 0,
    attach_debugger: bool = False,
    debugger_address: str = "",
    allow_new_browser_on_attach_fail: bool = True,
    interactive_verify: bool = False,
    verify_wait_seconds: int = 300,
) -> tuple[bool, dict]:
    """
    Browser-assisted fallback for ScienceDirect:
    - useful when requests is blocked but campus network browser can open PDF.
    """
    meta = {
        "method": "selenium",
        "status": "failed",
        "reasonCode": "selenium_unknown",
        "reasonMessage": "",
        "attachedDebugger": False,
        "debuggerAddress": "",
        "attemptedUrls": 0,
        "discoveredLinks": 0,
        "lastUrl": "",
        "humanVerificationTriggered": False,
        "verificationMode": "off",
        "verificationHint": "",
        "verificationWaitSeconds": int(max(0, verify_wait_seconds or 0)),
    }

    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except Exception as e:
        meta["reasonCode"] = "selenium_not_available"
        meta["reasonMessage"] = str(e)
        return False, meta

    download_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(download_dir, exist_ok=True)

    baseline = set(name for name in os.listdir(download_dir) if name.lower().endswith(".pdf"))
    if os.path.exists(out_path):
        try:
            os.remove(out_path)
        except OSError:
            pass

    def _build_standard_options(run_headless: bool | None = None) -> Options:
        options = Options()
        use_headless = headless if run_headless is None else bool(run_headless)
        if use_headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1440,960")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_experimental_option("prefs", {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True,
        })

        if use_profile:
            profile_root = _discover_local_chrome_profile_dir()
            if profile_root:
                options.add_argument(f"--user-data-dir={profile_root}")
                profile_name = _env_str("ELSEVIER_CHROME_PROFILE_DIR", "Default")
                options.add_argument(f"--profile-directory={profile_name}")
        return options

    driver = None
    attached_mode = False
    if attach_debugger:
        addr = debugger_address.strip() or _env_str("ELSEVIER_CHROME_DEBUGGER_ADDRESS", "127.0.0.1:9222")
        options = Options()
        options.add_experimental_option("debuggerAddress", addr)
        try:
            driver = webdriver.Chrome(options=options)
            attached_mode = True
            meta["attachedDebugger"] = True
            meta["debuggerAddress"] = addr
        except Exception as e:
            if not allow_new_browser_on_attach_fail:
                meta["reasonCode"] = "selenium_attach_failed"
                meta["reasonMessage"] = str(e)
                return False, meta

    if driver is None:
        try:
            driver = webdriver.Chrome(options=_build_standard_options())
            attached_mode = False
        except Exception as e:
            meta["reasonCode"] = "selenium_driver_start_failed"
            meta["reasonMessage"] = str(e)
            return False, meta
    current_headless = bool(headless) and not attached_mode
    if bool(interactive_verify):
        meta["verificationMode"] = "interactive"

    def _normalize_browser_link(link: str) -> str:
        if not link:
            return ""
        value = link.strip().replace("\\u002F", "/").replace("\\/", "/")
        if not ABS_URL_PATTERN.match(value):
            value = urllib.parse.urljoin("https://www.sciencedirect.com", value)
        return value

    def _relaunch_visible_browser() -> bool:
        nonlocal driver, current_headless, attached_mode
        try:
            driver.quit()
        except Exception:
            pass
        try:
            driver = webdriver.Chrome(options=_build_standard_options(run_headless=False))
            current_headless = False
            attached_mode = False
            try:
                driver.set_page_load_timeout(max(20, min(timeout, 60)))
            except Exception:
                pass
            return True
        except Exception as e:
            meta["reasonCode"] = "selenium_driver_relaunch_failed"
            meta["reasonMessage"] = str(e)
            return False

    try:
        try:
            driver.set_page_load_timeout(max(20, min(timeout, 60)))
        except Exception:
            pass
        if attached_mode:
            # For attached existing browser session, force download behavior via CDP.
            try:
                driver.execute_cdp_cmd("Page.setDownloadBehavior", {
                    "behavior": "allow",
                    "downloadPath": download_dir,
                })
            except Exception:
                pass

        queue: list[str] = []
        seen: set[str] = set()

        def _push(url: str):
            u = _normalize_browser_link(url)
            if not u or u in seen:
                return
            seen.add(u)
            queue.append(u)

        for url in candidate_html_urls:
            _push(url)
        for url in candidate_pdf_urls:
            _push(url)

        while queue:
            url = queue.pop(0)
            meta["attemptedUrls"] = int(meta["attemptedUrls"]) + 1
            meta["lastUrl"] = url
            try:
                driver.get(url)
            except Exception:
                continue

            if manual_wait_seconds > 0:
                time.sleep(manual_wait_seconds)
                manual_wait_seconds = 0
            else:
                time.sleep(2.5)

            blocked, verify_hint = _detect_human_verification(driver)
            if blocked:
                meta["humanVerificationTriggered"] = True
                meta["verificationHint"] = verify_hint
                if not interactive_verify:
                    meta["reasonCode"] = "selenium_human_verification_required"
                    meta["reasonMessage"] = (
                        "Human verification is required on ScienceDirect. "
                        "Enable interactive verification mode to continue."
                    )
                    return False, meta

                if current_headless:
                    if not _relaunch_visible_browser():
                        return False, meta
                    try:
                        driver.get(url)
                    except Exception:
                        continue
                    time.sleep(1.5)

                print(
                    "[Elsevier] Human verification detected. "
                    f"Please complete it in browser within {max(5, int(verify_wait_seconds or 0))} seconds."
                )
                verified, latest_hint = _wait_for_human_verification_pass(
                    driver,
                    wait_seconds=max(5, int(verify_wait_seconds or 0)),
                )
                if not verified:
                    meta["reasonCode"] = "selenium_human_verification_timeout"
                    meta["reasonMessage"] = (
                        "Human verification was not completed in time. "
                        f"Last hint: {latest_hint or verify_hint or 'unknown'}"
                    )
                    return False, meta
                # Give browser a short window to complete redirect/download.
                time.sleep(1.5)

            downloaded = _wait_for_new_pdf(download_dir, baseline, timeout=20)
            if downloaded:
                try:
                    os.replace(downloaded, out_path)
                except OSError:
                    pass
                if _is_valid_pdf_file(out_path):
                    meta["status"] = "success"
                    meta["reasonCode"] = ""
                    meta["reasonMessage"] = ""
                    return True, meta

            for link in _collect_pdf_links_from_browser(driver):
                meta["discoveredLinks"] = int(meta["discoveredLinks"]) + 1
                _push(link)

            # If now at a concrete PDF URL, wait longer for file write.
            current = (driver.current_url or "").lower()
            if ("/pdf" in current) or ("/pdfft" in current) or current.endswith(".pdf"):
                downloaded = _wait_for_new_pdf(download_dir, baseline, timeout=timeout)
                if downloaded:
                    try:
                        os.replace(downloaded, out_path)
                    except OSError:
                        pass
                    if _is_valid_pdf_file(out_path):
                        meta["status"] = "success"
                        meta["reasonCode"] = ""
                        meta["reasonMessage"] = ""
                        return True, meta

            baseline = set(name for name in os.listdir(download_dir) if name.lower().endswith(".pdf"))

        if _is_valid_pdf_file(out_path):
            meta["status"] = "success"
            meta["reasonCode"] = ""
            meta["reasonMessage"] = ""
            return True, meta

        meta["reasonCode"] = "selenium_no_pdf"
        meta["reasonMessage"] = "Selenium visited candidate URLs but no valid PDF was produced."
        return False, meta
    finally:
        driver.quit()


def _collect_pdf_links_from_html(html: str):
    if not html:
        return []
    links = []
    seen = set()

    for m in RELATIVE_PDF_PATTERN.findall(html):
        link = urllib.parse.urljoin("https://www.sciencedirect.com", m)
        if link not in seen:
            seen.add(link)
            links.append(link)

    for m in ABS_PDF_PATTERN.findall(html):
        link = m.replace("\\u002F", "/")
        link = link.replace("\\/", "/")
        if link not in seen:
            seen.add(link)
            links.append(link)

    return links


def _download_pdf_from_url(
    sess: requests.Session,
    url: str,
    out_path: str,
    timeout: int = 60,
    referer: str = "",
    extra_headers: dict | None = None,
) -> bool:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    if extra_headers:
        headers.update(extra_headers)

    resp = _safe_get(sess, url, headers=headers, timeout=timeout, allow_redirects=True, stream=True)
    if resp is None:
        return False

    try:
        if resp.status_code >= 400:
            return False

        ctype = (resp.headers.get("Content-Type") or "").lower()
        first_chunk = b""
        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 128):
                if not chunk:
                    continue
                if not first_chunk:
                    first_chunk = chunk[:16]
                f.write(chunk)

        if "pdf" in ctype:
            return _is_valid_pdf_file(out_path)
        return _is_pdf_bytes(first_chunk) and _is_valid_pdf_file(out_path)
    finally:
        try:
            resp.close()
        except Exception:
            pass


def _extract_doi_from_source_url(source_url: str) -> str:
    if not source_url:
        return ""
    text = source_url.strip()
    if "doi.org/" in text:
        return _normalize_doi(text.split("doi.org/", 1)[1].split("?", 1)[0])
    m = DOI_IN_TEXT_PATTERN.search(text)
    return _normalize_doi(m.group(1)) if m else ""


def _build_elsevier_source_url(doi: str, pii: str):
    if pii:
        return f"https://www.sciencedirect.com/science/article/pii/{pii}"
    if doi:
        return f"https://doi.org/{doi}"
    return ""


def _unpaywall_pdf_url(sess: requests.Session, doi: str, timeout: int = 30) -> str:
    if not doi:
        return ""
    url = f"{UNPAYWALL_API}/{urllib.parse.quote(doi, safe='')}"
    resp = _safe_get(
        sess,
        url,
        params={"email": EMAIL_CONTACT},
        timeout=timeout,
        headers={"User-Agent": "PaperFlow/1.0"},
    )
    if resp is None or resp.status_code != 200:
        return ""
    try:
        data = resp.json() or {}
    except Exception:
        return ""

    best = (data.get("best_oa_location") or {}).get("url_for_pdf") or ""
    if best:
        return best
    for item in data.get("oa_locations") or []:
        link = (item or {}).get("url_for_pdf") or ""
        if link:
            return link
    return ""


def _crossref_pdf_url(sess: requests.Session, doi: str, timeout: int = 30) -> str:
    if not doi:
        return ""
    url = f"{CROSSREF_WORKS_API}/{urllib.parse.quote(doi, safe='')}"
    resp = _safe_get(
        sess,
        url,
        timeout=timeout,
        headers={"User-Agent": "PaperFlow/1.0 (mailto:paperflow@example.com)"},
    )
    if resp is None or resp.status_code != 200:
        return ""
    try:
        data = resp.json() or {}
    except Exception:
        return ""
    links = (data.get("message") or {}).get("link") or []
    for item in links:
        ctype = ((item or {}).get("content-type") or "").lower()
        href = (item or {}).get("URL") or (item or {}).get("url") or ""
        if href and "pdf" in ctype:
            return href
    return ""


def download_elsevier_pdf(
    article_number: str,
    out_dir: str = "docs",
    source_url: str = "",
    doi: str = "",
    pii: str = "",
    elsevier_api_key: str = "",
    timeout: int = 80,
    selenium_fallback: bool | None = None,
    selenium_headless: bool | None = None,
    selenium_use_profile: bool | None = None,
    selenium_manual_wait_seconds: int | None = None,
    selenium_attach_debugger: bool | None = None,
    selenium_debugger_address: str | None = None,
    selenium_allow_new_browser_on_attach_fail: bool | None = None,
    selenium_interactive_verify: bool | None = None,
    selenium_verify_wait_seconds: int | None = None,
    debug: dict | None = None,
) -> str:
    """
    Try downloading an Elsevier/ScienceDirect PDF via multiple routes.
    Returns local file path when successful, otherwise empty string.
    """
    if debug is not None:
        debug.clear()
        debug.update({
            "provider": "elsevier",
            "status": "failed",
            "route": "",
            "reasonCode": "unknown",
            "reasonMessage": "",
            "doi": "",
            "pii": "",
        })

    os.makedirs(out_dir, exist_ok=True)
    safe_name = (article_number or "").strip()
    if not safe_name:
        if debug is not None:
            debug["reasonCode"] = "invalid_article_number"
            debug["reasonMessage"] = "article_number is empty."
        return ""

    out_path = os.path.join(out_dir, f"{safe_name}.pdf")
    if _is_valid_pdf_file(out_path):
        if debug is not None:
            debug.update({
                "status": "success",
                "route": "cache",
                "reasonCode": "",
                "reasonMessage": "",
            })
        return out_path

    doi = _normalize_doi(doi) or extract_doi_from_article_number(article_number) or _extract_doi_from_source_url(source_url)
    pii = (pii or "").strip() or extract_pii_from_article_number(article_number) or _extract_pii_from_url(source_url)
    if debug is not None:
        debug["doi"] = doi
        debug["pii"] = pii

    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })

    candidate_pdf_urls = []
    candidate_html_urls = []
    seen_pdf = set()
    seen_html = set()

    def _push_pdf(url: str):
        u = (url or "").strip()
        if not u:
            return
        if not ABS_URL_PATTERN.match(u):
            u = urllib.parse.urljoin("https://www.sciencedirect.com", u)
        if u not in seen_pdf:
            seen_pdf.add(u)
            candidate_pdf_urls.append(u)

    def _push_html(url: str):
        u = (url or "").strip()
        if not u:
            return
        if not ABS_URL_PATTERN.match(u):
            u = urllib.parse.urljoin("https://www.sciencedirect.com", u)
        if u not in seen_html:
            seen_html.add(u)
            candidate_html_urls.append(u)

    if source_url:
        if source_url.lower().endswith(".pdf") or "/pdf" in source_url.lower() or "/pdfft" in source_url.lower():
            _push_pdf(source_url)
        _push_html(source_url)

    if pii:
        _push_pdf(f"https://www.sciencedirect.com/science/article/pii/{pii}/pdf")
        _push_pdf(f"https://www.sciencedirect.com/science/article/pii/{pii}/pdfft?isDTMRedir=true&download=true")
        _push_html(f"https://www.sciencedirect.com/science/article/pii/{pii}")

    if doi:
        _push_html(f"https://doi.org/{doi}")

        # Elsevier content API may return direct PDF for eligible content.
        if elsevier_api_key:
            api_url = f"https://api.elsevier.com/content/article/doi/{urllib.parse.quote(doi, safe='')}"
            ok = _download_pdf_from_url(
                sess,
                f"{api_url}?httpAccept=application/pdf",
                out_path,
                timeout=timeout,
                extra_headers={
                    "X-ELS-APIKey": elsevier_api_key,
                    "Accept": "application/pdf",
                },
            )
            if ok:
                if debug is not None:
                    debug.update({
                        "status": "success",
                        "route": "elsevier_api_pdf",
                        "reasonCode": "",
                        "reasonMessage": "",
                    })
                return out_path
            if os.path.exists(out_path):
                try:
                    os.remove(out_path)
                except OSError:
                    pass

    # 1) Try all direct PDF candidates first.
    for pdf_url in list(candidate_pdf_urls):
        if _download_pdf_from_url(sess, pdf_url, out_path, timeout=timeout):
            if debug is not None:
                debug.update({
                    "status": "success",
                    "route": "direct_pdf_candidate",
                    "reasonCode": "",
                    "reasonMessage": "",
                })
            return out_path
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass

    # 2) Visit article pages, discover pdf links from HTML, then download.
    for article_url in list(candidate_html_urls):
        resp = _safe_get(
            sess,
            article_url,
            timeout=timeout,
            allow_redirects=True,
            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
        )
        if resp is None or resp.status_code >= 400:
            continue
        final_url = resp.url or article_url
        html = resp.text or ""
        discovered = _collect_pdf_links_from_html(html)
        for link in discovered:
            _push_pdf(link)

        # If DOI resolve lands on ScienceDirect with PII, append canonical PDF endpoints.
        if not pii:
            pii_from_final = _extract_pii_from_url(final_url)
            if pii_from_final:
                pii = pii_from_final
                _push_pdf(f"https://www.sciencedirect.com/science/article/pii/{pii}/pdf")
                _push_pdf(f"https://www.sciencedirect.com/science/article/pii/{pii}/pdfft?isDTMRedir=true&download=true")

    for pdf_url in list(candidate_pdf_urls):
        if _download_pdf_from_url(sess, pdf_url, out_path, timeout=timeout):
            if debug is not None:
                debug.update({
                    "status": "success",
                    "route": "html_discovered_pdf",
                    "reasonCode": "",
                    "reasonMessage": "",
                })
            return out_path
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass

    # 3) OA fallbacks by DOI.
    if doi:
        oa_pdf = _unpaywall_pdf_url(sess, doi)
        if oa_pdf and _download_pdf_from_url(sess, oa_pdf, out_path, timeout=timeout):
            if debug is not None:
                debug.update({
                    "status": "success",
                    "route": "unpaywall_pdf",
                    "reasonCode": "",
                    "reasonMessage": "",
                })
            return out_path
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass

        cr_pdf = _crossref_pdf_url(sess, doi)
        if cr_pdf and _download_pdf_from_url(sess, cr_pdf, out_path, timeout=timeout):
            if debug is not None:
                debug.update({
                    "status": "success",
                    "route": "crossref_pdf_link",
                    "reasonCode": "",
                    "reasonMessage": "",
                })
            return out_path
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass

    # 4) Browser-assisted fallback (important for campus network / institution access).
    if selenium_fallback is None:
        selenium_fallback = _env_bool("ELSEVIER_SELENIUM_FALLBACK", True)
    if selenium_headless is None:
        selenium_headless = _env_bool("ELSEVIER_SELENIUM_HEADLESS", True)
    if selenium_use_profile is None:
        selenium_use_profile = _env_bool("ELSEVIER_SELENIUM_USE_PROFILE", False)
    if selenium_manual_wait_seconds is None:
        selenium_manual_wait_seconds = _env_int("ELSEVIER_SELENIUM_MANUAL_WAIT_SECONDS", 0)
    if selenium_attach_debugger is None:
        selenium_attach_debugger = _env_bool("ELSEVIER_SELENIUM_ATTACH_DEBUGGER", False)
    if selenium_debugger_address is None:
        selenium_debugger_address = _env_str("ELSEVIER_CHROME_DEBUGGER_ADDRESS", "127.0.0.1:9222")
    if selenium_allow_new_browser_on_attach_fail is None:
        selenium_allow_new_browser_on_attach_fail = _env_bool(
            "ELSEVIER_SELENIUM_ALLOW_NEW_BROWSER_ON_ATTACH_FAIL",
            True,
        )
    if selenium_interactive_verify is None:
        selenium_interactive_verify = _env_bool("ELSEVIER_SELENIUM_INTERACTIVE_VERIFY", True)
    if selenium_verify_wait_seconds is None:
        selenium_verify_wait_seconds = _env_int("ELSEVIER_SELENIUM_VERIFY_WAIT_SECONDS", 300)

    if selenium_fallback:
        ok, selenium_meta = _download_elsevier_pdf_via_selenium(
            out_path=out_path,
            candidate_html_urls=list(candidate_html_urls),
            candidate_pdf_urls=list(candidate_pdf_urls),
            timeout=max(timeout, _env_int("ELSEVIER_SELENIUM_TIMEOUT", 180)),
            headless=bool(selenium_headless),
            use_profile=bool(selenium_use_profile),
            manual_wait_seconds=max(int(selenium_manual_wait_seconds), 0),
            attach_debugger=bool(selenium_attach_debugger),
            debugger_address=(selenium_debugger_address or "").strip(),
            allow_new_browser_on_attach_fail=bool(selenium_allow_new_browser_on_attach_fail),
            interactive_verify=bool(selenium_interactive_verify),
            verify_wait_seconds=max(5, int(selenium_verify_wait_seconds or 0)),
        )
        if ok and _is_valid_pdf_file(out_path):
            if debug is not None:
                debug.update({
                    "status": "success",
                    "route": "selenium_fallback",
                    "reasonCode": "",
                    "reasonMessage": "",
                    "seleniumMeta": selenium_meta,
                })
            return out_path
        if debug is not None:
            debug["seleniumMeta"] = selenium_meta

    if debug is not None:
        debug["reasonCode"] = "all_routes_failed"
        debug["reasonMessage"] = "Elsevier download failed across API, direct links, OA fallback, and selenium fallback."
    return ""


def search_elsevier(
    query: str,
    api_key: str = "",
    start: int = 0,
    max_results: int = 25,
    sort: str = "-date",
    subject: str = "",
) -> list[dict]:
    """
    Search Elsevier papers via the ScienceDirect Search API.

    If no api_key is provided, falls back to the OpenSearch-based approach.

    Args:
        query: Search keywords
        api_key: Elsevier API key (get free at https://dev.elsevier.com)
        start: Pagination offset
        max_results: Number of results
        sort: Sort field ("-date", "-relevance", "date")
        subject: Filter by subject area

    Returns:
        List of paper dicts
    """
    if api_key:
        return _search_via_api(query, api_key, start, max_results, sort, subject)
    else:
        return _search_via_opensearch(query, start, max_results)


def _search_via_api(
    query: str,
    api_key: str,
    start: int,
    max_results: int,
    sort: str,
    subject: str,
) -> list[dict]:
    """Search using official Elsevier API with API key."""
    headers = {
        "X-ELS-APIKey": api_key,
        "Accept": "application/json",
    }

    params = {
        "query": query,
        "start": start,
        "count": min(max_results, 100),
        "sort": sort,
    }
    if subject:
        params["subj"] = subject

    resp = requests.get(SCIENCEDIRECT_SEARCH_URL, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    results_list = data.get("search-results", {}).get("entry", [])
    papers = []

    for entry in results_list:
        doi = entry.get("prism:doi", "")
        pii = entry.get("pii", "")
        identifier = pii or doi.replace("/", "_") if doi else ""

        authors_raw = entry.get("authors", {}).get("author", [])
        if isinstance(authors_raw, list):
            authors = [a.get("$", "") for a in authors_raw]
        else:
            authors = []

        papers.append({
            "articleNumber": f"elsevier_{identifier}" if identifier else "",
            "articleTitle": entry.get("dc:title", ""),
            "title": entry.get("dc:title", ""),
            "authors": authors,
            "abstract": entry.get("dc:description", "") or "",
            "publicationDate": entry.get("prism:coverDate", ""),
            "publicationTitle": entry.get("prism:publicationName", ""),
            "displayPublicationTitle": "Elsevier",
            "downloadCount": None,
            "doi": doi,
            "pii": pii,
            "pdfLink": entry.get("link", [{}])[0].get("@href", "") if entry.get("link") else "",
            "sourceUrl": _build_elsevier_source_url(doi, pii),
            "source": "elsevier",
        })

    return papers


def _search_via_opensearch(query: str, start: int, max_results: int) -> list[dict]:
    """
    Fallback: search ScienceDirect via the public website with requests.
    Uses the public search endpoint that doesn't require an API key.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    url = "https://www.sciencedirect.com/search/api"
    params = {
        "qs": query,
        "offset": start,
        "show": min(max_results, 25),
        "sortBy": "date",
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        # If the public API doesn't work, return empty
        return _search_via_crossref(query, start, max_results)

    search_results = data.get("searchResults", [])
    papers = []

    for entry in search_results:
        doi = entry.get("doi", "")
        pii = entry.get("pii", "")
        identifier = pii or doi.replace("/", "_") if doi else ""

        authors = []
        for a in entry.get("authors", []):
            name = a.get("name", "")
            if name:
                authors.append(name)

        papers.append({
            "articleNumber": f"elsevier_{identifier}" if identifier else "",
            "articleTitle": entry.get("title", ""),
            "title": entry.get("title", ""),
            "authors": authors,
            "abstract": entry.get("teaser", "") or "",
            "publicationDate": entry.get("publicationDate", ""),
            "publicationTitle": entry.get("sourceTitle", ""),
            "displayPublicationTitle": "Elsevier / ScienceDirect",
            "downloadCount": None,
            "doi": doi,
            "pii": pii,
            "sourceUrl": _build_elsevier_source_url(doi, pii),
            "source": "elsevier",
        })

    return papers


def _search_via_crossref(query: str, start: int, max_results: int) -> list[dict]:
    """
    Ultimate fallback: use CrossRef API to find Elsevier papers.
    CrossRef is fully public, no API key needed.
    """
    url = "https://api.crossref.org/works"
    params = {
        "query": query,
        "filter": "member:78",  # 78 = Elsevier
        "rows": min(max_results, 50),
        "offset": start,
        "sort": "published",
        "order": "desc",
        "mailto": "paperflow@example.com",
    }

    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    items = data.get("message", {}).get("items", [])
    papers = []

    for item in items:
        doi = item.get("DOI", "")
        identifier = doi.replace("/", "_") if doi else ""

        authors = []
        for a in item.get("author", []):
            given = a.get("given", "")
            family = a.get("family", "")
            if given or family:
                authors.append(f"{given} {family}".strip())

        # Extract date
        date_parts = item.get("published", {}).get("date-parts", [[]])
        if date_parts and date_parts[0]:
            parts = date_parts[0]
            pub_date = "-".join(str(p).zfill(2) for p in parts)
        else:
            pub_date = ""

        title = ""
        if item.get("title"):
            title = item["title"][0] if isinstance(item["title"], list) else item["title"]

        journal = ""
        if item.get("container-title"):
            journal = item["container-title"][0] if isinstance(item["container-title"], list) else item["container-title"]

        abstract = item.get("abstract", "")
        # Clean HTML tags from abstract
        if abstract:
            abstract = re.sub(r"<[^>]+>", "", abstract)

        papers.append({
            "articleNumber": f"elsevier_{identifier}" if identifier else "",
            "articleTitle": title,
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "publicationDate": pub_date,
            "publicationTitle": journal,
            "displayPublicationTitle": "Elsevier",
            "downloadCount": None,
            "doi": doi,
            "sourceUrl": _build_elsevier_source_url(doi, ""),
            "source": "elsevier",
        })

    return papers


if __name__ == "__main__":
    papers = search_elsevier("deep learning power systems", max_results=5)
    for p in papers:
        print(f"  {p['articleNumber']}: {p['title'][:80]}")
    print(f"Total: {len(papers)}")
