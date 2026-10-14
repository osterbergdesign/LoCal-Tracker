"""Constants for the Matkoll integration."""

DOMAIN = "matkoll"
PANEL_URL = "matkoll"
STATIC_URL = "/matkoll_static"
MEALS = ("breakfast", "lunch", "dinner", "snack")
MEAL_LABELS = {"breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snack"}
# When planned meals show up in the Home Assistant calendar (local time).
MEAL_TIMES = {"breakfast": (7, 30, 30), "lunch": (12, 0, 60), "snack": (15, 0, 30), "dinner": (18, 0, 60)}
