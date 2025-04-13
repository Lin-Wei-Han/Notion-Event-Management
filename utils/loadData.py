import json
import os

def load_json_data(filename):
    """從 JSON 檔案載入數據"""
    try:
        # 如果檔案不存在，創建一個空的列表 (針對 time.json) 或字典 (針對 calendars.json)
        if not os.path.exists(filename):
             default_data = [] if 'time.json' in filename else {}
             save_json_data(default_data, filename) # 嘗試創建空檔案
             print(f"警告：檔案 {filename} 不存在，已創建空檔案。")
             return default_data

        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
            print(f"成功從 {filename} 載入數據。")
            return data
    except FileNotFoundError: # 即使上面檢查過，仍保留以防萬一
        print(f"錯誤：找不到設定檔 {filename}。")
        return None
    except json.JSONDecodeError:
        print(f"錯誤：無法解析 {filename} 的 JSON 格式。請檢查檔案內容。")
        return None
    except Exception as e:
        print(f"讀取 {filename} 時發生未預期錯誤: {e}")
        return None

def save_json_data(data, filename):
    """將數據儲存回 JSON 檔案"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print(f"已成功將更新後的數據儲存至 {filename}。")
        return True
    except Exception as e:
        print(f"儲存數據至 {filename} 時發生錯誤: {e}")
        return False

