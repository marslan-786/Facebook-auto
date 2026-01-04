import os
import glob
import asyncio
import random
import string
import shutil
import imageio
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse
from fastapi import FastAPI, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from playwright.async_api import async_playwright

# --- 🔥 USER SETTINGS 🔥 ---
live_logs = True 

# --- CONFIGURATION ---
CAPTURE_DIR = "./captures"
NUMBERS_FILE = "numbers.txt"
PROXY_FILE = "proxies.txt"
BASE_URL = "https://m.facebook.com/reg/" 

# --- INITIALIZE ---
app = FastAPI()
if not os.path.exists(CAPTURE_DIR): os.makedirs(CAPTURE_DIR)
app.mount("/captures", StaticFiles(directory=CAPTURE_DIR), name="captures")

SETTINGS = {"country": "Russia", "proxy_manual": ""}
BOT_RUNNING = False
logs = []

# --- RANDOM DATA ---
FIRST_NAMES = ["Ali", "Ahmed", "Kamran", "Bilal", "Usman", "Hamza", "Fahad", "Saad", "Zain", "Omer"]
LAST_NAMES = ["Khan", "Shah", "Butt", "Jutt", "Sheikh", "Raja", "Malik", "Ansari", "Qureshi", "Baig"]

def get_random_name():
    return random.choice(FIRST_NAMES), random.choice(LAST_NAMES)

def get_random_password():
    base = random.choice(["King", "Lion", "Tiger", "Star", "Moon", "Super"])
    nums = random.randint(1000, 9999)
    return f"{base}@{nums}"

# --- LOGGER ---
def log_msg(message, level="step"):
    if level == "step" and not live_logs: return
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = f"[{timestamp}] {message}"
    print(entry)
    logs.insert(0, entry)
    if len(logs) > 500: logs.pop()

# --- PROXY MANAGER (DIRECT SUPPORT ADDED) ---
def parse_proxy_string(proxy_str):
    if not proxy_str or len(proxy_str) < 5: return None
    p = proxy_str.strip()
    # IP:PORT:USER:PASS
    if p.count(":") == 3 and "://" not in p:
        parts = p.split(":")
        return {"server": f"http://{parts[0]}:{parts[1]}", "username": parts[2], "password": parts[3]}
    # STANDARD URL
    if "://" not in p: p = f"http://{p}"
    try:
        parsed = urlparse(p)
        cfg = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
        if parsed.username: cfg["username"] = parsed.username
        if parsed.password: cfg["password"] = parsed.password
        return cfg
    except: return None

def get_current_proxy():
    # 1. Manual Settings
    if SETTINGS["proxy_manual"] and len(SETTINGS["proxy_manual"]) > 5:
        return parse_proxy_string(SETTINGS["proxy_manual"])
    
    # 2. File Proxy (Rotate)
    if os.path.exists(PROXY_FILE):
        try:
            with open(PROXY_FILE, 'r') as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
            if lines: return parse_proxy_string(random.choice(lines))
        except: pass
    
    # 3. NO PROXY (Return None to use Direct Internet)
    return None

def get_next_number():
    if os.path.exists(NUMBERS_FILE):
        with open(NUMBERS_FILE, "r") as f: lines = f.read().splitlines()
        for num in lines: 
            if num.strip(): return num.strip()
    return None

# --- API ---
@app.get("/")
async def read_index(): return FileResponse('index.html')

@app.get("/status")
async def get_status():
    files = sorted(glob.glob(f'{CAPTURE_DIR}/*.jpg'), key=os.path.getmtime, reverse=True)[:10]
    images = [f"/captures/{os.path.basename(f)}" for f in files]
    
    # Proxy Check
    prox = get_current_proxy()
    p_disp = prox['server'] if prox else "🌐 Direct Internet"
    
    return JSONResponse({"logs": logs[:50], "images": images, "running": BOT_RUNNING, "current_country": SETTINGS["country"], "current_proxy": p_disp})

@app.post("/update_settings")
async def update_settings(country: str = Form(...), manual_proxy: Optional[str] = Form("")):
    SETTINGS["country"] = country
    SETTINGS["proxy_manual"] = manual_proxy
    return {"status": "updated"}

