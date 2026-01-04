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

# --- PROXY MANAGER ---
def parse_proxy_string(proxy_str):
    if not proxy_str or len(proxy_str) < 5: return None
    p = proxy_str.strip()
    if p.count(":") == 3 and "://" not in p:
        parts = p.split(":")
        return {"server": f"http://{parts[0]}:{parts[1]}", "username": parts[2], "password": parts[3]}
    if "://" not in p: p = f"http://{p}"
    try:
        parsed = urlparse(p)
        cfg = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
        if parsed.username: cfg["username"] = parsed.username
        if parsed.password: cfg["password"] = parsed.password
        return cfg
    except: return None

def get_current_proxy():
    if SETTINGS["proxy_manual"] and len(SETTINGS["proxy_manual"]) > 5:
        return parse_proxy_string(SETTINGS["proxy_manual"])
    if os.path.exists(PROXY_FILE):
        try:
            with open(PROXY_FILE, 'r') as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
            if lines: return parse_proxy_string(random.choice(lines))
        except: pass
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
    files = sorted(glob.glob(f'{CAPTURE_DIR}/*.jpg'), key=os.path.getmtime, reverse=True)[:20]
    images = [f"/captures/{os.path.basename(f)}" for f in files]
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
    rnd = random.randint(10,99)
    filename = f"{CAPTURE_DIR}/{timestamp}_{step_name}_{rnd}.jpg"
    try: await page.screenshot(path=filename)
    except: pass

async def show_red_dot(page, x, y):
    try:
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

# --- CLICK STRATEGIES ---
async def execute_click_strategy(page, element, strategy_id, desc):
    try:
        await element.scroll_into_view_if_needed()
        box = await element.bounding_box()
        if not box: return False
        
        cx = box['x'] + box['width'] / 2
        cy = box['y'] + box['height'] / 2
        rx = box['x'] + box['width'] - 20
        ry = cy

        if strategy_id == 1:
            log_msg(f"🔹 Logic 1 (Std): {desc}", level="step")
            await show_red_dot(page, cx, cy)
            await element.click(force=True, timeout=2000)
        elif strategy_id == 2:
            log_msg(f"🔹 Logic 2 (JS): {desc}", level="step")
            await show_red_dot(page, cx, cy)
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

async def secure_step(page, finder_func, success_check, step_name):
    # Check if already done
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
                
                await capture_step(page, f"Debug_{step_name}_L{logic_level}_Before", wait_time=0)
                await execute_click_strategy(page, btn.first, logic_level, step_name)
                
                log_msg("⏳ Page Reloading (5s)...", level="step")
                await asyncio.sleep(5) 
                
                await capture_step(page, f"Debug_{step_name}_L{logic_level}_After", wait_time=0)

                if await success_check().count() > 0: return True
                else: log_msg("⚠️ Next page not loaded yet...", level="step")
            else:
                if logic_level == 1: log_msg(f"⚠️ {step_name} missing...", level="step")
        except Exception: pass
    
    log_msg(f"❌ Failed: {step_name}", level="main")
    await capture_step(page, f"Stuck_{step_name}", wait_time=0)
    return False

# --- WORKER ---
async def master_loop():
    global BOT_RUNNING
    
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
            if res == "success": log_msg("🎉 Session Ended.", level="main")
            else: log_msg("❌ Session Failed.", level="main")
        except Exception as e:
            log_msg(f"🔥 Crash: {e}", level="main")
        
        await asyncio.sleep(2)

