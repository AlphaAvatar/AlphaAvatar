# Copyright 2026 AlphaAvatar project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations

import mimetypes
import os
import pathlib
import re
from collections.abc import Iterable
from urllib.parse import urljoin, urlparse

import requests
from markdown import markdown
from weasyprint import CSS, HTML

_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _safe_filename_from_url(u: str, fallback_ext: str = ".bin") -> str:
    parsed = urlparse(u)
    name = os.path.basename(parsed.path) or "image"
    if "." not in name:
        name += fallback_ext
    return name


def _download_binary(url: str, out_dir: pathlib.Path, timeout: int = 20) -> pathlib.Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(url, timeout=timeout, stream=True, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()

        content_type = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        ext = mimetypes.guess_extension(content_type) if content_type else None

        filename = _safe_filename_from_url(url, fallback_ext=ext or ".bin")
        path = out_dir / filename

        if ext and path.suffix.lower() != ext.lower():
            if "." not in os.path.basename(urlparse(url).path):
                path = path.with_suffix(ext)

        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 64):
                if chunk:
                    f.write(chunk)
        return path
    except Exception:
        return None


def _localize_md_images(md_text: str, page_url: str, assets_dir: pathlib.Path) -> str:
    images_dir = assets_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    replacements: dict[str, str] = {}

    def normalize_src(src: str) -> str:
        return src.strip().strip('"').strip("'")

    for m in _MD_IMAGE_RE.finditer(md_text):
        src = normalize_src(m.group(2))
        abs_url = urljoin(page_url, src)

        if abs_url in replacements:
            continue

        local_path = _download_binary(abs_url, images_dir)
        if not local_path:
            continue

        rel = local_path.relative_to(assets_dir).as_posix()
        replacements[src] = rel
        replacements[abs_url] = rel

    def _replace(match: re.Match) -> str:
        alt = match.group(1)
        src = normalize_src(match.group(2))
        abs_url = urljoin(page_url, src)
        new_src = replacements.get(src) or replacements.get(abs_url) or src
        return f"![{alt}]({new_src})"

    return _MD_IMAGE_RE.sub(_replace, md_text)


def save_single_url_content_to_pdf(
    *,
    url: str,
    title: str | None,
    markdown_content: str,
    output_pdf_path: str,
    work_dir: pathlib.Path,
    extra_image_urls: Iterable[str] | None = None,
    timeout: int = 20,
) -> None:
    """
    Saves the Markdown content (including images) of the specified URL as a PDF file.
    - url: Page URL (used to complete relative image paths)
    - title: Document title (optional)
    - markdown_content: Markdown content
    - output_pdf_path: Output PDF path
    - work_dir: Working directory, used to store downloaded image resources (a separate subdirectory is recommended for each PDF)
    - extra_image_urls: Optional, a list of additional images (e.g., Tavily's images field), which will be pre-downloaded to improve the hit rate.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = work_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    # 1) Pre-download extra_image_urls (optional)
    if extra_image_urls:
        img_dir = assets_dir / "images"
        for img in extra_image_urls:
            abs_url = urljoin(url, str(img))
            _download_binary(abs_url, img_dir, timeout=timeout)

    # 2) Localize image links in markdown (download + replace with relative paths)
    md = _localize_md_images(markdown_content or "", page_url=url, assets_dir=assets_dir)

    # 3) Assemble a single-page Markdown document (add headings and source)
    doc_title = title or url
    merged_md = f"# {doc_title}\n\n- URL: {url}\n\n---\n\n{md}\n"

    # 4) markdown -> html
    html_content = markdown(
        merged_md,
        extensions=["extra", "codehilite", "toc"],
        output_format="html5",
    )

    css = CSS(
        string="""
        body { font-family: Arial, Helvetica, sans-serif; font-size: 12px; line-height: 1.6; }
        h1, h2, h3 { color: #333; }
        pre { background: #f6f8fa; padding: 10px; overflow-x: auto; }
        code { font-family: Consolas, Monaco, monospace; }
        img { max-width: 100%; height: auto; }
        """
    )

    # 5) html -> pdf (base_url is crucial: it allows relative image paths to be loaded)
    HTML(string=html_content, base_url=str(assets_dir.resolve())).write_pdf(
        output_pdf_path,
        stylesheets=[css],
    )
