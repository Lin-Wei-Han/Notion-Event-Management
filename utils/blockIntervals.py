import datetime

# --- 屏蔽時間處理函數 ---
def get_blocked_intervals_for_date(blocked_rules, target_date, tz):
    """根據規則和目標日期，產生當天生效的屏蔽時間段"""
    intervals = []
    target_weekday = target_date.weekday() # Monday is 0 and Sunday is 6

    # 將 routine 名稱映射到星期幾數字
    weekday_map = {
        "weekly_mon": 0, "weekly_tue": 1, "weekly_wed": 2,
        "weekly_thu": 3, "weekly_fri": 4, "weekly_sat": 5, "weekly_sun": 6
    }

    for rule in blocked_rules:
        routine = rule.get("routine", "").lower()
        applies_today = False

        if routine == "daily":
            applies_today = True
        elif routine == "weekday":
            if 0 <= target_weekday <= 4: # 週一到週五
                applies_today = True
        elif routine in weekday_map:
            if target_weekday == weekday_map[routine]:
                applies_today = True

        if applies_today:
            try:
                start_time = datetime.datetime.strptime(rule["start_time"], "%H:%M:%S").time()
                end_time = datetime.datetime.strptime(rule["end_time"], "%H:%M:%S").time()

                start_dt = tz.localize(datetime.datetime.combine(target_date, start_time))
                # 處理跨午夜的情況 (例如 22:00 - 06:00)
                if end_time <= start_time:
                     # 結束時間在隔天
                     end_dt = tz.localize(datetime.datetime.combine(target_date + datetime.timedelta(days=1), end_time))
                else:
                     end_dt = tz.localize(datetime.datetime.combine(target_date, end_time))

                intervals.append({"start": start_dt, "end": end_dt})
            except (ValueError, KeyError) as e:
                print(f"警告：處理屏蔽規則時出錯: {rule}, 錯誤: {e}")
                continue # 跳過格式錯誤的規則

    return intervals

