from __future__ import annotations

import argparse
import base64
import copy
import io
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from html import escape
from itertools import zip_longest
from pathlib import Path, PureWindowsPath
from urllib.parse import quote, urlsplit


ROOT_DIR = Path(__file__).resolve().parent
SOURCE_DIR = ROOT_DIR / "report-src"
PARTIALS_DIR = SOURCE_DIR / "partials"
CSS_DIR = SOURCE_DIR / "css"
JS_DIR = SOURCE_DIR / "js"
TEMPLATES_DIR = SOURCE_DIR / "templates"
DATA_DIR = SOURCE_DIR / "data"
DIST_DIR = ROOT_DIR / "dist"

TITLE = "웹 취약점 진단 결과 보고서 템플릿"
CSS_ORDER = ("base.css", "components.css", "print.css")
JS_ORDER = ("placeholders.js", "page-tokens.js", "qa-panel.js", "init.js")
DATASET_NAMES = ("default", "stress", "real-assets")
STRESS_PROFILE_FILE = DATA_DIR / "stress.json"
REAL_ASSET_SAMPLE_DIR = DIST_DIR / "real-asset-samples"
REAL_ASSET_LOGO_FILE = REAL_ASSET_SAMPLE_DIR / "agency-logo-sample.png"
PRINT_PAGE_WIDTH_MM = 210.0
PRINT_PAGE_HEIGHT_MM = 297.0
PRINT_MARGIN_TOP_MM = 12.0
PRINT_MARGIN_RIGHT_MM = 11.0
PRINT_MARGIN_BOTTOM_MM = 14.0
PRINT_MARGIN_LEFT_MM = 11.0
PRINT_CONTENT_WIDTH_MM = PRINT_PAGE_WIDTH_MM - PRINT_MARGIN_LEFT_MM - PRINT_MARGIN_RIGHT_MM
PRINT_CONTENT_HEIGHT_MM = PRINT_PAGE_HEIGHT_MM - PRINT_MARGIN_TOP_MM - PRINT_MARGIN_BOTTOM_MM
LAYOUT_PROBE_MARKER = "layout-probe-result"
LAYOUT_PROBE_DELAY_MS = 220

BROWSER_EXECUTABLE_CANDIDATES = (
    "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)
PDF_HEADER_SUPPRESSION_FLAGS = ("--print-to-pdf-no-header", "--no-pdf-header-footer")

REAL_ASSET_SPECS = (
    {
        "file_name": "vertical-portal-capture.png",
        "width": 1280,
        "height": 2560,
        "image_format": "PNG",
        "title": "세로형 포털 캡처",
        "subtitle": "긴 스크롤 화면 / 메뉴 + 본문",
        "accent": "#2c6db5",
        "kind": "vertical-long",
        "dense_text": False,
    },
    {
        "file_name": "wide-admin-dashboard.jpg",
        "width": 2560,
        "height": 1280,
        "image_format": "JPEG",
        "title": "가로형 관리자 화면",
        "subtitle": "대시보드 / 차트 / 표 복합 레이아웃",
        "accent": "#3a6b5e",
        "kind": "horizontal-wide",
        "dense_text": False,
    },
    {
        "file_name": "hires-console-view.png",
        "width": 3200,
        "height": 1800,
        "image_format": "PNG",
        "title": "고해상도 상세 화면",
        "subtitle": "해상도 큰 스크린샷 축소 검증",
        "accent": "#8b5c1f",
        "kind": "high-resolution",
        "dense_text": False,
    },
    {
        "file_name": "dense-response-log.jpg",
        "width": 1800,
        "height": 2400,
        "image_format": "JPEG",
        "title": "텍스트 밀집 응답 캡처",
        "subtitle": "작은 글자 가독성 확인",
        "accent": "#7c3b2c",
        "kind": "dense-text",
        "dense_text": True,
    },
)

COUNT_CHECKS = OrderedDict(
    [
        ("section count", r"<section\b"),
        ("data-field count", r'\bdata-field="'),
        ("data-repeat count", r'\bdata-repeat="'),
        ("placeholder class count", r'\bclass="[^"]*\bplaceholder\b'),
        ("requires-input class count", r'\bclass="[^"]*\brequires-input\b'),
        ("toc-page class count", r'\bclass="[^"]*\btoc-page\b'),
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

PARTIAL_MARKER_RE = re.compile(r"(?m)^(?P<indent>[ \t]*)\[\[(?P<marker>[a-z0-9-]+)\]\][ \t]*$")
TEMPLATE_TOKEN_RE = re.compile(r"\[\[([a-zA-Z0-9_.-]+)\]\]")
PAGE_TOKEN_RE = re.compile(r"\{\{page:([^}]+)\}\}")
TOC_KEY_RE = re.compile(r'\bdata-toc-key="([^"]+)"')
INLINE_STYLE_BLOCK_RE = re.compile(r"<style>\s*(.*?)\s*</style>", re.S)
FIXED_HEIGHT_RE = re.compile(
    r"(?P<selector>[^{]+)\{(?P<body>[^}]*(?:overflow\s*:\s*hidden|overflow-y\s*:\s*hidden)[^}]*(?:height|min-height|max-height)\s*:[^}]*)\}",
    re.S,
)
PAGE_KEY_PATTERNS = (
    ("section", re.compile(r'<section\b[^>]*\bdata-toc-key="([^"]+)"', re.S)),
    ("heading", re.compile(r'<h[1-3]\b[^>]*\bdata-toc-key="([^"]+)"', re.S)),
    ("vuln-block", re.compile(r'<div\b[^>]*\bclass="[^"]*\bvuln-block\b[^"]*"[^>]*\bdata-toc-key="([^"]+)"', re.S)),
    ("table-caption", re.compile(r'<div\b[^>]*\bclass="[^"]*\btable-caption\b[^"]*"[^>]*\bdata-toc-key="([^"]+)"', re.S)),
    ("figure-caption", re.compile(r'<div\b[^>]*\bclass="[^"]*\bfigure-caption\b[^"]*"[^>]*\bdata-toc-key="([^"]+)"', re.S)),
)
CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
URL_UNSAFE_CHAR_RE = re.compile(r"[\x00-\x20\"'<>`]")
SAFE_HTML_ATTR_NAME_RE = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9:._-]*$")
SAFE_DATA_FIELD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SAFE_DOM_ID_RE = re.compile(r"[^a-z0-9._:-]+")
DATA_IMAGE_URL_RE = re.compile(r"^data:image/(?:png|jpe?g|gif|webp|svg\+xml);base64,[A-Za-z0-9+/=]+$", re.I)
TOC_BOLD_MARKER_RE = re.compile(r"font-weight\s*:\s*bold|<\s*(?:strong|b)\b", re.I)

ALLOWED_RISK_KEYS = {"high", "mid", "low"}
ALLOWED_REPEAT_NAMES = {
    "appendix-evidence",
    "checklist-item",
    "figure-index-entry",
    "finding-evidence",
    "finding-toc-entry",
    "mitigation-long",
    "mitigation-mid",
    "mitigation-short",
    "priority-item",
    "summary-finding",
    "summary-system",
    "table-index-entry",
    "toc-entry",
    "tool-list",
}
ALLOWED_TOC_INLINE_STYLES = {"", "padding-left: 15px", "margin-top: 10px"}
BLOCKED_URL_TEXT = "[허용되지 않는 URL]"


@dataclass(frozen=True)
class Block:
    html: str
    units: int


# Dataset values are always untrusted. Only fragments built inside this module
# from validated URLs and escaped text may cross the trust boundary as TrustedHtml.
@dataclass(frozen=True)
class TrustedHtml:
    html: str


@dataclass(frozen=True)
class RenderProfile:
    name: str
    toc_budget: int
    index_single_page_limit: int
    index_chunk_budget: int
    finding_page_budget: int
    evidence_chunk_budget: int
    countermeasure_row_budget: int
    countermeasure_page_budget: int
    appendix_page_budget: int
    unit_scale: float
    image_max_height_mm: int
    image_max_height_print_mm: int
    body_font_size_pt: float
    print_body_font_size_pt: float
    print_line_height: float


PROFILES: dict[str, RenderProfile] = {
    "normal-compact": RenderProfile(
        name="normal-compact",
        toc_budget=32,
        index_single_page_limit=40,
        index_chunk_budget=28,
        finding_page_budget=106,
        evidence_chunk_budget=40,
        countermeasure_row_budget=40,
        countermeasure_page_budget=92,
        appendix_page_budget=90,
        unit_scale=0.92,
        image_max_height_mm=160,
        image_max_height_print_mm=150,
        body_font_size_pt=10.0,
        print_body_font_size_pt=9.35,
        print_line_height=1.38,
    ),
    "normal-balanced": RenderProfile(
        name="normal-balanced",
        toc_budget=30,
        index_single_page_limit=36,
        index_chunk_budget=24,
        finding_page_budget=92,
        evidence_chunk_budget=34,
        countermeasure_row_budget=36,
        countermeasure_page_budget=88,
        appendix_page_budget=86,
        unit_scale=0.98,
        image_max_height_mm=156,
        image_max_height_print_mm=146,
        body_font_size_pt=10.0,
        print_body_font_size_pt=9.45,
        print_line_height=1.4,
    ),
    "stress-safe": RenderProfile(
        name="stress-safe",
        toc_budget=28,
        index_single_page_limit=32,
        index_chunk_budget=24,
        finding_page_budget=88,
        evidence_chunk_budget=32,
        countermeasure_row_budget=34,
        countermeasure_page_budget=86,
        appendix_page_budget=84,
        unit_scale=1.0,
        image_max_height_mm=155,
        image_max_height_print_mm=145,
        body_font_size_pt=10.0,
        print_body_font_size_pt=9.5,
        print_line_height=1.42,
    ),
}

DEFAULT_PROFILE_BY_DATASET = {
    "default": "normal-compact",
    "stress": "stress-safe",
    "real-assets": "normal-balanced",
}

DATASET_OUTPUT_SUFFIX = {
    "default": "",
    "stress": "-stress",
    "real-assets": "-real-assets",
}
TABLE_SAMPLE_BASENAME = "report-table-sample"

WINDOWS_FONT_DIR = Path(r"C:\Windows\Fonts")
MALGUN_FONT = WINDOWS_FONT_DIR / "malgun.ttf"
MALGUN_BOLD_FONT = WINDOWS_FONT_DIR / "malgunbd.ttf"
CONSOLAS_FONT = WINDOWS_FONT_DIR / "consola.ttf"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@lru_cache(maxsize=None)
def read_template(name: str) -> str:
    path = TEMPLATES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Missing template file: {path}")
    return read_text(path)


@lru_cache(maxsize=None)
def read_json_file(path: str) -> object:
    return json.loads(read_text(Path(path)))


def read_json_data(name: str) -> object:
    path = DATA_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Missing data file: {path}")
    return read_json_file(str(path))


def resolve_profile(dataset_name: str, override: str | None = None) -> RenderProfile:
    profile_name = override or DEFAULT_PROFILE_BY_DATASET[dataset_name]
    if profile_name not in PROFILES:
        raise KeyError(f"Unknown render profile: {profile_name}")
    return PROFILES[profile_name]


def scaled_units(units: int, scale: float) -> int:
    return max(1, math.ceil(units * scale))


@lru_cache(maxsize=1)
def resolve_browser_executable() -> str | None:
    for candidate in BROWSER_EXECUTABLE_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return str(path)
    for command in ("msedge.exe", "msedge", "microsoft-edge", "chromium-browser", "chromium", "google-chrome"):
        resolved = shutil.which(command)
        if resolved:
            return resolved
    return None


def browser_is_windows_executable(executable: str) -> bool:
    return executable.lower().endswith(".exe")


def to_windows_path(path: Path) -> str | None:
    resolved = path.resolve()
    if resolved.drive:
        return str(resolved)
    wslpath = shutil.which("wslpath")
    if wslpath:
        result = subprocess.run(
            [wslpath, "-w", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return normalize_text(result.stdout)
    parts = resolved.parts
    if len(parts) >= 4 and parts[1] == "mnt" and len(parts[2]) == 1:
        return str(PureWindowsPath(f"{parts[2].upper()}:/", *parts[3:]))
    return None


def browser_file_argument(path: Path, executable: str) -> str:
    if browser_is_windows_executable(executable):
        windows_path = to_windows_path(path)
        if not windows_path:
            raise RuntimeError(f"Cannot translate path for Windows browser: {path}")
        return windows_path
    return str(path)


def browser_file_uri(path: Path, executable: str) -> str:
    if browser_is_windows_executable(executable):
        windows_path = to_windows_path(path)
        if not windows_path:
            raise RuntimeError(f"Cannot translate file URI for Windows browser: {path}")
        posix_path = PureWindowsPath(windows_path).as_posix()
        return f"file:///{quote(posix_path, safe=':/')}"
    return path.resolve().as_uri()


def powershell_executable() -> str | None:
    for candidate in (
        "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
        "/mnt/c/Program Files/PowerShell/7/pwsh.exe",
    ):
        if Path(candidate).exists():
            return candidate
    return shutil.which("powershell.exe") or shutil.which("pwsh.exe")


def shell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def powershell_arg(value: str) -> str:
    return shell_single_quote(value) if re.search(r"\s", value) or "'" in value else value


def browser_temp_dir() -> Path:
    root_parts = ROOT_DIR.resolve().parts
    if len(root_parts) >= 3 and root_parts[1] == "mnt" and len(root_parts[2]) == 1:
        path = Path("/", "mnt", root_parts[2], "_codex_browser_tmp")
    else:
        path = DIST_DIR / ".browser-tmp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_browser_process(
    executable: str,
    args: list[str],
    *,
    timeout: int = 120,
    stdout_path: Path | None = None,
) -> subprocess.CompletedProcess[bytes]:
    if not browser_is_windows_executable(executable):
        return subprocess.run([executable, *args], capture_output=True, timeout=timeout)

    powershell = powershell_executable()
    if not powershell:
        return subprocess.run([executable, *args], capture_output=True, timeout=timeout)

    temp_script: Path | None = None
    temp_stdout: Path | None = None
    temp_stderr: Path | None = None
    try:
        windows_executable = to_windows_path(Path(executable)) or executable
        arg_lines = "\n".join(f"  {shell_single_quote(arg)}" for arg in args)
        script_body = "$ErrorActionPreference = 'Stop'\n" "$argList = @(\n" f"{arg_lines}\n" ")\n"
        stdout_target: Path | None = None
        stderr_target: Path | None = None
        if stdout_path:
            stdout_target = stdout_path
            stderr_target = browser_temp_dir() / f"stderr-{next(tempfile._get_candidate_names())}.txt"
            temp_stderr = stderr_target
            stdout_win_path = to_windows_path(stdout_target)
            stderr_win_path = to_windows_path(stderr_target)
            if not stdout_win_path or not stderr_win_path:
                raise RuntimeError("Cannot translate browser redirect paths for Windows browser")
            script_body += (
                f"Start-Process -FilePath {shell_single_quote(windows_executable)} "
                f"-ArgumentList $argList -Wait "
                f"-RedirectStandardOutput {shell_single_quote(stdout_win_path)} "
                f"-RedirectStandardError {shell_single_quote(stderr_win_path)}\n"
            )
        else:
            script_body += (
                f"Start-Process -FilePath {shell_single_quote(windows_executable)} "
                "-ArgumentList $argList -Wait\n"
            )

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix="-browser-wrapper.ps1",
            dir=browser_temp_dir(),
            delete=False,
        ) as handle:
            handle.write(script_body)
            temp_script = Path(handle.name)

        script_arg = to_windows_path(temp_script) or str(temp_script)
        script_result = subprocess.run(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_arg],
            capture_output=True,
            timeout=timeout,
        )
        stdout_bytes = stdout_target.read_bytes() if stdout_target and stdout_target.exists() else b""
        stderr_bytes = stderr_target.read_bytes() if stderr_target and stderr_target.exists() else b""
        combined_stderr = stderr_bytes or script_result.stderr
        return subprocess.CompletedProcess(
            [executable, *args],
            script_result.returncode,
            stdout_bytes,
            combined_stderr,
        )
    finally:
        if temp_stdout and temp_stdout.exists():
            temp_stdout.unlink()
        if temp_stderr and temp_stderr.exists():
            temp_stderr.unlink()
        if temp_script and temp_script.exists():
            temp_script.unlink()


def extract_at_rule_block(css: str, at_rule: str) -> str:
    start = css.find(at_rule)
    if start == -1:
        return ""
    brace_index = css.find("{", start)
    if brace_index == -1:
        return ""
    depth = 1
    cursor = brace_index + 1
    while cursor < len(css) and depth:
        char = css[cursor]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        cursor += 1
    return css[brace_index + 1 : cursor - 1].strip()


def profile_style_vars(profile: RenderProfile) -> str:
    return (
        f"--report-body-font-size:{profile.body_font_size_pt:.2f}pt;"
        f"--report-print-body-font-size:{profile.print_body_font_size_pt:.2f}pt;"
        f"--report-print-line-height:{profile.print_line_height:.2f};"
        f"--report-evidence-image-max-height:{profile.image_max_height_mm}mm;"
        f"--report-evidence-image-max-height-print:{profile.image_max_height_print_mm}mm;"
    )


def build_layout_probe_css(css: str) -> str:
    print_css = extract_at_rule_block(css, "@media print")
    return (
        css
        + "\n\n"
        + print_css
        + "\n\n"
        + f"""
body.layout-probe {{
  background: #fff;
  width: {PRINT_CONTENT_WIDTH_MM:.2f}mm;
  margin: 0 auto;
}}

body.layout-probe main.report-document {{
  width: auto;
  margin: 0;
}}

body.layout-probe section.print-page-start:not(:first-of-type) {{
  page-break-before: auto !important;
  break-before: auto !important;
}}

body.layout-probe section.report-section {{
  margin-bottom: 0;
}}
""".strip()
        + "\n"
    )


def build_layout_probe_document(body: str, css: str, profile: RenderProfile, dataset_name: str) -> str:
    probe_css = build_layout_probe_css(css)
    page_height_px = PRINT_CONTENT_HEIGHT_MM * 96 / 25.4
    probe_script = f"""
(() => {{
  const PAGE_HEIGHT_PX = {page_height_px:.3f};
  const delay = {LAYOUT_PROBE_DELAY_MS};
  function sourceFor(element) {{
    if (element.matches('section')) return 'section';
    if (element.matches('h1, h2, h3')) return 'heading';
    if (element.classList.contains('vuln-block')) return 'vuln-block';
    if (element.classList.contains('table-caption')) return 'table-caption';
    if (element.classList.contains('figure-caption')) return 'figure-caption';
    return element.tagName.toLowerCase();
  }}
  function collect() {{
    const sections = [...document.querySelectorAll('section.print-page-start')];
    const result = {{
      page_height_px: Math.round(PAGE_HEIGHT_PX * 100) / 100,
      estimated_total_pages: 0,
      page_map: {{}},
      sections: [],
    }};
    let currentPage = 1;
    for (const section of sections) {{
      const sectionRect = section.getBoundingClientRect();
      const seen = new Set();
      const sectionKeys = [];
      for (const element of section.querySelectorAll('[data-toc-key]')) {{
        const key = element.getAttribute('data-toc-key');
        if (!key || seen.has(key)) continue;
        seen.add(key);
        const rect = element.getBoundingClientRect();
        const relativeTop = Math.max(0, rect.top - sectionRect.top);
        const estimatedPage = currentPage + Math.floor(relativeTop / PAGE_HEIGHT_PX);
        sectionKeys.push(key);
        if (!result.page_map[key]) {{
          result.page_map[key] = {{
            page: estimatedPage,
            source: sourceFor(element),
            confidence: element.matches('section') ? '보조추정' : '추정',
          }};
        }}
      }}
      const estimatedPages = Math.max(1, Math.ceil((section.scrollHeight + 1) / PAGE_HEIGHT_PX));
      result.sections.push({{
        id: section.id,
        toc_keys: sectionKeys,
        start_page: currentPage,
        estimated_pages: estimatedPages,
        scroll_height_px: Math.round(section.scrollHeight),
      }});
      currentPage += estimatedPages;
    }}
    result.estimated_total_pages = Math.max(1, currentPage - 1);
    const marker = document.createElement('script');
    marker.id = '{LAYOUT_PROBE_MARKER}';
    marker.type = 'application/json';
    marker.textContent = JSON.stringify(result);
    document.body.appendChild(marker);
  }}
  window.addEventListener('load', () => window.setTimeout(collect, delay), {{ once: true }});
}})();
""".strip()
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="ko" data-theme="light" data-profile="{profile.name}" data-dataset="{dataset_name}" style="{profile_style_vars(profile)}"><head>\n'
        '    <meta charset="UTF-8">\n'
        f"    <title>{TITLE} · Layout Probe</title>\n"
        "    <style>\n"
        f"{probe_css}"
        "    </style>\n"
        "  </head>\n"
        '  <body class="layout-probe">\n'
        '    <main class="report-document">\n'
        f"{body}"
        "    </main>\n"
        "    <script>\n"
        f"{probe_script}\n"
        "    </script>\n"
        "  </body></html>\n"
    )


