from utils.blockIntervals import get_blocked_intervals_for_date
from utils.loadData import save_json_data

from googleapiclient.errors import HttpError
from googleapiclient.discovery import build
from google.oauth2 import service_account
import datetime
import json
import pytz
import os

# =======================
# --- 設定 ---
# =======================
constants_dir = './config'
credentials_dir = './credentials'

SERVICE_ACCOUNT_STR = os.environ.get('GOOGLE_CREDENTIALS_JSON')
SERVICE_ACCOUNT_FILE = json.loads(SERVICE_ACCOUNT_STR)
# SERVICE_ACCOUNT_FILE = os.path.join(credentials_dir, 'service_account_key.json')
CALENDARS_JSON_FILE = os.path.join(constants_dir, 'calendars.json')
TIME_JSON_FILE = os.path.join(constants_dir, 'time.json') 

SCOPES = ['https://www.googleapis.com/auth/calendar']
TIMEZONE = 'Asia/Taipei' # 台灣時區
YOUR_EMAIL = 'xcswap.john@gmail.com' # 您的真人 Email，用於分享新日曆


def authenticate_google_calendar_service_account():
    """使用服務帳戶金鑰進行認證並建立 service 物件"""
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        service = build('calendar', 'v3', credentials=creds)
        print("Google Calendar API 服務 (服務帳戶) 建立成功")
        return service
    except FileNotFoundError:
        print(f"錯誤：找不到服務帳戶金鑰檔案 {SERVICE_ACCOUNT_FILE}")
        return None
    except Exception as e:
        print(f"使用服務帳戶認證時發生錯誤: {e}")
        return None



# --- Calendar API Functions ---
def find_free_slots_multi_calendar(service, target_date_str, calendar_ids, blocked_rules, start_hour=8, end_hour=24, min_duration_hours=2):
    """
    查詢多個日曆在指定日期和時間範圍內的綜合空閒時段，並排除固定屏蔽時間。
    """
    if not service: print("未提供有效的服務物件。"); return []
    if not calendar_ids: print("未提供要查詢的日曆 ID。"); return []

    try:
        target_date = datetime.datetime.strptime(target_date_str, "%Y-%m-%d").date()
        tz = pytz.timezone(TIMEZONE)

        # --- 產生當天的屏蔽時段 ---
        fixed_blocked_intervals = get_blocked_intervals_for_date(blocked_rules, target_date, tz)
        print(f"根據規則，{target_date_str} 有 {len(fixed_blocked_intervals)} 個固定屏蔽時段。")
        # --------------------------

        time_min = tz.localize(datetime.datetime.combine(target_date, datetime.time(hour=start_hour)))
        if end_hour == 24:
             time_max = tz.localize(datetime.datetime.combine(target_date + datetime.timedelta(days=1), datetime.time.min))
        else:
             time_max = tz.localize(datetime.datetime.combine(target_date, datetime.time(hour=end_hour)))

        print(f"正在查詢日期 {target_date_str} 從 {start_hour}:00 到 {end_hour}:00 的綜合空閒時間...")
        print(f"查詢的日曆 IDs: {', '.join(calendar_ids)}")

        body = {"timeMin": time_min.isoformat(),"timeMax": time_max.isoformat(),"timeZone": TIMEZONE,"items": [{"id": cal_id} for cal_id in calendar_ids]}
        freebusy_result = service.freebusy().query(body=body).execute()

        # --- 收集所有日曆的忙碌時段 ---
        calendar_busy_intervals_raw = []
        calendars_busy_data = freebusy_result.get('calendars', {})
        for cal_id in calendar_ids:
            busy_times = calendars_busy_data.get(cal_id, {}).get('busy', [])
            if busy_times: calendar_busy_intervals_raw.extend(busy_times)
        # -----------------------------

        all_busy_intervals = []
        # 加入從日曆 API 獲取的忙碌時段
        for busy in calendar_busy_intervals_raw:
             try:
                 start = datetime.datetime.fromisoformat(busy['start'].replace('Z', '+00:00')).astimezone(tz)
                 end = datetime.datetime.fromisoformat(busy['end'].replace('Z', '+00:00')).astimezone(tz)
                 if start < time_max and end > time_min: all_busy_intervals.append({'start': max(start, time_min),'end': min(end, time_max)})
             except ValueError: print(f"  警告：無法解析日曆忙碌時段時間格式: {busy}"); continue

        # --- 加入當天的固定屏蔽時段 ---
        for block in fixed_blocked_intervals:
             # 確保屏蔽時段與查詢範圍有交集
             if block['start'] < time_max and block['end'] > time_min:
                   all_busy_intervals.append({
                       'start': max(block['start'], time_min), # 確保不早於查詢開始時間
                       'end': min(block['end'], time_max)      # 確保不晚於查詢結束時間
                   })
        # ---------------------------

        if not all_busy_intervals:
            print("綜合日曆事件和固定屏蔽規則後，在此時間範圍內均無忙碌時段。")
            duration = time_max - time_min
            if duration >= datetime.timedelta(hours=min_duration_hours): return [{'start': time_min.strftime("%Y-%m-%d %H:%M:%S"),'end': time_max.strftime("%Y-%m-%d %H:%M:%S"),'duration_hours': round(duration.total_seconds() / 3600, 2)}]
            else: return []

        # 按開始時間排序所有忙碌/屏蔽時段
        all_busy_intervals.sort(key=lambda x: x['start'])

        # --- 合併重疊或相鄰的忙碌/屏蔽時段 (邏輯同前) ---
        merged_busy_intervals = []
        current_merged_start = all_busy_intervals[0]['start']
        current_merged_end = all_busy_intervals[0]['end']
        for i in range(1, len(all_busy_intervals)):
            next_start = all_busy_intervals[i]['start']
            next_end = all_busy_intervals[i]['end']
            if next_start <= current_merged_end: current_merged_end = max(current_merged_end, next_end)
            else: merged_busy_intervals.append({'start': current_merged_start, 'end': current_merged_end}); current_merged_start = next_start; current_merged_end = next_end
        merged_busy_intervals.append({'start': current_merged_start, 'end': current_merged_end})
        print(f"合併後的總忙碌/屏蔽時段: {len(merged_busy_intervals)} 個")

        # --- 計算空閒時段 (邏輯同前) ---
        free_slots = []
        current_time = time_min
        for busy in merged_busy_intervals:
            busy_start = busy['start']; busy_end = busy['end']
            if current_time < busy_start: free_slots.append({'start': current_time, 'end': busy_start})
            current_time = busy_end
        if current_time < time_max: free_slots.append({'start': current_time, 'end': time_max})
        min_duration = datetime.timedelta(hours=min_duration_hours)
        long_enough_slots = []
        for slot in free_slots:
            slot_start = max(slot['start'], time_min); slot_end = min(slot['end'], time_max)
            duration = slot_end - slot_start
            if duration >= min_duration: long_enough_slots.append({'start': slot_start.strftime("%Y-%m-%d %H:%M:%S"),'end': slot_end.strftime("%Y-%m-%d %H:%M:%S"),'duration_hours': round(duration.total_seconds() / 3600, 2)})
        print(f"找到 {len(long_enough_slots)} 個至少 {min_duration_hours} 小時的綜合空閒時段 (已排除固定屏蔽時間)。")
        return long_enough_slots

    except HttpError as error: print(f'查詢空閒時間時發生 API 錯誤: {error}'); return []
    except ValueError as e:
        if 'strptime' in str(e): print(f"日期格式錯誤，請使用 YYYY-MM-DD 格式。 ({e})")
        else: print(f"處理時間時發生數值錯誤: {e}")
        return []
    except Exception as e: print(f'查詢空閒時間時發生未預期錯誤: {e}'); return []

