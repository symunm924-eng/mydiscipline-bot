import os
import json
import random
from datetime import datetime, date, timedelta

import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler

DATABASE_URL = os.environ["DATABASE_URL"]
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
CITY = os.environ.get("CITY", "Dhaka")
COUNTRY = os.environ.get("COUNTRY", "Bangladesh")
INTERVAL_MINUTES = int(os.environ.get("INTERVAL_MINUTES", "90"))
PRE_PRAYER_MINUTES = int(os.environ.get("PRE_PRAYER_MINUTES", "15"))

app = Flask(__name__)
CORS(app)

MOTIVATION = [
    "ছোট ছোট নিয়মিত কাজই বড় পরিবর্তন আনে।",
    "আজকের একটা ভালো কাজ, আগামীকালের ভিত্তি।",
    "নিজের সাথে করা ওয়াদা রাখাই সবচেয়ে বড় শক্তি।",
    "হাল ছেড়ো না, প্রতিটা দিন একটা নতুন সুযোগ।",
    "যা করার কথা ছিল, এখনই করে ফেলো।",
    "নিজেকে দেওয়া কথাটা আজও রাখো।",
]
PRAYER_ORDER = [("ফজর", "Fajr"), ("যোহর", "Dhuhr"), ("আসর", "Asr"), ("মাগরিব", "Maghrib"), ("এশা", "Isha")]


def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS daily (
        day TEXT PRIMARY KEY,
        data JSONB NOT NULL,
        pct INTEGER DEFAULT 0
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS sent_log (
        id SERIAL PRIMARY KEY,
        day TEXT,
        kind TEXT,
        sent_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(day, kind)
    )""")
    conn.commit()
    cur.close()
    conn.close()


def compute_pct(state):
    parts = []
    tasks = state.get("tasks", [])
    if tasks:
        parts.append(sum(1 for t in tasks if t.get("done")) / len(tasks))
    avoid = state.get("avoid", [])
    if avoid:
        parts.append(sum(1 for t in avoid if t.get("done")) / len(avoid))
    parts.append(1 if state.get("reading", 0) > 0 else 0)
    parts.append(1 if state.get("family", 0) > 0 else 0)
    if not parts:
        return 0
    return round(sum(parts) / len(parts) * 100)


def today_key():
    return date.today().isoformat()


@app.route("/api/day/<d>", methods=["GET"])
def get_day(d):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT data FROM daily WHERE day=%s", (d,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return jsonify(row["data"])
    return jsonify({"tasks": [], "avoid": [], "reading": 0, "family": 0, "tasbeeh": 0})


@app.route("/api/day/<d>", methods=["POST"])
def save_day(d):
    body = request.get_json(force=True)
    pct = compute_pct(body)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO daily(day, data, pct) VALUES (%s, %s, %s)
           ON CONFLICT(day) DO UPDATE SET data = EXCLUDED.data, pct = EXCLUDED.pct""",
        (d, json.dumps(body), pct),
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True, "pct": pct})


@app.route("/api/history")
def history():
    n = int(request.args.get("days", "7"))
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT day, pct FROM daily ORDER BY day DESC LIMIT %s", (n,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({r["day"]: r["pct"] for r in rows})


@app.route("/")
def health():
    return jsonify({"status": "MyDiscipline server running"})


def send_message(text):
    if not BOT_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=10)
    except Exception as e:
        print("send failed:", e)


def get_prayer_times():
    try:
        r = requests.get(
            "https://api.aladhan.com/v1/timingsByCity",
            params={"city": CITY, "country": COUNTRY, "method": 2},
            timeout=10,
        )
        return r.json()["data"]["timings"]
    except Exception:
        return None


def get_today_state():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT data FROM daily WHERE day=%s", (today_key(),))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row["data"] if row else {"tasks": [], "avoid": []}


def already_sent(kind):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sent_log WHERE day=%s AND kind=%s", (today_key(), kind))
    r = cur.fetchone()
    cur.close()
    conn.close()
    return r is not None


def mark_sent(kind):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sent_log(day, kind) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (today_key(), kind),
    )
    conn.commit()
    cur.close()
    conn.close()


def hourly_job():
    state = get_today_state()
    tasks = state.get("tasks", [])
    pending = [t["text"] for t in tasks if not t.get("done")]
    lines = [f"⏰ {datetime.now().strftime('%I:%M %p')} — চেক-ইন"]
    if pending:
        lines.append("🔲 এখনো বাকি:\n" + "\n".join("- " + p for p in pending))
    elif tasks:
        lines.append("✅ আজকের সব কাজ শেষ, মাশাল্লাহ!")
    else:
        lines.append("আজকের কাজ এখনো লেখা হয়নি, অ্যাপে গিয়ে লিখে ফেলো।")
    lines.append("💭 " + random.choice(MOTIVATION))
    send_message("\n\n".join(lines))


def prayer_check_job():
    timings = get_prayer_times()
    if not timings:
        return
    now = datetime.now()
    for bn, en in PRAYER_ORDER:
        t = timings.get(en)
        if not t:
            continue
        try:
            hh, mm = map(int, t.split(":")[:2])
        except Exception:
            continue
        prayer_dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        pre_dt = prayer_dt - timedelta(minutes=PRE_PRAYER_MINUTES)

        if pre_dt <= now < pre_dt + timedelta(minutes=1):
            kind = f"{bn}-pre"
            if not already_sent(kind):
                send_message(f"🕌 {PRE_PRAYER_MINUTES} মিনিট পর {bn}-এর সময় হবে। প্রস্তুত হও।")
                mark_sent(kind)

        if prayer_dt <= now < prayer_dt + timedelta(minutes=1):
            kind = f"{bn}-time"
            if not already_sent(kind):
                send_message(f"🕌 এখন {bn}-এর সময় হয়ে গেছে। নামাজ পড়ে নিয়েছ?")
                mark_sent(kind)


init_db()
scheduler = BackgroundScheduler()
scheduler.add_job(hourly_job, "interval", minutes=INTERVAL_MINUTES)
scheduler.add_job(prayer_check_job, "interval", minutes=1)
scheduler.start()
send_message("✅ MyDiscipline সার্ভার চালু হয়েছে। এখন থেকে অ্যাপের কাজের সাথে মিলিয়ে রিমাইন্ডার পাবে।")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
