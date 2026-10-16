#!/usr/bin/env python3
"""
Builds a TRMNL-compatible static dashboard for an Xteink X3 (or X4).

Output (in ./site/<SITE_SECRET>/):
  api/setup        JSON the device calls once when it's first set up
  api/display      JSON the device calls on every wake (image URL + how long to sleep)
  screen-<ts>.bmp  1-bit image: today's Google Tasks + the weather

Runs every 15 minutes on GitHub Actions. Each run recomputes `refresh_rate`
so the device's next wake lands near the next slot (default 04:00 and 12:00).

Environment:
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN  (required unless DEMO=1)
  TASKLIST_NAME   Google Tasks list to show (default: first list, usually "My Tasks")
  SHOW_UNDATED    "1" to also list tasks with no due date (default "0")
  LAT, LON        weather location (default Cambridge, MA)
  TZ_NAME         IANA time zone (default America/New_York)
  SLOTS           comma-separated HH:MM wake times (default "04:00,12:00")
  INTERVAL_HOURS  if set (e.g. "8"), wake every N hours instead of at SLOTS
  WIDTH, HEIGHT   screen size in pixels (default 792x528 for the X3; X4 is 800x480)
  SITE_SECRET     hard-to-guess folder name for the published files
  PUBLIC_BASE     full public URL of that folder (auto-derived on GitHub)
  DEMO            "1" to use sample tasks/weather without calling any API
"""

import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont

# ---------------- config ----------------
TZ = ZoneInfo(os.environ.get("TZ_NAME", "America/New_York"))
LAT = float(os.environ.get("LAT", "42.3736"))
LON = float(os.environ.get("LON", "-71.1097"))
SLOTS = [s.strip() for s in os.environ.get("SLOTS", "04:00,12:00").split(",") if s.strip()]
INTERVAL_HOURS = float(os.environ.get("INTERVAL_HOURS") or 0)
W = int(os.environ.get("WIDTH", "792"))
H = int(os.environ.get("HEIGHT", "528"))
TASKLIST_NAME = os.environ.get("TASKLIST_NAME", "").strip()
SHOW_UNDATED = os.environ.get("SHOW_UNDATED", "0") == "1"
DEMO = os.environ.get("DEMO", "0") == "1"
SITE_SECRET = os.environ.get("SITE_SECRET", "dashboard").strip("/")
CRON_MINUTES = 15  # how often the workflow runs

OUT = Path(os.environ.get("OUT_DIR", "site")) / SITE_SECRET

FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/Library/Fonts", "/System/Library/Fonts/Supplemental"]


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    for d in FONT_DIRS:
        p = Path(d) / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


F_DATE = font("DejaVuSans-Bold.ttf", 34)
F_SUB = font("DejaVuSans.ttf", 20)
F_TEMP = font("DejaVuSans-Bold.ttf", 56)
F_BODY = font("DejaVuSans.ttf", 24)
F_BODY_B = font("DejaVuSans-Bold.ttf", 24)
F_SMALL = font("DejaVuSans.ttf", 16)