# --- 其他函數 (create_event, create_new_calendar...) 保持不變 ---
def create_event(service, calendar_id_to_write, summary, start_datetime_str, end_datetime_str, description=None):
    """
    2. 在指定的日曆上寫入 event
    """
    if not service:
        print("未提供有效的服務物件。")
        return None
    try:
        tz = pytz.timezone(TIMEZONE)
        start_dt = tz.localize(datetime.datetime.strptime(start_datetime_str, "%Y-%m-%d %H:%M:%S"))
        end_dt = tz.localize(datetime.datetime.strptime(end_datetime_str, "%Y-%m-%d %H:%M:%S"))

        event = {
            'summary': summary,
            'description': description if description else '',
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': TIMEZONE},
            'end': {'dateTime': end_dt.isoformat(), 'timeZone': TIMEZONE},
        }

        print(f"正在日曆 '{calendar_id_to_write}' 上建立事件 '{summary}'...")
        created_event = service.events().insert(calendarId=calendar_id_to_write, body=event).execute()
        print(f"事件已建立: {created_event.get('summary')} ({created_event.get('htmlLink')})")
        return created_event

    except HttpError as error:
        print(f'建立事件時發生 API 錯誤: {error}')
        return None
    except ValueError:
        print(f"日期時間格式錯誤，請使用 YYYY-MM-DD HH:MM:SS 格式。")
        return None
    except Exception as e:
        print(f'建立事件時發生錯誤: {e}')
        return None


def create_new_calendar_owned_by_service_account(service, calendar_summary, calendars_dict):
    if not service: print("未提供有效的服務物件。"); return None
    if calendars_dict is None : print("錯誤：無法讀取日曆字典，無法更新 JSON。"); return None # 檢查 None
    try:
        calendar_body = {'summary': calendar_summary,'timeZone': TIMEZONE}
        print(f"正在建立服務帳戶擁有的新日曆 '{calendar_summary}'...")
        created_calendar = service.calendars().insert(body=calendar_body).execute()
        new_cal_id = created_calendar['id']; new_cal_summary = created_calendar['summary']
        print(f"日曆已建立: {new_cal_summary} (ID: {new_cal_id})")
        print(f"注意：這個日曆的擁有者是服務帳戶。")
        calendars_dict[new_cal_summary] = new_cal_id
        save_json_data(calendars_dict, CALENDARS_JSON_FILE) # 使用輔助函數儲存
        try:
            acl_rule = {'role': 'owner', 'scope': {'type': 'user', 'value': YOUR_EMAIL}}
            service.acl().insert(calendarId=new_cal_id, body=acl_rule).execute()
            print(f"已將新日曆 '{new_cal_summary}' 的擁有者權限分享給 {YOUR_EMAIL}")
        except HttpError as acl_error: print(f"分享新日曆 '{new_cal_summary}' 時發生錯誤: {acl_error}")
        return created_calendar
    except HttpError as error: print(f'建立日曆時發生 API 錯誤: {error}'); return None
    except Exception as e: print(f'建立日曆時發生錯誤: {e}'); return None

