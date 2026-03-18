from __future__ import annotations

import re
import sys
from collections import OrderedDict
from itertools import zip_longest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
SOURCE_DIR = ROOT_DIR / "report-src"
PARTIALS_DIR = SOURCE_DIR / "partials"
CSS_DIR = SOURCE_DIR / "css"
JS_DIR = SOURCE_DIR / "js"
DIST_DIR = ROOT_DIR / "dist"
DIST_FILE = DIST_DIR / "report.html"
REFERENCE_FILE = ROOT_DIR / "report.html"

TITLE = "웹 취약점 진단 결과 보고서 템플릿"
CSS_ORDER = ("base.css", "components.css", "print.css")
JS_ORDER = ("placeholders.js", "page-tokens.js", "qa-panel.js", "init.js")

COUNT_CHECKS = OrderedDict(
    [
        ("section count", r"<section\b"),
        ("data-field count", r'\bdata-field="'),
        ("data-repeat count", r'\bdata-repeat="'),
        ("placeholder class count", r'\bclass="[^"]*\bplaceholder\b'),
        ("requires-input class count", r'\bclass="[^"]*\brequires-input\b'),
        ("toc-page class count", r'\bclass="[^"]*\btoc-page\b'),
        ("page token literal count", r"\{\{page:[^}]+\}\}"),
    ]
)

SEQUENCE_CHECKS = OrderedDict(
    [
        ("section ids", r'<section\b[^>]*\bid="([^"]+)"'),
        ("section toc keys", r'<section\b[^>]*\bdata-toc-key="([^"]+)"'),
        ("heading ids", r'<h[12]\b[^>]*\bid="([^"]+)"'),
        ("heading toc keys", r'<h[12]\b[^>]*\bdata-toc-key="([^"]+)"'),
    ]
)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ordered_partials() -> list[Path]:
    partials = sorted(PARTIALS_DIR.glob("*.html"))
    if not partials:
        raise FileNotFoundError(f"No partial HTML files found in {PARTIALS_DIR}")
    return partials


def join_files(base_dir: Path, filenames: tuple[str, ...]) -> str:
    chunks: list[str] = []
    for name in filenames:
        path = base_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Missing source file: {path}")
        chunks.append(read_text(path).rstrip())
    return "\n\n".join(chunks) + "\n"


def join_partials(partials: list[Path]) -> str:
    return "\n\n".join(read_text(path).rstrip() for path in partials) + "\n"


def render_document(css: str, body: str, js: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="ko" data-theme="light" style=""><head>\n'
        '    <meta charset="UTF-8">\n'
        f"    <title>{TITLE}</title>\n"
        "    <style>\n"
        f"{css}"
        "    </style>\n"
        "  </head>\n"
        "  <body>\n"
        '    <main class="report-document">\n'
        f"{body}"
        "    </main>\n"
        "    <script>\n"
        f"{js}"
        "    </script>\n"
        "  </body></html>\n"
    )


def validate_embedded_document(html: str) -> list[str]:
    checks = []
    checks.append(
        "OK document embeds one <style> block"
        if html.count("<style>") == 1
        else "FAIL expected exactly one <style> block"
    )
    checks.append(
        "OK document embeds one <script> block"
        if html.count("<script>") == 1
        else "FAIL expected exactly one <script> block"
    )
    checks.append(
        "OK report wrapper present"
        if '<main class="report-document">' in html
        else "FAIL missing main.report-document wrapper"
    )
    checks.append(
        "OK submission audit panel present"
        if 'id="submission-audit-panel"' in html
        else "FAIL missing submission audit panel"
    )
    checks.append(
        "OK print CSS retained"
        if "@media print" in html and "@page {" in html
        else "FAIL missing print CSS blocks"
    )
    return checks


def compare_counts(reference_html: str, built_html: str) -> list[str]:
    results: list[str] = []
    for label, pattern in COUNT_CHECKS.items():
        expected = len(re.findall(pattern, reference_html, re.S))
        actual = len(re.findall(pattern, built_html, re.S))
        status = "OK" if expected == actual else "WARN"
        results.append(f"{status} {label}: reference={expected}, dist={actual}")
    return results


def compare_sequences(reference_html: str, built_html: str) -> list[str]:
    results: list[str] = []
    for label, pattern in SEQUENCE_CHECKS.items():
        reference_items = re.findall(pattern, reference_html, re.S)
        built_items = re.findall(pattern, built_html, re.S)
        if reference_items == built_items:
            results.append(f"OK {label}: sequence preserved ({len(reference_items)} items)")
            continue
        mismatch = first_mismatch(reference_items, built_items)
        results.append(
            "WARN "
            f"{label}: first mismatch at position {mismatch[0]} "
            f"(reference={mismatch[1]!r}, dist={mismatch[2]!r})"
        )
    return results


def first_mismatch(reference_items: list[str], built_items: list[str]) -> tuple[int, str, str]:
    for index, pair in enumerate(zip_longest(reference_items, built_items, fillvalue="<missing>"), start=1):
        if pair[0] != pair[1]:
            return index, pair[0], pair[1]
    return 0, "<none>", "<none>"


def compare_against_reference(built_html: str) -> list[str]:
    if not REFERENCE_FILE.exists():
        return [f"SKIP reference comparison: {REFERENCE_FILE} not found"]
    reference_html = read_text(REFERENCE_FILE)
    return compare_counts(reference_html, built_html) + compare_sequences(reference_html, built_html)


def build() -> int:
    partials = ordered_partials()
    css = join_files(CSS_DIR, CSS_ORDER)
    js = join_files(JS_DIR, JS_ORDER)
    body = join_partials(partials)
    html = render_document(css=css, body=body, js=js)

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    DIST_FILE.write_text(html, encoding="utf-8")

    print(f"Built {DIST_FILE}")
    print(f"Source partials: {len(partials)}")
    print(f"Embedded CSS files: {', '.join(CSS_ORDER)}")
    print(f"Embedded JS files: {', '.join(JS_ORDER)}")

    for message in validate_embedded_document(html):
        print(message)
    for message in compare_against_reference(html):
        print(message)

    return 0


if __name__ == "__main__":
    sys.exit(build())