# ---------------- data ----------------
def google_token() -> str:
    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "refresh_token": os.environ["GOOGLE_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def fetch_tasks(today: date) -> tuple[list[dict], list[str]]:
    """Returns (dated tasks due today or earlier, undated task titles)."""
    tok = google_token()
    hdr = {"Authorization": f"Bearer {tok}"}
    lists = requests.get(
        "https://tasks.googleapis.com/tasks/v1/users/@me/lists", headers=hdr, timeout=20
    ).json().get("items", [])
    if not lists:
        return [], []
    tl = next((l for l in lists if l["title"].lower() == TASKLIST_NAME.lower()), None) if TASKLIST_NAME else None
    tl = tl or lists[0]

    items, page = [], None
    while True:
        params = {"showCompleted": "false", "showHidden": "false", "maxResults": "100"}
        if page:
            params["pageToken"] = page
        r = requests.get(
            f"https://tasks.googleapis.com/tasks/v1/lists/{tl['id']}/tasks",
            headers=hdr, params=params, timeout=20,
        ).json()
        items += r.get("items", [])
        page = r.get("nextPageToken")
        if not page:
            break

    dated, undated = [], []
    for t in items:
        title = (t.get("title") or "").strip()
        if not title or t.get("parent"):  # skip blanks and subtasks
            continue
        if t.get("due"):
            d = date.fromisoformat(t["due"][:10])  # Google stores due as a date
            if d <= today:
                dated.append({"title": title, "overdue": d < today})
        else:
            undated.append(title)
    dated.sort(key=lambda x: (not x["overdue"], x["title"].lower()))
    return dated, undated


WMO = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Cloudy", 45: "Fog", 48: "Fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Showers", 81: "Showers", 82: "Heavy showers", 85: "Snow showers", 86: "Snow showers",
    95: "Thunderstorms", 96: "Thunderstorms", 99: "Thunderstorms",
}


def fetch_weather() -> dict:
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": LAT, "longitude": LON,
            "current": "temperature_2m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "temperature_unit": "fahrenheit", "timezone": str(TZ), "forecast_days": 2,
        },
        timeout=20,
    )
    r.raise_for_status()
    j = r.json()
    d = j["daily"]
    return {
        "now": round(j["current"]["temperature_2m"]),
        "hi": round(d["temperature_2m_max"][0]), "lo": round(d["temperature_2m_min"][0]),
        "rain": d["precipitation_probability_max"][0] or 0,
        "desc": WMO.get(d["weather_code"][0], ""),
        "tmr_hi": round(d["temperature_2m_max"][1]), "tmr_lo": round(d["temperature_2m_min"][1]),
        "tmr_desc": WMO.get(d["weather_code"][1], ""),
    }


# ---------------- drawing ----------------
def wrap(draw: ImageDraw.ImageDraw, text: str, f, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textlength(test, font=f) <= width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def render(now: datetime, tasks: list[dict], undated: list[str], wx: dict | None) -> Image.Image:
    img = Image.new("1", (W, H), 1)
    d = ImageDraw.Draw(img)
    m = 28
    left_w = int(W * 0.36)

    # Left column: date + weather
    d.text((m, m), now.strftime("%A"), font=F_DATE, fill=0)
    d.text((m, m + 44), now.strftime("%B %-d"), font=F_SUB, fill=0)
    y = m + 100
    if wx:
        d.text((m, y), f"{wx['now']}°", font=F_TEMP, fill=0)
        y += 72
        d.text((m, y), wx["desc"], font=F_BODY_B, fill=0)
        y += 34
        d.text((m, y), f"High {wx['hi']}°  Low {wx['lo']}°", font=F_SUB, fill=0)
        y += 30
        d.text((m, y), f"Rain {wx['rain']}%", font=F_SUB, fill=0)
        y += 48
        d.text((m, y), "Tomorrow", font=F_SMALL, fill=0)
        y += 22
        for line in wrap(d, f"{wx['tmr_desc']}, {wx['tmr_hi']}° / {wx['tmr_lo']}°", F_SUB, left_w - m - 12):
            d.text((m, y), line, font=F_SUB, fill=0)
            y += 26
    else:
        d.text((m, y), "Weather unavailable", font=F_SUB, fill=0)

    # Divider
    d.line([(left_w, m), (left_w, H - m)], fill=0, width=2)

    # Right column: tasks
    x = left_w + 28
    tw = W - x - m
    d.text((x, m), "Today", font=F_DATE, fill=0)
    y = m + 56
    rows = [(t["title"], t["overdue"]) for t in tasks]
    if SHOW_UNDATED:
        rows += [(t, False) for t in undated]
    if not rows:
        d.text((x, y), "Nothing due. Enjoy the day.", font=F_BODY, fill=0)
    bottom = H - m - 22
    shown = 0
    for title, overdue in rows:
        label = f"{title} (late)" if overdue else title
        lines = wrap(d, label, F_BODY, tw - 36)
        need = 34 * len(lines)
        if y + need > bottom:
            break
        d.rectangle([x, y + 5, x + 20, y + 25], outline=0, width=2)
        for i, line in enumerate(lines):
            d.text((x + 34, y + i * 34), line, font=F_BODY, fill=0)
        y += need + 6
        shown += 1
    if shown < len(rows):
        d.text((x, bottom), f"+ {len(rows) - shown} more", font=F_SMALL, fill=0)

    d.text((W - m, H - 18), f"Updated {now.strftime('%-I:%M %p')}", font=F_SMALL, fill=0, anchor="rs")
    return img


# ---------------- schedule ----------------
def seconds_until_next_slot(now: datetime) -> int:
    """Seconds from the device's likely fetch time to the next slot."""
    fetch = now + timedelta(minutes=CRON_MINUTES / 2)  # device fetches sometime before the next run
    best = None
    for day in (0, 1):
        for s in SLOTS:
            hh, mm = map(int, s.split(":"))
            cand = (fetch + timedelta(days=day)).replace(hour=hh, minute=mm, second=0, microsecond=0)
            if cand > fetch + timedelta(minutes=CRON_MINUTES) and (best is None or cand < best):
                best = cand
    return max(300, int((best - fetch).total_seconds()))


def public_base() -> str:
    if os.environ.get("PUBLIC_BASE"):
        return os.environ["PUBLIC_BASE"].rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "owner/repo")
    owner, name = repo.split("/")
    return f"https://{owner.lower()}.github.io/{name}/{SITE_SECRET}"


