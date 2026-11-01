"""SQLite-backed, per-LINE-user bookkeeping and conversation flows."""
import json
import hashlib
import os
import re
import sqlite3
from datetime import date, datetime
from zoneinfo import ZoneInfo

DB_PATH = os.getenv("LEDGER_DB_PATH", "ledger.sqlite3")
CATEGORIES = ["吃飯", "喝飲料", "交通", "學習", "遊戲", "應酬", "生活用品", "其他"]
LOCAL_TZ = ZoneInfo("Asia/Taipei")


def local_today():
    return datetime.now(LOCAL_TZ).date()


def connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=5000")
    return db


def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          user_id TEXT PRIMARY KEY, opening_balance INTEGER NOT NULL DEFAULT 0,
          stipend INTEGER, stipend_next TEXT
        );
        CREATE TABLE IF NOT EXISTS entries (
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
          kind TEXT NOT NULL CHECK(kind IN ('income','expense')),
          amount INTEGER NOT NULL, item TEXT NOT NULL, category TEXT,
          entry_date TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS entries_user_date ON entries(user_id, entry_date);
        CREATE UNIQUE INDEX IF NOT EXISTS one_stipend_per_due_date
          ON entries(user_id, entry_date) WHERE kind='income' AND item='每月生活費';
        CREATE TABLE IF NOT EXISTS states (user_id TEXT PRIMARY KEY, state TEXT NOT NULL);
        """)


def ensure_user(user_id):
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))


def get_state(user_id):
    with connect() as db:
        row = db.execute("SELECT state FROM states WHERE user_id=?", (user_id,)).fetchone()
    return json.loads(row[0]) if row else None


def set_state(user_id, state):
    with connect() as db:
        if state is None:
            db.execute("DELETE FROM states WHERE user_id=?", (user_id,))
        else:
            db.execute("INSERT OR REPLACE INTO states VALUES (?,?)", (user_id, json.dumps(state, ensure_ascii=False)))


def month_start(d):
    return d.replace(day=1)


def next_month(d):
    return date(d.year + (d.month == 12), 1 if d.month == 12 else d.month + 1, 1)


def catch_up(user_id):
    """Credit every scheduled stipend through today, exactly once per due month."""
    today = local_today()
    ensure_user(user_id)
    with connect() as db:
        user = db.execute("SELECT stipend, stipend_next FROM users WHERE user_id=?", (user_id,)).fetchone()
        due = date.fromisoformat(user["stipend_next"]) if user["stipend_next"] else None
        if user["stipend"] and due:
            while due <= today:
                db.execute("INSERT OR IGNORE INTO entries(user_id,kind,amount,item,entry_date) VALUES(?,?,?,?,?)",
                           (user_id, "income", user["stipend"], "每月生活費", due.isoformat()))
                due = next_month(due)
            db.execute("UPDATE users SET stipend_next=? WHERE user_id=?", (due.isoformat(), user_id))


def balance(user_id):
    with connect() as db:
        u = db.execute("SELECT opening_balance FROM users WHERE user_id=?", (user_id,)).fetchone()
        totals = db.execute("SELECT kind, COALESCE(SUM(amount),0) n FROM entries WHERE user_id=? GROUP BY kind", (user_id,)).fetchall()
    sums = {r["kind"]: r["n"] for r in totals}
    return u[0] + sums.get("income", 0) - sums.get("expense", 0)


def record_entry(user_id, data, item_text):
    """Save an entry using today by default and infer its category from the text."""
    item = item_text.strip()[:80]
    category = None
    if data["kind"] == "expense":
        explicit = next((c for c in CATEGORIES if c in item), None)
        if explicit:
            category = explicit
            item = item.replace(category, " ").strip(" ：:，,/") or category
        else:
            keywords = {
                "吃飯": ("早餐", "午餐", "晚餐", "宵夜", "便當", "吃飯", "餐", "麵", "飯"),
                "喝飲料": ("飲料", "咖啡", "奶茶", "手搖", "茶", "果汁"),
                "交通": ("捷運", "公車", "火車", "高鐵", "計程車", "計程", "交通", "加油", "停車", "車票"),
                "學習": ("學費", "課本", "文具", "教材", "課程", "學習", "影印"),
                "遊戲": ("遊戲", "遊戲點數", "遊戲儲值"),
                "應酬": ("聚餐", "請客", "送禮", "應酬"),
                "生活用品": ("生活用品", "衛生紙", "洗衣", "清潔", "日用品", "牙膏", "洗髮"),
            }
            category = next((c for c, words in keywords.items() if any(word in item for word in words)), "其他")
    day = local_today()
    with connect() as db:
        db.execute("INSERT INTO entries(user_id,kind,amount,item,category,entry_date) VALUES(?,?,?,?,?,?)",
                   (user_id, data["kind"], data["amount"], item, category, day.isoformat()))
        entry_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    kind = "支出" if data["kind"] == "expense" else "收入"
    extra = f"／{category}" if category else ""
    return f"已記錄{kind} #{entry_id}：{item} ${data['amount']:,}{extra}（今天）。目前餘額 ${balance(user_id):,}。"


def flex_table(title, period, headers, rows, alt_text):
    """Build a LINE Flex Message with spreadsheet-like aligned columns."""
    def cell(text, flex, align="start", bold=False, color="#333333"):
        return {"type": "text", "text": str(text), "flex": flex, "size": "sm",
                "align": align, "weight": "bold" if bold else "regular", "color": color,
                "wrap": True}

    contents = [
        {"type": "text", "text": title, "weight": "bold", "size": "lg", "color": "#493879"},
        {"type": "text", "text": period, "size": "xs", "color": "#888888", "margin": "sm"},
        {"type": "separator", "margin": "md"},
        {"type": "box", "layout": "horizontal", "spacing": "sm", "margin": "md",
         "contents": [cell(h, f, "end" if i else "start", True, "#6E5AA6")
                      for i, (h, f) in enumerate(headers)]},
        {"type": "separator", "margin": "sm"},
    ]
    for row in rows:
        contents.append({"type": "box", "layout": "horizontal", "spacing": "sm", "margin": "md",
                         "contents": [cell(v, f, "end" if i else "start")
                                      for i, (v, (_, f)) in enumerate(zip(row, headers))]})
    contents.extend([
        {"type": "separator", "margin": "md"},
        {"type": "text", "text": "資料依目前帳本紀錄統計", "size": "xxs", "color": "#999999", "margin": "md"},
    ])
    return {"type": "flex", "altText": alt_text,
            "contents": {"type": "bubble", "size": "giga",
                         "body": {"type": "box", "layout": "vertical", "contents": contents,
                                  "paddingAll": "18px"}}}


def export_monthly_workbook(user_id, today):
    """Write this user's monthly summary and transactions to reports/YYYY-MM.xlsx."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    start, end = month_start(today).isoformat(), next_month(today).isoformat()
    with connect() as db:
        summaries = db.execute(
            "SELECT COALESCE(category,'未分類') category, COUNT(*) count, SUM(amount) amount "
            "FROM entries WHERE user_id=? AND kind='expense' AND entry_date>=? AND entry_date<? "
            "GROUP BY category ORDER BY amount DESC", (user_id, start, end)
        ).fetchall()
        details = db.execute(
            "SELECT entry_date, kind, COALESCE(category,'') category, item, amount "
            "FROM entries WHERE user_id=? AND entry_date>=? AND entry_date<? "
            "ORDER BY entry_date, id", (user_id, start, end)
        ).fetchall()

    report_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports",
                              hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12])
    os.makedirs(report_dir, exist_ok=True)
    path = os.path.join(report_dir, f"{today:%Y-%m}.xlsx")
    workbook = Workbook()
    summary = workbook.active
    summary.title = "支出統計"
    summary.append([f"{today:%Y年%m月}支出分類統計"])
    summary.append(["類別", "筆數", "金額（元）", "占比"])
    total = sum(row["amount"] for row in summaries)
    for row in summaries:
        summary.append([row["category"], row["count"], row["amount"],
                        row["amount"] / total if total else 0])
    summary.append(["總計", sum(row["count"] for row in summaries), total, 1 if total else 0])
    summary.merge_cells(start_row=1, start_column=1, end_row=1, end_column=4)
    summary["A1"].font = Font(size=16, bold=True, color="493879")
    summary["A1"].alignment = Alignment(horizontal="center")
    for cell in summary[2]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="6E5AA6")
    for cell in summary[summary.max_row]:
        cell.font = Font(bold=True)
    for row_index in range(3, summary.max_row + 1):
        summary.cell(row_index, 3).number_format = '#,##0'
        summary.cell(row_index, 4).number_format = '0.0%'
    summary.freeze_panes = "A3"
    summary.auto_filter.ref = f"A2:D{summary.max_row}"
    for column, width in enumerate((18, 12, 16, 12), 1):
        summary.column_dimensions[get_column_letter(column)].width = width

    detail_sheet = workbook.create_sheet("交易明細")
    detail_sheet.append(["日期", "類型", "類別", "項目", "金額（元）"])
    for row in details:
        detail_sheet.append([row["entry_date"], "支出" if row["kind"] == "expense" else "收入",
                             row["category"], row["item"], row["amount"]])
    for cell in detail_sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="6E5AA6")
    detail_sheet.freeze_panes = "A2"
    detail_sheet.auto_filter.ref = f"A1:E{detail_sheet.max_row}"
    for column, width in enumerate((14, 12, 16, 30, 16), 1):
        detail_sheet.column_dimensions[get_column_letter(column)].width = width
    for cell in detail_sheet["E"][1:]:
        cell.number_format = '#,##0'

    workbook.save(path)
    return path


