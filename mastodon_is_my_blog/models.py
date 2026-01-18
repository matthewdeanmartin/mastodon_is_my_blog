# --- Pydantic Models ---
from pydantic import BaseModel


class PostIn(BaseModel):
    status: str
    visibility: str = "public"
    spoiler_text: str | None = None


class EditIn(BaseModel):
    status: str
    spoiler_text: str | None = None