async def run_fb_session(phone, proxy):
    try:
        # 🔥 COMPLETELY FRESH BROWSER FOR EVERY NUMBER 🔥
        async with async_playwright() as p:
            launch_args = {
                "headless": True, 
                "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox", "--ignore-certificate-errors"]
            }
            if proxy: launch_args["proxy"] = proxy 

            log_msg("🚀 Launching Fresh Browser...", level="step")
            try: browser = await p.chromium.launch(**launch_args)
            except Exception as e: log_msg(f"❌ Proxy Fail: {e}", level="main"); return "retry"

            pixel_5 = p.devices['Pixel 5'].copy()
            pixel_5['viewport'] = {'width': 412, 'height': 950}
            pixel_5['has_touch'] = True 
            
            # 🔥 EXPLICITLY CLEAR CONTEXT (Double Safety) 🔥
            context = await browser.new_context(**pixel_5, locale="en-US", ignore_https_errors=True)
            await context.clear_cookies()
            await context.clear_permissions()
            
            page = await context.new_page()

            log_msg("🌐 Opening Facebook...", level="step")
            try:
                if not BOT_RUNNING: return "stopped"
                await page.goto(BASE_URL, timeout=60000) 
                
                log_msg("⏳ Stabilizing (5s)...", level="step")
                await asyncio.sleep(5) 
                await capture_step(page, "01_Loaded", wait_time=0)

                # --- 0. COOKIES ---
                cookie_btn = page.get_by_text("Allow all cookies", exact=False).or_(page.get_by_role("button", name="Allow all cookies"))
                if await cookie_btn.count() > 0:
                    log_msg("🍪 Cookies Found...", level="step")
                    await execute_click_strategy(page, cookie_btn.first, 1, "Cookies")
                    await asyncio.sleep(3)

                # --- 1. CREATE ACCOUNT ---
                if not await secure_step(
                    page, 
                    lambda: page.get_by_role("button", name="Create new account").or_(page.get_by_text("Create new account")), 
                    lambda: page.get_by_text("First name", exact=False).or_(page.get_by_placeholder("First name")).or_(page.locator("input[name='firstname']")), 
                    "Create_Account_Btn"
                ): await browser.close(); return "retry"

                # --- 2. ENTER NAME ---
                fname, lname = get_random_name()
                
                log_msg("⏳ Waiting 5s for Fields...", level="step")
                await asyncio.sleep(5)
                
                f_target = page.get_by_text("First name", exact=False).last 
                if await f_target.count() > 0:
                    await execute_click_strategy(page, f_target, 3, "Click_First_Name_Text")
                    await asyncio.sleep(0.5)
                    await page.keyboard.type(fname, delay=100) 
                else:
                    log_msg("❌ First name text not found", level="main"); await browser.close(); return "retry"

                await asyncio.sleep(1)

                l_target = page.get_by_text("Surname", exact=False).or_(page.get_by_text("Last name", exact=False)).last
                if await l_target.count() > 0:
                    await execute_click_strategy(page, l_target, 3, "Click_Surname_Text")
                    await asyncio.sleep(0.5)
                    await page.keyboard.type(lname, delay=100) 
                else:
                    log_msg("❌ Surname text not found", level="main"); await browser.close(); return "retry"

                await capture_step(page, "02_Names_Typed", wait_time=1)

                # --- NEXT ---
                if not await secure_step(
                    page,
                    lambda: page.get_by_role("button", name="Next"),
                    lambda: page.get_by_text("birthday", exact=False).or_(page.get_by_text("date of birth", exact=False)).or_(page.get_by_text("Age", exact=True).or_(page.get_by_text("How old are you", exact=False))),
                    "Name_Next_Btn"
                ): await browser.close(); return "retry"

                # --- 3. AGE / DOB ---
                log_msg("📅 DOB Step Reached...", level="step")
                await asyncio.sleep(5) 
                
                if await page.get_by_text("Age", exact=True).count() > 0 or await page.locator("input[name='age']").count() > 0:
                    log_msg("🎂 Typing Age directly...", level="step")
                    await page.keyboard.type(str(random.randint(19, 29)))
                else:
                    log_msg("⌨️ Typing DOB directly...", level="step")
                    d = random.randint(1, 28)
                    m = random.randint(1, 12)
                    y = random.randint(1990, 2000)
                    full_date_str = f"{d:02d}{m:02d}{y}"
                    await page.keyboard.type(full_date_str, delay=200)
                    await capture_step(page, "Debug_DOB_Typed", wait_time=1)

                # --- NEXT AFTER DOB ---
                if not await secure_step(
                    page,
                    lambda: page.get_by_role("button", name="Next"),
                    lambda: page.get_by_text("gender", exact=False).or_(page.get_by_text("Male", exact=True)),
                    "Age_Next_Btn"
                ): await browser.close(); return "retry"

                # --- 4. GENDER ---
                log_msg("⚧ Selecting Gender...", level="step")
                await asyncio.sleep(2)
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
                await asyncio.sleep(2)
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
                await asyncio.sleep(2)
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
                await asyncio.sleep(2)
                save_choice = page.get_by_text("Not now", exact=True)
                
                if not await secure_step(
                    page,
                    lambda: save_choice,
                    lambda: page.get_by_text("I agree", exact=True),
                    "Save_Info_Btn"
                ): await browser.close(); return "retry"

                # --- 8. TERMS (I AGREE) + 1 MINUTE OBSERVATION ---
                log_msg("📜 Terms (I Agree)...", level="step")
                await asyncio.sleep(3)
                
                terms_btn = page.get_by_role("button", name="I agree").or_(page.get_by_text("I agree", exact=True).last)
                
                if await terms_btn.count() > 0:
                    # Capture Before
                    await capture_step(page, "Terms_Btn_Found_Before_Click")
                    
                    # CLICK I AGREE
                    await execute_click_strategy(page, terms_btn.first, 3, "I_Agree_Clicked")
                    
                    # 🔥 1-MINUTE OBSERVATION MODE 🔥
                    log_msg("👀 Entering 1-Minute Watch Mode (Capturing every 5s)...", level="main")
                    
                    for i in range(12): # 12 * 5 = 60 Seconds
                        if not BOT_RUNNING: break
                        await asyncio.sleep(5)
                        
                        # Capture status
                        await capture_step(page, f"Post_Agree_Watch_{i+1}", wait_time=0)
                        
                        # Optional: Check if code input appeared (Just for log, don't stop)
                        if await page.locator("input[name='c']").count() > 0:
                            log_msg(f"✅ Code Input Visible! (Watch Step {i+1})", level="main")
                        elif await page.get_by_text("Enter the confirmation code").count() > 0:
                            log_msg(f"✅ Confirmation Page! (Watch Step {i+1})", level="main")
                    
                    log_msg("🏁 Observation Ended.", level="main")
                    return "success" # Marked as processed
                
                else:
                    log_msg("❌ I Agree Button Not Found", level="main")
                    await capture_step(page, "Error_Terms_Missing")
                    await browser.close(); return "retry"

            except Exception as e:
                log_msg(f"❌ Session Error: {str(e)}", level="main"); await browser.close(); return "retry"
                
    except Exception as launch_e:
        log_msg(f"❌ LAUNCH ERROR: {launch_e}", level="main"); return "retry"