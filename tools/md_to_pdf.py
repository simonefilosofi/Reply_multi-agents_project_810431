"""Renders the data quality report from Markdown to a printable PDF. The Markdown is the report; HTML and PDF are renderings of it, so a run whose PDF step fails still delivers a readable one. Conversion is python-markdown for the HTML and headless Chrome for the print, which buys CSS layout, real tables and inline SVG for one system dependency. Two headless-Chrome behaviours are worked around here rather than rediscovered: on macOS it hangs silently instead of failing when reading a TCC-protected path, which includes the Desktop this project lives on, so on POSIX the conversion happens entirely under /tmp; and it writes the PDF but never exits, so the wait is on the file settling rather than on the process ending."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import markdown

_CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
)
_CHROME_ON_PATH = ("google-chrome", "chromium", "chrome", "msedge")
_TCC_SAFE_WORKSPACE = "/tmp"
_PDF_TIMEOUT_SECONDS = 120
_SETTLE_SECONDS = 0.7

_INK = "#0b3d0b"
_BODY = "#1f3d1f"
_MUTED = "#4a7a4a"
_RULE = "#9ae399"
_HEAD_FILL = "#ccf1cc"
_ZEBRA = "#f2fbf2"

_CSS = f"""
@page {{ size: A4; margin: 14mm 15mm; }}
* {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
html, body {{ margin: 0; padding: 0; }}
body {{
  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-size: 10pt; line-height: 1.45; color: {_BODY};
}}
table.page {{ width: 100%; border-collapse: collapse; }}
table.page > thead {{ display: table-header-group; }}
table.page > tfoot {{ display: table-footer-group; }}
table.page > thead > tr > td,
table.page > tfoot > tr > td,
table.page > tbody > tr > td {{ padding: 0; border: none; }}

.run-header {{ padding-bottom: 8pt; }}
.run-header .name {{ font-size: 8pt; letter-spacing: .08em;
                     text-transform: uppercase; color: {_MUTED}; }}
.run-header .rule {{ border-bottom: 1.5px solid {_INK}; margin-top: 4px; }}
.run-footer {{ padding-top: 8pt; }}
.run-footer .rule {{ border-top: 1px solid {_RULE}; margin-bottom: 4px; }}
.run-footer .note {{ font-size: 7pt; color: {_MUTED}; }}

h1 {{ font-size: 18pt; font-weight: 600; color: {_INK}; margin: 0 0 4pt; }}
h2 {{ font-size: 12.5pt; font-weight: 700; color: {_INK};
      margin: 16pt 0 5pt; padding-bottom: 3pt;
      border-bottom: 1px solid {_RULE}; }}
h3 {{ font-size: 10.5pt; font-weight: 700; color: {_INK}; margin: 11pt 0 4pt; }}
h1, h2, h3 {{ page-break-after: avoid; }}
p {{ margin: 5pt 0; orphans: 3; widows: 3; }}
strong, b {{ color: {_INK}; font-weight: 700; }}
ul, ol {{ margin: 5pt 0; padding-left: 18pt; }}
li {{ margin: 2.5pt 0; }}
hr {{ border: none; border-top: 1px solid {_RULE}; margin: 12pt 0; }}

.content table {{ border-collapse: collapse; width: 100%; margin: 7pt 0;
                  font-size: 8.5pt; }}
.content th, .content td {{ border: 1px solid {_RULE}; padding: 3pt 5pt;
                            vertical-align: top; text-align: left;
                            line-height: 1.3; }}
.content th {{ background: {_HEAD_FILL}; color: {_INK}; white-space: nowrap; }}
.content tbody tr:nth-child(even) td {{ background: {_ZEBRA}; }}
.content tr {{ page-break-inside: avoid; }}
.content thead {{ display: table-header-group; }}

svg {{ display: block; margin: 7pt 0 3pt; page-break-inside: avoid; }}
pre {{ background: {_ZEBRA}; border: 1px solid {_RULE}; border-radius: 3px;
       padding: 6pt 8pt; font-size: 8pt; line-height: 1.35;
       white-space: pre-wrap; word-wrap: break-word;
       page-break-inside: avoid; margin: 6pt 0; }}
code {{ font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 8.5pt; }}
p code, td code, li code {{ background: {_ZEBRA}; padding: 0 3px;
                            border-radius: 2px; }}
blockquote {{ margin: 6pt 0; padding: 5pt 9pt; border-left: 3px solid {_INK};
              background: {_HEAD_FILL}; font-size: 9.5pt; }}
sub {{ font-size: 7.5pt; color: {_MUTED}; display: inline-block;
       line-height: 1.3; margin: 1pt 0 4pt; }}
"""


def markdown_to_html(md_text: str, title: str, footer_note: str = "") -> str:
    """Wraps the rendered Markdown in the print stylesheet. The body sits inside a table whose
    thead and tfoot Chrome repeats on every printed page and whose height it reserves, which a
    fixed-position header cannot do."""
    body = markdown.markdown(
        md_text, extensions=["tables", "sane_lists", "attr_list", "md_in_html", "fenced_code"]
    )
    header = (
        f"<thead><tr><td><div class='run-header'><div class='name'>{title}</div>"
        "<div class='rule'></div></div></td></tr></thead>"
    )
    footer = (
        f"<tfoot><tr><td><div class='run-footer'><div class='rule'></div>"
        f"<div class='note'>{footer_note}</div></div></td></tr></tfoot>"
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title><style>{_CSS}</style></head><body>"
        f"<table class='page'>{header}{footer}"
        f"<tbody><tr><td><div class='content'>{body}</div></td></tr></tbody></table>"
        "</body></html>"
    )


def chrome_executable() -> str | None:
    """The browser used to print, or None when none is installed. CHROME_BINARY overrides the
    search, so a machine with a browser in an unusual place needs no code change."""
    override = os.getenv("CHROME_BINARY")
    if override and Path(override).exists():
        return override
    for candidate in _CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    for name in _CHROME_ON_PATH:
        found = shutil.which(name)
        if found:
            return found
    return None


def write_pdf(
    md_text: str, out_pdf: Path, title: str, footer_note: str = ""
) -> Path | None:
    """Prints the report to PDF, returning the path written or None when no browser is available.
    A missing browser is not an error: the Markdown is the report, and the caller has already
    written it."""
    browser = chrome_executable()
    if browser is None:
        return None
    html = markdown_to_html(md_text, title, footer_note)
    destination = Path(out_pdf).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dq-report-", dir=_workspace_root()) as work:
        staged = _print_to_pdf(browser, html, Path(work))
        shutil.move(str(staged), destination)
    return destination


def _workspace_root() -> str | None:
    """Where the conversion is staged. /tmp on a POSIX machine, for the macOS reason in the module
    docstring; the platform default on Windows, which has no /tmp and is not subject to TCC."""
    return _TCC_SAFE_WORKSPACE if os.name == "posix" else None


def _print_to_pdf(browser: str, html: str, work: Path) -> Path:
    html_path = work / "report.html"
    html_path.write_text(html, encoding="utf-8")
    pdf_path = work / "report.pdf"
    process = subprocess.Popen(
        [
            browser, "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-pdf-header-footer", f"--user-data-dir={work}/profile",
            f"--print-to-pdf={pdf_path}", html_path.as_uri(),
        ],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_pdf(process, pdf_path)
    finally:
        _terminate(process)
    return pdf_path


def _wait_for_pdf(process: subprocess.Popen, pdf_path: Path) -> None:
    deadline = time.time() + _PDF_TIMEOUT_SECONDS
    while time.time() < deadline:
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            size = pdf_path.stat().st_size
            time.sleep(_SETTLE_SECONDS)
            if pdf_path.stat().st_size == size:
                return
        if process.poll() is not None and not pdf_path.exists():
            raise RuntimeError(
                f"the browser exited with code {process.returncode} without writing a PDF"
            )
        time.sleep(0.5)
    raise RuntimeError(f"the browser did not write a PDF within {_PDF_TIMEOUT_SECONDS}s")


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
