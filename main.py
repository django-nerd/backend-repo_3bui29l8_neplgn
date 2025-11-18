import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
from datetime import datetime, timezone
from bson import ObjectId

from database import db

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Utility helpers

def to_str_id(doc: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(doc)
    if d.get("_id") is not None:
        d["id"] = str(d.pop("_id"))
    # Convert datetimes to isoformat strings
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


# Models
class CreateSessionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)

class PostMessageRequest(BaseModel):
    content: str = Field(..., min_length=1)


# Simple built-in explainer (no external API)

def generate_explanation(topic: str) -> str:
    topic_clean = topic.strip()
    sections = []
    sections.append(f"Quick summary\n- {topic_clean} in one sentence: [A clear, simple definition].")
    sections.append(
        "Key ideas\n- Concept 1: what it is and why it matters\n- Concept 2: how it connects\n- Concept 3: common pitfalls"
    )
    sections.append(
        "Step-by-step breakdown\n1) Start with the core definition\n2) Build an intuitive picture\n3) Add the formal detail\n4) Work through a tiny example\n5) Check your understanding"
    )
    sections.append(
        "Analogy\n- Imagine you're explaining it to a 10-year-old using a real-life story."
    )
    sections.append(
        "Worked example\n- Problem: a small, realistic question about the topic\n- Solution: show the steps with 1-2 short calculations or bullet points"
    )
    sections.append(
        "Common mistakes\n- Misunderstanding A\n- Misunderstanding B\n- Shortcut to avoid them"
    )
    sections.append(
        "Rapid self-quiz\n- Q1: ...\n- Q2: ...\n- Q3: ...\n(Answer in your head first, then check with notes)"
    )
    sections.append(
        "Mini study plan (20 minutes)\n- 5m: review summary + key ideas\n- 10m: do 2 tiny problems\n- 5m: reflect: what still feels fuzzy?"
    )

    header = f"Topic: {topic_clean}\n" + ("=" * (7 + len(topic_clean)))
    body = "\n\n".join(sections)
    return f"{header}\n\n{body}"


@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI Backend!"}

@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response


# Study tool API
@app.post("/api/sessions")
def create_session(req: CreateSessionRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    now = datetime.now(timezone.utc)
    data = {
        "title": req.title.strip(),
        "created_at": now,
        "updated_at": now,
    }
    inserted_id = db["studysession"].insert_one(data).inserted_id
    return {"id": str(inserted_id), "title": data["title"]}

@app.get("/api/sessions")
def list_sessions(limit: int = 20):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    items = db["studysession"].find({}).sort("updated_at", -1).limit(max(1, min(limit, 100)))
    return [to_str_id(doc) for doc in items]

@app.get("/api/sessions/{session_id}/messages")
def get_messages(session_id: str, limit: int = 100):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    cursor = db["message"].find({"session_id": session_id}).sort("created_at", 1).limit(max(1, min(limit, 500)))
    return [to_str_id(m) for m in cursor]

@app.post("/api/sessions/{session_id}/messages")
def post_message(session_id: str, req: PostMessageRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    now = datetime.now(timezone.utc)
    user_msg = {
        "session_id": session_id,
        "role": "user",
        "content": req.content.strip(),
        "created_at": now,
        "updated_at": now,
    }
    db["message"].insert_one(user_msg)

    assistant_text = generate_explanation(req.content)
    asst_msg = {
        "session_id": session_id,
        "role": "assistant",
        "content": assistant_text,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    db["message"].insert_one(asst_msg)

    # Touch session updated_at if it exists
    try:
        if ObjectId.is_valid(session_id):
            db["studysession"].update_one(
                {"_id": ObjectId(session_id)},
                {"$set": {"updated_at": datetime.now(timezone.utc)}}
            )
    except Exception:
        pass

    return {"messages": [to_str_id(user_msg), to_str_id(asst_msg)]}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
