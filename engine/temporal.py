from datetime import datetime
from schemas.rule_schema import ScheduleWindow

def is_within_schedule(now: datetime, schedule: ScheduleWindow):
    day = now.strftime("%a").lower()
    if day not in schedule.days:
        return False
    current_time = now.time()
    return schedule.start_time <= current_time <= schedule.end_time