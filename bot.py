import os
import random
from datetime import datetime

import requests
from apscheduler.schedulers.blocking import BlockingScheduler

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
CITY = os.environ.get("CITY", "Dhaka")
COUNTRY = os.environ.get("COUNTRY", "Bangladesh")
INTERVAL_MINUTES = int(os.environ.get("INTERVAL_MINUTES", "90"))

MOTIVATION = [
    "ছোট ছোট নিয়মিত কাজই বড় পরিবর্তন আনে।",
    "আজকের একটা ভালো কাজ, আগামীকালের ভিত্তি।",
    "নিজের সাথে করা ওয়াদা রাখাই সবচেয়ে বড় শক্তি।",
    "সময়মতো নামাজ, মনের শান্তি এনে দেয়।",
    "হাল ছেড়ো না, প্রতিটা দিন একটা নতুন সুযোগ।",
    "যা করার কথা ছিল, এখনই করে ফেলো।",
    "নিজেকে দেওয়া কথাটা আজও রাখো।",
]

PRAYER_LABELS = [("ফজর", "Fajr"), ("যোহর", "Dhuhr"), ("আসর", "Asr"), ("মাগরিব", "Maghrib"), ("এশা", "Isha")]


def get_prayer_times():
    try:
        url = "https://api.aladhan.com/v1/timingsByCity"
        params = {"city": CITY, "country": COUNTRY, "method": 2}
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()["data"]["timings"]
    except Exception:
        return None


def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=10)
    except Exception as e:
        print("Message send failed:", e)


def build_reminder():
    now = datetime.now()
    lines = [f"⏰ সময়: {now.strftime('%I:%M %p')}"]

    timings = get_prayer_times()
    if timings:
        rows = [f"{bn}: {timings[en]}" for bn, en in PRAYER_LABELS if en in timings]
        lines.append("🕌 আজকের নামাজের সময় (" + CITY + "):\n" + "\n".join(rows))

    lines.append("💭 " + random.choice(MOTIVATION))
    lines.append("\nMyDiscipline অ্যাপ খুলে আজকের কাজ চেক করো।")
    return "\n\n".join(lines)


def job():
    send_message(build_reminder())


if __name__ == "__main__":
    if not BOT_TOKEN or not CHAT_ID:
        print("BOT_TOKEN বা CHAT_ID সেট করা নেই। এনভায়রনমেন্ট ভেরিয়েবলে বসাও।")
    else:
        send_message("✅ MyDiscipline রিমাইন্ডার বট চালু হয়েছে। প্রতি " + str(INTERVAL_MINUTES) + " মিনিটে একটা মেসেজ পাবে।")
        scheduler = BlockingScheduler()
        scheduler.add_job(job, "interval", minutes=INTERVAL_MINUTES)
        scheduler.start()
