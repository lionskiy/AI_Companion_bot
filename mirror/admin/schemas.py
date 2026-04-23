from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class AppConfigEntry(BaseModel):
    key: str
    value: str


class AppConfigUpdate(BaseModel):
    value: str


class UserAdminView(BaseModel):
    user_id: UUID
    username: Optional[str] = None
    full_name: Optional[str] = None
    tg_username: Optional[str] = None
    is_premium: bool = False
    tier: str
    daily_ritual_enabled: bool
    created_at: str


class QuotaConfigView(BaseModel):
    tier: str
    daily_messages: int
    tarot_per_day: int
    astrology_per_day: int


class QuotaConfigUpdate(BaseModel):
    daily_messages: Optional[int] = None
    tarot_per_day: Optional[int] = None
    astrology_per_day: Optional[int] = None


class LLMRoutingView(BaseModel):
    task_kind: str
    tier: str
    provider_id: str
    model_id: str
    fallback_chain: list[dict]
    max_tokens: int
    temperature: float


class LLMRoutingUpdate(BaseModel):
    provider_id: Optional[str] = None
    model_id: Optional[str] = None
    fallback_chain: Optional[list[dict]] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None


class StatsView(BaseModel):
    total_users: int
    active_today: int
    messages_today: int
    rituals_sent_today: int
    tarot_today: int = 0
    astrology_today: int = 0
    chat_today: int = 0


class KBAddRequest(BaseModel):
    collection: str
    topic: str
    text: str


class KBCreateCollectionRequest(BaseModel):
    name: str          # e.g. "knowledge_dreams"
    description: str = ""


class KBStatsEntry(BaseModel):
    collection: str
    count: int


class KBEntryPreview(BaseModel):
    point_id: str
    topic: str
    text_preview: str


class KBIngestURLRequest(BaseModel):
    collection: str
    url: str
    topic: str = ""
    source_lang: str = "auto"  # auto | ru | en


class KBIngestResult(BaseModel):
    chunks_added: int
    collection: str
    source: str


class IngestJobView(BaseModel):
    id: str
    status: str          # running | done | error
    filename: str
    collection: str
    chunks_added: Optional[int] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str


class KBDatasetIngestRequest(BaseModel):
    collection: str
    dataset_url: str          # raw URL to JSON/JSONL/CSV file
    question_field: str = ""  # field name for question/context (auto-detect if empty)
    answer_field: str = ""    # field name for answer/response (auto-detect if empty)
    topic_prefix: str = ""    # prepend to all topics
    source_lang: str = "auto" # auto | ru | en — bilingual ingestion (original + translation)
    limit: int = 0            # max entries (0 = all)
