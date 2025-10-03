#!/usr/bin/env python3
"""Utility for merging appendices into a single HTML document.

The script expects a manifest JSON file with the following structure::

    {
        "title": "שם המסמך",
        "appendices": [
            {
                "description": "תיאור הנספח",
                "file": "path/to/file.ext",
                "type": "text|html|image|pdf",
                "encoding": "utf-8"
            },
            ...
        ]
    }

Only ``description`` and ``file`` are mandatory.  The ``type`` field is optional and
will be inferred from the file extension if omitted.  When ``encoding`` is not
provided it defaults to UTF-8.

The generated HTML document adheres to the required legal appendix format:

* A table of contents as the first page.
* Each appendix begins on a new page with a cover sheet that lists the appendix
  letter and description.
* The body of every appendix is embedded directly into the HTML file.
* The document is rendered right-to-left and includes CSS rules for page
  numbering when printed to PDF.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
from pathlib import Path
from typing import Any, Dict, Iterable, List

HEBREW_LETTERS: List[str] = [
    "א",
    "ב",
    "ג",
    "ד",
    "ה",
    "ו",
    "ז",
    "ח",
    "ט",
    "י",
    "כ",
    "ל",
    "מ",
    "נ",
    "ס",
    "ע",
    "פ",
    "צ",
    "ק",
    "ר",
    "ש",
    "ת",
]

SUPPORTED_IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".svg"}
SUPPORTED_TEXT_TYPES = {".txt", ".md"}
SUPPORTED_HTML_TYPES = {".html", ".htm"}
SUPPORTED_PDF_TYPES = {".pdf"}


class AppendixError(RuntimeError):
    """Raised when the manifest configuration is invalid."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge appendices into a single HTML file")
    parser.add_argument(
        "--manifest",
        required=True,
        type=Path,
        help="Path to the JSON manifest that describes the appendices",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/merged_appendices.html"),
        help="Destination HTML file (default: output/merged_appendices.html)",
    )
    parser.add_argument(
        "--title",
        type=str,
        default=None,
        help="Optional custom title for the table of contents page",
    )
    return parser.parse_args()


def load_manifest(manifest_path: Path) -> Dict[str, Any]:
    if not manifest_path.exists():
        raise AppendixError(f"Manifest file not found: {manifest_path}")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive branch
        raise AppendixError(f"Failed to parse manifest JSON: {exc}") from exc
    if "appendices" not in data or not isinstance(data["appendices"], Iterable):
        raise AppendixError("Manifest must contain an 'appendices' array")
    return data


