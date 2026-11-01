import os
import json
import urllib.request
from flask import Flask, request, abort
from dotenv import load_dotenv
from google import genai
from google.genai import types

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
    FlexMessage,
    FlexContainer,
)
from linebot.v3.webhooks import MessageEvent, StickerMessageContent, TextMessageContent

# 載入 .env 設定
load_dotenv()
from ledger import handle as handle_ledger

app = Flask(__name__)

# 讀取金鑰
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_BACKEND = os.getenv("MODEL_BACKEND", "gemini").lower()
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")

handler = WebhookHandler(LINE_CHANNEL_SECRET)
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if MODEL_BACKEND == "gemini" else None

# 以 LINE 使用者 ID 分開保存最近完成的對話；每組包含一則提問與一則回答。
MAX_HISTORY_TURNS = 5
conversation_history = {}


@app.route("/callback", methods=["POST"])
def callback():
    """接收 LINE Webhook 請求"""
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    """當收到使用者傳來的文字時"""
    user_text = event.message.text
    user_id = getattr(event.source, "user_id", None)
    print(f"📩 收到 LINE 訊息: {user_text}")

    # 記帳由固定規則處理，與 AI 問答彼此獨立。
    ledger_reply = handle_ledger(user_id, user_text) if user_id else None
    if ledger_reply:
        send_reply(event, ledger_reply)
        return

    # 1. 使用本地 Ollama 或 Google Gemini 產生回覆
    ai_reply = None
    history = conversation_history.get(user_id, []) if user_id else []
    if MODEL_BACKEND == "ollama":
        try:
            messages = [{
                "role": "system",
                "content": "你是一個親切的繁體中文 AI 助手，請用台灣習慣的口吻簡潔回答。你是在本地電腦運作，不能查詢即時網路資訊。",
            }]
            for previous_user_text, previous_ai_reply in history:
                messages.extend([
                    {"role": "user", "content": previous_user_text},
                    {"role": "assistant", "content": previous_ai_reply},
                ])
            messages.append({"role": "user", "content": user_text})
            payload = json.dumps({"model": OLLAMA_MODEL, "messages": messages, "stream": False}).encode("utf-8")
            req = urllib.request.Request(
                f"{OLLAMA_URL.rstrip('/')}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=180) as result:
                response = json.loads(result.read().decode("utf-8"))
            ai_reply = response.get("message", {}).get("content")
            if not ai_reply:
                ai_reply = "抱歉，這次沒有產生可顯示的文字回覆。"
        except Exception as e:
            print(f"⚠️ 本地模型暫時無法使用 ({e})")
    else:
        contents = []
        for previous_user_text, previous_ai_reply in history:
            contents.extend([
                types.Content(role="user", parts=[types.Part.from_text(text=previous_user_text)]),
                types.Content(role="model", parts=[types.Part.from_text(text=previous_ai_reply)]),
            ])
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_text)]))

        candidate_models = ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash"]
        for model_name in candidate_models:
            try:
                response = gemini_client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=(
                            "你是一個親切的繁體中文 AI 助手，請用台灣習慣的口吻簡潔回答。"
                            "回答最新消息或需要查證的資訊時，請使用 Google 搜尋並根據搜尋結果回答。"
                        ),
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                    ),
                )
                ai_reply = response.text
                if not ai_reply:
                    ai_reply = "抱歉，這次沒有產生可顯示的文字回覆。"

                sources = []
                candidates = response.candidates or []
                if candidates and candidates[0].grounding_metadata:
                    chunks = candidates[0].grounding_metadata.grounding_chunks or []
                    for chunk in chunks:
                        web_source = getattr(chunk, "web", None)
                        uri = getattr(web_source, "uri", None) if web_source else None
                        title = getattr(web_source, "title", None) if web_source else None
                        if uri and uri not in [source[1] for source in sources]:
                            sources.append((title or uri, uri))
                if sources:
                    ai_reply += "\n\n資料來源：\n" + "\n".join(
                        f"{index}. {title}\n{uri}"
                        for index, (title, uri) in enumerate(sources[:3], start=1)
                    )
                print(f"🤖 [{model_name}] 回覆成功: {ai_reply}")
                break
            except Exception as e:
                print(f"⚠️ {model_name} 暫時忙線或錯誤 ({e})，嘗試下一個備用模型...")

    if ai_reply and user_id:
        updated_history = history + [(user_text, ai_reply)]
        conversation_history[user_id] = updated_history[-MAX_HISTORY_TURNS:]

    if not ai_reply:
        ai_reply = "抱歉，目前 AI 助手暫時無法使用，請稍候再傳送一次試試看！"

    # 將 AI 回覆傳回給 LINE 使用者
    send_reply(event, ai_reply)


@handler.add(MessageEvent, message=StickerMessageContent)
def handle_sticker(event):
    """Treat any sticker as a request to show the text bookkeeping menu."""
    user_id = getattr(event.source, "user_id", None)
    if not user_id:
        return
    send_reply(event, handle_ledger(user_id, "記帳"))


def send_reply(event, message):
    try:
        if isinstance(message, dict) and message.get("type") == "flex":
            line_message = FlexMessage(
                alt_text=message["altText"],
                contents=FlexContainer.from_dict(message["contents"]),
            )
        else:
            line_message = TextMessage(text=message)
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[line_message],
                )
            )
        print("✅ 成功發送回覆至 LINE！")
    except Exception as e:
        print(f"❌ LINE 訊息發送失敗: {e}")


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"機器人伺服器啟動於 http://127.0.0.1:{port}")
    # 本機模式只聽自己的電腦；部署到 Render 時由 gunicorn 設定服務位址。
    app.run(host="127.0.0.1", port=port)
