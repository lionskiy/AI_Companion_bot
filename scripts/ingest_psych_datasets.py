"""
Ingestion pipeline for psychology/therapy datasets into knowledge_psych collection.

Usage:
    # All available datasets (with translation EN→RU):
    python scripts/ingest_psych_datasets.py --translate

    # Specific dataset:
    python scripts/ingest_psych_datasets.py --dataset cbt_bench --translate
    python scripts/ingest_psych_datasets.py --dataset reccon --translate
    python scripts/ingest_psych_datasets.py --dataset caiti --translate
    python scripts/ingest_psych_datasets.py --dataset kaggle_mental --file path/to/conversations.csv

    # Without translation (raw English, still searchable):
    python scripts/ingest_psych_datasets.py --dataset cbt_bench

Supported datasets:
    cbt_bench   — CBT-Bench Q&A (HuggingFace, auto-download)
    reccon      — RECCON emotion cause (GitHub, auto-download)
    caiti       — CaiTI therapy dialogs (GitHub, requires clone or --file)
    kaggle_mental — Kaggle mental health conversations (requires --file)

Requirements: pip install openai qdrant-client httpx
"""

import argparse
import asyncio
import csv
import io
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Iterator
from uuid import uuid4

import httpx

# ── Config ─────────────────────────────────────────────────────────────────────

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:19104")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
EMBED_MODEL = "text-embedding-3-large"
TRANSLATE_MODEL = "gpt-4o-mini"
COLLECTION = "knowledge_psych"
CHUNK_MAX = 900
BATCH_SIZE = 5  # embeddings per batch (rate limit safety)

# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Ingest psychology datasets into Qdrant KB")
    parser.add_argument("--dataset", choices=["cbt_bench", "reccon", "caiti", "kaggle_mental", "all"], default="all")
    parser.add_argument("--file", help="Local file path (for datasets that need manual download)")
    parser.add_argument("--translate", action="store_true", help="Translate EN→RU via LLM before embedding")
    parser.add_argument("--limit", type=int, default=0, help="Max entries per dataset (0 = all)")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no upload")
    args = parser.parse_args()

    if not OPENAI_API_KEY:
        print("ERROR: Set OPENAI_API_KEY environment variable")
        sys.exit(1)

    asyncio.run(run(args))


async def run(args):
    datasets_to_run = (
        ["cbt_bench", "reccon", "caiti", "kaggle_mental"]
        if args.dataset == "all"
        else [args.dataset]
    )

    total = 0
    for ds in datasets_to_run:
        print(f"\n{'='*60}")
        print(f"Dataset: {ds}")
        print(f"{'='*60}")
        try:
            count = await ingest_dataset(ds, args)
            total += count
            print(f"✓ {ds}: {count} entries added")
        except SkipDataset as e:
            print(f"⚠ {ds} skipped: {e}")
        except Exception as e:
            print(f"✗ {ds} failed: {e}")
            import traceback; traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"TOTAL: {total} entries added to {COLLECTION}")


class SkipDataset(Exception):
    pass


async def ingest_dataset(name: str, args) -> int:
    if name == "cbt_bench":
        return await ingest_cbt_bench(args)
    if name == "reccon":
        return await ingest_reccon(args)
    if name == "caiti":
        return await ingest_caiti(args)
    if name == "kaggle_mental":
        return await ingest_kaggle_mental(args)
    raise ValueError(f"Unknown dataset: {name}")


# ── CBT-Bench ─────────────────────────────────────────────────────────────────

