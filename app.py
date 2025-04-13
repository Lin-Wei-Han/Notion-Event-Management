from flask import Flask, request, redirect, url_for, render_template, jsonify, flash 
from dotenv import load_dotenv, find_dotenv
from utils.notionEvent import *
from utils.googleCalendar import *
from utils.blockIntervals import *
from utils.loadData import *
import datetime
import logging
import os

load_dotenv(find_dotenv())

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =======================
# --- 設定 ---
# =======================
config_dir = './config'
credentials_dir = './credentials'

SERVICE_ACCOUNT_STR = os.environ.get('GOOGLE_CREDENTIALS_JSON')
SERVICE_ACCOUNT_FILE = json.loads(SERVICE_ACCOUNT_STR)
# SERVICE_ACCOUNT_FILE = os.path.join(credentials_dir, 'service_account_key.json')
CALENDARS_JSON_FILE = os.path.join(config_dir, 'calendars.json')
TIME_JSON_FILE = os.path.join(config_dir, 'time.json') 

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

SCOPES = ['https://www.googleapis.com/auth/calendar']
TIMEZONE = 'Asia/Taipei' # 台灣時區

# =======================
# --- Flask App 設定 ---
# =======================
app = Flask(__name__)
# Flask 需要 secret_key 來使用 session 和 flash messages
# app.secret_key = os.urandom(24) # 正式環境請用更安全的方式管理
app.secret_key = os.environ.get('SECRET_KEY')
# --- Flask Routes for Frontend ---

@app.route('/')
def index():
    """主頁，直接顯示屏蔽時間列表和新增表單"""
    blocked_times = load_json_data(TIME_JSON_FILE)
    if blocked_times is None:
        blocked_times = [] # 如果載入失敗，顯示空列表
        flash("錯誤：無法載入屏蔽時間設定檔。", "error")
    # 使用 render_template 渲染 templates/manage_blocked_times.html
    return render_template('blocked_times.html', blocked_times=blocked_times)

@app.route('/blocked_times/add', methods=['POST'])
def add_blocked_time():
    """處理新增屏蔽時間的請求"""
    start_time = request.form.get('start_time')
    end_time = request.form.get('end_time')
    routine = request.form.get('routine')
    description = request.form.get('description', '') # 獲取描述，如果沒有則為空字串

    # 檢查是否有空值
    if not all([start_time, end_time, routine]):
        flash("錯誤：開始時間、結束時間和重複規則為必填項。", "error")
        # 如果檢查失敗，返回重新導向回應
        return redirect(url_for('index')) # 確保指向 index

    # 檢查時間格式
    try:
        datetime.datetime.strptime(start_time, "%H:%M:%S")
        datetime.datetime.strptime(end_time, "%H:%M:%S")
    except ValueError:
        flash("錯誤：時間格式不正確，請使用 HH:MM:SS。", "error")
         # 如果格式錯誤，返回重新導向回應
        return redirect(url_for('index')) # 確保指向 index

    # --- 如果上面都通過，執行以下邏輯 ---
    new_rule = {
        "start_time": start_time,
        "end_time": end_time,
        "routine": routine,
        "description": description
    }

    blocked_times = load_json_data(TIME_JSON_FILE)
    if blocked_times is None:
        blocked_times = [] # 如果檔案有問題，從空列表開始

    blocked_times.append(new_rule)

    if save_json_data(blocked_times, TIME_JSON_FILE):
        flash("成功新增屏蔽規則。", "success")
    else:
        flash("錯誤：儲存屏蔽規則失敗。", "error")

    # --- 函數的最後，必定返回重新導向回應 ---
    return redirect(url_for('index')) # 確保指向 index


@app.route('/blocked_times/delete/<int:index>', methods=['POST'])
def delete_blocked_time(index):
    """處理刪除屏蔽時間的請求"""
    blocked_times = load_json_data(TIME_JSON_FILE)

    if blocked_times is None:
        flash("錯誤：無法載入屏蔽時間設定檔，無法刪除。", "error")
        return redirect(url_for('index'))

    try:
        if 0 <= index < len(blocked_times):
            removed_rule = blocked_times.pop(index)
            print(f"準備刪除規則: {removed_rule}") # Log for debugging
            if save_json_data(blocked_times, TIME_JSON_FILE):
                # *** 修正 NameError & SyntaxError ***
                desc = removed_rule.get('description')
                start = removed_rule.get("start_time", "??")
                end = removed_rule.get("end_time", "??")
                if desc:
                    flash_message = f"成功刪除規則: {desc}"
                else:
                    flash_message = f"成功刪除規則: {start}-{end}"
                flash(flash_message, "success")
                # *** 修正結束 ***
            else:
                flash("錯誤：儲存更新後的屏蔽規則失敗。", "error")
                # 如果儲存失敗，可能需要考慮是否將刪除的規則加回去
                # blocked_times.insert(index, removed_rule)
        else:
            flash("錯誤：無效的規則索引。", "error")
    except IndexError:
         flash("錯誤：嘗試刪除的規則不存在。", "error")

    return redirect(url_for('index'))


@app.route('/webhook', methods=['POST'])
def notion_webhook():
    event = request.json

    if event.get('type') == 'url_verification':
        logger.info(event)
        return jsonify({'challenge': event['challenge']}), 200

    logger.info(event)

    # 一般事件處理
    WATCHED_PROPERTIES = {'title', 'GSFO', 'yLT%3A'}

    event_type = event.get('type')
    event_data = event.get('data', {})
    entity = event.get('entity', {})
    updated_properties = set(event_data.get('updated_properties', []))
    page_id = entity.get('id')

    if event_type == 'page.created':
        handle_page_created(page_id)
    elif event_type == 'page.properties_updated':
        if WATCHED_PROPERTIES & updated_properties:
            # 有交集才觸發處理
            handle_page_updated(page_id)
        else:
            logger.info(f'Skipped update for page {page_id} — irrelevant property change: {updated_properties}')
    elif event_type == 'page.deleted':
        handle_page_deleted(page_id)
    else:
        logger.info(f'Unhandled event type: {event_type}')

    return jsonify({'status': 'success'}), 200

# --- 主程式流程 ---
if __name__ == '__main__':
    # os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' # 如果有 OAuth 路由需要
    # app.run('localhost', 5000, debug=True) # debug=True 只用於開發
    app.run(debug=True, port=os.getenv("PORT", default=5000), host='0.0.0.0')
