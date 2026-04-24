"""Text extraction from PDF, EPUB, DOCX, FB2, HTML, TXT and lang detection."""
import io
import zipfile
from concurrent.futures import ThreadPoolExecutor

import structlog

logger = structlog.get_logger()

_THREAD_POOL = ThreadPoolExecutor(max_workers=4)


def extract_text_sync(data: bytes, filename: str, mime: str = "") -> str:
    """CPU-bound text extraction — run in thread pool via run_in_executor."""
    fname = filename.lower()
    if fname.endswith(".pdf") or "pdf" in mime:
        return _extract_pdf(data)
    if fname.endswith(".docx") or "wordprocessingml" in mime:
        return _extract_docx(data)
    if fname.endswith(".epub") or "epub" in mime:
        return _extract_epub(data)
    if fname.endswith(".fb2") or "fb2" in mime:
        return _extract_fb2(data)
    if fname.endswith((".html", ".htm")) or "html" in mime:
        return _extract_html(data)
    return _safe_decode(data)


def detect_lang(text: str) -> str:
    """Return 'ru', 'en', or 'other' based on character heuristics + langdetect."""
    if not text:
        return "ru"
    sample = text[:1000]
    cyrillic = sum(1 for c in sample if "Ѐ" <= c <= "ӿ")
    ratio = cyrillic / max(len(sample), 1)
    if ratio > 0.15:
        return "ru"
    try:
        from langdetect import detect
        return detect(sample)
    except Exception:
        return "en"


def _extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:
        raise RuntimeError(f"PDF extract error: {e}") from e


def _extract_docx(data: bytes) -> str:
    try:
        from docx import Document
        doc = Document(io.BytesIO(data))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        raise RuntimeError(f"DOCX extract error: {e}") from e


def _extract_epub(data: bytes) -> str:
    try:
        from bs4 import BeautifulSoup
        texts = []
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            opf_path = None
            if "META-INF/container.xml" in zf.namelist():
                container = BeautifulSoup(zf.read("META-INF/container.xml"), "xml")
                rootfile = container.find("rootfile")
                if rootfile:
                    opf_path = rootfile.get("full-path")

            ordered_items: list[str] = []
            if opf_path:
                try:
                    opf = BeautifulSoup(zf.read(opf_path), "xml")
                    manifest = {item["id"]: item["href"] for item in opf.find_all("item")}
                    base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
                    for itemref in opf.find_all("itemref"):
                        href = manifest.get(itemref.get("idref", ""), "")
                        if href:
                            ordered_items.append(base + href)
                except Exception:
                    pass

            if not ordered_items:
                ordered_items = [n for n in zf.namelist() if n.endswith((".xhtml", ".html", ".htm"))]

            for item in ordered_items:
                if item not in zf.namelist():
                    continue
                soup = BeautifulSoup(zf.read(item), "lxml")
                for tag in soup(["script", "style", "nav"]):
                    tag.decompose()
                chunk = soup.get_text(separator="\n", strip=True)
                if chunk:
                    texts.append(chunk)

        return "\n\n".join(texts)
    except Exception as e:
        raise RuntimeError(f"EPUB extract error: {e}") from e


def _extract_fb2(data: bytes) -> str:
    try:
        from bs4 import BeautifulSoup
        text = _safe_decode(data)
        soup = BeautifulSoup(text, "xml")
        parts = []
        for body in soup.find_all("body"):
            for tag in body.find_all(["binary", "image"]):
                tag.decompose()
            parts.append(body.get_text(separator="\n", strip=True))
        return "\n\n".join(p for p in parts if p)
    except Exception as e:
        raise RuntimeError(f"FB2 extract error: {e}") from e


def _extract_html(data: bytes) -> str:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(data, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)
    except Exception as e:
        raise RuntimeError(f"HTML extract error: {e}") from e


def _safe_decode(data: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")