async def ingest_cbt_bench(args) -> int:
    """
    CBT-Bench: Q&A dataset based on cognitive behavioral therapy.
    Source: https://huggingface.co/datasets/Psychotherapy-LLM/CBT-Bench
    Auto-downloads qa_seed.json from HuggingFace.
    """
    url = "https://huggingface.co/datasets/Psychotherapy-LLM/CBT-Bench/resolve/main/qa_seed.json"
    print(f"Downloading {url}...")
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    data = resp.json()
    print(f"Loaded {len(data)} CBT Q&A entries")

    entries = []
    for item in data:
        q = item.get("question") or item.get("Q") or item.get("input") or ""
        a = item.get("answer") or item.get("A") or item.get("output") or item.get("response") or ""
        if not q or not a:
            # Try to find any text fields
            vals = list(item.values())
            if len(vals) >= 2:
                q, a = str(vals[0]), str(vals[1])
        if q and a and len(a) > 30:
            entries.append({
                "topic": f"КПТ вопрос-ответ: {q[:60]}",
                "text": f"Вопрос: {q}\n\nОтвет: {a}",
                "source": "CBT-Bench",
            })

    if args.limit:
        entries = entries[:args.limit]

    print(f"Prepared {len(entries)} entries")
    return await upload_entries(entries, args.translate, args.dry_run, "КПТ")


# ── RECCON ────────────────────────────────────────────────────────────────────

async def ingest_reccon(args) -> int:
    """
    RECCON: Recognizing Emotion Cause in Conversations.
    Source: https://github.com/declare-lab/RECCON
    Downloads test data (emotion annotations on conversations).
    """
    # Use the publicly available test split
    base = "https://raw.githubusercontent.com/declare-lab/RECCON/main/data/original_annotation"
    files = [
        ("dailydialog_test.json", "DailyDialog"),
        ("iemocap_test.json", "IEMOCAP"),
    ]

    all_entries = []
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for fname, source_name in files:
            try:
                resp = await client.get(f"{base}/{fname}")
                if resp.status_code != 200:
                    print(f"  {fname}: HTTP {resp.status_code}, skipping")
                    continue
                data = resp.json()
                entries = _parse_reccon(data, source_name)
                print(f"  {fname}: {len(entries)} entries")
                all_entries.extend(entries)
            except Exception as e:
                print(f"  {fname}: error {e}")

    if not all_entries:
        raise SkipDataset("No RECCON files could be downloaded")

    if args.limit:
        all_entries = all_entries[:args.limit]

    print(f"Prepared {len(all_entries)} RECCON entries")
    return await upload_entries(all_entries, args.translate, args.dry_run, "Эмоции")


def _parse_reccon(data: dict, source: str) -> list[dict]:
    entries = []
    for conv_id, utterances in data.items():
        # Each conversation: list of {text, speaker, emotion, expanded_emotion_cause_evidence}
        if not isinstance(utterances, list):
            continue
        # Extract emotion-cause pairs
        for utt in utterances:
            text = utt.get("text") or utt.get("utterance") or ""
            emotion = utt.get("emotion", "")
            causes = utt.get("expanded_emotion_cause_evidence") or []
            if not text or emotion in ("", "neutral", "no-context"):
                continue
            cause_texts = [c.get("text", "") for c in causes if isinstance(c, dict)]
            cause_str = " | ".join(c for c in cause_texts if c)
            if emotion and text:
                body = f"Высказывание: {text}\nЭмоция: {emotion}"
                if cause_str:
                    body += f"\nПричина: {cause_str}"
                entries.append({
                    "topic": f"Эмоция в диалоге: {emotion}",
                    "text": body,
                    "source": f"RECCON/{source}",
                })
    return entries


# ── CaiTI ─────────────────────────────────────────────────────────────────────

