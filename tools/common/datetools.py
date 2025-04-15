from typing import Annotated
from datetime import datetime
from semantic_kernel.skill_definition import sk_function

@sk_function(description="Returns today's date in YYYY-MM-DD format.")
def get_today_date() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    return f"Today's date is {today}"

@sk_function(description="Returns the current time in HH:MM format.")
def get_time() -> str:
    current_time = datetime.now().strftime("%H:%M")
    return f"The current time is {current_time}"
