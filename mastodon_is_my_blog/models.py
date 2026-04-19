# --- Pydantic Models ---
from datetime import datetime

from pydantic import BaseModel


class PostIn(BaseModel):
    status: str
    visibility: str = "public"
    spoiler_text: str | None = None


class EditIn(BaseModel):
    status: str
    spoiler_text: str | None = None


class DraftNodeIn(BaseModel):
    client_id: str
    parent_client_id: str | None = None
    mode: str = "single"
    body: str = ""
    spoiler_text: str | None = None
    visibility: str = "public"


class DraftIn(BaseModel):
    title: str | None = None
    reply_to_status_id: str | None = None
    tree_json: str = "[]"
    editor_engine: str = "plain"
    language: str | None = None
    identity_id: int | None = None


class DraftOut(BaseModel):
    id: int
    meta_account_id: int
    identity_id: int | None
    reply_to_status_id: str | None
    title: str | None
    tree_json: str
    editor_engine: str
    language: str | None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    published_root_status_id: str | None

    model_config = {"from_attributes": True}


class PublishTreeIn(BaseModel):
    identity_id: int


class SplitNodeIn(BaseModel):
    client_id: str
    max_chars: int = 500
    add_counter: bool = False


class SplitChunk(BaseModel):
    body: str
    order: int


class SpellcheckIn(BaseModel):
    text: str
    language: str = "en-US"


class SpellcheckMatch(BaseModel):
    message: str
    offset: int
    length: int
    replacements: list[str]
    rule_id: str


class SpellcheckOut(BaseModel):
    matches: list[SpellcheckMatch]
