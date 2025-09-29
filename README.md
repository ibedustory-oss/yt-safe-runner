
# YouTube Safe Kids Fetcher (MVP)

サーバーレス(Cloud Run推奨)で、ホワイトリストしたチャンネルの新着動画をYouTube Data APIから取得するバックエンドの最小構成です。

- 言語: Python 3.11
- フレームワーク: Flask
- ストレージ: SQLite（MVP。将来はCloud SQL/Firestoreに置き換え推奨）
- スケジュール: Cloud Scheduler（またはCron）→ HTTP叩く

## できること
- 環境変数 `CHANNEL_IDS`（カンマ区切り）に設定したチャンネルの新着動画を取得
- 直近取得の `publishedAt` をSQLiteに保存して差分取得（`publishedAfter`）
- 結果はJSONで返却（本番はキュー投入やDB保存に置換して下さい）

## 必要な環境変数
- `YOUTUBE_API_KEY`: YouTube Data API v3 のAPIキー
- `CHANNEL_IDS`: チャンネルIDのカンマ区切り（例: `UC5h5YVVGuH0r6o8YbFD9F9A,UC0C-w0YjGpqDXGB8IHb662A`）
  - 例はダミーです。実チャンネルIDに置き換えてください。

## ローカル実行
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export YOUTUBE_API_KEY=YOUR_KEY
export CHANNEL_IDS=CHANNEL_ID1,CHANNEL_ID2
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## エンドポイント
- `GET /health` ヘルスチェック
- `POST /fetch` 手動実行（スケジューラから呼ぶ）
  - レスポンス: 取得した新着動画の配列

## Cloud Run デプロイ（例）
```bash
gcloud builds submit --tag gcr.io/PROJECT_ID/youtube-fetcher
gcloud run deploy youtube-fetcher \
  --image gcr.io/PROJECT_ID/youtube-fetcher \
  --platform managed \
  --region europe-west1 \
  --allow-unauthenticated \
  --set-env-vars YOUTUBE_API_KEY=YOUR_KEY,CHANNEL_IDS=CHAN1,CHAN2
```

## Cloud Scheduler 設定（5分ごと）
Cloud Schedulerから以下のHTTPを叩く設定にします。
- URL: `https://<YOUR_CLOUD_RUN_URL>/fetch`
- メソッド: POST
- ヘッダ: `Content-Type: application/json`
- ボディ: `{}`

## 注意
- SQLiteはCloud Runのコンテナ内に置かれるため、スケールアウト時は共有されません。
  - 本番ではCloud SQL(PostgreSQL)など外部DBに置き換えてください。
- ここではMVPとして新着をJSONで返しています。実運用ではPub/SubやDB保存へ接続してください。
```
