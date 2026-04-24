"""Text chunking — paragraph-aware splitter matching existing implementation."""
import re


def chunk_text(text: str, max_chars: int = 900, overlap: int = 100) -> list[str]:
    """Split text into overlapping chunks, respecting paragraph boundaries."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        # Large paragraph — always split it immediately, never merge into current
        if len(para) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for sent in _split_sentences(para, max_chars):
                chunks.append(sent)
            continue
        # Para fits — try to append to current chunk
        if not current or len(current) + len(para) + 2 <= max_chars:
            current = (current + "\n\n" + para).strip() if current else para
        else:
            chunks.append(current)
            tail = current[-overlap:] if len(current) > overlap else current
            # Start new chunk: try tail+para, else just para (para always ≤ max_chars)
            candidate = (tail + "\n\n" + para).strip()
            current = candidate if len(candidate) <= max_chars else para
    if current:
        chunks.append(current)
    return [c for c in chunks if len(c) >= 30]


def _split_sentences(text: str, max_chars: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks, buf = [], ""
    for s in sentences:
        if len(buf) + len(s) + 1 <= max_chars:
            buf = (buf + " " + s).strip() if buf else s
        else:
            if buf:
                chunks.append(buf)
            buf = s[:max_chars]
    if buf:
        chunks.append(buf)
    return [c for c in chunks if c]
