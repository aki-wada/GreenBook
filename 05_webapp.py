"""
GreenBook RAG Web Application
- FastAPI + Jinja2 テンプレート
- SSE (Server-Sent Events) でストリーミング回答
- 04_query.py の検索ロジックを再利用

Usage:
  python 05_webapp.py                  # http://localhost:8000
  python 05_webapp.py --port 9000      # ポート指定
"""
import sys
import json
import time
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
import uvicorn

from config import (
    LM_STUDIO_BASE_URL, LM_STUDIO_API_KEY,
    LM_STUDIO_MODEL_EN, LM_STUDIO_MODEL_JA, LM_STUDIO_MODEL_DEFAULT,
    MAX_CONTEXT_TOKENS, MAX_OUTPUT_TOKENS, TEMPERATURE,
)

# 04_query.py の関数を再利用
from query_core import (
    search, build_context_with_budget, detect_language,
    estimate_tokens, get_openai_client, get_embedding_model, get_collection,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="GreenBook RAG")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


# --- 起動時にモデルをプリロード ---

@app.on_event("startup")
async def startup():
    logger.info("Pre-loading embedding model and VectorDB...")
    get_embedding_model()
    get_collection()
    logger.info("Ready.")


# --- ページ ---

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# --- API ---

@app.post("/api/query")
async def api_query(request: Request):
    body = await request.json()
    question = body.get("question", "").strip()
    if not question:
        return {"error": "Empty question"}

    def generate():
        start = time.time()

        # 1. 検索
        lang = detect_language(question)
        hits = search(question)
        context, used_hits = build_context_with_budget(hits, question)

        sources = [
            {
                "page": h["page"],
                "score": round(1 - h["distance"], 3),
                "preview": h["text"][:120].replace("\n", " "),
            }
            for h in used_hits
        ]

        yield f"event: sources\ndata: {json.dumps({'sources': sources, 'chunks_used': len(used_hits)})}\n\n"

        # 2. ストリーミング回答生成
        model_name = LM_STUDIO_MODEL_JA if lang == "ja" else LM_STUDIO_MODEL_EN
        system_prompt = (
            "You are a radiology assistant specializing in the content of "
            "Radiology Review Manual (GreenBook 7th Edition). "
            "Answer questions based ONLY on the provided reference material. "
            "Always cite page numbers in your answer. "
            "If the reference does not contain relevant information, say so clearly. "
            "Answer in the same language as the question. "
            "When answering in Japanese, use standard radiology terminology "
            "while keeping English technical terms where conventionally used. "
            "Format your answer using Markdown: use **bold** for emphasis, "
            "headings (##) for sections, bullet lists for enumerations, "
            "and Markdown tables (| col1 | col2 |) when presenting structured data."
        )
        user_prompt = (
            f"## Reference Material\n\n{context}\n\n---\n\n"
            f"## Question\n{question}\n\n"
            f"Please answer based on the reference material above, citing page numbers."
        )

        client = get_openai_client()
        try:
            stream = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=TEMPERATURE,
                max_tokens=MAX_OUTPUT_TOKENS,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield f"event: token\ndata: {json.dumps({'text': delta.content})}\n\n"

        except Exception as e:
            logger.warning(f"{model_name} failed ({e}), falling back to {LM_STUDIO_MODEL_DEFAULT}")
            try:
                stream = client.chat.completions.create(
                    model=LM_STUDIO_MODEL_DEFAULT,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=TEMPERATURE,
                    max_tokens=MAX_OUTPUT_TOKENS,
                    stream=True,
                )
                for chunk in stream:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield f"event: token\ndata: {json.dumps({'text': delta.content})}\n\n"
                model_name = LM_STUDIO_MODEL_DEFAULT
            except Exception as e2:
                yield f"event: error\ndata: {json.dumps({'error': str(e2)})}\n\n"
                return

        elapsed = round(time.time() - start, 1)
        yield f"event: done\ndata: {json.dumps({'model': model_name, 'language': lang, 'elapsed': elapsed})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/health")
async def health():
    try:
        client = get_openai_client()
        models = client.models.list()
        model_ids = [m.id for m in models.data]
        collection = get_collection()
        return {
            "status": "ok",
            "lm_studio": True,
            "models": model_ids,
            "vectordb_chunks": collection.count(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


if __name__ == "__main__":
    port = 8321
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--port" and i + 1 < len(sys.argv) - 1:
            port = int(sys.argv[i + 2])

    print(f"\n  GreenBook RAG Web → http://localhost:{port}\n")
    uvicorn.run(app, host="0.0.0.0", port=port)
