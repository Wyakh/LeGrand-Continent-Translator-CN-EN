#!/usr/bin/env python3
"""Turn a text-based French article PDF into styled English and Chinese PDFs.

Configuration: .env beside this script, or NEWS_API_* environment variables.
Run from this folder: python news_translate.py ARTICLE.pdf --keep
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import unicodedata
import urllib.error
import urllib.request

try:
    import pymupdf as fitz
except ImportError:
    print('Missing PyMuPDF: use the batch launcher or run python -m pip install -r "'
          + str(Path(__file__).resolve().parent / "requirements.txt") + '"', file=sys.stderr)
    raise SystemExit(2)

BASE_URL = "https://api.openai.com/v1"
TOKEN_LIMIT = 7500
MARK = re.compile(r"\[\[ASSET_(\d{4})\]\]")
WORD = re.compile(r"\w+", re.UNICODE)
CONFIG_NAMES = ("NEWS_API_KEY", "NEWS_API_MODEL", "NEWS_API_BASE_URL")
TITLE_MARK = "[[TRANSLATED_TITLE]]"


def read_local_config(path: Path) -> dict[str, str]:
    """Read only three expected settings; never print credentials."""
    if not path.exists():
        return {}
    config = {}
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise ValueError(f"Invalid .env entry on line {number}: use NAME=value")
        name, value = stripped.split("=", 1)
        name = name.strip()
        if name not in CONFIG_NAMES:
            raise ValueError(f"Unknown .env setting on line {number}: {name}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if not value or "\x00" in value:
            raise ValueError(f"Empty or invalid .env value for {name} on line {number}")
        config[name] = value
    return config


def api_config() -> tuple[str, str, str]:
    local = read_local_config(Path(__file__).resolve().parent / ".env")
    config = {name: os.environ.get(name) or local.get(name, "") for name in CONFIG_NAMES}
    key, model = config["NEWS_API_KEY"], config["NEWS_API_MODEL"]
    url = config["NEWS_API_BASE_URL"] or BASE_URL
    if not key or key == "YOUR_API_KEY_HERE" or not model or model == "YOUR_MODEL_NAME_HERE":
        raise ValueError("Set NEWS_API_KEY and NEWS_API_MODEL in .env beside news_translate.py; source kept")
    if not re.fullmatch(r"https?://[^\s]+", url):
        raise ValueError("NEWS_API_BASE_URL must be an http(s) URL")
    return key, model, url


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def join_lines(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    out = ""
    for line in lines:
        if out.endswith("-") and line and line[0].islower():
            out = out[:-1] + line
        else:
            out += (" " if out else "") + line
    out = re.sub(r"\s+", " ", out).strip()
    return re.sub(r"(?<=\w)- (?=\w)", "-", out)


def body_parts(page):
    """Preserve commentary style based on PDF span color/size and indentation."""
    width, height = page.rect.width, page.rect.height
    parts, removed = [], []
    for block in page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]:
        if block.get("type") != 0:
            continue
        rect = fitz.Rect(block["bbox"])
        lines = []
        spans = []
        for line in block.get("lines", []):
            value = "".join(s["text"] for s in line.get("spans", [])).strip()
            if value:
                lines.append(value)
            spans.extend(line.get("spans", []))
        if not lines:
            continue
        value = "\n".join(lines)
        reason = None
        if rect.x1 < max(55, width * .105):
            reason = "margin furniture or page number"
        elif rect.y0 > height * .95 and re.fullmatch(r"\d{1,3}", value.strip()):
            reason = "page number"
        elif rect.y1 < height * .12 and rect.x0 < width * .16 and len(value) < 65:
            reason = "page header"
        if reason:
            removed.append({"reason": reason, "text": value, "bbox": list(rect)})
            continue
        major = max(spans, key=lambda s: len(s.get("text", "")), default={})
        color = major.get("color", 0)
        muted = (color & 255) > 75 and ((color >> 8) & 255) > 75
        is_commentary = bool(muted and rect.x0 >= width * .15 and major.get("size", 0) >= 13)
        parts.append({"text": join_lines(value), "bbox": list(rect), "x": rect.x0, "y": rect.y0,
                      "style": "commentary" if is_commentary else "normal",
                      "font_size": round(float(major.get("size", 0)), 1)})
    return parts, removed


def image_rects(page):
    seen = set()
    for image in page.get_images(full=True):
        xref = image[0]
        for rect in page.get_image_rects(xref):
            if min(rect.width, rect.height) < 22 or rect.width * rect.height < 2500:
                continue
            key = (xref, tuple(round(n, 2) for n in rect))
            if key not in seen:
                seen.add(key)
                yield xref, rect


def extract(pdf: Path, work: Path) -> tuple[str, dict]:
    work.mkdir(parents=True, exist_ok=True)
    assets = work / "assets"
    assets.mkdir(exist_ok=True)
    manifest = {"source": str(pdf.resolve()), "pages": 0, "assets": {}, "excluded": [], "source_filename": pdf.stem}
    paragraphs = []
    asset_id = 0
    with fitz.open(pdf) as doc:
        if doc.is_encrypted or not doc.page_count:
            raise ValueError("Encrypted or empty PDF is not supported")
        manifest["pages"] = doc.page_count
        for page_no, page in enumerate(doc, 1):
            blocks, removed = body_parts(page)
            for item in removed:
                item["page"] = page_no
            manifest["excluded"].extend(removed)
            elements = []
            for block in blocks:
                if block["text"]:
                    elements.append((block["y"], block["x"], block["text"], block["style"]))
            for xref, rect in image_rects(page):
                asset_id += 1
                token = f"[[ASSET_{asset_id:04d}]]"
                image = doc.extract_image(xref)
                ext = image.get("ext", "png").lower()
                data = image["image"]
                if ext not in {"png", "jpeg", "jpg", "webp"}:
                    ext = "png"
                    data = page.get_pixmap(clip=rect, matrix=fitz.Matrix(2, 2)).tobytes("png")
                path = assets / f"asset-{asset_id:04d}.{ext}"
                path.write_bytes(data)
                manifest["assets"][token] = {"file": str(path.relative_to(work)).replace("\\", "/"),
                                              "page": page_no, "bbox": list(rect)}
                elements.append((rect.y0, rect.x0, token, "asset"))
            elements.sort(key=lambda item: (item[0], item[1]))
            page_parts = [(text, style) for _, _, text, style in elements]
            if paragraphs and page_parts and paragraphs[-1][1] == page_parts[0][1]:
                prev, style = paragraphs[-1]
                following = page_parts[0][0]
                if style != "asset" and prev and following and (
                    prev.endswith(("-", ",", ":", ";")) or (prev[-1].isalnum() and following[0].islower())
                ):
                    separator = "" if prev.endswith("-") else " "
                    paragraphs[-1] = (prev + separator + following, style)
                    page_parts.pop(0)
            paragraphs.extend(page_parts)
    # Explicit labels give the translator the distinction between article and
    # gray editorial commentary; the article's filename is translated separately.
    source = "Source PDF filename (translate as a title; not a path): " + pdf.stem + "\n\n"
    for text, style in paragraphs:
        source += (f"[[COMMENTARY]]\n{text}\n[[/COMMENTARY]]" if style == "commentary" else text) + "\n\n"
    source = source.strip() + "\n"
    if len(WORD.findall(source)) < 100:
        raise ValueError("Little text found; scanned PDFs require OCR")
    write_text(work / "source.fr.txt", source)
    write_text(work / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return source, manifest


def chunks(source: str) -> list[str]:
    groups = source.strip().split("\n\n")
    result, current = [], ""
    for group in groups:
        if len(group) > TOKEN_LIMIT:
            raise ValueError("Extracted block too long; inspect source.fr.txt")
        if len(current) + len(group) + 2 > TOKEN_LIMIT and current:
            result.append(current)
            current = ""
        current += ("\n\n" if current else "") + group
    if current:
        result.append(current)
    return result


def ask_api(text: str, language: str, key: str, model: str, url: str) -> str:
    instruction = (
        f"Translate the French news excerpt faithfully into {language}. Reply ONLY with Markdown, without fences. "
        "Preserve paragraph order, quotations, captions, editorial comments and all facts. Do not invent or verify claims. "
        "Preserve [[ASSET_0001]]-style markers exactly, each on its own line. "
        "Preserve every [[COMMENTARY]] ... [[/COMMENTARY]] pair exactly, on separate lines; "
        "translate the text INSIDE as editorial commentary, distinct from the article body. "
        "If the excerpt begins with 'Source PDF filename', translate the title phrase into the target language "
        "and put it FIRST as: [[TRANSLATED_TITLE]] your translated natural-language title. "
        "Do not reproduce the Source PDF filename line. Also translate the article's displayed headline normally. "
        "Do not translate branding inside images. Do not add a preface."
    )
    payload = {"model": model, "temperature": 1, "messages": [
        {"role": "system", "content": instruction}, {"role": "user", "content": text}
    ]}
    request = urllib.request.Request(url.rstrip("/") + "/chat/completions",
                                     data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                     headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                                     method="POST")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.load(response)
            answer = result["choices"][0]["message"]["content"]
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("API returned empty translation")
            return answer.strip()
        except urllib.error.HTTPError as exc:
            detail = exc.read(400).decode("utf-8", "replace")
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise RuntimeError(f"Translation API HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3:
                raise
        time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def commentary_tokens(text: str) -> list[str]:
    return re.findall(r"(?m)^\[\[/?COMMENTARY\]\]\s*$", text)


def validate_translation(source: str, answer: str, language: str, number: int) -> None:
    expected = MARK.findall(source)
    if expected != MARK.findall(answer):
        raise ValueError(f"Asset marker mismatch in {language} chunk {number}")
    for marker in expected:
        if not re.search(r"(?m)^\[\[ASSET_" + marker + r"\]\]\s*$", answer):
            raise ValueError(f"Asset marker must be on its own line in {language} chunk {number}")
    if commentary_tokens(source) != commentary_tokens(answer):
        raise ValueError(f"Editorial-commentary marker mismatch in {language} chunk {number}")
    if number == 1:
        if not re.search(r"(?m)^\[\[TRANSLATED_TITLE\]\]\s*[^\n]+$", answer):
            raise ValueError(f"Translated filename title missing in {language} chunk 1")
    elif TITLE_MARK in answer:
        raise ValueError(f"Unexpected translated title marker in {language} chunk {number}")


def translate(source: str, work: Path, language: str, key: str, model: str, url: str) -> Path:
    parts = chunks(source)
    target = work / f"translated.{language}.md"
    translated = []
    for index, part in enumerate(parts, 1):
        print(f"  {language} chunk {index}/{len(parts)}", flush=True)
        answer = ask_api(part, language, key, model, url)
        validate_translation(part, answer, language, index)
        translated.append(answer)
        write_text(target, "\n\n".join(translated) + "\n")
    return target


def translated_title(markdown: str) -> str:
    match = re.search(r"(?m)^\[\[TRANSLATED_TITLE\]\]\s*([^\n]+)\s*$", markdown)
    if not match or markdown.count(TITLE_MARK) != 1:
        raise ValueError("Translation must contain exactly one translated filename title")
    title = match.group(1).strip().strip("\"'“”‘’«» ")
    title = unicodedata.normalize("NFC", title)
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title).strip(" .")
    title = re.sub(r"\s+", " ", title)
    if not title or title in (".", "..") or len(title) > 105:
        raise ValueError("Translated filename is empty or too long; inspect its Markdown")
    return title


def markdown_to_html(markdown: str, manifest: dict, work: Path, language: str) -> str:
    lines = markdown.splitlines()
    output, paragraph, commentary = [], [], False

    def inline(value):
        value = html.escape(value)
        value = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", value)
        value = re.sub(r"\*(.+?)\*", r"<em>\1</em>", value)
        return value

    def flush():
        if paragraph:
            text = " ".join(paragraph)
            output.append(("<p class='commentary'>" if commentary else "<p>") + inline(text) + "</p>")
            paragraph.clear()

    for raw in lines:
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith(TITLE_MARK):
            flush()
            continue
        if line == "[[COMMENTARY]]":
            flush()
            if commentary:
                raise ValueError("Nested commentary markers are invalid")
            commentary = True
            continue
        if line == "[[/COMMENTARY]]":
            flush()
            if not commentary:
                raise ValueError("Unmatched commentary close marker")
            commentary = False
            continue
        marker = MARK.fullmatch(line)
        if marker:
            flush()
            item = manifest["assets"].get(line)
            if not item:
                raise ValueError(f"Unknown image marker: {line}")
            image_path = (work / item["file"]).resolve()
            ext = image_path.suffix.lower()
            mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/webp" if ext == ".webp" else "image/png"
            encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
            output.append(f'<figure><img src="data:{mime};base64,{encoded}" alt="Original image, page {item["page"]}"></figure>')
        elif line.startswith(("# ", "## ", "### ")):
            flush()
            level = min(3, len(line) - len(line.lstrip("#")))
            output.append(f"<h{level}>" + inline(line[level + 1:]) + f"</h{level}>")
        elif line.startswith("> "):
            flush()
            output.append("<blockquote>" + inline(line[2:]) + "</blockquote>")
        elif re.match(r"^[-*] ", line):
            flush()
            output.append("<p>• " + inline(line[2:]) + "</p>")
        else:
            if MARK.search(line):
                raise ValueError(f"Asset marker must appear on its own line: {line[:100]}")
            paragraph.append(line)
    flush()
    if commentary:
        raise ValueError("Unclosed commentary marker")
    css = """@page{size:A4;margin:65px 65px 66px}body{font-family:Arial,'Noto Sans SC',sans-serif;color:#202020;font-size:11pt;line-height:1.55}h1{font-size:22pt}h2{font-size:16pt}h3{font-size:13pt}p,blockquote{margin:0 0 12px}blockquote,p.commentary{margin-left:26px;border-left:2px solid #888;padding-left:16px;color:#777}blockquote{margin-bottom:15px}p.commentary{margin-top:8px;margin-bottom:14px;font-size:11.5pt;line-height:1.6}figure{margin:20px auto;text-align:center;break-inside:avoid}img{max-width:100%;max-height:480px;object-fit:contain}"""
    return f'<!doctype html><html lang="{("en" if language == "english" else "zh-CN")}"><meta charset="utf-8"><style>{css}</style><body><main>{"".join(output)}</main></body></html>'


def render(markdown: Path, manifest: dict, work: Path, output: Path, language: str) -> None:
    source = markdown.read_text(encoding="utf-8")
    translated_title(source)
    expected = list(manifest["assets"])
    actual = [f"[[ASSET_{n}]]" for n in MARK.findall(source)]
    if expected != actual:
        raise ValueError(f"Wrong asset sequence in {markdown.name}")
    if len(WORD.findall(source)) < 100 and len(source.strip()) < 400:
        raise ValueError(f"Translation unexpectedly short: {markdown}")
    html_doc = markdown_to_html(source, manifest, work, language)
    write_text(work / f"preview.{language}.html", html_doc)
    story = fitz.Story(html=html_doc, em=12)
    media = fitz.paper_rect("a4")
    writer = fitz.DocumentWriter(str(output))
    pages = 0
    try:
        while True:
            content = fitz.Rect(65, 65, media.width - 65, media.height - 66)
            more, filled = story.place(content)
            if filled[3] <= content.y0 and more:
                raise ValueError("A block is too large to fit on a PDF page")
            device = writer.begin_page(media)
            story.draw(device)
            writer.end_page()
            pages += 1
            if not more:
                break
            if pages > 100:
                raise ValueError("Output exceeded 100 pages")
    finally:
        writer.close()
    with fitz.open(output) as result:
        if not result.page_count or len("".join(p.get_text() for p in result)) < 200:
            raise ValueError(f"Rendered PDF validation failed: {output}")
    print(f"  Validated {output.name}: {pages} pages")


def output_paths(pdf: Path, work: Path) -> dict[str, Path]:
    results = {}
    for language in ("english", "chinese"):
        text = (work / f"translated.{language}.md").read_text(encoding="utf-8")
        title = translated_title(text)
        candidate = pdf.with_name(f"{title}.pdf")
        if candidate == pdf or candidate in results.values() or candidate.exists():
            raise FileExistsError(f"Output name clashes with another PDF: {candidate.name}")
        results[language] = candidate
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf", type=Path, help="French text-based PDF")
    parser.add_argument("--keep", action="store_true", help="Keep source PDF and intermediate working directory")
    parser.add_argument("--extract-only", action="store_true", help="No API, render, or deletion")
    parser.add_argument("--render-only", action="store_true", help="Use existing translated Markdown; never delete source")
    parser.add_argument("--work-dir", type=Path, help="Override intermediate location, default cache/<stem>.work beside this script")
    args = parser.parse_args()
    pdf = args.pdf.resolve()
    if not pdf.is_file() or pdf.suffix.lower() != ".pdf":
        parser.error("provide an existing PDF file")
    work = args.work_dir.resolve() if args.work_dir else Path(__file__).resolve().parent / "cache" / (pdf.stem + ".work")
    if work == pdf.parent or work == pdf or work in pdf.parents or pdf in work.parents:
        parser.error("work directory must not be the PDF, its parent, or inside the PDF")
    if not args.keep and not args.extract_only and not args.render_only and args.work_dir:
        parser.error("custom --work-dir requires --keep to prevent accidental directory deletion")
    outputs = {}
    try:
        if args.render_only:
            manifest = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
            if Path(manifest["source"]).resolve() != pdf:
                raise ValueError("Work directory belongs to another source PDF")
        else:
            print("Extracting without AI...", flush=True)
            _, manifest = extract(pdf, work)
            print(f"  Pages: {manifest['pages']}; assets: {len(manifest['assets'])}; margin items removed: {len(manifest['excluded'])}")
        if args.extract_only:
            print(f"Extraction available in {work}; source unchanged")
            return 0
        if not args.render_only:
            key, model, url = api_config()
            source = (work / "source.fr.txt").read_text(encoding="utf-8")
            for language in ("english", "chinese"):
                translate(source, work, language, key, model, url)
        outputs = output_paths(pdf, work)
        for language, output in outputs.items():
            print(f"Rendering {language}...", flush=True)
            render(work / f"translated.{language}.md", manifest, work, output, language)
        if args.keep or args.render_only:
            print("Kept original and cache working files.")
        else:
            # Never recursively remove user-supplied directories. Keep the original
            # if the intermediate folder cannot be removed safely.
            default_work = Path(__file__).resolve().parent / "cache" / (pdf.stem + ".work")
            if work != default_work:
                raise ValueError("Cleanup requires default cache directory; use --keep with --work-dir")
            shutil.rmtree(work)
            pdf.unlink()
            print("Deleted intermediate assets/Markdown and original after validating both PDFs.")
        print("Done: " + ", ".join(str(path) for path in outputs.values()))
        return 0
    except Exception as exc:
        print(f"FAILED: {exc}\nSource was not deliberately deleted; inspect {work}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
