import os
import json
import time
import hashlib
from pathlib import Path
from datetime import datetime, timezone

import requests


API_URL = "https://trouverunlogement.lescrous.fr/api/fr/search/47"

SEARCH_URL = (
"https://trouverunlogement.lescrous.fr/"
)

PAYLOAD = {
    "idTool": 47,
    "need_aggregation": True,
    "page": 1,
    "pageSize": 24,
    "sector": None,
    "occupationModes": [],
    "location": [
        {"lon": -9.9079, "lat": 51.7087},
        {"lon": 14.3224, "lat": 40.5721},
    ],
    "residence": None,
    "precision": 3,
    "equipment": [],
    "price": {"max": 10000000},
    "area": {"min": 0},
    "adaptedPmr": False,
    "toolMechanism": "residual",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://trouverunlogement.lescrous.fr",
    "Referer": SEARCH_URL,
}

STATE_FILE = Path("last_seen.json")
CHECK_EVERY = 180  # 3 minutes


def get_session():
    session = requests.Session()
    session.headers.update(HEADERS)

    # First visit the website to obtain any normal anonymous cookies.
    try:
        session.get(SEARCH_URL, timeout=20)
    except requests.RequestException as e:
        print("Initial website request failed:", e)

    return session


def fetch_rooms(session):
    response = session.post(
        API_URL,
        json=PAYLOAD,
        timeout=30,
    )

    print(
        datetime.now(timezone.utc).isoformat(),
        "HTTP",
        response.status_code,
    )

    response.raise_for_status()

    data = response.json()

    results = data.get("results", {})
    items = results.get("items", [])
    total = results.get("total", {}).get("value", 0)

    print("CROUS total:", total)
    print("Items:", len(items))

    return items


def room_id(room):
    # Prefer a stable ID if CROUS provides one.
    for key in (
        "id",
        "_id",
        "uuid",
        "housingId",
        "housing_id",
        "residenceId",
    ):
        if room.get(key) is not None:
            return str(room[key])

    # Otherwise hash the complete room object.
    raw = json.dumps(
        room,
        sort_keys=True,
        ensure_ascii=False,
    )

    return hashlib.sha256(raw.encode()).hexdigest()


def load_previous():
    if not STATE_FILE.exists():
        return set()

    try:
        data = json.loads(STATE_FILE.read_text())
        return set(data)
    except Exception:
        return set()


def save_current(rooms):
    ids = [room_id(room) for room in rooms]
    STATE_FILE.write_text(
        json.dumps(ids, ensure_ascii=False, indent=2)
    )


def send_ntfy(rooms):
    topic = os.environ.get("NTFY_TOPIC")

    if not topic:
        print("ERROR: NTFY_TOPIC secret is missing")
        return

    lines = [
        "🚨 CROUS BESANÇON — LOGEMENT DISPONIBLE 🚨",
        "",
        f"{len(rooms)} logement(s) detected.",
        "",
    ]

    for i, room in enumerate(rooms[:10], 1):
        lines.append(f"🏠 Logement #{i}")

        # Try to display useful fields if they exist.
        for key in (
            "name",
            "title",
            "residenceName",
            "residence",
            "rent",
            "price",
            "surface",
        ):
            if key in room:
                lines.append(f"{key}: {room[key]}")

        lines.append("")

    lines.append(f"🔗 {SEARCH_URL}")

    message = "\n".join(lines)

    response = requests.post(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers={
            "Title": "CROUS BESANÇON",
            "Priority": "5",
            "Tags": "rotating_light,house",
            "Click": SEARCH_URL,
        },
        timeout=20,
    )

    response.raise_for_status()

    print("📱 ntfy notification sent!")


def check_once(session):
    try:
        rooms = fetch_rooms(session)

        previous = load_previous()
        current = {room_id(room): room for room in rooms}

        new_rooms = [
            room
            for rid, room in current.items()
            if rid not in previous
        ]

        if new_rooms:
            print("🚨 NEW ROOMS:", len(new_rooms))
            send_ntfy(new_rooms)

        save_current(rooms)

    except Exception as e:
        print("CHECK ERROR:", repr(e))


def main():
    print("===================================")
    print(" CROUS BESANÇON MONITOR")
    print(" Polling every 3 minutes")
    print("===================================")

    session = get_session()

    while True:
        started = time.monotonic()

        check_once(session)

        elapsed = time.monotonic() - started
        sleep_time = max(0, CHECK_EVERY - elapsed)

        print(f"Next check in {sleep_time:.0f} seconds...")
        time.sleep(sleep_time)


if __name__ == "__main__":
    main()
