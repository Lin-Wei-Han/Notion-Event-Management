from dotenv import load_dotenv, find_dotenv
from utils.loadData import *
from utils.googleCalendar import *
import requests
import logging
import os

load_dotenv(find_dotenv())

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


config_dir = './config'
credentials_dir = './credentials'

SERVICE_ACCOUNT_FILE = os.path.join(credentials_dir, 'service_account_key.json')
CALENDARS_JSON_FILE = os.path.join(config_dir, 'calendars.json')
TIME_JSON_FILE = os.path.join(config_dir, 'time.json') 

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

known_calendars = load_json_data(CALENDARS_JSON_FILE)
blocked_time_rules = load_json_data(TIME_JSON_FILE)


def handle_page_created(page_id):
    logger.info(f'Page created: {page_id}')
    name, category, due = fetch_and_log_page_properties(page_id)

    calendar_service = authenticate_google_calendar_service_account()

    if name and calendar_service:
        calendar_ids_to_query_list = list(known_calendars.values())
        free_slots_result = find_free_slots_multi_calendar(
            calendar_service, due, calendar_ids_to_query_list, blocked_time_rules,
            start_hour=8, end_hour=24, min_duration_hours=2
        )
        first_slot_start = free_slots_result[0]['start']

        # 如果有空閒則插入，沒有則強制插入早上八點
        if free_slots_result:
            event_start_dt = datetime.datetime.strptime(first_slot_start, "%Y-%m-%d %H:%M:%S")
        else:
            event_start_dt = datetime.datetime.strptime(f'{due} 08:00:00', "%Y-%m-%d %H:%M:%S")

        calendar_id = get_or_create_calendar_id(calendar_service, category, known_calendars)
            
        event_end_dt = event_start_dt + datetime.timedelta(hours=2) # 建立 2 小時事件
        event_end_str = event_end_dt.strftime("%Y-%m-%d %H:%M:%S")

        create_event(calendar_service,
                    calendar_id_to_write=calendar_id, # 使用查找到的 ID
                    summary=name,
                    start_datetime_str=first_slot_start,
                    end_datetime_str=event_end_str,
                    description='透過 Python Service Account API 自動建立的事件')



def handle_page_updated(page_id):
    logger.info(f'Page updated: {page_id}')
    fetch_and_log_page_properties(page_id)


def handle_page_deleted(page_id):
    logger.info(f'Page deleted: {page_id}')
    fetch_and_log_page_properties(page_id)


def fetch_and_log_page_properties(page_id):
    url = f"{NOTION_API_BASE}/pages/{page_id}"
    response = requests.get(url, headers=NOTION_HEADERS)

    if response.status_code == 200:
        page = response.json()
        properties = page.get('properties', {})
        
        # 拆出去的欄位處理函式
        name = extract_title(properties, 'Name')
        category = extract_select(properties, 'Category')
        due = extract_date(properties, 'Due')

        logger.info(f"Page [{page_id}] Summary:")
        logger.info(f"  Name: {name}")
        logger.info(f"  Category: {category}")
        logger.info(f"  Due: {due}")
        return name, category, due
    else:
        logger.error(f"Failed to fetch page properties for {page_id}. Status: {response.status_code}, Body: {response.text}")
        return None, None, None

def extract_title(properties, field_name):
    title_data = properties.get(field_name, {}).get("title", [])
    return "".join(part.get("plain_text", "") for part in title_data)


def extract_select(properties, field_name):
    # 先取得 category 屬性的資料，如果不存在則為空字典
    category_prop = properties.get(field_name, {})
    # 取得 select 的部分
    select_data = category_prop.get("select") # 不要給預設值 {}，這樣才能判斷是不是 None

    # 檢查 select_data 是否存在且不是 None
    if select_data:
        return select_data.get("name") # 如果 select_data 存在，才去取 name
    else:
        return None # 如果 category 屬性不存在，或 select 部分是 None，則回傳 None


def extract_date(properties, field_name):
    from datetime import datetime
    date_str = properties.get(field_name, {}).get("date", {}).get("start", None)
    if date_str:
        try:
            return datetime.fromisoformat(date_str).date().isoformat()
        except ValueError:
            logger.warning(f"Invalid date format for {field_name}: {date_str}")
            return None
    return None

def get_or_create_calendar_id(calendar_service, category, known_calendars):
    """
    根據類別獲取或創建日曆 ID。
    
    Args:
        calendar_service: Google Calendar API 服務物件
        category: 日曆類別名稱
        known_calendars: 已知日曆的字典
        
    Returns:
        str: 選定的日曆 ID
    """
    if category is None:
        category = "Personal"
    else:
        if category not in known_calendars:
            new_cal = create_new_calendar_owned_by_service_account(
                calendar_service,
                category,
                known_calendars # 傳入目前的日曆字典以供更新
            )
            if new_cal:
                calendar_id_to_write = new_cal['id']
                return calendar_id_to_write
            else:
                category = "Personal"
    return known_calendars.get(category)