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

def update_notion_id_property(page_id: str, value: str, property_name: str) -> bool:
    """
    更新指定 Notion 頁面的特定文字屬性 (Rich Text)。

    Args:
        page_id (str): 要更新的 Notion 頁面 ID。
        property_name (str): 要更新的屬性名稱 (需與 Notion 中的名稱完全一致)。
        value (str): 要寫入屬性的文字內容。
        api_base (str): Notion API 的基礎 URL (例如 "https://api.notion.com/v1")。
        headers (dict): 包含驗證資訊等的請求標頭。

    Returns:
        bool: 如果更新成功則返回 True，否則返回 False。
    """
    update_url = f"{NOTION_API_BASE}/pages/{page_id}"

    # 為 Text (Rich Text) 屬性建構 payload
    payload = {
        "properties": {
            property_name: {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": value
                        }
                    }
                ]
            }
        }
    }

    try:
        response = requests.patch(update_url, headers=NOTION_HEADERS, json=payload)

        if response.status_code == 200:
            logger.info(f"Successfully updated Notion page {page_id} property 'Google Event id'.")
            return True
        else:
            logger.error(f"Failed to update Notion page {page_id} property 'Google Event id'. Status: {response.status_code}, Response: {response.text}")
            return False

    except requests.exceptions.RequestException as e:
        logger.error(f"Request error updating Notion page {page_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error updating Notion page {page_id}: {e}")
        return False


def handle_insert_event(name, category, due, page_id):
    calendar_service = authenticate_google_calendar_service_account()

    if name and calendar_service:
        calendar_ids_to_query_list = list(known_calendars.values())
        blocked_time_rules = load_json_data(TIME_JSON_FILE)
        
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

        new_event_object = create_event(calendar_service,
                        calendar_id_to_write=calendar_id, # 使用查找到的 ID
                        summary=name,
                        start_datetime_str=first_slot_start,
                        end_datetime_str=event_end_str,
                        description='透過 Python Service Account API 自動建立的事件')
        if new_event_object:
            event_id = new_event_object.get('id')
            print(f"{name}: 成功建立事件，事件 ID 為: {event_id}")

            update_event_successful = update_notion_id_property(page_id=page_id, value=event_id, property_name="Google Event id")
            update_calendar_successful = update_notion_id_property(page_id=page_id, value=calendar_id, property_name="Google Calendar id")
            if update_event_successful and update_calendar_successful:
                print(f"{name}: Event ID 和日曆 ID 都已成功更新回 Notion 頁面 {page_id}")
            else:
                print(f"{name}: 更新 Event ID 或日曆 ID 回 Notion 頁面 {page_id} 失敗。")
        else:
            print(f"{name}: 建立事件失敗。")

def delete_google_calendar_event(service, calendar_id: str, event_id: str) -> bool:
    """
    從指定的 Google 日曆中刪除特定事件。

    Args:
        service: 已驗證的 Google Calendar API 服務物件。
        calendar_id (str): 事件所在的日曆 ID (例如 'primary' 或特定日曆的 ID)。
        event_id (str): 要刪除的事件 ID。

    Returns:
        bool: 如果刪除成功則返回 True，否則返回 False。
    """
    if not service or not calendar_id or not event_id:
        logger.error("delete_google_calendar_event: Missing required arguments (service, calendar_id, event_id).")
        return False

    try:
        # 呼叫 Google Calendar API 的 delete 方法
        service.events().delete(
            calendarId=calendar_id,
            eventId=event_id
        ).execute()

        logger.info(f"Successfully deleted event '{event_id}' from calendar '{calendar_id}'.")
        print(f"成功從日曆 '{calendar_id}' 刪除事件 '{event_id}'。")
        return True

    except HttpError as error:
        # 處理 API 錯誤
        # 特別處理 404 Not Found 或 410 Gone，表示事件可能已被刪除
        if error.resp.status in [404, 410]:
             logger.warning(f"Event '{event_id}' not found in calendar '{calendar_id}'. It might have already been deleted. Status: {error.resp.status}")
             print(f"警告：在日曆 '{calendar_id}' 中找不到事件 '{event_id}' (可能已被刪除)。狀態碼: {error.resp.status}")
             # 根據您的需求，找不到事件可能也算是一種「成功狀態」（目標是確保它不存在）
             # 如果希望找不到也回傳 True，可以修改這裡。目前設定為回傳 False。
             return False # 或者 return True 如果找不到也算成功
        else:
             logger.error(f"Failed to delete event '{event_id}' from calendar '{calendar_id}'. An API error occurred: {error}")
             print(f"從日曆 '{calendar_id}' 刪除事件 '{event_id}' 失敗。API 錯誤: {error}")
             return False

    except Exception as e:
        logger.error(f"An unexpected error occurred while deleting event '{event_id}' from calendar '{calendar_id}': {e}")
        print(f"刪除日曆 '{calendar_id}' 的事件 '{event_id}' 時發生未預期錯誤: {e}")
        return False

