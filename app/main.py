
import os
import json
import sqlite3
from datetime import datetime, timezone
from flask import Flask, request, jsonify
import requests

YT_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
CHANNEL_IDS = [c.strip() for c in os.environ.get("CHANNEL_IDS", "").split(",") if c.strip()]

DB_PATH = os.environ.get("DB_PATH", "/tmp/state.db")  # Cloud Runなら/tmpは書き込み可（短期）

app = Flask(__name__)

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS channel_state (channel_id TEXT PRIMARY KEY, last_published_at TEXT)"
        )
        conn.commit()

def get_last_published_at(channel_id: str) -> str | None:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("SELECT last_published_at FROM channel_state WHERE channel_id = ?", (channel_id,))
        row = cur.fetchone()
        return row[0] if row else None

def set_last_published_at(channel_id: str, published_at: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO channel_state(channel_id, last_published_at) VALUES(?, ?) ON CONFLICT(channel_id) DO UPDATE SET last_published_at=excluded.last_published_at",
            (channel_id, published_at),
        )
        conn.commit()

def isoformat(dt: datetime) -> str:
    return dt.replace(microsecond=0).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def fetch_new_videos_for_channel(channel_id: str):
    # 前回取得の最終時刻を得る
    last = get_last_published_at(channel_id)
    if last is None:
        # 初回は直近24時間に限定（無限取得を避ける）
        since = datetime.now(timezone.utc).timestamp() - 24*3600
        published_after = datetime.fromtimestamp(since, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    else:
        published_after = last

    # YouTube Data API: search.list でpublishedAfterフィルタ（チャンネル内最新順）
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

    videos = []
    latest_ts_iso = published_after
    for it in items:
        vid = it["id"]["videoId"]
        sn = it["snippet"]
        published_at = sn["publishedAt"]
        title = sn["title"]
        description = sn.get("description", "")
        thumbnails = sn.get("thumbnails", {})
        channel_title = sn.get("channelTitle", "")

        videos.append({
            "videoId": vid,
            "publishedAt": published_at,
            "title": title,
            "description": description,
            "thumbnails": thumbnails,
            "channelId": channel_id,
            "channelTitle": channel_title,
            "url": f"https://www.youtube.com/watch?v={vid}",
        })
        # 最新のpublishedAtを更新用に保持
        if published_at > latest_ts_iso:
            latest_ts_iso = published_at

    # state更新
    if latest_ts_iso and latest_ts_iso > published_after:
        set_last_published_at(channel_id, latest_ts_iso)

    return videos

@app.get("/health")
def health():
    return jsonify({"ok": True})

@app.post("/fetch")
def fetch():
    if not YT_API_KEY or not CHANNEL_IDS:
        return jsonify({"error": "Missing YOUTUBE_API_KEY or CHANNEL_IDS"}), 400
    init_db()
    all_new = []
    for ch in CHANNEL_IDS:
        try:
            vids = fetch_new_videos_for_channel(ch)
            all_new.extend(vids)
        except Exception as e:
            all_new.append({"channelId": ch, "error": str(e)})
    # ここで本来はPub/SubやDB保存に切り替える
    return jsonify({"count": len(all_new), "videos": all_new})

if __name__ == "__main__":
    # for local debugging
    app.run(host="0.0.0.0", port=8080)