@app.post("/upload_proxies")
async def upload_proxies(file: UploadFile = File(...)):
    with open(PROXY_FILE, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    return {"status": "saved"}

@app.post("/upload_numbers")
async def upload_numbers(file: UploadFile = File(...)):
    with open(NUMBERS_FILE, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    log_msg(f"📂 Numbers File Uploaded", level="main")
    return {"status": "saved"}

@app.post("/start")
async def start_bot(bt: BackgroundTasks):
    global BOT_RUNNING
    if not BOT_RUNNING:
        BOT_RUNNING = True
        bt.add_task(master_loop)
    return {"status": "started"}

@app.post("/stop")
async def stop_bot():
    global BOT_RUNNING
    BOT_RUNNING = False
    log_msg("🛑 STOP COMMAND RECEIVED.", level="main")
    return {"status": "stopping"}

# --- VISUAL HELPERS ---
async def capture_step(page, step_name, wait_time=0):
    if not BOT_RUNNING: return
    if wait_time > 0: await asyncio.sleep(wait_time)
    timestamp = datetime.now().strftime("%H%M%S")
    filename = f"{CAPTURE_DIR}/{timestamp}_{step_name}.jpg"
    try: await page.screenshot(path=filename)
    except: pass

async def show_red_dot(page, x, y):
    try:
        # Puts a red dot at X,Y to show where the bot clicked
        await page.evaluate(f"""
            var dot = document.createElement('div');
            dot.style.position = 'absolute'; 
            dot.style.left = '{x-15}px'; dot.style.top = '{y-15}px';
            dot.style.width = '30px'; dot.style.height = '30px'; 
            dot.style.background = 'rgba(255, 0, 0, 0.7)'; 
            dot.style.borderRadius = '50%'; dot.style.zIndex = '2147483647'; 
            dot.style.pointerEvents = 'none'; dot.style.border = '3px solid white'; 
            dot.style.boxShadow = '0 0 10px rgba(255,0,0,0.5)';
            document.body.appendChild(dot);
            setTimeout(() => {{ dot.remove(); }}, 1500);
        """)
    except: pass

# --- 🔥 CLICK STRATEGIES (WITH RED DOTS EVERYWHERE) 🔥 ---
async def execute_click_strategy(page, element, strategy_id, desc):
    try:
        await element.scroll_into_view_if_needed()
        box = await element.bounding_box()
        if not box: return False
        
        # Calculate Coords
        cx = box['x'] + box['width'] / 2
        cy = box['y'] + box['height'] / 2
        rx = box['x'] + box['width'] - 20
        ry = cy

        # ALWAYS SHOW DOT BEFORE CLICKING (Requirement Met)
        if strategy_id == 1:
            log_msg(f"🔹 Logic 1 (Std): {desc}", level="step")
            await show_red_dot(page, cx, cy) # Visual added
            await element.click(force=True, timeout=2000)

        elif strategy_id == 2:
            log_msg(f"🔹 Logic 2 (JS): {desc}", level="step")
            await show_red_dot(page, cx, cy) # Visual added
            await element.evaluate("e => e.click()")

        elif strategy_id == 3:
            log_msg(f"🔹 Logic 3 (Tap Center): {desc}", level="step")
            await show_red_dot(page, cx, cy)
            await page.touchscreen.tap(cx, cy)

        elif strategy_id == 4:
            log_msg(f"🔹 Logic 4 (Tap Right): {desc}", level="step")
            await show_red_dot(page, rx, ry)
            await page.touchscreen.tap(rx, ry)

        elif strategy_id == 5:
            log_msg(f"🔹 Logic 5 (CDP): {desc}", level="step")
            await show_red_dot(page, cx, cy)
            client = await page.context.new_cdp_session(page)
            await client.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": cx, "y": cy}]})
            await asyncio.sleep(0.15)
            await client.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})

        return True
    except: return False

# --- 🔥 SECURE STEP (LADDER) 🔥 ---
async def secure_step(page, finder_func, success_check, step_name):
    # Check success first
    try:
        if await success_check().count() > 0: return True
    except: pass

    for logic_level in range(1, 6):
        if not BOT_RUNNING: return False
        
        log_msg(f"⏳ Finding {step_name}...", level="step")
        await asyncio.sleep(2) 
        
        try:
            btn = finder_func()
            if await btn.count() > 0:
                if logic_level > 1: log_msg(f"♻️ Logic {logic_level}...", level="step")
                
                await execute_click_strategy(page, btn.first, logic_level, step_name)
                
                await asyncio.sleep(0.5)
                await capture_step(page, f"{step_name}_L{logic_level}", wait_time=0)
                await asyncio.sleep(4) # Wait for page load
                
                if await success_check().count() > 0: return True
            else:
                log_msg(f"⚠️ {step_name} not found...", level="step")
        except Exception: pass
    
    log_msg(f"❌ Failed: {step_name}", level="main")
    return False

