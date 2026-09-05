"""
Stock price target alert -> LINE Messaging API
รันสคริปต์นี้ซ้ำๆ (เช่นทุก 10 นาที ผ่าน GitHub Actions cron)
- อ่านรายการหุ้น/เป้าหมายจาก config.json
- ดึงราคาปัจจุบันด้วย yfinance (US ใช้ ticker ปกติ, TH ต่อท้ายด้วย .BK)
- ถ้าราคาถึงเป้าหมายที่ยังไม่ achieved -> ส่ง LINE broadcast แล้ว mark achieved=true
- เขียน config.json กลับ เพื่อไม่ให้แจ้งเตือนซ้ำ (workflow จะ commit กลับเข้า repo)
"""

import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import yfinance as yf

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
LINE_API_URL = "https://api.line.me/v2/bot/message/broadcast"
BANGKOK_TZ = ZoneInfo("Asia/Bangkok")
MAX_TARGETS_PER_STOCK = 5


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get_current_price(yf_ticker):
    """คืนค่า (price, currency) หรือ (None, None) ถ้าดึงไม่ได้"""
    try:
        t = yf.Ticker(yf_ticker)
        info = t.fast_info
        price = info.get("last_price") or info.get("lastPrice")
        currency = info.get("currency")
        if price is None:
            hist = t.history(period="1d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
        return price, currency
    except Exception as e:
        print(f"[WARN] ดึงราคา {yf_ticker} ไม่สำเร็จ: {e}")
        return None, None


def target_hit(price, target):
    if target["condition"] == "above":
        return price >= target["price"]
    elif target["condition"] == "below":
        return price <= target["price"]
    return False


def send_line_broadcast(message):
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        print("[ERROR] ไม่พบ LINE_CHANNEL_ACCESS_TOKEN ใน environment")
        return False
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    payload = {"messages": [{"type": "text", "text": message}]}
    resp = requests.post(LINE_API_URL, headers=headers, json=payload, timeout=15)
    if resp.status_code != 200:
        print(f"[ERROR] ส่ง LINE ไม่สำเร็จ: {resp.status_code} {resp.text}")
        return False
    return True


def format_message(stock, target, price):
    now = datetime.now(BANGKOK_TZ).strftime("%d/%m/%Y %H:%M น.")
    direction = "ขึ้นถึง" if target["condition"] == "above" else "ลงถึง"
    return (
        f"🔔 แจ้งเตือนราคาหุ้นถึงเป้าหมาย\n"
        f"หุ้น: {stock['symbol']}\n"
        f"ตลาด: {stock['market']}\n"
        f"ราคาปัจจุบัน: {price:,.2f} {stock['currency']}\n"
        f"เป้าหมายที่ {target['id']}: {direction} {target['price']:,.2f} {stock['currency']}\n"
        f"เวลา: {now}"
    )


def main():
    cfg = load_config()
    changed = False
    any_alert = False

    for stock in cfg["watchlist"]:
        targets = stock.get("targets", [])
        if len(targets) > MAX_TARGETS_PER_STOCK:
            print(f"[WARN] {stock['symbol']} มีเป้าหมายเกิน {MAX_TARGETS_PER_STOCK} รายการ (จะเช็คทุกรายการที่ใส่ไว้)")

        pending = [t for t in targets if not t.get("achieved")]
        if not pending:
            continue

        price, _ = get_current_price(stock["yf_ticker"])
        if price is None:
            continue

        print(f"{stock['symbol']} ({stock['yf_ticker']}) = {price} {stock['currency']}")

        for target in pending:
            if target_hit(price, target):
                msg = format_message(stock, target, price)
                print("[ALERT]\n" + msg)
                if send_line_broadcast(msg):
                    target["achieved"] = True
                    changed = True
                    any_alert = True

    if changed:
        save_config(cfg)
        print("อัปเดต config.json (บันทึกสถานะ achieved แล้ว)")

    if not any_alert:
        print("ยังไม่มีเป้าหมายไหนถึงราคาที่ตั้งไว้ในรอบนี้")


if __name__ == "__main__":
    main()
