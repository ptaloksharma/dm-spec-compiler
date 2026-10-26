"""Module 1 — Local ingestion & Markdown converter.

Deterministic HTML / Markdown / PDF → clean Markdown normalisation.
NO LLM calls anywhere in this module: structure is extracted with
BeautifulSoup (HTML), a heading-preserving line filter (Markdown), and
PyMuPDF text blocks (PDF). Every output file records its source in a
front-matter block so downstream stages keep provenance.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field

import fitz  # PyMuPDF
from bs4 import BeautifulSoup

SUPPORTED = {".html", ".htm", ".md", ".markdown", ".pdf"}


@dataclass
class IngestedDoc:
    source_path: str
    kind: str  # html | markdown | pdf
    title: str
    markdown: str
    sha256: str
    warnings: list[str] = field(default_factory=list)
    raw_html: str = ""  # populated for kind=="html" (rich DOM extraction)


# --------------------------------------------------------------------------- #
# HTML                                                                          #
# --------------------------------------------------------------------------- #
_CLUTTER_TAGS = ("script", "style", "noscript", "svg", "nav", "footer",
                 "header", "form", "iframe", "button", "select")


def html_to_markdown(text: str) -> tuple[str, str, list[str]]:
    """Return (title, markdown, warnings) — deterministic, tag-table driven."""
    warnings: list[str] = []
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(_CLUTTER_TAGS):
        tag.decompose()

    title = (soup.title.string.strip() if soup.title and soup.title.string else "")

    out: list[str] = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6",
                             "p", "li", "table", "pre", "code", "blockquote"]):
        name = el.name
        if name.startswith("h") and len(name) == 2 and name[1].isdigit():
            level = int(name[1])
            body = el.get_text(" ", strip=True)
            if body:
                out.append(f"{'#' * level} {body}")
                if not title and level == 1:
                    title = body
        elif name in ("pre", "code"):
            body = el.get_text("\n", strip=False).rstrip()
            if body and name == "pre":
                out.append(f"```\n{body}\n```")
        elif name == "li":
            body = el.get_text(" ", strip=True)
            if body:
                out.append(f"- {body}")
        elif name == "table":
            out.append(_table_to_md(el))
        elif name == "blockquote":
            body = el.get_text(" ", strip=True)
            if body:
                out.append(f"> {body}")
        else:  # p
            body = el.get_text(" ", strip=True)
            if body:
                out.append(body)

    md = "\n\n".join(b for b in out if b).strip() + "\n"
    if not md.strip():
        warnings.append("html contained no extractable content blocks")
    return title or "untitled", md, warnings


def _table_to_md(table) -> str:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    header = "| " + " | ".join(rows[0]) + " |"
    sep = "|" + "|".join([" --- "] * width) + "|"
    body = ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join([header, sep, *body])


# --------------------------------------------------------------------------- #
# Markdown                                                                      #
# --------------------------------------------------------------------------- #
_HTML_LINE_RE = re.compile(r"<(?!!--)[a-zA-Z/][^>]*>")


def markdown_to_markdown(text: str) -> tuple[str, str, list[str]]:
    """Strip residual HTML tags/clutter; preserve headings, lists, tables."""
    warnings: list[str] = []
    kept: list[str] = []
    title = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = _HTML_LINE_RE.sub("", line)
        if stripped != line:
            warnings.append("stripped inline html from a markdown line")
        kept.append(stripped)
        if not title and stripped.startswith("# "):
            title = stripped[2:].strip()
    md = "\n".join(kept).strip() + "\n"
    return title or "untitled", md, warnings


# --------------------------------------------------------------------------- #
# PDF                                                                           #
# --------------------------------------------------------------------------- #
def pdf_to_markdown(path: str) -> tuple[str, str, list[str]]:
    """PyMuPDF text-block extraction with size-ranked heading detection."""
    warnings: list[str] = []
    doc = fitz.open(path)
    blocks: list[tuple[float, str]] = []
    sizes: list[float] = []
    for page in doc:
        for b in page.get_text("dict").get("blocks", []):
            for line in b.get("lines", []):
                spans = line.get("spans", [])
                text = "".join(s.get("text", "") for s in spans).strip()
                if not text:
                    continue
                size = max((s.get("size", 0.0) for s in spans), default=0.0)
                sizes.append(size)
                blocks.append((size, text))
    doc.close()
    if not blocks:
        warnings.append("pdf yielded no text blocks (scanned image?)")
        return "untitled", "", warnings

    body_size = sorted(sizes)[len(sizes) // 2] if sizes else 0.0
    out: list[str] = []
    title = ""
    for size, text in blocks:
        if size >= body_size * 1.6:
            out.append(f"# {text}")
            if not title:
                title = text
        elif size >= body_size * 1.3:
            out.append(f"## {text}")
        elif size >= body_size * 1.12:
            out.append(f"### {text}")
        else:
            out.append(text)
    return title or "untitled", "\n\n".join(out).strip() + "\n", warnings


# --------------------------------------------------------------------------- #
# Driver                                                                        #
# --------------------------------------------------------------------------- #
def ingest_file(path: str) -> IngestedDoc:
    ext = os.path.splitext(path)[1].lower()
    raw_sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    raw_html = ""
    if ext in (".html", ".htm"):
        raw_html = open(path, encoding="utf-8", errors="replace").read()
        title, md, w = html_to_markdown(raw_html)
        kind = "html"
    elif ext in (".md", ".markdown"):
        title, md, w = markdown_to_markdown(open(path, encoding="utf-8", errors="replace").read())
        kind = "markdown"
    elif ext == ".pdf":
        title, md, w = pdf_to_markdown(path)
        kind = "pdf"
    else:
        raise ValueError(f"unsupported spec type: {ext}")
    return IngestedDoc(source_path=path, kind=kind, title=title,
                       markdown=md, sha256=raw_sha, warnings=w,
                       raw_html=raw_html)


def ingest_dir(incoming: str, out_dir: str) -> list[IngestedDoc]:
    """Convert every supported file in ``incoming`` to a clean .md in ``out_dir``."""
    os.makedirs(out_dir, exist_ok=True)
    docs: list[IngestedDoc] = []
    for fname in sorted(os.listdir(incoming)):
        path = os.path.join(incoming, fname)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext not in SUPPORTED:
            continue
        doc = ingest_file(path)
        docs.append(doc)
        base = os.path.splitext(fname)[0]
        out_path = os.path.join(out_dir, f"{base}.md")
        front = (
            "---\n"
            f"source_file: {fname}\n"
            f"source_kind: {doc.kind}\n"
            f"source_sha256: {doc.sha256}\n"
            f"title: {doc.title!r}\n"
            "---\n\n"
        )
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(front + doc.markdown)
    return docs
