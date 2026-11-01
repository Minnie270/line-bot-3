"""Create and activate the LINE rich menu used by the bookkeeping bot.

Run once after installing requirements and setting LINE_CHANNEL_ACCESS_TOKEN:
    python3 setup_rich_menu.py
"""
import json
import os
import urllib.request
from io import BytesIO

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

load_dotenv()
TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
if not TOKEN:
    raise SystemExit("請先設定 LINE_CHANNEL_ACCESS_TOKEN")

W, H = 2500, 1686
image = Image.new("RGB", (W, H), "#f5f2eb")
draw = ImageDraw.Draw(image)
font_candidates = [
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "DejaVuSans.ttf",
]
font_path = next((path for path in font_candidates if os.path.exists(path)), "DejaVuSans.ttf")
font = ImageFont.truetype(font_path, 112)
labels = ["記支出", "記收入", "本月支出", "類別統計", "查餘額", "更多功能"]
colors = ["#d96c55", "#4d9b79", "#5279a8", "#8064a2", "#d29a3a", "#52616b"]
for i, label in enumerate(labels):
    row, col = divmod(i, 3)
    x0, y0 = col * W // 3, row * H // 2
    x1, y1 = (col + 1) * W // 3, (row + 1) * H // 2
    draw.rounded_rectangle((x0 + 24, y0 + 24, x1 - 24, y1 - 24), radius=42, fill=colors[i])
    box = draw.textbbox((0, 0), label, font=font)
    draw.text(((x0 + x1 - box[2]) / 2, (y0 + y1 - box[3]) / 2 - 10), label, fill="white", font=font)

buf = BytesIO()
image.save(buf, format="PNG")

def post(url, data, content_type="application/json"):
    req = urllib.request.Request(url, data=data, headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": content_type}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as response:
        body = response.read()
        return json.loads(body) if body else {}

menu = {
    "size": {"width": W, "height": H}, "selected": True,
    "name": "記帳功能選單", "chatBarText": "記帳選單", "areas": []
}
texts = ["記支出", "記收入", "本月支出", "類別統計", "查餘額", "記帳"]
for i, text in enumerate(texts):
    row, col = divmod(i, 3)
    menu["areas"].append({
        "bounds": {"x": col * W // 3, "y": row * H // 2, "width": W // 3, "height": H // 2},
        "action": {"type": "message", "label": labels[i], "text": text},
    })
created = post("https://api.line.me/v2/bot/richmenu", json.dumps(menu).encode())
menu_id = created["richMenuId"]
post(f"https://api-data.line.me/v2/bot/richmenu/{menu_id}/content", buf.getvalue(), "image/png")
post(f"https://api.line.me/v2/bot/user/all/richmenu/{menu_id}", b"")
print(f"已建立並啟用圖文選單：{menu_id}")
