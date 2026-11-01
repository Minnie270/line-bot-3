"""在終端機和本機 Ollama 模型聊天，不需要 LINE 金鑰或額外套件。"""

import json
import os
import time
import urllib.error
import urllib.request


MODEL = os.getenv("MODEL", "qwen3:4b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
MAX_HISTORY_TURNS = 5

SYSTEM_PROMPT = (
    "你是一個親切、簡潔的台灣繁體中文助手。"
    "先直接回答重點；不知道或不確定時要坦白說。"
    "你沒有即時網路，不能查詢最新資訊。"
)


def ask_model(question, history):
    """把問題和最近幾組對話送到本機 Ollama。"""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    for old_question, old_answer in history:
        messages.append({"role": "user", "content": old_question})
        messages.append({"role": "assistant", "content": old_answer})

    messages.append({"role": "user", "content": question})
    data = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "keep_alive": "30m",
        "options": {"num_ctx": 4096},
    }
    request = urllib.request.Request(
        f"{OLLAMA_URL.rstrip('/')}/api/chat",
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=600) as response:
        result = json.loads(response.read().decode("utf-8"))

    return result.get("message", {}).get("content", "").strip()


def main():
    """在終端機讀取問題並顯示本機模型的回答。"""
    print("LINE Bot 本地模型版（模擬模式，不會連 LINE）")
    print(f"使用模型：{MODEL}")
    print("輸入問題後按 Enter；輸入 quit 離開。\n")

    history = []

    while True:
        try:
            question = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n模擬結束。")
            break

        if question.lower() in {"quit", "exit", "離開", "結束"}:
            print("模擬結束。")
            break
        if not question:
            continue

        start_time = time.time()
        try:
            answer = ask_model(question, history)
            if not answer:
                answer = "抱歉，這次沒有產生文字回答。"
        except urllib.error.URLError:
            answer = "找不到 Ollama。請先打開 Ollama，再重新執行這個程式。"
        except Exception as error:
            answer = f"發生錯誤：{error}"

        elapsed = time.time() - start_time
        print(f"bot：{answer}")
        print(f"（本機模型 {MODEL}，約 {elapsed:.1f} 秒）\n")

        if answer.startswith("發生錯誤：") or answer.startswith("找不到 Ollama"):
            continue

        history.append((question, answer))
        history = history[-MAX_HISTORY_TURNS:]


if __name__ == "__main__":
    main()