def pil_font(size: int, *, bold: bool = False):
    try:
        from PIL import ImageFont
    except Exception:
        return None

    candidates = [MALGUN_BOLD_FONT, MALGUN_FONT, CONSOLAS_FONT] if bold else [MALGUN_FONT, CONSOLAS_FONT]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except Exception:
                continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def image_file_to_data_uri(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def create_raster_sample(
    output_path: Path,
    *,
    width: int,
    height: int,
    image_format: str,
    title: str,
    subtitle: str,
    accent: str,
    dense_text: bool = False,
) -> dict[str, object]:
    from PIL import Image, ImageDraw

    background = (238, 244, 249)
    chrome = (35, 51, 79)
    panel = (255, 255, 255)
    muted = (104, 122, 147)
    border = (199, 214, 233)
    accent_rgb = tuple(int(accent[i : i + 2], 16) for i in (1, 3, 5))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    title_font = pil_font(max(28, width // 34), bold=True)
    section_font = pil_font(max(20, width // 54), bold=True)
    body_font = pil_font(max(18, width // 72))
    mono_font = pil_font(max(16, width // 84))

    draw.rectangle((0, 0, width, 88), fill=chrome)
    draw.rectangle((32, 120, width - 32, height - 32), fill=panel, outline=border, width=3)
    draw.rectangle((64, 164, width - 64, 240), fill=accent_rgb)
    draw.text((92, 182), title, fill=(255, 255, 255), font=title_font)
    draw.text((92, 258), subtitle, fill=chrome, font=section_font)

    sidebar_width = max(180, width // 5)
    draw.rounded_rectangle((92, 318, 92 + sidebar_width, height - 92), radius=22, fill=(243, 247, 252), outline=border, width=2)
    for index in range(10):
        top = 356 + index * 76
        if top + 26 > height - 120:
            break
        draw.rounded_rectangle((122, top, 122 + sidebar_width - 60, top + 28), radius=6, fill=accent_rgb if index == 0 else border)

    content_left = 128 + sidebar_width
    content_right = width - 96
    card_top = 330
    card_gap = 24
    card_height = 220 if not dense_text else 188
    card_count = 3 if height < 1900 else 5
    for card_index in range(card_count):
        top = card_top + card_index * (card_height + card_gap)
        if top + card_height > height - 124:
            break
        draw.rounded_rectangle((content_left, top, content_right, top + card_height), radius=18, fill=(250, 252, 255), outline=border, width=2)
        draw.text((content_left + 28, top + 24), f"Section {card_index + 1}", fill=chrome, font=section_font)
        line_y = top + 72
        line_count = 7 if dense_text else 5
        for line_index in range(line_count):
            line_width = max(220, content_right - content_left - 80 - (line_index % 3) * 80)
            draw.rounded_rectangle((content_left + 28, line_y, content_left + 28 + line_width, line_y + 18), radius=4, fill=border)
            line_y += 28
        draw.rounded_rectangle((content_left + 28, top + card_height - 56, content_left + 240, top + card_height - 26), radius=8, fill=accent_rgb)

    footer_top = height - 148
    draw.rectangle((92, footer_top, width - 92, footer_top + 34), fill=(245, 248, 252))
    draw.text(
        (112, footer_top + 6),
        f"{width}x{height} / {image_format.upper()} / {'dense-text' if dense_text else 'general-ui'}",
        fill=muted,
        font=mono_font,
    )

    if dense_text:
        dense_left = content_left
        dense_top = max(330, height - 980)
        dense_bottom = height - 198
        draw.rounded_rectangle((dense_left, dense_top, content_right, dense_bottom), radius=18, fill=(255, 255, 255), outline=border, width=2)
        draw.text((dense_left + 24, dense_top + 20), "Log / Response Preview", fill=chrome, font=section_font)
        cursor_y = dense_top + 64
        for line_index in range(24):
            text = (
                f"{line_index + 1:02d} GET /api/v2/report/detail?id={1200 + line_index}"
                f"&trace=TRACE-{line_index:02d}-ABCD1234 status=200 message=ALLOW"
            )
            draw.text((dense_left + 24, cursor_y), text, fill=(73, 84, 103), font=mono_font)
            cursor_y += 24
            if cursor_y > dense_bottom - 30:
                break

    save_kwargs = {}
    if image_format.upper() == "JPEG":
        save_kwargs["quality"] = 92
        save_kwargs["subsampling"] = 0
    image.save(output_path, format=image_format.upper(), **save_kwargs)
    return {
        "file_name": output_path.name,
        "file_path": str(output_path),
        "image_format": image_format.lower(),
        "image_src": image_file_to_data_uri(output_path),
        "image_width": width,
        "image_height": height,
    }


def real_asset_record(spec: dict[str, object], path: Path, *, source: str) -> dict[str, object]:
    return {
        "file_name": path.name,
        "file_path": str(path),
        "image_format": str(spec["image_format"]).lower(),
        "image_src": image_file_to_data_uri(path),
        "image_width": int(spec["width"]),
        "image_height": int(spec["height"]),
        "kind": spec["kind"],
        "source": source,
    }


def ensure_real_asset_samples() -> list[dict[str, object]]:
    assets: list[dict[str, object]] = []
    for spec in REAL_ASSET_SPECS:
        path = REAL_ASSET_SAMPLE_DIR / str(spec["file_name"])
        if path.exists():
            assets.append(real_asset_record(spec, path, source="existing-file"))
            continue
        try:
            asset = create_raster_sample(
                path,
                width=int(spec["width"]),
                height=int(spec["height"]),
                image_format=str(spec["image_format"]),
                title=str(spec["title"]),
                subtitle=str(spec["subtitle"]),
                accent=str(spec["accent"]),
                dense_text=bool(spec["dense_text"]),
            )
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Pillow 미설치 상태이며 기존 PNG/JPG 샘플도 없습니다. "
                "dist/real-asset-samples/를 유지하거나 Pillow를 설치하십시오."
            ) from exc
        asset["kind"] = spec["kind"]
        asset["source"] = "generated"
        assets.append(asset)
    return assets


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


def normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value)


def raw_text(value: object) -> str:
    return "" if value is None else str(value)


def strip_control_chars(value: str, *, replacement: str = "") -> str:
    return CONTROL_CHAR_RE.sub(replacement, value)


def escape_html_text(value: object) -> str:
    return escape(raw_text(value), quote=False)


def escape_html_attr(value: object) -> str:
    return escape(strip_control_chars(raw_text(value), replacement=" "), quote=True)


def render_trusted_html(value: object) -> str:
    if not isinstance(value, TrustedHtml):
        raise TypeError(f"Expected TrustedHtml, got {type(value).__name__}")
    return value.html


def trusted_html(value: str) -> TrustedHtml:
    return TrustedHtml(value)


def sanitize_url(
    value: object,
    *,
    allowed_schemes: tuple[str, ...] = ("https",),
    allow_relative: bool = True,
    allow_data_image: bool = False,
) -> str:
    candidate = raw_text(value).strip()
    if not candidate:
        return ""
    if URL_UNSAFE_CHAR_RE.search(candidate):
        return ""
    parts = urlsplit(candidate)
    scheme = parts.scheme.lower()
    if scheme == "data":
        if allow_data_image and DATA_IMAGE_URL_RE.fullmatch(candidate):
            return candidate
        return ""
    if scheme:
        if scheme not in allowed_schemes:
            return ""
        if scheme in {"http", "https"} and not parts.netloc:
            return ""
        return candidate
    if not allow_relative:
        return ""
    if candidate.startswith("//") or parts.netloc:
        return ""
    return candidate


def sanitize_image_src(value: object) -> str:
    return sanitize_url(value, allowed_schemes=("https",), allow_relative=True, allow_data_image=True)


def sanitize_target_url(value: object) -> str:
    return sanitize_url(value, allowed_schemes=("http", "https"), allow_relative=True, allow_data_image=False)


def sanitize_display_url(value: object) -> str:
    raw_value = raw_text(value).strip()
    if not raw_value:
        return ""
    sanitized = sanitize_target_url(raw_value)
    return sanitized or BLOCKED_URL_TEXT


def sanitize_risk_key(value: object) -> str:
    key = normalize_text(value).lower()
    return key if key in ALLOWED_RISK_KEYS else "low"


def sanitize_repeat_name(value: object) -> str:
    name = normalize_text(value)
    return name if name in ALLOWED_REPEAT_NAMES else "invalid-repeat"


def sanitize_toc_style(value: object) -> str:
    style = normalize_text(value)
    return style if style in ALLOWED_TOC_INLINE_STYLES else ""


def sanitize_data_field(value: object, fallback: str = "invalid.field") -> str:
    field = strip_control_chars(raw_text(value))
    return field if SAFE_DATA_FIELD_RE.fullmatch(field) else fallback


def sanitize_dom_id(value: object, *, prefix: str) -> str:
    text = normalize_text(value).lower()
    slug = SAFE_DOM_ID_RE.sub("-", text).strip("-._:")
    if not slug:
        slug = prefix
    if not slug[0].isalpha():
        slug = f"{prefix}-{slug}"
    return slug


def toc_label_text(value: object) -> str:
    return strip_tags(raw_text(value))


def render_toc_label_fragment(value: object) -> TrustedHtml:
    label_text = escape_html_text(toc_label_text(value))
    if TOC_BOLD_MARKER_RE.search(raw_text(value)):
        return trusted_html(f"<strong>{label_text}</strong>")
    return trusted_html(f"<span>{label_text}</span>")


def text_units(value: object, chars_per_unit: int = 95, base: int = 0) -> int:
    text = normalize_text(value)
    if not text:
        return max(1, base)
    return max(1, base + math.ceil(len(text) / chars_per_unit))


def list_units(items: list[str], chars_per_unit: int = 110, base: int = 0) -> int:
    if not items:
        return max(1, base)
    return max(1, base + sum(text_units(item, chars_per_unit) for item in items))


def pack_blocks(blocks: list[Block], budget: int, scale: float = 1.0) -> list[list[Block]]:
    pages: list[list[Block]] = []
    current: list[Block] = []
    current_units = 0
    for block in blocks:
        units = min(scaled_units(block.units, scale), budget)
        if current and current_units + units > budget:
            pages.append(current)
            current = [block]
            current_units = units
            continue
        current.append(block)
        current_units += units
    if current:
        pages.append(current)
    return pages


def join_blocks(blocks: list[str], indent: str = "") -> str:
    content = "\n\n".join(block.rstrip() for block in blocks if block.strip())
    if not indent or not content:
        return content
    return "\n".join(f"{indent}{line}" if line else "" for line in content.splitlines())


def indent_block(text: str, indent: str) -> str:
    return "\n".join(f"{indent}{line}" if line else "" for line in text.splitlines())


def template_token_context(template: str, token_start: int) -> str:
    state = "text"
    quote_char = ""
    index = 0
    while index < token_start:
        if state == "text":
            if template.startswith("<!--", index):
                state = "comment"
                index += 4
                continue
            if template[index] == "<":
                state = "tag"
                index += 1
                continue
            index += 1
            continue
        if state == "comment":
            if template.startswith("-->", index):
                state = "text"
                index += 3
                continue
            index += 1
            continue
        char = template[index]
        if quote_char:
            if char == quote_char:
                quote_char = ""
            index += 1
            continue
        if char in {'"', "'"}:
            quote_char = char
            index += 1
            continue
        if char == ">":
            state = "text"
            index += 1
            continue
        index += 1
    if state == "comment":
        return "text"
    if quote_char:
        return "attr"
    return state


def render_template_token(template_name: str, key: str, value: object, *, context: str) -> str:
    if context == "text":
        if isinstance(value, TrustedHtml):
            return render_trusted_html(value)
        return escape_html_text(value)
    if context == "attr":
        if isinstance(value, TrustedHtml):
            raise TypeError(f"TrustedHtml cannot be inserted into attribute context: {template_name}:{key}")
        return escape_html_attr(value)
    if isinstance(value, TrustedHtml):
        return render_trusted_html(value)
    raise TypeError(f"{template_name}:{key} requires an explicit TrustedHtml fragment")


def render_template(template_name: str, context: dict[str, object]) -> str:
    template = read_template(template_name)

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context:
            raise KeyError(f"Missing template value '{key}' for {template_name}")
        return render_template_token(
            template_name,
            key,
            context[key],
            context=template_token_context(template, match.start()),
        )

    return TEMPLATE_TOKEN_RE.sub(replace, template)


def render_li_items(items: list[str], indent: str) -> str:
    return "\n".join(f"{indent}<li>{escape_html_text(item)}</li>" for item in items)


def render_cover_logo_html(dataset: dict[str, object]) -> str:
    logo = dataset.get("_real_asset_logo")
    if not isinstance(logo, dict):
        return "[기관 로고]"
    image_src = sanitize_image_src(logo.get("image_src"))
    if not image_src:
        return "[기관 로고]"
    return (
        f'<img src="{escape_html_attr(image_src)}" alt="기관 로고 샘플" '
        'style="max-width: 100%; max-height: 100%; object-fit: contain; display: block" />'
    )


def risk_badge_class(risk_key: str) -> str:
    return {
        "high": "badge-high",
        "mid": "badge-mid",
        "low": "badge-low",
    }[sanitize_risk_key(risk_key)]


def priority_row_class(risk_key: str) -> str:
    return {
        "high": "priority-high",
        "mid": "priority-mid",
        "low": "priority-low",
    }[sanitize_risk_key(risk_key)]


def mitigation_repeat_name(track: str) -> str:
    return sanitize_repeat_name(f"mitigation-{track}")


def mitigation_id_classes(track: str) -> str:
    return "auto-field" if track == "short" else "placeholder auto-field"


def finding_dom_id(finding: dict[str, object]) -> str:
    return sanitize_dom_id(f"finding-{raw_text(finding.get('id', ''))}", prefix="finding")


def finding_toc_key(finding: dict[str, object]) -> str:
    return finding_dom_id(finding)


def dataset_output_paths(dataset_name: str) -> tuple[Path, Path, Path]:
    suffix = DATASET_OUTPUT_SUFFIX[dataset_name]
    return (
        DIST_DIR / f"report{suffix}.html",
        DIST_DIR / f"report{suffix}.pdf",
        DIST_DIR / f"report{suffix}.validation.json",
    )


def load_dataset(dataset_name: str, profile: RenderProfile) -> dict[str, object]:
    dataset = {
        "toc": read_json_data("toc.json"),
        "indices": read_json_data("indices.json"),
        "diagnostic_overview": read_json_data("diagnostic_overview.json"),
        "summary": read_json_data("summary.json"),
        "findings": read_json_data("findings.json"),
        "countermeasures": read_json_data("countermeasures.json"),
        "appendix_c": read_json_data("appendix-c.json"),
        "stress_profile": read_json_data("stress.json") if STRESS_PROFILE_FILE.exists() else {},
        "_dataset_name": dataset_name,
        "_profile": profile,
        "_profile_name": profile.name,
    }
    if dataset_name == "stress":
        return synthesize_stress_dataset(dataset)
    if dataset_name == "real-assets":
        return synthesize_real_asset_dataset(dataset)
    return dataset


def synthesize_real_asset_dataset(base_dataset: dict[str, object]) -> dict[str, object]:
    dataset = copy.deepcopy(base_dataset)
    assets = ensure_real_asset_samples()
    if REAL_ASSET_LOGO_FILE.exists():
        dataset["_real_asset_logo"] = {
            "file_name": REAL_ASSET_LOGO_FILE.name,
            "file_path": str(REAL_ASSET_LOGO_FILE),
            "image_format": "png",
            "image_src": image_file_to_data_uri(REAL_ASSET_LOGO_FILE),
        }
    asset_cursor = 0

    for finding in dataset["findings"]:
        for evidence in finding["evidences"]:
            asset = assets[asset_cursor % len(assets)]
            asset_cursor += 1
            evidence.update(
                {
                    "image_src": asset["image_src"],
                    "image_alt": f"{finding['id']} {evidence['evidence_id']} {asset['kind']} sample image",
                    "image_width": asset["image_width"],
                    "image_height": asset["image_height"],
                    "image_kind": asset["kind"],
                    "image_format": asset["image_format"],
                    "image_file_name": asset["file_name"],
                }
            )

    for index, item in enumerate(dataset["appendix_c"]):
        asset = assets[(asset_cursor + index) % len(assets)]
        item.update(
            {
                "image_src": asset["image_src"],
                "image_alt": f"Appendix {item['evidence_id']} {asset['kind']} sample image",
                "image_width": asset["image_width"],
                "image_height": asset["image_height"],
                "image_kind": asset["kind"],
                "image_format": asset["image_format"],
                "image_file_name": asset["file_name"],
            }
        )

    dataset["_real_asset_samples"] = [
        {
            "file_name": asset["file_name"],
            "file_path": asset["file_path"],
            "image_format": asset["image_format"],
            "image_width": asset["image_width"],
            "image_height": asset["image_height"],
            "kind": asset["kind"],
        }
        for asset in assets
    ]
    return dataset


def table_sample_output_paths() -> tuple[Path, Path, Path]:
    return (
        DIST_DIR / f"{TABLE_SAMPLE_BASENAME}.html",
        DIST_DIR / f"{TABLE_SAMPLE_BASENAME}.pdf",
        DIST_DIR / f"{TABLE_SAMPLE_BASENAME}.validation.json",
    )


def synthesize_target_table_rows(count: int = 28) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index in range(1, count + 1):
        rows.append(
            {
                "number": str(index),
                "system_name": f"업무 포털 시스템 {index:02d}",
                "target_url": (
                    f"https://target-{index:02d}.example.go.kr/portal/service/{1000 + index}/"
                    f"detail/view?role={'admin' if index % 4 == 0 else 'user'}&traceId=TAB-{index:02d}-{'X' * 10}"
                ),
                "account_level": "일반/관리자" if index % 3 == 0 else "일반",
                "note": (
                    "실제 multi-page 표 헤더 반복 및 continuation caption 검증용 샘플 데이터. "
                    f"장문 비고 #{index:02d} / API 포함 여부={'예' if index % 2 else '아니오'} / "
                    "운영·개발 분리 여부 및 접근 제어 조건을 함께 기재."
                ),
            }
        )
    return rows


def synthesize_stress_dataset(base_dataset: dict[str, object]) -> dict[str, object]:
    profile = dict(base_dataset.get("stress_profile") or {})
    findings_count = int(profile.get("finding_count", 10))
    appendix_count = int(profile.get("appendix_count", 14))
    evidence_pattern = list(profile.get("evidence_counts", [3, 4, 5, 6, 4, 5, 3, 6, 4, 5]))
    system_names = list(
        profile.get(
            "systems",
            [
                "대민 통합 포털",
                "행정업무 지원 시스템",
                "민원 처리 API 게이트웨이",
                "통합 인증 서비스",
                "모바일 민원 백엔드",
            ],
        )
    )
    owner_names = list(
        profile.get(
            "owners",
            [
                "디지털서비스팀",
                "정보보호팀",
                "통합운영팀",
                "서비스개발팀",
                "데이터플랫폼팀",
            ],
        )
    )
    reviewer_names = list(
        profile.get(
            "reviewers",
            [
                "품질보증책임자",
                "모의해킹 PM",
                "보안아키텍트",
                "운영총괄",
                "서비스오너",
            ],
        )
    )

    def risk_info(index: int) -> tuple[str, str]:
        plan = [
            ("high", "상"),
            ("high", "상"),
            ("mid", "중"),
            ("high", "상"),
            ("mid", "중"),
            ("low", "하"),
            ("mid", "중"),
            ("high", "상"),
            ("mid", "중"),
            ("low", "하"),
            ("mid", "중"),
            ("high", "상"),
        ]
        return plan[index % len(plan)]

    def long_url(index: int, segment: int) -> str:
        return (
            f"https://portal-{(index % len(system_names)) + 1}.example.go.kr/"
            f"api/v2/workflow/case/{1000 + index}/step/{segment}/result/detail?"
            f"userId=stress-user-{index:02d}&role=auditor&traceId=TRACE-{index:02d}-{segment:02d}-"
            f"{'a' * 18}&redirect=%2Fconsole%2Fview%2Freport%2F{index:02d}%2F{segment:02d}%2Fraw"
        )

    def paragraph(index: int, topic: str, extra: str = "") -> str:
        return (
            f"{topic} 구간에서 파라미터 검증과 권한 검증이 동시에 누락된 상태를 가정한 stress 문단입니다. "
            f"테스트 계정, 운영과 유사한 데이터셋, 장문의 한글 설명, 영문 식별자, 긴 URL과 파라미터 문자열이 함께 배치되어도 "
            f"줄바꿈과 페이지 분할이 안정적으로 유지되어야 합니다. "
            f"특히 requestId=REQ-{index:02d}-{'X' * 16}, referencePath={long_url(index, 1)} 와 같이 셀 폭을 쉽게 넘길 수 있는 문자열을 포함합니다. "
            f"이 문단은 보고서의 wrapping, orphan/widow, overflow 제어를 검증하기 위해 의도적으로 길게 작성되었습니다. {extra}"
        )

    def list_item(index: int, step: int) -> str:
        return (
            f"{step}. stress 재현 단계 {step}에서는 endpoint={long_url(index, step)} 로 요청을 전송하고 "
            f"header X-Stress-Trace=TRACE-{index:02d}-{step:02d}-{'B' * 12}, "
            f"payload=caseId={10000 + index * 10 + step}&authority=normal-user&override={'true' if step % 2 else 'false'} 값을 함께 사용합니다."
        )

    def svg_data_uri(width: int, height: int, title: str, subtitle: str, accent: str) -> str:
        svg = f"""
<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#f5f9ff"/>
      <stop offset="100%" stop-color="#e1ebf8"/>
    </linearGradient>
    <pattern id="grid" width="48" height="48" patternUnits="userSpaceOnUse">
      <path d="M 48 0 L 0 0 0 48" fill="none" stroke="#d7e3f2" stroke-width="1"/>
    </pattern>
  </defs>
  <rect width="{width}" height="{height}" fill="url(#bg)"/>
  <rect width="{width}" height="{height}" fill="url(#grid)"/>
  <rect x="36" y="36" width="{width - 72}" height="{height - 72}" rx="18" fill="white" stroke="{accent}" stroke-width="6"/>
  <rect x="72" y="88" width="{max(140, width - 144)}" height="54" rx="10" fill="{accent}" opacity="0.92"/>
  <text x="96" y="124" font-family="Malgun Gothic, Noto Sans KR, sans-serif" font-size="34" font-weight="700" fill="white">{escape(title)}</text>
  <text x="96" y="188" font-family="Malgun Gothic, Noto Sans KR, sans-serif" font-size="24" fill="#1a2a4a">{escape(subtitle)}</text>
  <g transform="translate(96 250)">
    <rect width="{max(220, width - 192)}" height="{max(180, height - 360)}" rx="14" fill="#eff5fc" stroke="#bfd2ea" stroke-width="3"/>
    <rect x="36" y="42" width="{max(140, width - 264)}" height="28" rx="6" fill="#1a2a4a" opacity="0.9"/>
    <rect x="36" y="96" width="{max(120, width - 300)}" height="18" rx="4" fill="#6f89ab" opacity="0.55"/>
    <rect x="36" y="136" width="{max(180, width - 240)}" height="18" rx="4" fill="#6f89ab" opacity="0.3"/>
    <rect x="36" y="176" width="{max(150, width - 320)}" height="18" rx="4" fill="#6f89ab" opacity="0.3"/>
  </g>
  <text x="{width - 72}" y="{height - 48}" text-anchor="end" font-family="Consolas, monospace" font-size="20" fill="#5f7592">
    {width} x {height} / stress preview
  </text>
</svg>
""".strip()
        encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
        return f"data:image/svg+xml;base64,{encoded}"

    def image_spec(index: int, evidence_index: int) -> tuple[int, int, str]:
        palette = ["#2c4a7c", "#2c6db5", "#3a6b5e", "#8b5c1f"]
        variants = [
            (1880, 880, palette[0]),
            (960, 1760, palette[1]),
            (2100, 760, palette[2]),
            (1180, 1520, palette[3]),
        ]
        return variants[(index + evidence_index) % len(variants)]

    findings: list[dict[str, object]] = []
    appendix_items: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    priority_rows: list[dict[str, object]] = []
    mitigation_rows = {"short": [], "mid": [], "long": []}
    figure_counter = 2

    for index in range(findings_count):
        finding_id = f"VUL-{index + 1:03d}"
        system_name = system_names[index % len(system_names)]
        risk_key, risk_label = risk_info(index)
        evidence_count = evidence_pattern[index % len(evidence_pattern)]
        target_url = long_url(index, 0)
        title = (
            f"{system_name}의 인증 우회 및 장문 파라미터 위변조를 통한 "
            f"비인가 데이터 조회 가능성 #{index + 1}"
        )
        evidence_ids: list[str] = []
        evidences: list[dict[str, object]] = []
        for evidence_index in range(evidence_count):
            evidence_id = f"EVD-{index + 1:03d}-{evidence_index + 1:02d}"
            width, height, accent = image_spec(index, evidence_index)
            figure_id = f"figure-{figure_counter:02d}"
            figure_counter += 1
            evidence_ids.append(evidence_id)
            evidence_title = (
                f"stress 재현 증빙 {evidence_index + 1}: 요청/응답 비교, 긴 URL, 세로/가로 비율 검증"
            )
            image_src = svg_data_uri(
                width=width,
                height=height,
                title=evidence_id,
                subtitle=f"{finding_id} / {system_name} / {width}x{height}",
                accent=accent,
            )
            evidence = {
                "evidence_id": evidence_id,
                "title": evidence_title,
                "lead_label": "파라미터/입력값" if evidence_index % 2 == 0 else "재현 단계",
                "lead_field": "input" if evidence_index % 2 == 0 else "step",
                "lead_text": (
                    f"id={index + 1}&workflow={'admin-export' if evidence_index % 2 == 0 else 'case-view'}"
                    f"&redirect={long_url(index, evidence_index + 1)}"
                ),
                "io_text": paragraph(
                    index,
                    "요청/응답 요약",
                    f"responseSnippet=HTTP/1.1 200 OK, message=success, debugPath=/srv/app/releases/{20260318 + evidence_index}/logs/audit-{index:02d}.json",
                ),
                "appendix_ref": f"Appendix C · {evidence_id}",
                "box_text": "[증빙 이미지 삽입]",
                "figure_id": figure_id,
                "figure_caption": f"[그림 {figure_counter - 1}] {finding_id} stress 재현 증빙 화면 {evidence_index + 1}",
                "image_src": image_src,
                "image_alt": f"{finding_id} {evidence_id} stress 증빙 이미지",
                "image_width": width,
                "image_height": height,
            }
            evidences.append(evidence)
            appendix_items.append(
                {
                    "evidence_id": evidence_id,
                    "finding_ref": f"[관련 취약점: {finding_id}]",
                    "title": evidence_title,
                    "finding_id": finding_id,
                    "evidence_type": "스크린샷 / 패킷 로그 / 응답 본문 / 도구 출력",
                    "body_ref": f"4장 상세 결과 · {evidence_id}",
                    "box_text": "[추가 증빙 이미지 삽입]",
                    "figure_id": figure_id,
                    "figure_caption": f"[그림 {figure_counter - 1}] Appendix C stress 추가 증빙 {evidence_id}",
                    "description": paragraph(index, "추가 증빙 설명", f"부록 증빙은 {evidence_id}와 직접 연결되며 traceRef=APP-{index:02d}-{evidence_index:02d}-{'C' * 10} 값을 포함합니다."),
                    "image_src": image_src,
                    "image_alt": f"Appendix {evidence_id} stress 이미지",
                    "image_width": width,
                    "image_height": height,
                }
            )

        findings.append(
            {
                "id": finding_id,
                "toc_number": f"{index + 1})",
                "toc_title": title,
                "risk_key": risk_key,
                "risk_label": risk_label,
                "title": title,
                "target_name": system_name,
                "target_url": target_url,
                "code": ["IA", "IN", "SI", "XS", "SF", "WM"][index % 6],
                "path": f"/api/v2/case/{index + 1}/detail/export/{'x' * 18}",
                "result": "취약",
                "discovered_at": f"2026-03-{(index % 9) + 3:02d}",
                "due_at": f"2026-04-{(index % 15) + 5:02d}",
                "status": "미조치" if index % 3 == 0 else "조치중",
                "owner": owner_names[index % len(owner_names)],
                "reviewer": reviewer_names[index % len(reviewer_names)],
                "summary": paragraph(index, "한 줄 요약", "이 문장은 줄바꿈, 한국어/영문 혼합, URL wrapping, 긴 파라미터 문자열을 동시에 검증합니다."),
                "description": paragraph(index, "취약점 설명", "정상 동작 대비 비정상 동작을 장문으로 기술한 예시입니다."),
                "cause": paragraph(index, "발생 원인", "서버측 권한 검증 누락, 입력값 검증 미흡, 상태 전이 검증 부재가 동시에 존재하는 시나리오입니다."),
                "repro_parameters": f"requestId=REQ-{index:02d}-{'P' * 14}&userNo={100000 + index}&redirect={long_url(index, 2)}",
                "repro_request": f"POST {long_url(index, 3)} / header X-Stress-Trace=TRACE-{index:02d}-REQ / body: role=user&override=true&returnUrl=/admin/export/{index:02d}",
                "repro_response": paragraph(index, "응답 요약", "응답 메시지, 데이터 노출 여부, 권한 우회 결과를 장문으로 기록합니다."),
                "evidence_refs": ", ".join(evidence_ids),
                "repro_steps": [list_item(index, step) for step in range(1, 5)],
                "evidences": evidences,
                "impact": paragraph(index, "영향 범위", "개인정보, 업무 이력, 관리자 기능 토큰 등 다수의 민감 데이터가 포함될 수 있습니다."),
                "risk_rationale": paragraph(index, "위험도 판정 근거", "장문 근거와 복합 영향 요인을 넣어도 카드가 자연스럽게 다음 페이지로 이동해야 합니다."),
                "risk_difficulty": "보통" if risk_key != "low" else "낮음",
                "risk_asset": "고객정보 / 관리자 기능 / 내부 API",
                "risk_precondition": "인증된 일반 사용자 계정 1개와 응답 파라미터 추적 가능 환경",
                "remediation_steps": [
                    paragraph(index, "대응 방안 1", "서버측 객체 단위 권한 검증을 우선 적용합니다."),
                    paragraph(index, "대응 방안 2", "입력값 화이트리스트, 응답 최소화, 로깅 마스킹 정책을 함께 적용합니다."),
                    paragraph(index, "대응 방안 3", "장문의 재검증 포인트와 회귀 테스트 포인트를 한 줄에 몰아넣어도 wrapping 되어야 합니다."),
                ],
                "references": [
                    "OWASP Top 10 2021 A01 / CWE-639 / CWE-285",
                    f"기관 내부 API 보안 기준서 2026-1호 / reference={long_url(index, 4)}",
                    "주요정보통신기반시설 기술적 취약점 분석·평가 방법 상세가이드",
                ],
                "retest_date": f"2026-05-{(index % 15) + 1:02d}",
                "retest_result": "미수행",
                "retest_note": paragraph(index, "조치 후 재점검 결과", "장문 비고가 셀을 벗어나지 않는지 검증합니다."),
                "note": paragraph(index, "비고", f"relatedIssue=SEC-{index + 101}, changeWindow=2026-W{index + 9}, ownerMemo={owner_names[index % len(owner_names)]}"),
            }
        )

        summary_rows.append(
            {
                "number": str(index + 1),
                "system_name": system_name,
                "finding_id": finding_id,
                "title": title,
                "risk_key": risk_key,
                "risk_label": risk_label,
                "status": "미조치" if index % 3 == 0 else "조치중",
            }
        )
        priority_rows.append(
            {
                "row_class": "priority-high" if risk_key == "high" else "priority-mid" if risk_key == "mid" else "priority-low",
                "rank": f"{index + 1}순위",
                "finding_id": finding_id,
                "title": title,
                "risk_key": risk_key,
                "risk_label": risk_label,
                "due": f"2026-04-{(index % 15) + 5:02d}",
                "owner": owner_names[index % len(owner_names)],
            }
        )

        mitigation_track = "short" if risk_key == "high" else "mid" if risk_key == "mid" else "long"
        mitigation_rows[mitigation_track].append(
            {
                "repeat_name": f"mitigation-{mitigation_track}",
                "risk_key": risk_key,
                "risk_label": risk_label,
                "id_field": f"mitigation.{mitigation_track}.id",
                "id_classes": "auto-field",
                "finding_id": finding_id,
                "title_field": f"mitigation.{mitigation_track}.title",
                "title": title,
                "action_field": f"mitigation.{mitigation_track}.action",
                "action": paragraph(index, "조치 내용", "긴 문단 조치안, 우선순위, 협업 부서, 회귀 테스트 계획을 포함합니다."),
                "owner_field": f"mitigation.{mitigation_track}.owner",
                "owner": owner_names[index % len(owner_names)],
                "due_field": f"mitigation.{mitigation_track}.due",
                "due": f"2026-04-{(index % 20) + 1:02d}",
                "retest_field": f"mitigation.{mitigation_track}.retest",
                "retest": paragraph(index, "재점검 기준", "긴 URL, 파라미터, 응답 메세지를 포함하는 재점검 기준입니다."),
            }
        )

    systems_summary: list[dict[str, object]] = []
    for system_name in system_names:
        related = [finding for finding in findings if finding["target_name"] == system_name]
        if not related:
            continue
        vuln_count = len(related)
        systems_summary.append(
            {
                "system_name": system_name,
                "total": "21",
                "vuln": str(vuln_count),
                "ok": str(max(0, 21 - vuln_count)),
                "na": "0",
            }
        )

    appendix_items = appendix_items[:appendix_count]
    base_dataset["findings"] = findings
    base_dataset["appendix_c"] = appendix_items
    base_dataset["summary"] = {
        "systems": systems_summary,
        "findings": summary_rows,
        "priorities": priority_rows,
    }
    base_dataset["countermeasures"] = mitigation_rows
    return base_dataset


def toc_entry_context(entry: dict[str, object]) -> dict[str, object]:
    toc_key = sanitize_dom_id(entry["toc_key"], prefix="toc")
    page_key = sanitize_dom_id(entry.get("page_key", toc_key), prefix="page")
    style = sanitize_toc_style(entry.get("style", ""))
    # Safe because the visible TOC label is rebuilt from stripped text and fixed inline tags only.
    return {
        "item_style": style,
        "repeat_name": sanitize_repeat_name(entry["repeat"]),
        "toc_key": toc_key,
        "label_fragment": render_toc_label_fragment(entry.get("label_html", "")),
        "page_field": sanitize_data_field(f"page.{page_key}"),
        "page_token": f"{{{{page:{page_key}}}}}",
    }


def render_toc_entry(entry: dict[str, object]) -> str:
    return render_template("toc-item.html", toc_entry_context(entry))


def render_finding_toc_entries(dataset: dict[str, object]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for finding in dataset["findings"]:
        entries.append(
            {
                "repeat": "finding-toc-entry",
                "toc_key": finding_toc_key(finding),
                "style": "padding-left: 15px",
                "label_html": f"{raw_text(finding['toc_number'])} {raw_text(finding['id'])} · {raw_text(finding['toc_title'])}",
            }
        )
    return entries


def render_toc_entries(dataset: dict[str, object]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for entry in dataset["toc"]["main"]:
        if entry.get("expand") == "finding-toc":
            entries.extend(render_finding_toc_entries(dataset))
            continue
        entries.append(dict(entry))
    return entries


def render_table_index_entries(dataset: dict[str, object]) -> list[dict[str, object]]:
    return [dict(entry) for entry in dataset["indices"]["tables"]]


def render_figure_index_entries(dataset: dict[str, object]) -> list[dict[str, object]]:
    rendered: list[dict[str, object]] = []
    for entry in dataset["indices"]["figures"]:
        expand = entry.get("expand")
        if expand == "finding-figures":
            for finding in dataset["findings"]:
                for evidence in finding["evidences"]:
                    rendered.append(
                        {
                            "repeat": "figure-index-entry",
                            "toc_key": evidence["figure_id"],
                            "label_html": raw_text(evidence["figure_caption"]),
                        }
                    )
            continue
        if expand == "appendix-figures":
            for evidence in dataset["appendix_c"]:
                rendered.append(
                    {
                        "repeat": "figure-index-entry",
                        "toc_key": evidence["figure_id"],
                        "label_html": raw_text(evidence["figure_caption"]),
                    }
                )
            continue
        rendered.append(dict(entry))
    return rendered


def toc_item_units(entry: dict[str, object]) -> int:
    label = toc_label_text(entry.get("label_html", ""))
    return max(1, math.ceil(len(normalize_text(label)) / 34))


def render_toc_sections(dataset: dict[str, object]) -> str:
    profile: RenderProfile = dataset["_profile"]
    entries = render_toc_entries(dataset)
    rendered_entries = [
        {
            "html": render_toc_entry(entry),
            "units": scaled_units(toc_item_units(entry), profile.unit_scale),
        }
        for entry in entries
    ]
    chunks: list[list[str]] = []
    current: list[str] = []
    current_units = 0
    budget = profile.toc_budget
    for entry in rendered_entries:
        if current and current_units + entry["units"] > budget:
            chunks.append(current)
            current = [entry["html"]]
            current_units = entry["units"]
            continue
        current.append(entry["html"])
        current_units += entry["units"]
    if current:
        chunks.append(current)

    sections: list[str] = []
    for index, chunk in enumerate(chunks):
        section_classes = "report-section report-frontmatter print-page-start"
        if index:
            section_classes += " report-continuation continued-page"
        section_id = "toc" if index == 0 else f"toc-continuation-{index}"
        toc_attr = ' data-toc-key="toc"' if index == 0 else ""
        continued = '<div class="continued-label">목차 계속</div>\n' if index else ""
        sections.append(
            f"""<section class="{section_classes}" id="{section_id}"{toc_attr}>
      <div class="section-bar">목 차</div>
      {continued}<div class="toc-list{' toc-list-compact' if index else ''}">
{join_blocks(chunk, '        ')}
      </div>
    </section>"""
        )
    return "\n\n".join(sections)


def render_index_sections(dataset: dict[str, object]) -> str:
    profile: RenderProfile = dataset["_profile"]
    table_entries = render_table_index_entries(dataset)
    figure_entries = render_figure_index_entries(dataset)
    table_html = [render_toc_entry(entry) for entry in table_entries]
    figure_html = [render_toc_entry(entry) for entry in figure_entries]
    total_units = sum(scaled_units(toc_item_units(entry), profile.unit_scale) for entry in table_entries + figure_entries) + 8
    if total_units <= profile.index_single_page_limit:
        return f"""<section class="report-section report-frontmatter print-page-start" id="lot-lof" data-toc-key="lot-lof">
      <div class="section-bar">표 차례</div>
      <div class="toc-list toc-list-compact">
{join_blocks(table_html, '        ')}
      </div>

      <div class="section-bar" style="margin-top: 40px">그림 차례</div>
      <div class="toc-list toc-list-compact">
{join_blocks(figure_html, '        ')}
      </div>
    </section>"""

    sections: list[str] = []
    for entries, title in ((table_entries, "표 차례"), (figure_entries, "그림 차례")):
        chunk_budget = profile.index_chunk_budget
        chunked: list[list[str]] = []
        current: list[str] = []
        current_units = 0
        for entry in entries:
            units = scaled_units(toc_item_units(entry), profile.unit_scale)
            html = render_toc_entry(entry)
            if current and current_units + units > chunk_budget:
                chunked.append(current)
                current = [html]
                current_units = units
                continue
            current.append(html)
            current_units += units
        if current:
            chunked.append(current)
        for chunk in chunked:
            section_id = "lot-lof" if not sections else f"lot-lof-continuation-{len(sections)}"
            toc_attr = ' data-toc-key="lot-lof"' if not sections else ""
            continued = f'<div class="continued-label">{title} 계속</div>\n' if sections else ""
            sections.append(
                f"""<section class="report-section report-frontmatter print-page-start{' report-continuation continued-page' if sections else ''}" id="{section_id}"{toc_attr}>
      <div class="section-bar">{title}</div>
      {continued}<div class="toc-list toc-list-compact">
{join_blocks(chunk, '        ')}
      </div>
    </section>"""
            )
    return "\n\n".join(sections)


def render_tool_list_rows(dataset: dict[str, object]) -> str:
    rows: list[str] = []
    for item in dataset["diagnostic_overview"]["tool_list"]:
        rows.append(
            render_template(
                "tool-list-row.html",
                {
                    "name": item.get("name", ""),
                    "usage": item.get("usage", ""),
                    "note": item.get("note", ""),
                },
            )
        )
    return "\n".join(rows)


def render_checklist_item_rows(dataset: dict[str, object]) -> str:
    rows: list[str] = []
    for item in dataset["diagnostic_overview"]["checklist_items"]:
        risk_key = sanitize_risk_key(item.get("risk_key"))
        rows.append(
            render_template(
                "checklist-item.html",
                {
                    "code": item.get("code", ""),
                    "name": item.get("name", ""),
                    "point": item.get("point", ""),
                    "risk_key": risk_key,
                    "risk_label": item.get("risk_label", ""),
                    "risk_badge_class": risk_badge_class(risk_key),
                    "result_field": sanitize_data_field(f"checklist.result.{raw_text(item.get('code')).lower()}"),
                    "result_text": "[양호/취약/해당없음]",
                },
            )
        )
    return "\n".join(rows)


def render_summary_system_rows(dataset: dict[str, object]) -> str:
    rows: list[str] = []
    for item in dataset["summary"]["systems"]:
        rows.append(
            render_template(
                "summary-system-row.html",
                {
                    "system_name": item.get("system_name", ""),
                    "total": item.get("total", ""),
                    "vuln": item.get("vuln", ""),
                    "ok": item.get("ok", ""),
                    "na": item.get("na", ""),
                },
            )
        )
    return "\n".join(rows)


def render_summary_finding_rows(dataset: dict[str, object]) -> str:
    rows: list[str] = []
    for item in dataset["summary"]["findings"]:
        risk_key = sanitize_risk_key(item.get("risk_key"))
        rows.append(
            render_template(
                "summary-finding-row.html",
                {
                    "number": item.get("number", ""),
                    "system_name": item.get("system_name", ""),
                    "finding_id": item.get("finding_id", ""),
                    "title": item.get("title", ""),
                    "risk_key": risk_key,
                    "risk_badge_class": risk_badge_class(risk_key),
                    "risk_label": item.get("risk_label", ""),
                    "status": item.get("status", ""),
                },
            )
        )
    return "\n".join(rows)


def render_priority_item_rows(dataset: dict[str, object]) -> str:
    rows: list[str] = []
    for item in dataset["summary"]["priorities"]:
        risk_key = sanitize_risk_key(item.get("risk_key"))
        rows.append(
            render_template(
                "priority-item-row.html",
                {
                    "row_class": priority_row_class(risk_key),
                    "rank": item.get("rank", ""),
                    "finding_id": item.get("finding_id", ""),
                    "title": item.get("title", ""),
                    "risk_key": risk_key,
                    "risk_badge_class": risk_badge_class(risk_key),
                    "risk_label": item.get("risk_label", ""),
                    "due": item.get("due", ""),
                    "owner": item.get("owner", ""),
                },
            )
        )
    return "\n".join(rows)


def render_mitigation_rows(dataset: dict[str, object], track: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in dataset["countermeasures"][track]:
        risk_key = sanitize_risk_key(item.get("risk_key"))
        rows.append(
            {
                "html": render_template(
                    "mitigation-row.html",
                    {
                        "repeat_name": mitigation_repeat_name(track),
                        "risk_key": risk_key,
                        "risk_badge_class": risk_badge_class(risk_key),
                        "risk_label": item.get("risk_label", ""),
                        "id_classes": mitigation_id_classes(track),
                        "id_field": sanitize_data_field(f"mitigation.{track}.id"),
                        "finding_id": item.get("finding_id", ""),
                        "title_field": sanitize_data_field(f"mitigation.{track}.title"),
                        "title": item.get("title", ""),
                        "action_field": sanitize_data_field(f"mitigation.{track}.action"),
                        "action": item.get("action", ""),
                        "owner_field": sanitize_data_field(f"mitigation.{track}.owner"),
                        "owner": item.get("owner", ""),
                        "due_field": sanitize_data_field(f"mitigation.{track}.due"),
                        "due": item.get("due", ""),
                        "retest_field": sanitize_data_field(f"mitigation.{track}.retest"),
                        "retest": item.get("retest", ""),
                    },
                ),
                "units": 3 + text_units(item["title"], 42) + text_units(item["action"], 92) + text_units(item["retest"], 100),
            }
        )
    return rows


def render_figure_media_html(item: dict[str, object], data_prefix: str) -> TrustedHtml:
    image_src = sanitize_image_src(item.get("image_src"))
    if not image_src:
        return trusted_html(
            '<div class="evidence-box large evidence-placeholder placeholder requires-input">'
            f"{escape_html_text(item.get('box_text', ''))}</div>"
        )
    alt = escape_html_attr(item.get("image_alt") or item.get("title") or "증빙 이미지")
    return trusted_html(
        '<div class="evidence-box large evidence-media">'
        f'<img src="{escape_html_attr(image_src)}" alt="{alt}" class="evidence-image" data-field="{escape_html_attr(sanitize_data_field(f"{data_prefix}.image"))}" />'
        "</div>"
    )


def render_finding_evidence(evidence: dict[str, object], finding_id: str) -> str:
    # Safe because the media fragment is rebuilt here from validated URLs and escaped alt text only.
    figure_media_fragment = render_figure_media_html(evidence, "finding.evidence")
    return render_template(
        "finding-evidence.html",
        {
            "evidence_id": evidence.get("evidence_id", ""),
            "title": evidence.get("title", ""),
            "lead_label": evidence.get("lead_label", ""),
            "lead_data_field": sanitize_data_field(f"finding.evidence.{raw_text(evidence.get('lead_field') or 'detail').lower()}"),
            "lead_text": evidence.get("lead_text", ""),
            "io_text": evidence.get("io_text", ""),
            "appendix_ref": evidence.get("appendix_ref", ""),
            "finding_id": finding_id,
            "figure_media_fragment": figure_media_fragment,
            "figure_id": sanitize_dom_id(evidence.get("figure_id", ""), prefix="figure"),
            "figure_caption": evidence.get("figure_caption", ""),
        },
    )


def render_appendix_panel(item: dict[str, object]) -> str:
    # Safe because the media fragment is rebuilt here from validated URLs and escaped alt text only.
    figure_media_fragment = render_figure_media_html(item, "appendix.evidence")
    return render_template(
        "appendix-evidence.html",
        {
            "evidence_id": item.get("evidence_id", ""),
            "finding_ref": item.get("finding_ref", ""),
            "title": item.get("title", ""),
            "finding_id": item.get("finding_id", ""),
            "evidence_type": item.get("evidence_type", ""),
            "body_ref": item.get("body_ref", ""),
            "figure_media_fragment": figure_media_fragment,
            "figure_id": sanitize_dom_id(item.get("figure_id", ""), prefix="figure"),
            "figure_caption": item.get("figure_caption", ""),
            "description": item.get("description", ""),
        },
    )


def first_finding_preamble() -> str:
    return indent_block(
        "\n".join(
            [
                '<h1 class="chapter-title" id="chapter-4" data-toc-key="chapter-4">4. 웹 취약점 진단 상세 결과</h1>',
                '<div class="info-note">',
                "  ※ 아래 블록은 취약점 1건을 실무 제출 수준으로 정리하기 위한 기본 템플릿입니다. 동일 구조를 복사하여 취약점 건수만큼 반복 작성하십시오.",
                "</div>",
            ]
        ),
        "  ",
    )


def render_meta_block(finding: dict[str, object]) -> Block:
    risk_key = sanitize_risk_key(finding.get("risk_key"))
    target_url = sanitize_display_url(finding.get("target_url"))
    html = f"""
<div class="detail-grid vuln-detail-meta keep-together">
  <div class="detail-card keep-together">
    <div class="detail-card-title">기본 정보</div>
    <div class="detail-card-body">
      <table style="margin: 0">
        <tbody>
          <tr><td width="26%" style="background: #f0f6ff; font-weight: bold">관리번호</td><td class="auto-field wrap-anywhere" data-field="finding.id">{escape_html_text(finding.get('id', ''))}</td></tr>
          <tr><td style="background: #f0f6ff; font-weight: bold">대상 시스템</td><td class="placeholder requires-input auto-field wrap-anywhere" data-field="finding.targetName">{escape_html_text(finding.get('target_name', ''))}</td></tr>
          <tr><td style="background: #f0f6ff; font-weight: bold">대상 URL</td><td class="placeholder requires-input auto-field wrap-anywhere wrap-pre" data-field="finding.targetUrl">{escape_html_text(target_url)}</td></tr>
          <tr><td style="background: #f0f6ff; font-weight: bold">취약점명</td><td class="placeholder requires-input auto-field wrap-anywhere" data-field="finding.title">{escape_html_text(finding.get('title', ''))}</td></tr>
          <tr><td style="background: #f0f6ff; font-weight: bold">점검 코드</td><td class="placeholder requires-input auto-field wrap-anywhere" data-field="finding.code">{escape_html_text(finding.get('code', ''))}</td></tr>
          <tr><td style="background: #f0f6ff; font-weight: bold">발생 경로</td><td class="placeholder requires-input auto-field wrap-anywhere wrap-pre" data-field="finding.path">{escape_html_text(finding.get('path', ''))}</td></tr>
        </tbody>
      </table>
    </div>
  </div>
  <div class="detail-meta-stack">
    <div class="detail-card keep-together">
      <div class="detail-card-title">판정 및 조치 현황</div>
      <div class="detail-card-body">
        <table style="margin: 0">
          <tbody>
            <tr><td width="34%" style="background: #f0f6ff; font-weight: bold">진단 결과</td><td class="placeholder auto-field wrap-anywhere" data-field="finding.result">{escape_html_text(finding.get('result', ''))}</td></tr>
            <tr><td style="background: #f0f6ff; font-weight: bold">최종 위험도</td><td><span class="badge {risk_badge_class(risk_key)}" data-risk="{escape_html_attr(risk_key)}" data-field="finding.finalRisk">{escape_html_text(finding.get('risk_label', ''))}</span></td></tr>
            <tr><td style="background: #f0f6ff; font-weight: bold">발견일</td><td class="placeholder requires-input auto-field wrap-anywhere" data-field="finding.discoveredAt">{escape_html_text(finding.get('discovered_at', ''))}</td></tr>
            <tr><td style="background: #f0f6ff; font-weight: bold">조치 기한</td><td class="placeholder requires-input auto-field wrap-anywhere" data-field="finding.dueAt">{escape_html_text(finding.get('due_at', ''))}</td></tr>
            <tr><td style="background: #f0f6ff; font-weight: bold">조치 상태</td><td class="placeholder auto-field wrap-anywhere" data-field="finding.status">{escape_html_text(finding.get('status', ''))}</td></tr>
            <tr><td style="background: #f0f6ff; font-weight: bold">담당자</td><td class="placeholder requires-input auto-field wrap-anywhere" data-field="finding.owner">{escape_html_text(finding.get('owner', ''))}</td></tr>
            <tr><td style="background: #f0f6ff; font-weight: bold">확인자</td><td class="placeholder requires-input auto-field wrap-anywhere" data-field="finding.reviewer">{escape_html_text(finding.get('reviewer', ''))}</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</div>
""".strip()
    units = 18 + text_units(target_url, 70) + text_units(finding["title"], 60) + text_units(finding["path"], 70)
    return Block(html=html, units=units)


def render_summary_block(finding: dict[str, object]) -> Block:
    html = f"""
<div class="summary-strip keep-together">
  <strong>한 줄 요약</strong><br />
  <span class="placeholder requires-input auto-field wrap-anywhere wrap-pre" data-field="finding.summary">{escape_html_text(finding.get('summary', ''))}</span>
</div>
""".strip()
    return Block(html=html, units=4 + text_units(finding["summary"], 110))


def render_text_block(title: str, field: str, value: str) -> Block:
    html = f"""
<div class="vuln-detail-section allow-split">
  <h3 class="subsection-title">{escape_html_text(title)}</h3>
  <p class="placeholder requires-input auto-field wrap-anywhere wrap-pre" data-field="{escape_html_attr(sanitize_data_field(field))}">{escape_html_text(value)}</p>
</div>
""".strip()
    return Block(html=html, units=4 + text_units(value, 115))


def render_repro_block(finding: dict[str, object]) -> Block:
    html = f"""
<div class="vuln-detail-section allow-split">
  <h3 class="subsection-title">재현 절차</h3>
  <table class="evidence-summary-table">
    <tbody>
      <tr><td>입력값/파라미터</td><td class="placeholder requires-input auto-field wrap-anywhere wrap-pre" data-field="finding.repro.parameters">{escape_html_text(finding.get('repro_parameters', ''))}</td></tr>
      <tr><td>요청 요약</td><td class="placeholder requires-input auto-field wrap-anywhere wrap-pre" data-field="finding.repro.request">{escape_html_text(finding.get('repro_request', ''))}</td></tr>
      <tr><td>응답 요약</td><td class="placeholder requires-input auto-field wrap-anywhere wrap-pre" data-field="finding.repro.response">{escape_html_text(finding.get('repro_response', ''))}</td></tr>
      <tr><td>주요 증빙 ID</td><td class="auto-field wrap-anywhere" data-field="finding.evidenceRefs">{escape_html_text(finding.get('evidence_refs', ''))}</td></tr>
    </tbody>
  </table>
  <ol class="step-list placeholder requires-input auto-field wrap-pre" data-field="finding.repro.steps">
{render_li_items(finding["repro_steps"], "    ")}
  </ol>
</div>
""".strip()
    units = 10 + text_units(finding["repro_parameters"], 90) + text_units(finding["repro_request"], 90) + text_units(finding["repro_response"], 90) + list_units(finding["repro_steps"], 120)
    return Block(html=html, units=units)


def estimated_media_units(
    item: dict[str, object],
    profile: RenderProfile,
    *,
    placeholder_height_mm: float,
) -> int:
    width = int(item.get("image_width") or 0)
    height = int(item.get("image_height") or 0)
    image_src = sanitize_image_src(item.get("image_src"))
    if width and height:
        metrics = estimate_image_print_metrics(width, height, max_height_mm=profile.image_max_height_print_mm)
        return max(8, math.ceil(metrics["display_height_mm"] * 0.42))
    if image_src:
        return max(8, math.ceil(placeholder_height_mm * 0.42))
    return max(5, math.ceil(placeholder_height_mm * 0.34))


def evidence_units(evidence: dict[str, object], profile: RenderProfile) -> int:
    width = int(evidence.get("image_width") or 0)
    height = int(evidence.get("image_height") or 0)
    image_ratio_units = estimated_media_units(evidence, profile, placeholder_height_mm=20.0)
    if width and height:
        ratio = height / max(1, width)
        if ratio >= 1.4:
            image_ratio_units += 4
        elif ratio <= 0.5:
            image_ratio_units += 1
    return (
        9
        + text_units(evidence["title"], 60)
        + text_units(evidence["lead_text"], 90)
        + text_units(evidence["io_text"], 95)
        + image_ratio_units
    )


def render_evidence_blocks(finding: dict[str, object]) -> list[Block]:
    profile: RenderProfile = finding["_profile"]
    evidences = list(finding["evidences"])
    chunks: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] = []
    current_units = 0
    for evidence in evidences:
        units = scaled_units(evidence_units(evidence, profile), profile.unit_scale)
        if current and current_units + units > profile.evidence_chunk_budget:
            chunks.append(current)
            current = [evidence]
            current_units = units
            continue
        current.append(evidence)
        current_units += units
    if current:
        chunks.append(current)

    blocks: list[Block] = []
    for index, chunk in enumerate(chunks):
        title = "재현 증빙" if index == 0 else "재현 증빙 (계속)"
        chunk_html = [render_finding_evidence(evidence, str(finding["id"])) for evidence in chunk]
        html = f"""
<div class="vuln-detail-section allow-split">
  <h3 class="subsection-title">{escape_html_text(title)}</h3>
  <div class="evidence-list">
{join_blocks(chunk_html, '    ')}
  </div>
  </div>
""".strip()
        raw_units = max(12, sum(evidence_units(evidence, profile) for evidence in chunk))
        blocks.append(Block(html=html, units=raw_units))
    return blocks


def render_risk_block(finding: dict[str, object]) -> Block:
    html = f"""
<div class="vuln-detail-section allow-split">
  <h3 class="subsection-title">위험도 및 판정 근거</h3>
  <div class="risk-rationale keep-together">
    <p class="placeholder requires-input auto-field wrap-anywhere wrap-pre" data-field="finding.riskRationale">{escape_html_text(finding.get('risk_rationale', ''))}</p>
    <ul class="tight-list">
      <li>공격 난이도: <span class="placeholder auto-field wrap-anywhere" data-field="finding.riskDifficulty">{escape_html_text(finding.get('risk_difficulty', ''))}</span></li>
      <li>영향 자산: <span class="placeholder auto-field wrap-anywhere" data-field="finding.riskAsset">{escape_html_text(finding.get('risk_asset', ''))}</span></li>
      <li>선행 조건: <span class="placeholder auto-field wrap-anywhere" data-field="finding.riskPrecondition">{escape_html_text(finding.get('risk_precondition', ''))}</span></li>
    </ul>
  </div>
</div>
""".strip()
    units = 7 + text_units(finding["risk_rationale"], 105)
    return Block(html=html, units=units)


def render_list_block(title: str, field: str, items: list[str], ordered: bool) -> Block:
    tag = "ol" if ordered else "ul"
    class_name = "step-list" if ordered else "tight-list"
    html = f"""
<div class="vuln-detail-section allow-split">
  <h3 class="subsection-title">{escape_html_text(title)}</h3>
  <{tag} class="{class_name} placeholder{' requires-input' if ordered else ''} auto-field wrap-pre" data-field="{escape_html_attr(sanitize_data_field(field))}">
{render_li_items(items, "    ")}
  </{tag}>
</div>
""".strip()
    return Block(html=html, units=5 + list_units(items, 110))


def render_retest_block(finding: dict[str, object]) -> Block:
    html = f"""
<div class="vuln-detail-section allow-split">
  <h3 class="subsection-title">조치 후 재점검 결과</h3>
  <div class="retest-box keep-together">
    <table style="margin: 0">
      <tbody>
        <tr><td width="18%" style="background: #f0f6ff; font-weight: bold">재점검일</td><td class="placeholder auto-field wrap-anywhere" data-field="finding.retestDate">{escape_html_text(finding.get('retest_date', ''))}</td></tr>
        <tr><td style="background: #f0f6ff; font-weight: bold">재점검 결과</td><td class="placeholder auto-field wrap-anywhere" data-field="finding.retestResult">{escape_html_text(finding.get('retest_result', ''))}</td></tr>
        <tr><td style="background: #f0f6ff; font-weight: bold">확인 내용</td><td class="placeholder auto-field wrap-anywhere wrap-pre" data-field="finding.retestNote">{escape_html_text(finding.get('retest_note', ''))}</td></tr>
        <tr><td style="background: #f0f6ff; font-weight: bold">비고</td><td class="placeholder auto-field wrap-anywhere wrap-pre" data-field="finding.note">{escape_html_text(finding.get('note', ''))}</td></tr>
      </tbody>
    </table>
  </div>
</div>
""".strip()
    units = 8 + text_units(finding["retest_note"], 100) + text_units(finding["note"], 100)
    return Block(html=html, units=units)


def render_finding_blocks(finding: dict[str, object], finding_index: int) -> list[Block]:
    blocks: list[Block] = []
    if finding_index == 0:
        blocks.append(Block(first_finding_preamble(), 9))
    blocks.extend(
        [
            render_meta_block(finding),
            render_summary_block(finding),
            render_text_block("취약점 설명", "finding.description", str(finding["description"])),
            render_text_block("발생 원인", "finding.cause", str(finding["cause"])),
            render_repro_block(finding),
        ]
    )
    blocks.extend(render_evidence_blocks(finding))
    blocks.extend(
        [
            render_text_block("영향 범위", "finding.impact", str(finding["impact"])),
            render_risk_block(finding),
            render_list_block("대응 방안", "finding.remediation", list(finding["remediation_steps"]), ordered=True),
            render_list_block("참고 기준", "finding.references", list(finding["references"]), ordered=False),
            render_retest_block(finding),
        ]
    )
    return blocks


def render_finding_page(
    finding: dict[str, object],
    page_blocks: list[Block],
    finding_index: int,
    page_index: int,
) -> str:
    section_id = "chapter-4-section" if finding_index == 0 and page_index == 0 else sanitize_dom_id(
        f"{finding_toc_key(finding)}-section-{page_index + 1}",
        prefix="section",
    )
    section_toc_key = "chapter-4" if finding_index == 0 and page_index == 0 else finding_toc_key(finding) if page_index == 0 else ""
    finding_block_id = finding_dom_id(finding) if page_index == 0 else sanitize_dom_id(
        f"{finding_dom_id(finding)}-continued-{page_index + 1}",
        prefix="finding",
    )
    finding_block_toc_key = finding_toc_key(finding) if page_index == 0 else ""
    finding_block_repeat = "finding" if page_index == 0 else "finding-continuation"
    continued_label_fragment = (
        trusted_html(
            f'<div class="continued-label">상세 결과 계속 · {escape_html_text(finding.get("id", ""))}</div>'
        )
        if page_index
        else trusted_html("")
    )
    section_preamble_fragment = trusted_html("")
    content_blocks = page_blocks
    if finding_index == 0 and page_index == 0 and page_blocks and page_blocks[0].html.lstrip().startswith("<h1 class=\"chapter-title\""):
        section_preamble_fragment = trusted_html(page_blocks[0].html)
        content_blocks = page_blocks[1:]

    risk_key = sanitize_risk_key(finding.get("risk_key"))
    # Safe because the preamble is generated by this module and never built from raw dataset HTML.
    # Safe because the continuation label is constructed from escaped finding text inside fixed markup.
    # Safe because block HTML is generated by server-side renderers that already escape untrusted fields.
    finding_content_fragment = trusted_html(join_blocks([block.html for block in content_blocks], "      "))

    return render_template(
        "finding-section.html",
        {
            "section_extra_classes": " report-continuation" if finding_index or page_index else "",
            "section_id": section_id,
            "section_toc_key": section_toc_key,
            "section_preamble_fragment": section_preamble_fragment,
            "finding_block_id": finding_block_id,
            "finding_block_repeat": finding_block_repeat,
            "finding_block_toc_key": finding_block_toc_key,
            "finding_block_extra_classes": " continued-page-block" if page_index else "",
            "finding_id": finding.get("id", ""),
            "title": finding.get("title", ""),
            "risk_key": risk_key,
            "risk_badge_class": risk_badge_class(risk_key),
            "risk_label": finding.get("risk_label", ""),
            "continued_label_fragment": continued_label_fragment,
            "finding_content_fragment": finding_content_fragment,
        },
    )


def render_finding_sections(dataset: dict[str, object]) -> str:
    profile: RenderProfile = dataset["_profile"]
    sections: list[str] = []
    for finding_index, finding in enumerate(dataset["findings"]):
        finding["_profile"] = profile
        pages = pack_blocks(
            render_finding_blocks(finding, finding_index),
            budget=profile.finding_page_budget,
            scale=profile.unit_scale,
        )
        for page_index, page_blocks in enumerate(pages):
            sections.append(render_finding_page(finding, page_blocks, finding_index, page_index))
    return "\n\n".join(sections)


def mitigation_caption(track: str) -> tuple[str, str, str]:
    mapping = {
        "short": ("chapter-5-short", "1) 단기 조치 (즉시 ~ 1개월 이내)", "[표 17] 단기 조치 목록"),
        "mid": ("chapter-5-mid", "2) 중기 조치 (1개월 ~ 3개월 이내)", "[표 18] 중기 조치 목록"),
        "long": ("chapter-5-long", "3) 장기 조치 (3개월 이상)", "[표 19] 장기 조치 목록"),
    }
    return mapping[track]


def render_mitigation_track_block(track: str, chunk_rows: list[str], chunk_index: int) -> Block:
    toc_key, heading, caption = mitigation_caption(track)
    caption_id = {"short": "table-17", "mid": "table-18", "long": "table-19"}[track]
    caption_text = caption if chunk_index == 0 else f"{caption} (계속)"
    heading_attr = f' id="{toc_key}" data-toc-key="{toc_key}"' if chunk_index == 0 else ""
    caption_attr = f' id="{caption_id}" data-toc-key="{caption_id}"' if chunk_index == 0 else ""
    html = f"""
<div class="mitigation-block allow-split">
  <h2 class="section-title"{heading_attr}>{heading if chunk_index == 0 else heading.replace(')', ') (계속)', 1)}</h2>
  <table class="dense-table">
    <colgroup>
      <col style="width: 10%" />
      <col style="width: 18%" />
      <col style="width: 10%" />
      <col style="width: 28%" />
      <col style="width: 12%" />
      <col style="width: 10%" />
      <col style="width: 12%" />
    </colgroup>
    <thead>
      <tr>
        <th>관리번호</th>
        <th>취약점명</th>
        <th>최종 위험도</th>
        <th>조치 내용</th>
        <th>담당 부서</th>
        <th>완료 예정일</th>
        <th>재점검 기준</th>
      </tr>
    </thead>
    <tbody>
{join_blocks(chunk_rows, '      ')}
    </tbody>
  </table>
  <div class="table-caption"{caption_attr}>{caption_text}</div>
</div>
""".strip()
    units = 8 + len(chunk_rows) * 10
    return Block(html=html, units=units)


def render_countermeasure_sections(dataset: dict[str, object]) -> str:
    profile: RenderProfile = dataset["_profile"]
    intro_block = Block(
        html="""<div class="info-note">
        ※ 아래 보호대책은 상세 결과의 최종 위험도와 판정 근거를 바탕으로 단기·중기·장기 조치로 구분한 것입니다.
      </div>""",
        units=7,
    )
    track_blocks: list[Block] = [intro_block]
    for track in ("short", "mid", "long"):
        rows = render_mitigation_rows(dataset, track)
        chunks: list[list[str]] = []
        current: list[str] = []
        current_units = 0
        for row in rows:
            row_units = scaled_units(int(row["units"]), profile.unit_scale)
            if current and current_units + row_units > profile.countermeasure_row_budget:
                chunks.append(current)
                current = [row["html"]]
                current_units = row_units
                continue
            current.append(row["html"])
            current_units += row_units
        if current:
            chunks.append(current)
        for chunk_index, chunk in enumerate(chunks or [[]]):
            track_blocks.append(render_mitigation_track_block(track, chunk, chunk_index))

    pages = pack_blocks(track_blocks, budget=profile.countermeasure_page_budget, scale=profile.unit_scale)
    sections: list[str] = []
    for page_index, blocks in enumerate(pages):
        chapter_title = (
            '<h1 class="chapter-title" id="chapter-5" data-toc-key="chapter-5">5. 보호대책</h1>'
            if page_index == 0
            else '<div class="continued-label">5. 보호대책 계속</div>'
        )
        sections.append(
            f"""<section class="report-section print-page-start{' report-continuation continued-page' if page_index else ''}" id="chapter-5-section-{page_index + 1}"{' data-toc-key="chapter-5"' if page_index == 0 else ''}>
      {chapter_title}
{join_blocks([block.html for block in blocks], '      ')}
    </section>"""
        )
    return "\n\n".join(sections)


def appendix_panel_units(item: dict[str, object], profile: RenderProfile) -> int:
    ratio_units = estimated_media_units(item, profile, placeholder_height_mm=26.0)
    width = int(item.get("image_width") or 0)
    height = int(item.get("image_height") or 0)
    if width and height:
        ratio = height / max(width, 1)
        if ratio >= 1.35:
            ratio_units += 4
        elif ratio <= 0.55:
            ratio_units += 1
    return 10 + text_units(item["title"], 60) + text_units(item["description"], 95) + ratio_units


def render_appendix_c_sections(dataset: dict[str, object]) -> str:
    profile: RenderProfile = dataset["_profile"]
    intro = Block(
        html="""<div class="info-note">
        ※ 본 섹션은 본문 상세 결과와 분리하여 관리해야 하는 추가 증빙 자료를 정리하는 영역입니다. 각 증빙은 증빙 ID, 관련 취약점 관리번호, 제목, 설명을 함께 기록하십시오.
      </div>""",
        units=7,
    )
    blocks: list[Block] = [intro]
    for item in dataset["appendix_c"]:
        blocks.append(Block(render_appendix_panel(item), appendix_panel_units(item, profile)))
    pages = pack_blocks(blocks, budget=profile.appendix_page_budget, scale=profile.unit_scale)
    sections: list[str] = []
    for page_index, page_blocks in enumerate(pages):
        sections.append(
            f"""<section class="report-section print-page-start{' report-continuation continued-page' if page_index else ''}" id="appendix-c-{page_index + 1}"{' data-toc-key="appendix-c"' if page_index == 0 else ''}>
      <div class="section-bar">부록 C. 추가 증빙 자료</div>
      {'<div class="continued-label">추가 증빙 자료 계속</div>' if page_index else ''}
{join_blocks([block.html for block in page_blocks], '      ')}
    </section>"""
            )
    return "\n\n".join(sections)


def target_table_row_units(row: dict[str, str]) -> int:
    return 4 + text_units(row["system_name"], 36) + text_units(row["target_url"], 62) + text_units(row["note"], 80)


def render_target_table_rows(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    rendered: list[dict[str, object]] = []
    for row in rows:
        safe_target_url = sanitize_display_url(row["target_url"])
        rendered.append(
            {
                "html": (
                    "      <tr>"
                    f"<td align=\"center\">{escape_html_text(row['number'])}</td>"
                    f"<td class=\"wrap-anywhere wrap-pre\">{escape_html_text(row['system_name'])}</td>"
                    f"<td class=\"wrap-anywhere wrap-pre\">{escape_html_text(safe_target_url)}</td>"
                    f"<td align=\"center\">{escape_html_text(row['account_level'])}</td>"
                    f"<td class=\"wrap-anywhere wrap-pre\">{escape_html_text(row['note'])}</td>"
                    "</tr>"
                ),
                "units": target_table_row_units(row),
            }
        )
    return rendered


def render_target_table_sample_sections(profile: RenderProfile) -> str:
    rows = render_target_table_rows(synthesize_target_table_rows())
    chunk_budget = 58
    chunks: list[list[str]] = []
    current: list[str] = []
    current_units = 0
    for row in rows:
        units = scaled_units(int(row["units"]), profile.unit_scale)
        if current and current_units + units > chunk_budget:
            chunks.append(current)
            current = [str(row["html"])]
            current_units = units
            continue
        current.append(str(row["html"]))
        current_units += units
    if current:
        chunks.append(current)

    sections: list[str] = []
    for index, chunk in enumerate(chunks):
        heading_html = (
            '<h1 class="chapter-title" id="table-sample" data-toc-key="table-sample">표 헤더 반복 검증 샘플</h1>'
            if index == 0
            else '<div class="continued-label">[표 5] 웹 취약점 진단 대상 계속</div>'
        )
        section_attr = ' data-toc-key="table-sample"' if index == 0 else ""
        caption_text = "[표 5] 웹 취약점 진단 대상" if index == 0 else "[표 5] 웹 취약점 진단 대상 (계속)"
        sections.append(
            f"""<section class="report-section print-page-start{' report-continuation continued-page' if index else ''}" id="table-sample-section-{index + 1}"{section_attr}>
      {heading_html}
      <h2 class="section-title">4) 대상{' (계속)' if index else ''}</h2>
      <div class="info-note">
        ※ Chromium/Edge에서 thead 반복과 별도로, build 단계에서 continuation table을 명시적으로 생성한 검증 샘플입니다.
      </div>
      <div class="keep-together">
        <table class="checklist-table dense-table">
          <colgroup>
            <col style="width: 10%" />
            <col style="width: 25%" />
            <col style="width: 35%" />
            <col style="width: 15%" />
            <col style="width: 15%" />
          </colgroup>
          <thead>
            <tr>
              <th width="10%">번호</th>
              <th width="25%">시스템명</th>
              <th width="35%">대상 URL</th>
              <th width="15%">계정 수준</th>
              <th width="15%">비고</th>
            </tr>
          </thead>
          <tbody>
{join_blocks(chunk, '            ')}
          </tbody>
        </table>
        <div class="table-caption">{caption_text}</div>
      </div>
    </section>"""
        )
    return "\n\n".join(sections)


def render_partial(path: Path, dataset: dict[str, object]) -> str:
    text = read_text(path)

    def replace(match: re.Match[str]) -> str:
        marker = match.group("marker")
        if marker not in PARTIAL_RENDERERS:
            raise KeyError(f"Unknown render marker '{marker}' in {path}")
        rendered = PARTIAL_RENDERERS[marker](dataset).rstrip()
        return indent_block(rendered, match.group("indent"))

    return PARTIAL_MARKER_RE.sub(replace, text)


PARTIAL_RENDERERS = {
    "cover-logo-html": render_cover_logo_html,
    "toc-sections": render_toc_sections,
    "index-sections": render_index_sections,
    "tool-list-rows": render_tool_list_rows,
    "checklist-item-rows": render_checklist_item_rows,
    "summary-system-rows": render_summary_system_rows,
    "summary-finding-rows": render_summary_finding_rows,
    "priority-item-rows": render_priority_item_rows,
    "finding-sections": render_finding_sections,
    "countermeasure-sections": render_countermeasure_sections,
    "appendix-c-sections": render_appendix_c_sections,
}


def join_partials(partials: list[Path], dataset: dict[str, object]) -> str:
    return "\n\n".join(render_partial(path, dataset).rstrip() for path in partials) + "\n"


def render_document(css: str, body: str, js: str, profile: RenderProfile, dataset_name: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="ko" data-theme="light" data-profile="{escape_html_attr(profile.name)}" data-dataset="{escape_html_attr(dataset_name)}" style="{escape_html_attr(profile_style_vars(profile))}"><head>\n'
        '    <meta charset="UTF-8">\n'
        f"    <title>{escape_html_text(TITLE)}</title>\n"
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


def extract_print_sections(html: str) -> list[str]:
    section_pattern = re.compile(r"<section\b[^>]*\bclass=\"[^\"]*\bprint-page-start\b[^\"]*\"[^>]*>.*?</section>", re.S)
    return section_pattern.findall(html)


def minimal_html_for_section(section_html: str, source_html: str) -> str:
    style_match = INLINE_STYLE_BLOCK_RE.search(source_html)
    style = style_match.group(1) if style_match else ""
    html_tag = re.search(r"<html\b[^>]*\bstyle=\"([^\"]*)\"", source_html, re.S)
    html_style = html_tag.group(1) if html_tag else ""
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="ko" style="{html_style}"><head>\n'
        '    <meta charset="UTF-8">\n'
        "    <style>\n"
        f"{style}"
        "    </style>\n"
        "  </head>\n"
        "  <body>\n"
        '    <main class="report-document">\n'
        f"{section_html}\n"
        "    </main>\n"
        "  </body></html>\n"
    )


def probe_section_pdf_spans(
    html: str,
    dataset_name: str,
    *,
    limit: int = 20,
    allow_local_file_access: bool = False,
) -> dict[str, object]:
    page_sections = extract_print_sections(html)
    if not page_sections:
        return {"status": "미검증", "reason": "print-page-start section 없음"}
    if len(page_sections) > limit:
        return {
            "status": "미검증",
            "reason": f"section span probe 제한 초과 ({len(page_sections)} > {limit})",
            "section_count": len(page_sections),
        }

    results: list[dict[str, object]] = []
    current_page = 1
    for index, section_html in enumerate(page_sections, start=1):
        section_id_match = re.search(r'\bid="([^"]+)"', section_html)
        section_id = section_id_match.group(1) if section_id_match else f"section-{index}"
        temp_html = DIST_DIR / f".section-probe-{dataset_name}-{index:02d}.html"
        temp_pdf = DIST_DIR / f".section-probe-{dataset_name}-{index:02d}.pdf"
        write_text(temp_html, minimal_html_for_section(section_html, html))
        if temp_pdf.exists():
            temp_pdf.unlink()
        pdf_result = build_pdf(
            temp_html.resolve(),
            temp_pdf.resolve(),
            allow_local_file_access=allow_local_file_access,
        )
        temp_html.unlink(missing_ok=True)
        temp_pdf.unlink(missing_ok=True)
        if pdf_result.get("status") != "OK":
            return {
                "status": "미검증",
                "reason": f"section span probe 실패: {section_id}",
                "section_id": section_id,
                "pdf": pdf_result,
            }
        page_span = max(1, int(pdf_result.get("page_count") or 1))
        results.append(
            {
                "index": index,
                "id": section_id,
                "start_page": current_page,
                "page_span": page_span,
            }
        )
        current_page += page_span

    return {
        "status": "OK",
        "section_count": len(results),
        "estimated_total_pages": current_page - 1,
        "sections": results,
    }


def build_page_map(
    html: str,
    section_span_probe: dict[str, object] | None = None,
) -> dict[str, dict[str, object]]:
    page_sections = extract_print_sections(html)
    probed_sections = list(section_span_probe.get("sections") or []) if section_span_probe and section_span_probe.get("status") == "OK" else []
    page_map: dict[str, dict[str, object]] = {}
    for section_index, section_html in enumerate(page_sections, start=1):
        section_start_page = section_index
        section_page_span = 1
        if probed_sections and section_index <= len(probed_sections):
            section_start_page = int(probed_sections[section_index - 1]["start_page"])
            section_page_span = int(probed_sections[section_index - 1]["page_span"])
        for source, pattern in PAGE_KEY_PATTERNS:
            for match in pattern.finditer(section_html):
                toc_key = match.group(1)
                offset = match.start()
                page_number = section_start_page
                if section_page_span > 1 and source != "section":
                    offset_ratio = offset / max(len(section_html), 1)
                    page_number += min(section_page_span - 1, int(offset_ratio * section_page_span))
                confidence = "추정"
                if source == "section":
                    confidence = "확정"
                elif source in {"heading", "vuln-block"} and offset <= 1200:
                    confidence = "확정"
                elif section_page_span > 1 and page_number != section_start_page:
                    confidence = "보조추정"
                page_map.setdefault(
                    toc_key,
                    {
                        "page": page_number,
                        "source": source,
                        "confidence": confidence,
                    },
                )
    return page_map


def run_layout_probe(
    *,
    body: str,
    css: str,
    profile: RenderProfile,
    dataset_name: str,
    allow_local_file_access: bool = False,
) -> dict[str, object]:
    browser = resolve_browser_executable()
    if not browser:
        return {"status": "미검증", "reason": "headless browser 미탐지"}

    probe_html = build_layout_probe_document(body=body, css=css, profile=profile, dataset_name=dataset_name)
    temp_path: Path | None = None
    stdout_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=f"-{dataset_name}-layout-probe.html",
            dir=DIST_DIR,
            delete=False,
        ) as handle:
            handle.write(probe_html)
            temp_path = Path(handle.name)

        stdout_path = browser_temp_dir() / f"layout-probe-{dataset_name}.dom.html"
        if stdout_path.exists():
            stdout_path.unlink()

        result = run_browser_process(
            browser,
            layout_probe_browser_args(
                temp_path,
                browser,
                allow_local_file_access=allow_local_file_access,
            ),
            timeout=120,
            stdout_path=stdout_path,
        )
        if result.returncode != 0:
            return {
                "status": "미검증",
                "reason": "layout probe 실행 실패",
                "stderr": normalize_text(result.stderr.decode("utf-8", errors="ignore")),
            }
        if not stdout_path.exists():
            return {"status": "미검증", "reason": "layout probe DOM 산출물 미생성"}
        dom = read_text(stdout_path)
        match = re.search(
            rf'<script id="{LAYOUT_PROBE_MARKER}" type="application/json">(.*?)</script>',
            dom,
            re.S,
        )
        if not match:
            return {"status": "미검증", "reason": "layout probe 결과 마커 미발견"}
        payload = json.loads(match.group(1))
        payload["status"] = "OK"
        payload["browser"] = browser
        return payload
    except Exception as exc:
        return {"status": "미검증", "reason": f"layout probe 예외: {exc}"}
    finally:
        if stdout_path and stdout_path.exists():
            stdout_path.unlink()
        if temp_path and temp_path.exists():
            temp_path.unlink()


def merge_page_maps(
    build_page_map_data: dict[str, dict[str, object]],
    layout_probe: dict[str, object] | None = None,
) -> dict[str, dict[str, object]]:
    if not layout_probe or layout_probe.get("status") != "OK":
        return build_page_map_data

    probe_page_map = dict(layout_probe.get("page_map") or {})
    merged: dict[str, dict[str, object]] = {}
    for toc_key in sorted(set(build_page_map_data) | set(probe_page_map)):
        build_entry = dict(build_page_map_data.get(toc_key) or {})
        probe_entry = dict(probe_page_map.get(toc_key) or {})
        if not probe_entry:
            merged[toc_key] = build_entry
            continue

        page = int(probe_entry.get("page") or build_entry.get("page") or 0)
        source = build_entry.get("source") or probe_entry.get("source") or "unknown"
        confidence = probe_entry.get("confidence") or build_entry.get("confidence") or "추정"
        build_page = build_entry.get("page")
        if build_page is not None:
            build_page = int(build_page)
        if build_page is not None and build_page == page and build_entry.get("confidence") == "확정":
            confidence = "확정"
        elif build_page is not None and build_page != page:
            confidence = "보조추정"
        merged[toc_key] = {
            "page": page,
            "source": source,
            "confidence": confidence,
            "build_page": build_page,
            "probe_page": page,
        }
    return merged


def replace_page_tokens(html: str, page_map: dict[str, dict[str, object]]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return str(page_map.get(key, {}).get("page", match.group(0)))

    return PAGE_TOKEN_RE.sub(replace, html)


def resolve_page_tokens(html: str) -> str:
    return replace_page_tokens(html, build_page_map(html))


def validate_self_contained(html: str) -> list[str]:
    checks = []
    checks.append(
        "OK self-contained style/script blocks present"
        if html.count("<style>") == 1 and html.count("<script>") == 1
        else "FAIL expected a single embedded <style> and <script> block"
    )
    checks.append(
        "OK no linked stylesheet/script remains"
        if "rel=\"stylesheet\"" not in html and "<script src=" not in html
        else "FAIL external asset reference remains"
    )
    checks.append(
        "OK no @import remains"
        if "@import" not in html
        else "FAIL external @import remains"
    )
    return checks


def compare_against_reference(reference_path: Path, built_html: str, label: str) -> list[str]:
    if not reference_path.exists():
        return [f"SKIP [{label}] reference comparison: {reference_path.name} not found"]
    reference_html = read_text(reference_path)
    results: list[str] = []
    for name, pattern in COUNT_CHECKS.items():
        expected = len(re.findall(pattern, reference_html, re.S))
        actual = len(re.findall(pattern, built_html, re.S))
        status = "OK" if expected == actual else "WARN"
        results.append(f"{status} [{label}] {name}: reference={expected}, dist={actual}")
    for name, pattern in SEQUENCE_CHECKS.items():
        reference_items = re.findall(pattern, reference_html, re.S)
        built_items = re.findall(pattern, built_html, re.S)
        if reference_items == built_items:
            results.append(f"OK [{label}] {name}: sequence preserved ({len(reference_items)} items)")
            continue
        mismatch = first_mismatch(reference_items, built_items)
        results.append(
            "WARN "
            f"[{label}] {name}: first mismatch at position {mismatch[0]} "
            f"(reference={mismatch[1]!r}, dist={mismatch[2]!r})"
        )
    return results


def first_mismatch(reference_items: list[str], built_items: list[str]) -> tuple[int, str, str]:
    for index, pair in enumerate(zip_longest(reference_items, built_items, fillvalue="<missing>"), start=1):
        if pair[0] != pair[1]:
            return index, pair[0], pair[1]
    return 0, "<none>", "<none>"


def detect_fixed_height_overflow_pairs(css: str) -> list[str]:
    findings: list[str] = []
    for match in FIXED_HEIGHT_RE.finditer(css):
        selector = normalize_text(match.group("selector"))
        if "cover-page" in selector or "submission-audit-panel" in selector:
            continue
        findings.append(selector)
    return findings


def summarize_pagination(html: str) -> dict[str, object]:
    section_ids = re.findall(
        r'<section\b[^>]*\bclass="[^"]*\bprint-page-start\b[^"]*"[^>]*\bid="([^"]+)"',
        html,
        re.S,
    )
    return {
        "print_page_start_sections": len(section_ids),
        "toc_sections": sum(1 for value in section_ids if value == "toc" or value.startswith("toc-continuation-")),
        "index_sections": sum(1 for value in section_ids if value == "lot-lof" or value.startswith("lot-lof-continuation-")),
        "finding_sections": sum(
            1 for value in section_ids if value == "chapter-4-section" or value.startswith("finding-vul-")
        ),
        "countermeasure_sections": sum(1 for value in section_ids if value.startswith("chapter-5-section-")),
        "appendix_c_sections": sum(1 for value in section_ids if value.startswith("appendix-c-")),
    }


def estimate_image_print_metrics(
    width: int,
    height: int,
    *,
    max_height_mm: int,
    max_width_mm: float = 166.0,
) -> dict[str, float]:
    natural_height_mm = max_width_mm * height / max(width, 1)
    display_height_mm = min(natural_height_mm, float(max_height_mm))
    display_width_mm = max_width_mm if natural_height_mm <= max_height_mm else float(max_height_mm) * width / max(height, 1)
    width_in = display_width_mm / 25.4
    height_in = display_height_mm / 25.4
    effective_ppi = min(width / max(width_in, 0.01), height / max(height_in, 0.01))
    return {
        "display_width_mm": round(display_width_mm, 1),
        "display_height_mm": round(display_height_mm, 1),
        "effective_ppi": round(effective_ppi, 1),
    }


def collect_image_validation(dataset: dict[str, object], profile: RenderProfile) -> dict[str, object]:
    items: list[dict[str, object]] = []
    candidates: list[tuple[str, dict[str, object]]] = []
    for finding in dataset["findings"]:
        for evidence in finding["evidences"]:
            candidates.append((f"{finding['id']}::{evidence['evidence_id']}", evidence))
    for evidence in dataset["appendix_c"]:
        candidates.append((f"APPENDIX::{evidence['evidence_id']}", evidence))

    for label, item in candidates:
        image_src = sanitize_image_src(item.get("image_src"))
        if not image_src:
            continue
        if "data:image/svg+xml" in image_src:
            continue
        width = int(item.get("image_width") or 0)
        height = int(item.get("image_height") or 0)
        if not width or not height:
            continue
        image_format = str(item.get("image_format") or ("png" if "data:image/png" in image_src else "jpeg"))
        if image_format not in {"png", "jpg", "jpeg"}:
            continue
        metrics = estimate_image_print_metrics(width, height, max_height_mm=profile.image_max_height_print_mm)
        image_kind = str(item.get("image_kind") or "general")
        min_ppi = 140 if image_kind == "dense-text" else 120 if image_kind == "high-resolution" else 100
        items.append(
            {
                "label": label,
                "kind": image_kind,
                "format": image_format,
                "file_name": item.get("image_file_name"),
                "image_width": width,
                "image_height": height,
                "display_width_mm": metrics["display_width_mm"],
                "display_height_mm": metrics["display_height_mm"],
                "effective_ppi": metrics["effective_ppi"],
                "readability_threshold_ppi": min_ppi,
                "readability_status": "OK" if metrics["effective_ppi"] >= min_ppi else "주의",
            }
        )

    return {
        "mode": "actual-raster" if items else "placeholder-or-vector",
        "items": items,
        "summary": {
            "total": len(items),
            "png_count": sum(1 for item in items if item["format"] == "png"),
            "jpeg_count": sum(1 for item in items if item["format"] in {"jpg", "jpeg"}),
            "all_readable_by_threshold": all(item["readability_status"] == "OK" for item in items) if items else None,
            "validation_basis": "추정 기반: 이미지 픽셀 수와 print max-height를 기준으로 유효 PPI를 계산",
        },
    }


def summarize_page_map(
    page_map: dict[str, dict[str, object]],
    layout_probe: dict[str, object] | None = None,
    section_span_probe: dict[str, object] | None = None,
    pdf_result: dict[str, object] | None = None,
) -> dict[str, object]:
    exact = sum(1 for item in page_map.values() if item["confidence"] == "확정")
    inferred = sum(1 for item in page_map.values() if item["confidence"] in {"추정", "보조추정"})
    shifted = sum(
        1
        for item in page_map.values()
        if item.get("build_page") is not None and item.get("probe_page") is not None and item["build_page"] != item["probe_page"]
    )
    preview = [
        {
            "toc_key": key,
            "page": value["page"],
            "source": value["source"],
            "confidence": value["confidence"],
        }
        for key, value in sorted(page_map.items())[:12]
    ]
    pdf_level_comparison = "미검증"
    pdf_level_reason = "PDF 본문 텍스트 추출 기반 직접 대조 미구현"
    layout_probe_summary = {"status": "미검증", "reason": "layout probe 미실행"}
    if layout_probe:
        layout_probe_summary = {
            "status": layout_probe.get("status"),
            "estimated_total_pages": layout_probe.get("estimated_total_pages"),
            "section_count": len(layout_probe.get("sections") or []),
            "largest_sections": [
                {
                    "id": item["id"],
                    "start_page": item["start_page"],
                    "estimated_pages": item["estimated_pages"],
                }
                for item in sorted(
                    list(layout_probe.get("sections") or []),
                    key=lambda item: (-int(item.get("estimated_pages") or 0), int(item.get("start_page") or 0)),
                )[:5]
            ],
            "reason": layout_probe.get("reason"),
        }
        if layout_probe.get("status") == "OK" and pdf_result and pdf_result.get("status") == "OK":
            estimated_total = int(layout_probe.get("estimated_total_pages") or 0)
            pdf_total = int(pdf_result.get("page_count") or 0)
            delta = estimated_total - pdf_total
            pdf_level_comparison = "부분 검증"
            pdf_level_reason = (
                "layout probe와 실제 PDF 총 페이지 수 비교 "
                f"(probe={estimated_total}, pdf={pdf_total}, delta={delta})"
            )
    if section_span_probe:
        section_probe_summary = {
            "status": section_span_probe.get("status"),
            "estimated_total_pages": section_span_probe.get("estimated_total_pages"),
            "section_count": section_span_probe.get("section_count"),
            "largest_sections": [
                {
                    "id": item["id"],
                    "start_page": item["start_page"],
                    "page_span": item["page_span"],
                }
                for item in sorted(
                    list(section_span_probe.get("sections") or []),
                    key=lambda item: (-int(item.get("page_span") or 0), int(item.get("start_page") or 0)),
                )[:5]
            ],
            "reason": section_span_probe.get("reason"),
        }
        layout_probe_summary["section_span_probe"] = section_probe_summary
        if section_span_probe.get("status") == "OK" and pdf_result and pdf_result.get("status") == "OK":
            estimated_total = int(section_span_probe.get("estimated_total_pages") or 0)
            pdf_total = int(pdf_result.get("page_count") or 0)
            delta = estimated_total - pdf_total
            pdf_level_comparison = "부분 검증"
            pdf_level_reason = (
                "section span probe와 실제 PDF 총 페이지 수 비교 "
                f"(probe={estimated_total}, pdf={pdf_total}, delta={delta})"
            )
    return {
        "mapped_keys": len(page_map),
        "exact_keys": exact,
        "inferred_keys": inferred,
        "probe_shifted_keys": shifted,
        "pdf_level_comparison": pdf_level_comparison,
        "pdf_level_reason": pdf_level_reason,
        "layout_probe": layout_probe_summary,
        "preview": preview,
    }


def validate_print_safety(
    html: str,
    dataset: dict[str, object],
    page_map: dict[str, dict[str, object]],
    layout_probe: dict[str, object] | None = None,
    section_span_probe: dict[str, object] | None = None,
    pdf_result: dict[str, object] | None = None,
) -> dict[str, object]:
    css_match = INLINE_STYLE_BLOCK_RE.search(html)
    css = css_match.group(1) if css_match else ""
    issues = detect_fixed_height_overflow_pairs(css)
    continuation_count = len(
        re.findall(r'<section\b[^>]*\bclass="[^"]*\breport-continuation\b', html, re.S)
    )
    unresolved_page_spans = len(
        re.findall(r'<span\b[^>]*\bclass="[^"]*\btoc-page\b[^"]*"[^>]*>\s*\{\{page:[^}]+\}\}\s*</span>', html, re.S)
    )
    checks = {
        "page_tokens_remaining": unresolved_page_spans,
        "continued_pages": continuation_count,
        "fixed_height_overflow_pairs": issues,
        "has_keep_together": ".keep-together" in css,
        "has_allow_split": ".allow-split" in css,
        "has_repeated_table_headers": "table-header-group" in css,
        "has_wrap_anywhere": "overflow-wrap: anywhere" in css,
        "has_pre_wrap": "white-space: pre-wrap" in css,
        "self_contained_checks": validate_self_contained(html),
        "profile": dataset.get("_profile_name"),
        "page_map": summarize_page_map(
            page_map,
            layout_probe=layout_probe,
            section_span_probe=section_span_probe,
            pdf_result=pdf_result,
        ),
        "pagination_summary": summarize_pagination(html),
        "image_validation": collect_image_validation(dataset, dataset["_profile"]),
    }
    return checks


def browser_available() -> bool:
    return resolve_browser_executable() is not None


def path_page_count(pdf_path: Path) -> int | None:
    if not pdf_path.exists():
        return None
    data = pdf_path.read_bytes()
    return len(re.findall(rb"/Type\s*/Page\b", data))


def file_access_browser_flags(*, allow_local_file_access: bool = False) -> list[str]:
    return ["--allow-file-access-from-files"] if allow_local_file_access else []


def layout_probe_browser_args(
    html_path: Path,
    browser: str,
    *,
    allow_local_file_access: bool = False,
) -> list[str]:
    return [
        "--headless=new",
        "--disable-gpu",
        *file_access_browser_flags(allow_local_file_access=allow_local_file_access),
        "--dump-dom",
        "--virtual-time-budget=6000",
        browser_file_uri(html_path, browser),
    ]


def pdf_browser_args(
    html_path: Path,
    pdf_path: Path,
    browser: str,
    *,
    allow_local_file_access: bool = False,
) -> list[str]:
    return [
        "--headless=new",
        "--disable-gpu",
        *file_access_browser_flags(allow_local_file_access=allow_local_file_access),
        *PDF_HEADER_SUPPRESSION_FLAGS,
        f"--print-to-pdf={browser_file_argument(pdf_path, browser)}",
        "--virtual-time-budget=4000",
        browser_file_uri(html_path, browser),
    ]


def build_pdf(
    html_path: Path,
    pdf_path: Path,
    *,
    allow_local_file_access: bool = False,
) -> dict[str, object]:
    browser = resolve_browser_executable()
    if not browser:
        return {"status": "미검증", "reason": "headless browser 미탐지"}
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    if pdf_path.exists():
        pdf_path.unlink()
    args = pdf_browser_args(
        html_path,
        pdf_path,
        browser,
        allow_local_file_access=allow_local_file_access,
    )
    if browser_is_windows_executable(browser) and powershell_executable():
        windows_browser = to_windows_path(Path(browser)) or browser
        arg_list = "@(" + ",".join(shell_single_quote(arg) for arg in args) + ")"
        command = (
            f"Start-Process -FilePath {shell_single_quote(windows_browser)} "
            f"-ArgumentList {arg_list} -Wait"
        )
        result = subprocess.run(
            [powershell_executable(), "-NoProfile", "-Command", command],
            capture_output=True,
            timeout=120,
        )
    else:
        result = subprocess.run([browser, *args], capture_output=True, timeout=120)
    if result.returncode != 0:
        return {
            "status": "미검증",
            "reason": "headless browser PDF 생성 실패",
            "stderr": normalize_text(result.stderr.decode("utf-8", errors="ignore")),
        }
    deadline = time.time() + 20
    while time.time() < deadline and not pdf_path.exists():
        time.sleep(0.25)
    if not pdf_path.exists():
        return {
            "status": "미검증",
            "reason": "headless browser PDF 미생성",
            "stderr": normalize_text(result.stderr.decode("utf-8", errors="ignore")),
        }
    return {
        "status": "OK",
        "page_count": path_page_count(pdf_path),
        "path": str(pdf_path),
        "browser": browser,
    }


def build_dataset(
    dataset_name: str,
    partials: list[Path],
    css: str,
    js: str,
    profile_override: str | None = None,
    *,
    allow_local_file_access: bool = False,
) -> dict[str, object]:
    profile = resolve_profile(dataset_name, profile_override)
    dataset = load_dataset(dataset_name, profile)
    body = join_partials(partials, dataset)
    html_source = render_document(css=css, body=body, js=js, profile=profile, dataset_name=dataset_name)
    section_span_probe = probe_section_pdf_spans(
        html_source,
        dataset_name,
        allow_local_file_access=allow_local_file_access,
    )
    build_page_map_data = build_page_map(html_source, section_span_probe=section_span_probe)
    layout_probe = run_layout_probe(
        body=body,
        css=css,
        profile=profile,
        dataset_name=dataset_name,
        allow_local_file_access=allow_local_file_access,
    )
    page_map = merge_page_maps(build_page_map_data, layout_probe=layout_probe)
    html = replace_page_tokens(html_source, page_map)

    html_path, pdf_path, validation_path = dataset_output_paths(dataset_name)
    write_text(html_path, html)
    pdf_result = build_pdf(
        html_path,
        pdf_path,
        allow_local_file_access=allow_local_file_access,
    )
    validation = validate_print_safety(
        html,
        dataset,
        page_map,
        layout_probe=layout_probe,
        section_span_probe=section_span_probe,
        pdf_result=pdf_result,
    )
    validation["pdf"] = pdf_result
    validation["dataset"] = dataset_name
    validation["profile"] = profile.name
    validation["reference_checks"] = compare_against_reference(ROOT_DIR / "report.html", html, f"{dataset_name}:root")
    validation["baseline_checks"] = compare_against_reference(DIST_DIR / "report.pre-refactor-v1.html", html, f"{dataset_name}:baseline")
    if "_real_asset_samples" in dataset:
        validation["image_validation"]["sample_files"] = dataset["_real_asset_samples"]
    if "_real_asset_logo" in dataset:
        validation["image_validation"]["cover_logo_file"] = dataset["_real_asset_logo"]
    if pdf_result.get("status") == "OK":
        page_count = int(pdf_result["page_count"] or 0)
        validation["pagination_summary"]["pdf_page_count"] = page_count
        validation["pagination_summary"]["spill_pages"] = max(
            0,
            page_count - int(validation["pagination_summary"]["print_page_start_sections"]),
        )
        if page_map:
            max_mapped_page = max(int(item["page"]) for item in page_map.values())
            validation["page_map"]["max_mapped_page"] = max_mapped_page
            validation["page_map"]["within_pdf_page_count"] = max_mapped_page <= page_count
            validation["page_map"]["pdf_page_delta"] = page_count - max_mapped_page
    write_text(validation_path, json.dumps(validation, ensure_ascii=False, indent=2))
    return {
        "html_path": html_path,
        "pdf_path": pdf_path,
        "validation_path": validation_path,
        "validation": validation,
    }


def build_table_sample(
    css: str,
    js: str,
    profile_override: str | None = None,
    *,
    allow_local_file_access: bool = False,
) -> dict[str, object]:
    profile = resolve_profile("real-assets", profile_override)
    dataset_stub = {
        "findings": [],
        "appendix_c": [],
        "_profile": profile,
        "_profile_name": profile.name,
    }
    body = render_target_table_sample_sections(profile)
    html_source = render_document(css=css, body=body, js=js, profile=profile, dataset_name="table-sample")
    section_span_probe = probe_section_pdf_spans(
        html_source,
        "table-sample",
        allow_local_file_access=allow_local_file_access,
    )
    build_page_map_data = build_page_map(html_source, section_span_probe=section_span_probe)
    layout_probe = run_layout_probe(
        body=body,
        css=css,
        profile=profile,
        dataset_name="table-sample",
        allow_local_file_access=allow_local_file_access,
    )
    page_map = merge_page_maps(build_page_map_data, layout_probe=layout_probe)
    html = replace_page_tokens(html_source, page_map)

    html_path, pdf_path, validation_path = table_sample_output_paths()
    write_text(html_path, html)
    pdf_result = build_pdf(
        html_path,
        pdf_path,
        allow_local_file_access=allow_local_file_access,
    )
    validation = validate_print_safety(
        html,
        dataset_stub,
        page_map,
        layout_probe=layout_probe,
        section_span_probe=section_span_probe,
        pdf_result=pdf_result,
    )
    validation["pdf"] = pdf_result
    validation["dataset"] = "table-sample"
    validation["profile"] = profile.name
    validation["table_header_validation"] = {
        "sample_row_count": len(synthesize_target_table_rows()),
        "continuation_tables": html.count("[표 5] 웹 취약점 진단 대상 (계속)"),
        "validation_mode": "명시적 continuation table 생성 + thead 반복 CSS 병행",
        "thead_present": "<thead>" in html,
        "caption_split_risk": "낮음",
    }
    if pdf_result.get("status") == "OK":
        page_count = int(pdf_result["page_count"] or 0)
        validation["pagination_summary"]["pdf_page_count"] = page_count
        validation["pagination_summary"]["spill_pages"] = max(
            0,
            page_count - int(validation["pagination_summary"]["print_page_start_sections"]),
        )
        if page_map:
            max_mapped_page = max(int(item["page"]) for item in page_map.values())
            validation["page_map"]["max_mapped_page"] = max_mapped_page
            validation["page_map"]["within_pdf_page_count"] = max_mapped_page <= page_count
            validation["page_map"]["pdf_page_delta"] = page_count - max_mapped_page
    write_text(validation_path, json.dumps(validation, ensure_ascii=False, indent=2))
    return {
        "html_path": html_path,
        "pdf_path": pdf_path,
        "validation_path": validation_path,
        "validation": validation,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build self-contained report HTML/PDF outputs.")
    parser.add_argument(
        "--dataset",
        choices=("all",) + DATASET_NAMES,
        default="all",
        help="Build only one dataset or every dataset profile.",
    )
    parser.add_argument(
        "--profile",
        choices=tuple(PROFILES),
        default=None,
        help="Override the default render profile for the selected dataset(s).",
    )
    parser.add_argument(
        "--allow-local-file-access",
        action="store_true",
        help="Development-only opt-in for Chromium file:// access. Disabled by default for report builds.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    partials = ordered_partials()
    css = join_files(CSS_DIR, CSS_ORDER)
    js = join_files(JS_DIR, JS_ORDER)
    targets = list(DATASET_NAMES) if args.dataset == "all" else [args.dataset]

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Source partials: {len(partials)}")
    print(f"Bundled CSS files: {', '.join(CSS_ORDER)}")
    print(f"Bundled JS files: {', '.join(JS_ORDER)}")
    if args.allow_local_file_access:
        print("Warning: --allow-local-file-access enabled for this build")

    for dataset_name in targets:
        result = build_dataset(
            dataset_name,
            partials,
            css,
            js,
            profile_override=args.profile,
            allow_local_file_access=args.allow_local_file_access,
        )
        print(f"Built {result['html_path']}")
        print(f"Validation {result['validation_path']}")
        print(f"Profile {result['validation']['profile']}")
        pdf_status = result["validation"]["pdf"]["status"]
        if pdf_status == "OK":
            print(f"Built {result['pdf_path']} ({result['validation']['pdf']['page_count']} pages)")
        else:
            print(f"PDF {dataset_name}: {result['validation']['pdf']['reason']}")
        print(
            f"Continuation pages: {result['validation']['continued_pages']} / "
            f"Page tokens remaining: {result['validation']['page_tokens_remaining']}"
        )
        if result["validation"]["fixed_height_overflow_pairs"]:
            print(
                "Fixed-height overflow pairs detected: "
                + ", ".join(result["validation"]["fixed_height_overflow_pairs"])
            )
        else:
            print("Fixed-height overflow pairs detected: none")

    table_sample = build_table_sample(
        css,
        js,
        profile_override=args.profile,
        allow_local_file_access=args.allow_local_file_access,
    )
    print(f"Built {table_sample['html_path']}")
    print(f"Validation {table_sample['validation_path']}")
    if table_sample["validation"]["pdf"]["status"] == "OK":
        print(f"Built {table_sample['pdf_path']} ({table_sample['validation']['pdf']['page_count']} pages)")
    else:
        print(f"PDF table-sample: {table_sample['validation']['pdf']['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