async def ingest_caiti(args) -> int:
    """
    CaiTI: Conversational AI for Therapy Interactions.
    Source: https://github.com/Columbia-ICSL/CaiTI_dataset
    Requires manual clone or --file pointing to the JSON data.

    If --file not given, tries to download from GitHub directly.
    """
    if args.file and Path(args.file).exists():
        raw = Path(args.file).read_text(encoding="utf-8")
        data = json.loads(raw)
        entries = _parse_caiti(data)
        print(f"Loaded from file: {len(entries)} entries")
    else:
        # Try to fetch the main dataset file
        urls_to_try = [
            "https://raw.githubusercontent.com/Columbia-ICSL/CaiTI_dataset/main/data/caiti_dataset.json",
            "https://raw.githubusercontent.com/Columbia-ICSL/CaiTI_dataset/main/dataset.json",
            "https://raw.githubusercontent.com/Columbia-ICSL/CaiTI_dataset/main/CaiTI_dataset.json",
        ]
        data = None
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            for url in urls_to_try:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        print(f"Downloaded from {url}")
                        break
                except Exception:
                    continue

        if data is None:
            raise SkipDataset(
                "CaiTI not auto-downloadable. Clone the repo and pass "
                "--file path/to/data.json"
            )
        entries = _parse_caiti(data)

    if args.limit:
        entries = entries[:args.limit]

    print(f"Prepared {len(entries)} CaiTI entries")
    return await upload_entries(entries, args.translate, args.dry_run, "Терапия")


def _parse_caiti(data) -> list[dict]:
    entries = []
    items = data if isinstance(data, list) else data.get("data", [data])
    for item in items:
        if isinstance(item, dict):
            # Look for therapist/client exchanges
            turns = item.get("turns") or item.get("conversation") or item.get("messages") or []
            if not turns and "therapist" in item:
                turns = [{"role": "therapist", "text": item["therapist"]},
                         {"role": "client", "text": item.get("client", "")}]
            if turns:
                dialog_text = "\n".join(
                    f"{t.get('role','?').capitalize()}: {t.get('text', t.get('content',''))}"
                    for t in turns if t.get("text") or t.get("content")
                )
                if len(dialog_text) > 100:
                    topic_hint = item.get("topic") or item.get("issue") or item.get("label") or "терапевтический диалог"
                    entries.append({
                        "topic": f"Терапевтический диалог: {str(topic_hint)[:60]}",
                        "text": dialog_text[:1800],
                        "source": "CaiTI",
                    })
    return entries


# ── Kaggle Mental Health Conversations ────────────────────────────────────────

async def ingest_kaggle_mental(args) -> int:
    """
    Human and LLM Mental Health Conversations.
    Source: https://www.kaggle.com/datasets/birdy654/human-and-llm-mental-health-conversations
    Requires manual download (Kaggle API or web UI), then pass --file.

    CSV format: typically has 'question'/'answer' or 'Context'/'Response' columns.
    """
    if not args.file:
        raise SkipDataset(
            "Kaggle dataset requires manual download.\n"
            "  1. Download from: https://www.kaggle.com/datasets/birdy654/human-and-llm-mental-health-conversations\n"
            "  2. Run: python scripts/ingest_psych_datasets.py --dataset kaggle_mental --file path/to/data.csv"
        )

    path = Path(args.file)
    if not path.exists():
        raise SkipDataset(f"File not found: {path}")

    entries = []
    if path.suffix.lower() == ".csv":
        entries = _parse_mental_csv(path)
    elif path.suffix.lower() in (".json", ".jsonl"):
        entries = _parse_mental_json(path)
    else:
        raise SkipDataset(f"Unsupported file format: {path.suffix}")

    if args.limit:
        entries = entries[:args.limit]

    print(f"Prepared {len(entries)} Kaggle mental health entries")
    return await upload_entries(entries, args.translate, args.dry_run, "Психическое здоровье")