def handle_page_created(page_id: str):
    logger.info(f'Page created: {page_id}')
    name, category, due, google_event_id, google_calender_id = fetch_and_log_page_properties(page_id)

    handle_insert_event(name, category, due, page_id)



def handle_page_updated(page_id):
    logger.info(f'Page updated: {page_id}')
    name, category, due, google_event_id, google_calender_id = fetch_and_log_page_properties(page_id)

    if google_event_id and google_calender_id:
        calendar_service = authenticate_google_calendar_service_account()

        if calendar_service:
            delete_successful = delete_google_calendar_event(
                service=calendar_service,
                calendar_id=google_calender_id,
                event_id=google_event_id
            )

            if delete_successful:
                logger.info(f"Successfully processed deletion for page {page_id}.")
                handle_insert_event(name, category, due, page_id)
            else:
                logger.warning(f"Failed or unable to delete Google Calendar event for deleted page {page_id}.")
        else:
            logger.error("Could not authenticate Google Calendar service to delete event.")
    else:
        logger.info(f"No Google Event ID found or category missing for deleted page {page_id}. No Google Calendar event to delete.")



def handle_page_deleted(page_id):
    logger.info(f'Page deleted: {page_id}')
    name, category, due, google_event_id, google_calender_id = fetch_and_log_page_properties(page_id)

    if google_event_id and google_calender_id:
        calendar_service = authenticate_google_calendar_service_account()

        if calendar_service:
            delete_successful = delete_google_calendar_event(
                service=calendar_service,
                calendar_id=google_calender_id,
                event_id=google_event_id
            )

            if delete_successful:
                logger.info(f"Successfully processed deletion for page {page_id}.")
            else:
                logger.warning(f"Failed or unable to delete Google Calendar event for deleted page {page_id}.")
        else:
            logger.error("Could not authenticate Google Calendar service to delete event.")
    else:
        logger.info(f"No Google Event ID found or category missing for deleted page {page_id}. No Google Calendar event to delete.")


def fetch_and_log_page_properties(page_id):
    url = f"{NOTION_API_BASE}/pages/{page_id}"
    response = requests.get(url, headers=NOTION_HEADERS)

    if response.status_code == 200:
        page = response.json()
        properties = page.get('properties', {})

        for name, prop in properties.items():
            logger.info(f"- {name}: {prop}")
        
        # 拆出去的欄位處理函式
        name = extract_title(properties, 'Name')
        category = extract_select(properties, 'Category')
        due = extract_date(properties, 'Due')
        google_event_id = extract_Google_id(properties, 'Google Event id')
        google_calender_id = extract_Google_id(properties, 'Google Calendar id')

        logger.info(f"Page [{page_id}] Summary:")
        logger.info(f"  Name: {name}")
        logger.info(f"  Category: {category}")
        logger.info(f"  Due: {due}")
        return name, category, due, google_event_id, google_calender_id
    else:
        logger.error(f"Failed to fetch page properties for {page_id}. Status: {response.status_code}, Body: {response.text}")
        return None, None, None

def extract_title(properties, field_name):
    title_data = properties.get(field_name, {}).get("title", [])
    return "".join(part.get("plain_text", "") for part in title_data)

def extract_Google_id(properties, field_name):
    rich_text_data = properties.get(field_name, {}).get("rich_text", [])
    return "".join(part.get("plain_text", "") for part in rich_text_data)

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