def normalize_appendices(raw_appendices: Iterable[Any]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for index, item in enumerate(raw_appendices, start=1):
        if not isinstance(item, dict):
            raise AppendixError(f"Appendix entry #{index} must be an object")
        if "file" not in item:
            raise AppendixError(f"Appendix entry #{index} is missing a 'file' attribute")
        if not item.get("description"):
            raise AppendixError(f"Appendix entry #{index} is missing a description")
        normalized.append(item)
    return normalized


def ensure_hebrew_sequence(total: int) -> List[str]:
    if total > len(HEBREW_LETTERS):
        raise AppendixError(
            f"Cannot assign Hebrew letters to {total} appendices. Supported maximum is {len(HEBREW_LETTERS)}."
        )
    return HEBREW_LETTERS[:total]


def infer_type(file_path: Path, explicit: str | None) -> str:
    if explicit:
        return explicit.lower()
    suffix = file_path.suffix.lower()
    if suffix in SUPPORTED_TEXT_TYPES:
        return "text"
    if suffix in SUPPORTED_HTML_TYPES:
        return "html"
    if suffix in SUPPORTED_IMAGE_TYPES:
        return "image"
    if suffix in SUPPORTED_PDF_TYPES:
        return "pdf"
    raise AppendixError(
        f"Unsupported file type '{suffix}' for appendix: {file_path}."
        " Provide an explicit 'type' in the manifest if this is intentional."
    )


def file_to_data_uri(path: Path, mime_type: str) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{data}"


def render_appendix_content(app: Dict[str, Any], letter: str) -> str:
    path = Path(app["file"])
    if not path.exists():
        raise AppendixError(f"Appendix file not found: {path}")

    content_type = infer_type(path, app.get("type"))
    description = html.escape(str(app.get("description", "")))
    encoding = app.get("encoding", "utf-8")

    if content_type == "text":
        text = path.read_text(encoding=encoding)
        body = html.escape(text).replace("\n", "<br />\n")
        return f'<div class="appendix-text" aria-label="תוכן נספח {letter}">{body}</div>'

    if content_type == "html":
        html_content = path.read_text(encoding=encoding)
        return f'<div class="appendix-html" aria-label="תוכן נספח {letter}">{html_content}</div>'

    if content_type == "image":
        mime_type, _ = mimetypes.guess_type(path.as_posix())
        if not mime_type:
            mime_type = "image/png"
        data_uri = file_to_data_uri(path, mime_type)
        alt_text = description or f"תמונה עבור נספח {letter}"
        return "".join(
            [
                f'<div class="appendix-image" aria-label="תוכן נספח {letter}">',
                f'<img src="{data_uri}" alt="{alt_text}" />',
                "</div>",
            ]
        )

    if content_type == "pdf":
        data_uri = file_to_data_uri(path, "application/pdf")
        return "".join(
            [
                f'<div class="appendix-pdf" aria-label="תוכן נספח {letter}">',
                f'<embed src="{data_uri}" type="application/pdf" width="100%" height="900px" />',
                "</div>",
            ]
        )

    raise AppendixError(f"Unsupported appendix content type: {content_type}")


def build_toc_items(letters: Iterable[str], appendices: List[Dict[str, Any]]) -> str:
    items: List[str] = []
    for index, (letter, appendix) in enumerate(zip(letters, appendices), start=1):
        anchor = f"appendix-{index}"
        description = html.escape(str(appendix.get("description", "")))
        letter_with_prime = f"{letter}'"
        items.append(
            f'<li><a href="#{anchor}">נספח {letter_with_prime} – {description}</a></li>'
        )
    return "\n".join(items)


def build_appendix_sections(letters: Iterable[str], appendices: List[Dict[str, Any]]) -> str:
    sections: List[str] = []
    for index, (letter, appendix) in enumerate(zip(letters, appendices), start=1):
        anchor = f"appendix-{index}"
        letter_with_prime = f"{letter}'"
        description = html.escape(str(appendix.get("description", "")))
        content = render_appendix_content(appendix, letter_with_prime)
        section_html = f"""
<section class="appendix" id="{anchor}">
  <div class="appendix-cover">
    <div class="appendix-title">נספח {letter_with_prime}</div>
    <div class="appendix-description">{description}</div>
  </div>
  <div class="appendix-body">
    {content}
  </div>
</section>
""".strip()
        sections.append(section_html)
    return "\n\n".join(sections)


def assemble_document(manifest: Dict[str, Any], output_path: Path, title: str | None) -> None:
    appendices = normalize_appendices(manifest.get("appendices", []))
    if not appendices:
        raise AppendixError("Manifest does not contain any appendices")

    letters = ensure_hebrew_sequence(len(appendices))
    toc_title = title or manifest.get("title") or "תוכן עניינים"

    toc_items_html = build_toc_items(letters, appendices)
    appendix_sections_html = build_appendix_sections(letters, appendices)

    html_document = f"""
<!DOCTYPE html>
<html lang="he">
  <head>
    <meta charset="utf-8" />
    <title>{html.escape(str(toc_title))}</title>
    <style>
      @page {{
        size: A4;
        margin: 2cm;
      }}
      body {{
        direction: rtl;
        font-family: 'Arial', 'Helvetica', sans-serif;
        text-align: right;
        background: #ffffff;
        color: #111111;
        margin: 0;
      }}
      .document {{
        padding: 2rem 3rem;
      }}
      .toc {{
        page-break-after: always;
      }}
      .toc h1 {{
        font-size: 2.4rem;
        margin-bottom: 1.5rem;
        text-align: center;
      }}
      .toc ol {{
        list-style: none;
        counter-reset: toc-counter;
        padding: 0;
      }}
      .toc li {{
        font-size: 1.2rem;
        margin-bottom: 0.8rem;
      }}
      .toc li::before {{
        counter-increment: toc-counter;
        content: counter(toc-counter) '. ';
        margin-left: 0.5rem;
      }}
      .toc a {{
        color: inherit;
        text-decoration: none;
      }}
      .toc a:hover {{
        text-decoration: underline;
      }}
      .appendix {{
        page-break-before: always;
        text-align: right;
      }}
      .appendix:first-of-type {{
        page-break-before: auto;
      }}
      .appendix-cover {{
        text-align: center;
        margin-bottom: 2rem;
      }}
      .appendix-title {{
        font-size: 3rem;
        font-weight: 700;
      }}
      .appendix-description {{
        font-size: 1.4rem;
        margin-top: 0.5rem;
      }}
      .appendix-body {{
        font-size: 1rem;
        line-height: 1.7;
      }}
      .appendix-text {{
        white-space: pre-wrap;
        font-family: 'Assistant', 'Rubik', 'Arial', sans-serif;
        font-size: 1.05rem;
      }}
      .appendix-html {{
        font-size: 1.05rem;
      }}
      .appendix-image {{
        text-align: center;
      }}
      .appendix-image img {{
        max-width: 100%;
        height: auto;
      }}
      .appendix-pdf embed {{
        width: 100%;
        height: 900px;
        border: 1px solid #cccccc;
      }}
      @media print {{
        body {{
          margin: 0;
        }}
        .document {{
          padding: 0;
        }}
        .toc {{
          page-break-after: always;
        }}
        .appendix {{
          page-break-before: always;
        }}
        footer {{
          position: running(pageFooter);
        }}
      }}
      @page {{
        @bottom-center {{
          content: 'עמוד ' counter(page) ' מתוך ' counter(pages);
          font-size: 10pt;
        }}
      }}
    </style>
  </head>
  <body>
    <div class="document" dir="rtl">
      <section class="toc" aria-label="תוכן עניינים">
        <h1>{html.escape(str(toc_title))}</h1>
        <ol>
          {toc_items_html}
        </ol>
      </section>
      {appendix_sections_html}
    </div>
  </body>
</html>
""".strip()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_document, encoding="utf-8")


def main() -> None:
    args = parse_args()
    manifest = load_manifest(args.manifest)
    try:
        assemble_document(manifest, args.output, args.title)
    except AppendixError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