# --- WORKER ---
async def master_loop():
    global BOT_RUNNING
    
    # Check numbers first
    if not get_next_number():
        log_msg("ℹ️ No Numbers File.", level="main")
        BOT_RUNNING = False; return

    log_msg("🟢 Worker Started.", level="main")
    
    while BOT_RUNNING:
        current_number = get_next_number()
        if not current_number:
            log_msg("ℹ️ No Numbers Left.", level="main"); BOT_RUNNING = False; break
            
        proxy_cfg = get_current_proxy()
        p_show = proxy_cfg['server'] if proxy_cfg else "🌐 Direct Internet"
        
        log_msg(f"🔵 Processing: {current_number}", level="main") 
        log_msg(f"🌍 Connection: {p_show}", level="step") 
        
        try:
            res = await run_fb_session(current_number, proxy_cfg)
            if res == "success": log_msg("🎉 Verified!", level="main")
            else: log_msg("❌ Failed.", level="main")
        except Exception as e:
            log_msg(f"🔥 Crash: {e}", level="main")
        
        await asyncio.sleep(2)

async def run_fb_session(phone, proxy):
    try:
        async with async_playwright() as p:
            launch_args = {
                "headless": True, 
                "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox", "--ignore-certificate-errors"]
            }
            
            # 🔥 PROXY OR DIRECT 🔥
            if proxy: launch_args["proxy"] = proxy 

            log_msg("🚀 Launching...", level="step")
            try: browser = await p.chromium.launch(**launch_args)
            except Exception as e: log_msg(f"❌ Proxy Fail: {e}", level="main"); return "retry"

            pixel_5 = p.devices['Pixel 5'].copy()
            pixel_5['viewport'] = {'width': 412, 'height': 950}
            pixel_5['has_touch'] = True 
            
            context = await browser.new_context(**pixel_5, locale="en-US", ignore_https_errors=True)
            page = await context.new_page()

            log_msg("🌐 Opening Facebook...", level="step")
            try:
                if not BOT_RUNNING: return "stopped"
                await page.goto(BASE_URL, timeout=60000) 
                
                log_msg("⏳ Stabilizing (5s)...", level="step")
                await asyncio.sleep(5) 
                await capture_step(page, "01_Loaded", wait_time=0)

                # --- 1. CLICK CREATE ACCOUNT ---
                if not await secure_step(
                    page, 
                    lambda: page.get_by_role("button", name="Create new account").or_(page.get_by_text("Create new account")), 
                    lambda: page.get_by_text("What's your name?", exact=False).or_(page.get_by_text("First name", exact=False)), 
                    "Create_Account_Btn"
                ): await browser.close(); return "retry"

                # --- 2. ENTER NAME ---
                fname, lname = get_random_name()
                log_msg(f"✍️ Name: {fname} {lname}", level="step")
                
                f_input = page.locator("input[name='firstname']")
                l_input = page.locator("input[name='lastname']")
                
                if await f_input.count() > 0:
                    await f_input.fill(fname)
                    await l_input.fill(lname)
                    await capture_step(page, "02_NameFilled", wait_time=0)
                    
                    if not await secure_step(
                        page,
                        lambda: page.get_by_role("button", name="Next"),
                        lambda: page.get_by_text("birthday", exact=False).or_(page.get_by_text("date of birth", exact=False)),
                        "Name_Next_Btn"
                    ): await browser.close(); return "retry"
                else:
                    log_msg("❌ Name fields not found", level="main"); await browser.close(); return "retry"

                # --- 3. DOB SELECTION (Logic: Click Year -> Scroll -> Set) ---
                log_msg("📅 Setting DOB...", level="step")
                
                # Try to open year picker (Look for 202x)
                year_picker = page.locator("span").filter(has_text="202").first
                if await year_picker.count() == 0: year_picker = page.get_by_text("202", exact=False).first
                
                if await year_picker.count() > 0:
                    await execute_click_strategy(page, year_picker, 3, "Open_Year_Picker")
                    await asyncio.sleep(2)
                    
                    # Scroll & Pick old year
                    old_year = page.get_by_text("199", exact=False).first 
                    if await old_year.count() == 0:
                        await page.mouse.wheel(0, 500) # Scroll down
                        await asyncio.sleep(1)
                        await page.touchscreen.tap(200, 600) # Blind tap
                    else:
                        await execute_click_strategy(page, old_year, 3, "Select_199x")
                    
                    await asyncio.sleep(1)
                    set_btn = page.get_by_text("Set", exact=True).or_(page.get_by_role("button", name="Set"))
                    if await set_btn.count() > 0: await execute_click_strategy(page, set_btn, 1, "Set_DOB")
                
                if not await secure_step(
                    page,
                    lambda: page.get_by_role("button", name="Next"),
                    lambda: page.get_by_text("gender", exact=False).or_(page.get_by_text("Male", exact=True)),
                    "DOB_Next_Btn"
                ): await browser.close(); return "retry"

                # --- 4. GENDER ---
                gender_opt = page.get_by_text("Male", exact=True).first
                if await gender_opt.count() > 0: await execute_click_strategy(page, gender_opt, 3, "Male_Option")
                
                if not await secure_step(
                    page,
                    lambda: page.get_by_role("button", name="Next"),
                    lambda: page.get_by_text("mobile number", exact=False),
                    "Gender_Next_Btn"
                ): await browser.close(); return "retry"

                # --- 5. MOBILE NUMBER ---
                log_msg(f"📱 Input: {phone}", level="step")
                num_input = page.locator("input[type='tel']").or_(page.locator("input[name='reg_email__']"))
                
                if await num_input.count() > 0:
                    await num_input.fill(phone)
                    await capture_step(page, "05_PhoneFilled", wait_time=0)
                    
                    if not await secure_step(
                        page,
                        lambda: page.get_by_role("button", name="Next"),
                        lambda: page.get_by_text("password", exact=False),
                        "Phone_Next_Btn"
                    ): await browser.close(); return "retry"

                # --- 6. PASSWORD ---
                pwd = get_random_password()
                pwd_input = page.locator("input[type='password']")
                if await pwd_input.count() > 0:
                    await pwd_input.fill(pwd)
                    if not await secure_step(
                        page,
                        lambda: page.get_by_role("button", name="Next"),
                        lambda: page.get_by_text("Save", exact=True).or_(page.get_by_text("Not now", exact=True)),
                        "Pwd_Next_Btn"
                    ): await browser.close(); return "retry"

                # --- 7. SAVE INFO ---
                save_choice = page.get_by_text("Not now").or_(page.get_by_text("Save"))
                await secure_step(
                    page,
                    lambda: save_choice,
                    lambda: page.get_by_text("I agree", exact=True),
                    "Save_Info_Btn"
                )

                # --- 8. TERMS ---
                if not await secure_step(
                    page,
                    lambda: page.get_by_text("I agree", exact=True).or_(page.get_by_role("button", name="I agree")),
                    lambda: page.get_by_text("confirmation code", exact=False).or_(page.get_by_text("Send code via", exact=False)),
                    "Terms_Agree_Btn"
                ): await browser.close(); return "retry"

                # --- 9. CONFIRMATION (SMS CHECK) ---
                if await page.get_by_text("Send code via WhatsApp", exact=False).count() > 0:
                    sms_opt = page.get_by_text("Send code via SMS", exact=False)
                    if await sms_opt.count() > 0:
                        await execute_click_strategy(page, sms_opt, 3, "Select_SMS")
                        await asyncio.sleep(1)
                    
                    if not await secure_step(
                        page,
                        lambda: page.get_by_role("button", name="Continue").or_(page.get_by_role("button", name="Send code")),
                        lambda: page.get_by_text("Enter the confirmation code", exact=False).or_(page.locator("input[type='number']")),
                        "Send_Code_Btn"
                    ): await browser.close(); return "retry"

                # --- 10. SUCCESS ---
                code_input = page.locator("input[name='c']") 
                success_text = page.get_by_text("Enter the confirmation code", exact=False)
                
                if await code_input.count() > 0 or await success_text.count() > 0:
                    log_msg("✅ SUCCESS! Code Sent.", level="main")
                    await capture_step(page, "Success", wait_time=1)
                    await browser.close(); return "success"
                else:
                    log_msg("❌ Failed at Final Step.", level="main")
                    await browser.close(); return "retry"

            except Exception as e:
                log_msg(f"❌ Session Error: {str(e)}", level="main"); await browser.close(); return "retry"
                
    except Exception as launch_e:
        log_msg(f"❌ LAUNCH ERROR: {launch_e}", level="main"); return "retry"