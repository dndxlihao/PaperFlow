import os
from datetime import datetime, timezone

from crawl_arxiv import download_arxiv_pdf
from crawl_elsevier import (
    download_elsevier_pdf,
    extract_doi_from_article_number,
    extract_pii_from_article_number,
)
from getDoc import down_pdf


def _expected_pdf_path(article_number: str, out_dir: str) -> str:
    return os.path.join(out_dir, f"{article_number}.pdf")


def _safe_remove(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _should_try_elsevier(article_number: str, source_url: str = "", doi: str = "") -> bool:
    arn = (article_number or "").strip().lower()
    src = (source_url or "").strip().lower()
    d = (doi or "").strip().lower()

    if arn.startswith("elsevier_"):
        return True
    if arn.startswith("crossref_") and d.startswith("10.1016/"):
        return True
    if "sciencedirect.com" in src:
        return True
    if "doi.org/10.1016/" in src:
        return True
    if d.startswith("10.1016/"):
        return True
    return False


def _provider_from_article(article_number: str, source_url: str = "", doi: str = "") -> str:
    arn = (article_number or "").strip()
    if arn.startswith("arxiv_"):
        return "arxiv"
    if arn.isdigit():
        return "ieee"
    if _should_try_elsevier(arn, source_url=source_url, doi=doi):
        return "elsevier"
    return "unknown"


def _base_report(article_number: str, source_url: str, provider: str) -> dict:
    return {
        "articleNumber": article_number,
        "provider": provider,
        "success": False,
        "path": "",
        "sourceUrl": source_url or "",
        "reasonCode": "",
        "reasonMessage": "",
        "fromCache": False,
        "meta": {},
        "attemptedAt": datetime.now(timezone.utc).isoformat(),
    }


def download_pdf_by_article_with_report(
    article_number: str,
    out_dir: str,
    source_url: str = "",
    elsevier_api_key: str = "",
    elsevier_selenium_fallback: bool | None = None,
    elsevier_selenium_headless: bool | None = None,
    elsevier_selenium_use_profile: bool | None = None,
    elsevier_selenium_manual_wait_seconds: int | None = None,
    elsevier_selenium_attach_debugger: bool | None = None,
    elsevier_selenium_debugger_address: str | None = None,
    elsevier_selenium_allow_new_browser_on_attach_fail: bool | None = None,
    elsevier_selenium_interactive_verify: bool | None = None,
    elsevier_selenium_verify_wait_seconds: int | None = None,
) -> tuple[str, dict]:
    """
    Download PDF for a paper id across supported sources.
    Returns (absolute local path when successful, report dict).
    """
    arn = (article_number or "").strip()
    provider = _provider_from_article(arn, source_url=source_url, doi=extract_doi_from_article_number(arn))
    report = _base_report(arn, source_url or "", provider)
    if not arn:
        report["reasonCode"] = "invalid_article_number"
        report["reasonMessage"] = "article_number is empty."
        return "", report

    os.makedirs(out_dir, exist_ok=True)
    out_path = _expected_pdf_path(arn, out_dir)
    if os.path.exists(out_path) and os.path.getsize(out_path) > 2048:
        report["success"] = True
        report["path"] = out_path
        report["fromCache"] = True
        report["reasonCode"] = ""
        return out_path, report

    # arXiv
    if arn.startswith("arxiv_"):
        try:
            path = download_arxiv_pdf(arn, out_dir=out_dir)
            if path and os.path.exists(path):
                report["success"] = True
                report["path"] = path
                return path, report
            report["reasonCode"] = "arxiv_download_failed"
            report["reasonMessage"] = "arXiv downloader returned empty result."
            return "", report
        except Exception as e:
            report["reasonCode"] = "arxiv_exception"
            report["reasonMessage"] = str(e)
            return "", report

    # IEEE
    if arn.isdigit():
        try:
            down_pdf(arn)
            if os.path.exists(out_path) and os.path.getsize(out_path) > 2048:
                report["success"] = True
                report["path"] = out_path
                return out_path, report
            report["reasonCode"] = "ieee_download_failed"
            report["reasonMessage"] = "IEEE downloader completed but no valid PDF file found."
            return "", report
        except Exception as e:
            report["reasonCode"] = "ieee_exception"
            report["reasonMessage"] = str(e)
            return "", report

    # Elsevier / ScienceDirect family (including CrossRef DOI 10.1016/*)
    doi = extract_doi_from_article_number(arn)
    pii = extract_pii_from_article_number(arn)
    if _should_try_elsevier(arn, source_url=source_url, doi=doi):
        path = ""
        elsevier_debug = {}
        try:
            path = download_elsevier_pdf(
                article_number=arn,
                out_dir=out_dir,
                source_url=source_url,
                doi=doi,
                pii=pii,
                elsevier_api_key=elsevier_api_key or "",
                selenium_fallback=elsevier_selenium_fallback,
                selenium_headless=elsevier_selenium_headless,
                selenium_use_profile=elsevier_selenium_use_profile,
                selenium_manual_wait_seconds=elsevier_selenium_manual_wait_seconds,
                selenium_attach_debugger=elsevier_selenium_attach_debugger,
                selenium_debugger_address=elsevier_selenium_debugger_address,
                selenium_allow_new_browser_on_attach_fail=elsevier_selenium_allow_new_browser_on_attach_fail,
                selenium_interactive_verify=elsevier_selenium_interactive_verify,
                selenium_verify_wait_seconds=elsevier_selenium_verify_wait_seconds,
                debug=elsevier_debug,
            )
        except Exception as e:
            _safe_remove(out_path)
            report["reasonCode"] = "elsevier_exception"
            report["reasonMessage"] = str(e)
            report["meta"] = {"elsevier": elsevier_debug}
            return "", report

        report["meta"] = {"elsevier": elsevier_debug}
        if path and os.path.exists(path):
            report["success"] = True
            report["path"] = path
            return path, report
        report["reasonCode"] = elsevier_debug.get("reasonCode") or "elsevier_download_failed"
        report["reasonMessage"] = elsevier_debug.get("reasonMessage") or "Elsevier downloader returned empty result."
        return "", report

    report["reasonCode"] = "unsupported_source"
    report["reasonMessage"] = "article_number does not match a supported source."
    return "", report


def download_pdf_by_article(
    article_number: str,
    out_dir: str,
    source_url: str = "",
    elsevier_api_key: str = "",
    elsevier_selenium_fallback: bool | None = None,
    elsevier_selenium_headless: bool | None = None,
    elsevier_selenium_use_profile: bool | None = None,
    elsevier_selenium_manual_wait_seconds: int | None = None,
    elsevier_selenium_attach_debugger: bool | None = None,
    elsevier_selenium_debugger_address: str | None = None,
    elsevier_selenium_allow_new_browser_on_attach_fail: bool | None = None,
    elsevier_selenium_interactive_verify: bool | None = None,
    elsevier_selenium_verify_wait_seconds: int | None = None,
) -> str:
    path, _ = download_pdf_by_article_with_report(
        article_number=article_number,
        out_dir=out_dir,
        source_url=source_url,
        elsevier_api_key=elsevier_api_key,
        elsevier_selenium_fallback=elsevier_selenium_fallback,
        elsevier_selenium_headless=elsevier_selenium_headless,
        elsevier_selenium_use_profile=elsevier_selenium_use_profile,
        elsevier_selenium_manual_wait_seconds=elsevier_selenium_manual_wait_seconds,
        elsevier_selenium_attach_debugger=elsevier_selenium_attach_debugger,
        elsevier_selenium_debugger_address=elsevier_selenium_debugger_address,
        elsevier_selenium_allow_new_browser_on_attach_fail=elsevier_selenium_allow_new_browser_on_attach_fail,
        elsevier_selenium_interactive_verify=elsevier_selenium_interactive_verify,
        elsevier_selenium_verify_wait_seconds=elsevier_selenium_verify_wait_seconds,
    )
    return path
