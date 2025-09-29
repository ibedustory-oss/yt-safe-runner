import os
import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import requests
from flask import Flask, request, jsonify

# ── Environment ────────────────────────────────────────────────────────────────
YT_API_KEY: str = os.environ.get("YOUTUBE_API_KEY", "")
CHANNEL_IDS: List[str] = [c.strip() for c in os.environ.get("CHANNEL_IDS", "").split(",") if c.strip()]

# Cloud Run では /tmp が書き込み可。MVP用。→本番はCloud SQL等へ置換推奨
DB_PATH: str = os.environ.get("DB_PATH", "/tmp/state.db")

app = Flask(__name__)

# ── DB helpers ────────────────────────────────────────────────────────────────
def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS channel_state (
              channel_id TEXT PRIMARY KEY,
              last_published_at TEXT
            )
            """
        )
        conn.commit()

def get_last_published_at(channel_id: str) -> Optional[str]:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "SELECT last_published_at FROM channel_state WHERE channel_id = ?",
            (channel_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None

def set_last_published_at(channel_id: str, published_at: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO channel_state(channel_id, last_published_at)
            VALUES(?, ?)
            ON CONFLICT(channel_id)
            DO UPDATE SET last_published_at=excluded.last_published_at
            """,
            (channel_id, published_at),
        )
        conn.commit()

# ── YouTube fetcher ───────────────────────────────────────────────────────────
def fetch_new_videos_for_channel(channel_id: str) -> List[Dict[str, Any]]:
    """
    指定チャンネルの新着動画を YouTube Data API で取得。
    初回は直近24時間に限定（無限取得を避ける）。
    以降は DB の last_published_at を publishedAfter に使用。
    """
    last = get_last_published_at(channel_id)
    if last is None:
        since = datetime.now(timezone.utc).timestamp() - 24 * 3600
        published_after = datetime.fromtimestamp(since, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    else:
        published_after = last

    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "key": YT_API_KEY,
        "channelId": channel_id,
        "part": "id,snippet",
        "type": "video",
        "order": "date",
        "publishedAfter": published_after,
        "maxResults": 50,
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    items = data.get("items", [])

    videos: List[Dict[str, Any]] = []
    latest_ts_iso = published_after
    for it in items:
        vid = it["id"]["videoId"]
        sn = it["snippet"]
        published_at = sn["publishedAt"]
        title = sn.get("title", "")
        description = sn.get("description", "")
        thumbnails = sn.get("thumbnails", {})
        channel_title = sn.get("channelTitle", "")

        videos.append(
            {
                "videoId": vid,
                "publishedAt": published_at,
                "title": title,
                "description": description,
                "thumbnails": thumbnails,
                "channelId": channel_id,
                "channelTitle": channel_title,
                "url": f"https://www.youtube.com/watch?v={vid}",
            }
        )
        if published_at > latest_ts_iso:
            latest_ts_iso = published_at

    if latest_ts_iso and latest_ts_iso > published_after:
        set_last_published_at(channel_id, latest_ts_iso)

    return videos

# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    return jsonify(
        {
            "ok": True,
            "service": "YouTube Safe Kids Fetcher (MVP)",
            "try": ["GET /health", "POST /fetch", "GET /fetch"],
            "channels": CHANNEL_IDS,
        }
    )

@app.get("/health")
def health():
    return jsonify({"ok": True})

@app.route("/fetch", methods=["POST", "GET"])
def fetch():
    if not YT_API_KEY or not CHANNEL_IDS:
        return jsonify({"error": "Missing YOUTUBE_API_KEY or CHANNEL_IDS"}), 400

    init_db()
    all_new: List[Dict[str, Any]] = []
    for ch in CHANNEL_IDS:
        try:
            vids = fetch_new_videos_for_channel(ch)
            all_new.extend(vids)
        except Exception as e:
            all_new.append({"channelId": ch, "error": str(e)})

    return jsonify({"count": len(all_new), "videos": all_new})

# ── Local debug ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # ローカル実行用（Cloud Runではgunicornで起動）
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
