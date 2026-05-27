from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import chat, conversations

app = FastAPI(title="Ollive Chatbot API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(conversations.router)
app.include_router(chat.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "chatbot-api"}
