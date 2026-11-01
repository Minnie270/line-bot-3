# LINE Bot 本地模型版

這個專案包含兩種使用方式：

- **終端機模擬模式**：必交的簡單版本，不接 LINE、不需要金鑰，使用電腦上的 Ollama 模型回答問題。
- **LINE Bot 模式**：延伸版本，讓 LINE 訊息交給本機模型回答。需要 LINE 金鑰和網路通道；電腦必須保持開機。

本機模型是 `qwen3:4b`。最近 5 組問答會暫存在程式記憶體中；關閉程式後會清空。

## 終端機模擬模式

### 安裝

1. 安裝 Python 3。
2. 安裝並打開 [Ollama](https://ollama.com/download)。
3. 在終端機下載模型：

   ```bash
   ollama pull qwen3:4b
   ```

### 開始聊天

在放有 `line_bot_lite.py` 的資料夾裡執行：

```bash
python3 line_bot_lite.py --simulate
```

輸入問題後按 Enter。輸入 `quit` 離開。模型只使用本機知識，不能查詢即時網路資訊。

## LINE Bot 延伸模式

`app.py` 是 LINE Webhook 版本。先安裝套件：

```bash
python3 -m pip install -r requirements.txt
```

把 `.env.example` 複製成 `.env`，再填入 LINE Developers 的 Channel secret 和 Channel access token。不要把 `.env` 上傳到 GitHub。

在 `.env` 設定：

```text
MODEL_BACKEND=ollama
OLLAMA_MODEL=qwen3:4b
```

保持 Ollama 開啟，再執行：

```bash
python3 app.py
```

要讓 LINE 連到本機，還需要臨時網路通道並設定 LINE Webhook。使用期間電腦、Ollama、Bot 和通道都要保持運作；關閉通道後，LINE 就無法連到本機。

## LINE 記帳功能

記帳流程與 AI 問答分開處理，不會把記帳訊息交給模型。每位 LINE 使用者有獨立帳本，支援記支出、記收入、本月支出、支出類別統計、餘額、收入明細、最近 10 筆紀錄、修改與刪除紀錄，以及初始餘額和每月生活費設定。支出類別為吃飯、喝飲料、交通、學習、遊戲、應酬、生活用品、其他。

每月生活費設定後，從下一個每月 1 號開始列為固定收入；若 bot 當時未運作，使用者下次傳訊息時會補登到期月份。這是帳本自動入帳，不代表銀行實際收款。記帳日期依台灣時區處理。

### 建立聊天室底部圖文選單

完成套件安裝並設定 `LINE_CHANNEL_ACCESS_TOKEN` 後，在本機執行一次：

```bash
python3 setup_rich_menu.py
```

腳本會建立並設為所有好友的預設選單。圖文選單的「更多功能」會開啟文字選單，包含初始餘額、生活費設定、收入明細、最近紀錄和修改／刪除。

### 帳本資料保存

預設資料庫是專案目錄下的 `ledger.sqlite3`，可用 `LEDGER_DB_PATH` 指定路徑。請定期備份這個檔案。Render 免費服務的本機檔案系統不是持久儲存，重啟或重新部署可能清除帳目；若要在線上長期使用，請先為服務設定持久磁碟，並將 `LEDGER_DB_PATH` 指到該磁碟路徑。

## 我改了什麼

- 加入不用 LINE 金鑰的終端機模擬程式 `line_bot_lite.py`。
- 讓 `app.py` 可以選擇使用本機 Ollama 模型，同時保留原本 Gemini 模式。
- 在兩種模式中保留每位使用者最近 5 組問答。

## 我的實測紀錄

- 模型：`qwen3:4b`
- 電腦：MacBook Air M4，16 GB 統一記憶體，沒有獨立顯示卡
- 一題約：請在自己的電腦實際測量後填寫
- 遇到的問題：請依照自己的實際情況填寫

## 金鑰與隱私

- `.env` 已列在 `.gitignore`，只放在自己的電腦，不要上傳。
- 終端機模擬模式不會連 LINE；問題會送到本機 Ollama 處理。
- LINE 延伸模式會把訊息經由 LINE 和網路通道送到自己的電腦，請勿用來處理敏感資料。
