import copy
import re
import unittest
from pathlib import Path

import build_report


class ReportSecurityTest(unittest.TestCase):
    def sample_finding(self) -> dict[str, object]:
        profile = build_report.resolve_profile("default", None)
        dataset = build_report.load_dataset("default", profile)
        finding = copy.deepcopy(dataset["findings"][0])
        finding["_profile"] = profile
        return finding

    def test_summary_text_is_escaped(self) -> None:
        finding = {"summary": '<img src=x onerror=alert(1)>'}
        block = build_report.render_summary_block(finding)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", block.html)
        self.assertNotIn('<img src=x onerror=alert(1)>', block.html)

    def test_image_src_attribute_breakout_is_blocked(self) -> None:
        fragment = build_report.render_figure_media_html(
            {
                "image_src": 'x" onerror="alert(1)',
                "box_text": "[placeholder]",
                "title": "caption",
            },
            "finding.evidence",
        )
        html = build_report.render_trusted_html(fragment)
        self.assertIn("[placeholder]", html)
        self.assertNotIn("<img", html)
        self.assertNotIn("onerror=", html)

    def test_finding_render_escapes_text_fields_and_blocks_bad_target_url(self) -> None:
        finding = self.sample_finding()
        finding["title"] = '<svg/onload=alert(1)>'
        finding["target_url"] = "javascript:alert(1)"
        finding["summary"] = '<img src=x onerror=alert(1)>'
        finding["repro_steps"] = ['<script>alert(1)</script>']
        finding["references"] = ['<b>reference</b>']
        finding["evidences"] = []

        page_html = build_report.render_finding_page(
            finding,
            build_report.render_finding_blocks(finding, 0),
            0,
            0,
        )

        self.assertIn("&lt;svg/onload=alert(1)&gt;", page_html)
        self.assertNotIn("<svg/onload=alert(1)>", page_html)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", page_html)
        self.assertNotIn('<img src=x onerror=alert(1)>', page_html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page_html)
        self.assertNotIn("<script>alert(1)</script>", page_html)
        self.assertIn("&lt;b&gt;reference&lt;/b&gt;", page_html)
        self.assertNotIn("<b>reference</b>", page_html)
        self.assertIn(build_report.BLOCKED_URL_TEXT, page_html)
        self.assertNotIn("javascript:alert(1)", page_html)

    def test_trusted_fragment_is_explicit(self) -> None:
        plain_html = build_report.render_template(
            "toc-item.html",
            {
                "item_style": "",
                "repeat_name": "toc-entry",
                "toc_key": "chapter-1",
                "label_fragment": "<strong>unsafe</strong>",
                "page_field": "page.chapter-1",
                "page_token": "{{page:chapter-1}}",
            },
        )
        self.assertIn("&lt;strong&gt;unsafe&lt;/strong&gt;", plain_html)
        self.assertNotIn("<strong>unsafe</strong>", plain_html)

        trusted_html = build_report.render_template(
            "toc-item.html",
            {
                "item_style": "",
                "repeat_name": "toc-entry",
                "toc_key": "chapter-1",
                "label_fragment": build_report.trusted_html("<strong>safe</strong>"),
                "page_field": "page.chapter-1",
                "page_token": "{{page:chapter-1}}",
            },
        )
        self.assertIn("<strong>safe</strong>", trusted_html)

    def test_toc_dataset_html_is_sanitized_to_internal_fragment(self) -> None:
        html = build_report.render_toc_entry(
            {
                "repeat": "toc-entry",
                "toc_key": "chapter-1",
                "style": "padding-left: 15px",
                "label_html": '<img src=x onerror=alert(1)><strong>TOC</strong>',
            }
        )
        self.assertNotIn("<img", html)
        self.assertIn("<strong>TOC</strong>", html)
        self.assertNotIn("onerror=", html)

    def test_url_policy_blocks_unsafe_schemes(self) -> None:
        self.assertEqual("", build_report.sanitize_image_src('x" onerror="alert(1)'))
        self.assertEqual("", build_report.sanitize_image_src("javascript:alert(1)"))
        self.assertEqual("", build_report.sanitize_image_src("JaVaScRiPt:alert(1)"))
        self.assertEqual("", build_report.sanitize_image_src("java\nscript:alert(1)"))
        self.assertEqual("", build_report.sanitize_image_src("java\tscript:alert(1)"))
        self.assertEqual("", build_report.sanitize_image_src(" javascript:alert(1)"))
        self.assertEqual("", build_report.sanitize_image_src("file:///etc/passwd"))
        self.assertEqual("", build_report.sanitize_image_src("data:image/svg+xml;base64,PHN2Zy8+"))
        self.assertEqual("", build_report.sanitize_image_src("../secrets.png"))
        self.assertEqual("", build_report.sanitize_image_src("images/../secrets.png"))
        self.assertEqual("", build_report.sanitize_image_src("..%2fsecrets.png"))
        self.assertEqual("", build_report.sanitize_image_src("images/%2e%2e/secrets.png"))
        self.assertEqual("", build_report.sanitize_image_src("\\Windows\\secret.png"))
        self.assertEqual("", build_report.sanitize_image_src("/mnt/d/secret.png"))
        self.assertEqual("", build_report.sanitize_target_url("vbscript:msgbox(1)"))
        self.assertEqual("", build_report.sanitize_target_url("JaVaScRiPt:alert(1)"))
        self.assertEqual("", build_report.sanitize_target_url("java\r\nscript:alert(1)"))
        self.assertEqual(
            "https://example.com/image.png",
            build_report.sanitize_image_src("https://example.com/image.png"),
        )
        self.assertEqual(
            "images/evidence.png",
            build_report.sanitize_image_src("images/evidence.png"),
        )
        self.assertEqual(
            "./images/evidence.png?v=1",
            build_report.sanitize_image_src("./images/evidence.png?v=1"),
        )
        self.assertEqual(
            "data:image/png;base64,QUJDRA==",
            build_report.sanitize_image_src("data:image/png;base64,QUJDRA=="),
        )

    def test_relative_image_path_traversal_does_not_reach_img_sink(self) -> None:
        fragment = build_report.render_figure_media_html(
            {
                "image_src": "../private/screenshot.png",
                "box_text": "[blocked traversal]",
                "title": "caption",
            },
            "finding.evidence",
        )
        html = build_report.render_trusted_html(fragment)
        self.assertIn("[blocked traversal]", html)
        self.assertNotIn("<img", html)
        self.assertNotIn("../private/screenshot.png", html)

    def test_mandatory_payloads_do_not_land_in_active_sinks(self) -> None:
        finding = self.sample_finding()
        finding["summary"] = '<img src=x onerror=alert(1)>'
        finding["title"] = "</td><script>alert(1)</script>"
        finding["target_url"] = "  JaVaScRiPt:alert(1)"
        finding["repro_steps"] = [
            "<b>step one</b>",
            "</li><script>alert(2)</script><li>",
        ]
        finding["references"] = ["<a href=javascript:alert(1)>ref</a>"]
        finding["evidences"][0]["image_src"] = 'x" onerror="alert(1)'
        finding["evidences"][1]["image_src"] = "file:///etc/passwd"

        page_html = build_report.render_finding_page(
            finding,
            build_report.render_finding_blocks(finding, 0),
            0,
            0,
        )

        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", page_html)
        self.assertIn("&lt;/td&gt;&lt;script&gt;alert(1)&lt;/script&gt;", page_html)
        self.assertIn("&lt;b&gt;step one&lt;/b&gt;", page_html)
        self.assertIn("&lt;/li&gt;&lt;script&gt;alert(2)&lt;/script&gt;&lt;li&gt;", page_html)
        self.assertIn("&lt;a href=javascript:alert(1)&gt;ref&lt;/a&gt;", page_html)
        self.assertIn(build_report.BLOCKED_URL_TEXT, page_html)
        self.assertGreaterEqual(page_html.count("evidence-placeholder"), 2)
        self.assertNotRegex(page_html, re.compile(r"<script\b", re.I))
        self.assertNotRegex(page_html, re.compile(r"<[^>]+\sonerror\s*=", re.I))
        self.assertNotRegex(page_html, re.compile(r"""(?:src|href)\s*=\s*["']\s*javascript:""", re.I))
        self.assertNotRegex(page_html, re.compile(r"""(?:src|href)\s*=\s*["']\s*file:""", re.I))

    def test_pdf_build_args_disable_file_access_by_default(self) -> None:
        html_path = Path("report.html")
        pdf_path = Path("report.pdf")

        pdf_args = build_report.pdf_browser_args(html_path, pdf_path, "chromium")
        probe_args = build_report.layout_probe_browser_args(html_path, "chromium")
        dev_pdf_args = build_report.pdf_browser_args(
            html_path,
            pdf_path,
            "chromium",
            allow_local_file_access=True,
        )

        self.assertNotIn("--allow-file-access-from-files", pdf_args)
        self.assertNotIn("--allow-file-access-from-files", probe_args)
        self.assertIn("--allow-file-access-from-files", dev_pdf_args)


if __name__ == "__main__":
    unittest.main()