def handle(user_id, text):
    """Return a ledger response, or None when text belongs to the existing AI chat."""
    ensure_user(user_id)
    catch_up(user_id)
    msg = text.strip()
    state = get_state(user_id)
    if msg in {"取消", "返回"} and state:
        set_state(user_id, None)
        return "已取消。輸入「記帳」可開啟功能選單。"

    if state:
        step, data = state["step"], state
        if step == "amount":
            match = re.fullmatch(r"\s*([\d,]+)\s*(?:元)?(?:\s+(.+))?\s*", msg)
            if not match:
                return "請輸入「金額 項目」，例如「55 午餐」；或輸入「取消」退出。"
            amount = int(match.group(1).replace(",", ""))
            if amount <= 0:
                return "金額要大於 0，請輸入例如「55 午餐」。"
            item = match.group(2)
            if item:
                set_state(user_id, None)
                return record_entry(user_id, {**data, "amount": amount}, item)
            data.update(amount=amount, step="item")
            set_state(user_id, data)
            return "請輸入項目，例如「午餐」；日期會自動記今天。"
        if step in {"opening", "stipend"}:
            try:
                amount = int(msg.replace(",", "").replace("元", "").strip())
                if amount < 0 or (step != "opening" and amount == 0):
                    raise ValueError()
            except ValueError:
                return "請輸入有效的整數金額（元），或輸入「取消」。"
            if step == "opening":
                with connect() as db: db.execute("UPDATE users SET opening_balance=? WHERE user_id=?", (amount, user_id))
                set_state(user_id, None)
                return f"初始餘額已設為 ${amount:,}。目前餘額：${balance(user_id):,}。"
            if step == "stipend":
                # Start on the next first of a month; this avoids retroactive credits before setup.
                today = local_today()
                first = next_month(today)
                with connect() as db: db.execute("UPDATE users SET stipend=?, stipend_next=? WHERE user_id=?", (amount, first.isoformat(), user_id))
                set_state(user_id, None)
                catch_up(user_id)
                return f"每月生活費已設為 ${amount:,}，從 {first.isoformat()} 起每月自動入帳；下次使用時會補登。"
        if step == "item":
            set_state(user_id, None)
            return record_entry(user_id, data, msg)
        if step == "category":
            if msg not in CATEGORIES: return "請從這些類別選一個：" + "、".join(CATEGORIES)
            data.update(category=msg, step="date")
            set_state(user_id, data)
            return "日期是今天嗎？回覆「是」或輸入 YYYY-MM-DD。"
        if step == "date":
            if msg in {"是", "今天", "今日"}: day = local_today()
            else:
                try: day = date.fromisoformat(msg)
                except ValueError: return "請回覆「是」使用今天，或輸入 YYYY-MM-DD；輸入「取消」可退出。"
            with connect() as db:
                db.execute("INSERT INTO entries(user_id,kind,amount,item,category,entry_date) VALUES(?,?,?,?,?,?)",
                           (user_id, data["kind"], data["amount"], data["item"], data.get("category"), day.isoformat()))
                entry_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            set_state(user_id, None)
            kind = "支出" if data["kind"] == "expense" else "收入"
            extra = f"／{data['category']}" if data.get("category") else ""
            return f"已記錄{kind} #{entry_id}：{data['item']} ${data['amount']:,}{extra}（{day.isoformat()}）。目前餘額 ${balance(user_id):,}。"

    if state and state["step"] == "edit_id":
        try: entry_id = int(msg)
        except ValueError: return "請輸入紀錄編號，或輸入「取消」。"
        with connect() as db: row = db.execute("SELECT id FROM entries WHERE id=? AND user_id=?", (entry_id,user_id)).fetchone()
        if not row: return "找不到這筆紀錄，請確認編號。"
        set_state(user_id, {"step":"edit_field","id":entry_id}); return "要修改哪個欄位？\n1 金額\n2 項目\n3 類別\n4 日期"
    if state and state["step"] == "edit_field":
        fields = {"1":"amount", "2":"item", "3":"category", "4":"entry_date"}
        if msg not in fields: return "請輸入 1、2、3 或 4。"
        field = fields[msg]
        if field == "category":
            set_state(user_id, {**state, "step":"edit_category"}); return "請輸入新類別：" + "、".join(CATEGORIES)
        prompt = {"amount":"請輸入新的金額（元）。", "item":"請輸入新的項目名稱。", "entry_date":"請輸入新日期 YYYY-MM-DD。"}[field]
        set_state(user_id, {**state, "step":"edit_value", "field":field}); return prompt
    if state and state["step"] == "edit_category":
        if msg not in CATEGORIES: return "請選擇：" + "、".join(CATEGORIES)
        with connect() as db: db.execute("UPDATE entries SET category=? WHERE id=? AND user_id=?", (msg,state["id"],user_id))
        set_state(user_id, None); return f"紀錄 #{state['id']} 的類別已更新為「{msg}」。"
    if state and state["step"] == "edit_value":
        field = state["field"]
        if field == "amount":
            try: value = int(msg.replace(",", "").replace("元", "")); assert value > 0
            except (ValueError, AssertionError): return "請輸入大於 0 的整數金額。"
            shown = f"${value:,}"
        elif field == "entry_date":
            try: value = date.fromisoformat(msg).isoformat()
            except ValueError: return "請輸入有效日期 YYYY-MM-DD。"
            shown = value
        else:
            value = msg[:80]; shown = value
        with connect() as db: db.execute(f"UPDATE entries SET {field}=? WHERE id=? AND user_id=?", (value,state["id"],user_id))
        set_state(user_id, None); return f"紀錄 #{state['id']} 已更新為 {shown}。"
    if state and state["step"] == "delete_id":
        try: entry_id = int(msg)
        except ValueError: return "請輸入紀錄編號，或輸入「取消」。"
        with connect() as db: cursor = db.execute("DELETE FROM entries WHERE id=? AND user_id=?", (entry_id,user_id))
        if not cursor.rowcount: return "找不到這筆紀錄，請確認編號。"
        set_state(user_id, None); return f"紀錄 #{entry_id} 已刪除。"

    if msg in {"記帳", "帳本", "記帳選單"}:
        return "記帳功能：\n1 記支出\n2 記收入\n3 本月支出\n4 類別統計\n5 查餘額\n6 最近紀錄\n7 修改紀錄\n8 刪除紀錄\n9 設初始餘額\n10 設每月生活費\n回覆數字開始操作。"
    if msg in {"1", "記支出", "支出"}:
        set_state(user_id, {"step":"amount", "kind":"expense"}); return "請輸入「金額 項目」，例如「55 午餐」。可加分類：「55 午餐 吃飯」；日期預設今天。"
    if msg in {"2", "記收入", "收入"}:
        set_state(user_id, {"step":"amount", "kind":"income"}); return "請輸入「金額 項目」，例如「500 打工」；日期預設今天。"
    if msg in {"9", "設定初始餘額", "初始餘額"}:
        set_state(user_id, {"step":"opening"}); return "請輸入初始餘額（元，可輸入 0）。"
    if msg in {"10", "設定每月生活費", "每月生活費"}:
        set_state(user_id, {"step":"stipend"}); return "請輸入每月生活費金額（元）。下次使用時會自動補登到期月份。"

    today = local_today(); start = month_start(today).isoformat(); end = next_month(today).isoformat()
    if msg in {"3", "本月支出", "查本月支出"}:
        with connect() as db:
            total = db.execute("SELECT COALESCE(SUM(amount),0) FROM entries WHERE user_id=? AND kind='expense' AND entry_date>=? AND entry_date<?", (user_id,start,end)).fetchone()[0]
        return flex_table(f"{today:%Y年%m月}支出統計", "本月累計",
                          [("統計項目", 3), ("金額", 2)],
                          [["支出總額", f"${total:,}"]],
                          f"{today:%Y年%m月}支出共 ${total:,}")
    if msg in {"4", "類別統計", "本月分類"}:
        with connect() as db:
            rows = db.execute("SELECT COALESCE(category,'未分類') category,COUNT(*) count,SUM(amount) amount FROM entries WHERE user_id=? AND kind='expense' AND entry_date>=? AND entry_date<? GROUP BY category ORDER BY amount DESC", (user_id,start,end)).fetchall()
        report_path = export_monthly_workbook(user_id, today)
        report_relative_path = os.path.relpath(report_path, os.path.dirname(os.path.abspath(__file__)))
        total = sum(row["amount"] for row in rows)
        table_rows = [[row["category"], str(row["count"]), f"${row['amount']:,}",
                       f"{row['amount'] * 100 / total:.1f}%" if total else "0.0%"] for row in rows]
        table_rows.append(["總計", str(sum(row["count"] for row in rows)), f"${total:,}", "100%" if total else "0%"])
        return flex_table(f"{today:%Y年%m月}支出分類", f"Excel 已更新：{report_relative_path}",
                          [("類別", 4), ("筆數", 2), ("金額", 3), ("占比", 2)],
                          table_rows or [["本月尚無紀錄", "0", "$0", "0%"]],
                          f"{today:%Y年%m月}支出分類統計，共 ${total:,}")
    if msg in {"5", "查餘額", "餘額"}: return f"目前餘額：${balance(user_id):,}。"
    if msg in {"6", "最近紀錄", "查看紀錄"}:
        with connect() as db: rows = db.execute("SELECT id,kind,amount,item,category,entry_date FROM entries WHERE user_id=? ORDER BY entry_date DESC,id DESC LIMIT 10", (user_id,)).fetchall()
        return "最近紀錄：\n" + ("\n".join(f"#{r['id']} {r['entry_date']} {'支出' if r['kind']=='expense' else '收入'} {r['item']} ${r['amount']:,}" + (f"／{r['category']}" if r['category'] else "") for r in rows) or "目前沒有紀錄。")
    if msg in {"7", "修改紀錄"}:
        set_state(user_id, {"step":"edit_id"}); return "請輸入要修改的紀錄編號（可先看「最近紀錄」）。"
    if msg in {"8", "刪除紀錄"}:
        set_state(user_id, {"step":"delete_id"}); return "請輸入要刪除的紀錄編號（可先看「最近紀錄」）。"
    if msg in {"收入明細", "每月收入"}:
        with connect() as db: rows = db.execute("SELECT entry_date,item,amount FROM entries WHERE user_id=? AND kind='income' AND entry_date>=? AND entry_date<? ORDER BY entry_date", (user_id,start,end)).fetchall()
        return f"{today:%Y年%m月}收入明細：\n" + ("\n".join(f"{r['entry_date']} {r['item']} ${r['amount']:,}" for r in rows) or "本月還沒有收入紀錄。")
    if re.fullmatch(r"\s*[\d,]+\s*(?:元)?\s+.+", msg):
        return "我收到「金額＋項目」格式了。請先點選「記支出」或「記收入」，再輸入這筆資料，避免記錯帳。"
    if "分類" in msg:
        return "記支出時，分類寫在項目後面即可，例如「55 午餐 吃飯」；也可以省略分類，系統會依項目猜測。請先點選「記支出」開始。"
    return None


init_db()