def main() -> None:
    now = datetime.now(TZ)
    if DEMO:
        tasks = [
            {"title": "Water the plants", "overdue": True},
            {"title": "Take vitamins", "overdue": False},
            {"title": "Return library book before the branch closes at 6", "overdue": False},
            {"title": "15 minutes of Spanish", "overdue": False},
            {"title": "Pick up dry cleaning", "overdue": False},
        ]
        undated = ["Book dentist appointment"]
        wx = {"now": 54, "hi": 61, "lo": 47, "rain": 20, "desc": "Partly cloudy",
              "tmr_hi": 58, "tmr_lo": 44, "tmr_desc": "Light rain"}
    else:
        try:
            tasks, undated = fetch_tasks(now.date())
        except Exception as e:
            print(f"Tasks failed: {e}", file=sys.stderr)
            tasks, undated = [{"title": "Couldn't load tasks", "overdue": False}], []
        try:
            wx = fetch_weather()
        except Exception as e:
            print(f"Weather failed: {e}", file=sys.stderr)
            wx = None

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "api").mkdir(exist_ok=True)
    stamp = str(int(time.time()))
    fname = f"screen-{stamp}.bmp"
    render(now, tasks, undated, wx).save(OUT / fname)
    render(now, tasks, undated, wx).convert("L").save(OUT / "preview.png")

    base = public_base()
    refresh = int(INTERVAL_HOURS * 3600) if INTERVAL_HOURS > 0 else seconds_until_next_slot(now)
    display = {
        "status": 0, "image_url": f"{base}/{fname}", "filename": f"screen-{stamp}",
        "refresh_rate": refresh, "update_firmware": False, "firmware_url": None,
        "reset_firmware": False, "special_function": "none",
    }
    setup = {
        "status": 200, "api_key": "static-dashboard", "friendly_id": "XTEINK",
        "image_url": f"{base}/{fname}", "filename": f"screen-{stamp}", "message": "Device set up",
    }
    (OUT / "api" / "display").write_text(json.dumps(display))
    (OUT / "api" / "setup").write_text(json.dumps(setup))
    Path(OUT.parent / "index.html").write_text("<!doctype html><title>.</title>")
    print(f"Built {fname}; device sleeps {refresh}s ({refresh/3600:.1f} h); base {base}")


if __name__ == "__main__":
    main()