def _parse_mental_csv(path: Path) -> list[dict]:
    entries = []
    with open(path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            keys = {k.lower().strip(): v for k, v in row.items()}
            q = keys.get("question") or keys.get("context") or keys.get("input") or keys.get("prompt") or ""
            a = keys.get("answer") or keys.get("response") or keys.get("output") or keys.get("reply") or ""
            if not q:
                # Fallback: use first two non-empty columns
                vals = [v.strip() for v in row.values() if v.strip()]
                if len(vals) >= 2:
                    q, a = vals[0], vals[1]
            if q and a and len(a) > 30:
                entries.append({
                    "topic": f"Психическое здоровье: {q[:60]}",
                    "text": f"Запрос: {q}\n\nОтвет: {a}",
                    "source": "Kaggle/MentalHealth",
                })
    return entries


def _parse_mental_json(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # JSONL
        data = [json.loads(line) for line in raw.splitlines() if line.strip()]
    items = data if isinstance(data, list) else [data]
    entries = []
    for item in items:
        q = item.get("question") or item.get("context") or item.get("input") or ""
        a = item.get("answer") or item.get("response") or item.get("output") or ""
        if q and a and len(a) > 30:
            entries.append({
                "topic": f"Психическое здоровье: {q[:60]}",
                "text": f"Запрос: {q}\n\nОтвет: {a}",
                "source": "Kaggle/MentalHealth",
            })
    return entries


# ── LLM helpers ───────────────────────────────────────────────────────────────

async def translate_to_russian(text: str, client: httpx.AsyncClient) -> str:
    """Translate text EN→RU using OpenAI. Returns original if translation fails."""
    # Quick check — if already mostly Cyrillic, skip
    cyrillic = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    if cyrillic / max(len(text), 1) > 0.3:
        return text

    payload = {
        "model": TRANSLATE_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты переводчик. Переведи текст на русский язык, сохранив структуру и форматирование. "
                    "Психологические термины переводи точно. Верни ТОЛЬКО перевод, без комментариев."
                ),
            },
            {"role": "user", "content": text[:3000]},
        ],
        "max_tokens": 1500,
        "temperature": 0.1,
    }
    try:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"    Translation failed: {e}")
        return text


async def embed_text(text: str, client: httpx.AsyncClient) -> list[float]:
    payload = {
        "model": EMBED_MODEL,
        "input": text[:8000],
    }
    resp = await client.post(
        "https://api.openai.com/v1/embeddings",
        json=payload,
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


# ── Upload pipeline ───────────────────────────────────────────────────────────

async def upload_entries(
    entries: list[dict],
    translate: bool,
    dry_run: bool,
    category: str,
) -> int:
    if dry_run:
        print(f"[DRY RUN] Would upload {len(entries)} entries")
        for e in entries[:3]:
            print(f"  Topic: {e['topic']}")
            print(f"  Text: {e['text'][:120]}...")
        return 0

    from qdrant_client import QdrantClient
    from qdrant_client.models import PointStruct

    qdrant = QdrantClient(url=QDRANT_URL)

    added = 0
    async with httpx.AsyncClient() as http:
        for i, entry in enumerate(entries):
            topic = entry["topic"]
            text = entry["text"]

            # Translate if requested
            if translate:
                print(f"  [{i+1}/{len(entries)}] Translating: {topic[:50]}...")
                text = await translate_to_russian(text, http)
                topic_parts = topic.split(":", 1)
                if len(topic_parts) == 2:
                    prefix = topic_parts[0]
                    eng_hint = topic_parts[1].strip()
                    # Don't translate topic separately — use translated text first line
                    first_line = text.split("\n")[0][:60]
                    topic = f"{prefix}: {first_line}"

                await asyncio.sleep(0.3)  # rate limit

            # Embed
            try:
                print(f"  [{i+1}/{len(entries)}] Embedding: {topic[:50]}...")
                embedding = await embed_text(f"{topic}\n{text}", http)
            except Exception as e:
                print(f"  Embedding failed: {e}, skipping")
                await asyncio.sleep(2)
                continue

            # Upload to Qdrant
            point_id = str(uuid4())
            qdrant.upsert(
                collection_name=COLLECTION,
                points=[PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "topic": topic,
                        "text": text,
                        "collection": COLLECTION,
                        "source": entry.get("source", ""),
                        "category": category,
                    },
                )],
            )
            added += 1

            # Rate limit: pause every BATCH_SIZE
            if added % BATCH_SIZE == 0:
                print(f"  Progress: {added}/{len(entries)}")
                await asyncio.sleep(1)

    return added


if __name__ == "__main__":
    main()
