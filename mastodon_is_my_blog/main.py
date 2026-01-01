from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from .masto_client import client
from .token_store import get_token, set_token  # same idea as before (sqlite row)

app = FastAPI()

class PostIn(BaseModel):
    status: str
    visibility: str = "public"
    spoiler_text: str | None = None

class EditIn(BaseModel):
    status: str
    spoiler_text: str | None = None

@app.get("/api/me")
async def me():
    token = await get_token()
    if not token:
        raise HTTPException(401, "Not connected")
    m = client(token)
    return m.account_verify_credentials()

@app.get("/api/posts")
async def posts(limit: int = 20):
    token = await get_token()
    if not token:
        raise HTTPException(401, "Not connected")
    m = client(token)
    me = m.account_verify_credentials()
    return m.account_statuses(me["id"], limit=limit, exclude_reblogs=True)

@app.post("/api/posts")
async def create_post(payload: PostIn):
    token = await get_token()
    if not token:
        raise HTTPException(401, "Not connected")
    m = client(token)
    if not payload.status.strip():
        raise HTTPException(400, "Empty post")
    return m.status_post(
        status=payload.status,
        visibility=payload.visibility,
        spoiler_text=payload.spoiler_text,
    )

@app.get("/api/posts/{status_id}")
async def get_post(status_id: str):
    token = await get_token()
    if not token:
        raise HTTPException(401, "Not connected")
    return client(token).status(status_id)

@app.get("/api/posts/{status_id}/comments")
async def comments(status_id: str):
    token = await get_token()
    if not token:
        raise HTTPException(401, "Not connected")
    # ancestors/descendants thread view :contentReference[oaicite:5]{index=5}
    return client(token).status_context(status_id)

@app.get("/api/posts/{status_id}/source")
async def source(status_id: str):
    token = await get_token()
    if not token:
        raise HTTPException(401, "Not connected")
    # editable source payload :contentReference[oaicite:6]{index=6}
    return client(token).status_source(status_id)

@app.post("/api/posts/{status_id}/edit")
async def edit(status_id: str, payload: EditIn):
    token = await get_token()
    if not token:
        raise HTTPException(401, "Not connected")
    m = client(token)
    if not payload.status.strip():
        raise HTTPException(400, "Empty post")

    # In-place edit (no delete/re-add) :contentReference[oaicite:7]{index=7}
    return m.status_update(
        status_id,
        status=payload.status,
        spoiler_text=payload.spoiler_text,
    )
