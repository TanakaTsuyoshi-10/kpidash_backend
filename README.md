# MaruokaKPI Backend

KPI管理システムのバックエンドAPI

## 技術スタック

- Python 3.11
- FastAPI
- Supabase (PostgreSQL)
- Google Cloud Run

## ローカル開発

### 環境構築

```bash
# 仮想環境作成
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 依存関係インストール
pip install -r requirements.txt

# 環境変数設定
cp .env.example .env
# .env ファイルを編集
```

### 起動

```bash
uvicorn app.main:app --reload --port 8000
```

### API ドキュメント

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Docker

### ローカルでビルド・実行

```bash
# ビルド
docker build -t maruoka-kpi-backend .

# 実行
docker run -p 8080:8080 --env-file .env maruoka-kpi-backend
```

### ヘルスチェック

```bash
curl http://localhost:8080/health
```

## API エンドポイント

| メソッド | エンドポイント | 説明 |
|---------|---------------|------|
| GET | /health | ヘルスチェック |
| GET | /docs | Swagger UI |
| GET | /auth/me | 認証ユーザー情報 |
| GET | /kpi/departments | 部門一覧 |
| GET | /kpi/summary | KPIサマリー |
| POST | /upload/csv | CSVアップロード |
| POST | /upload/excel | Excelアップロード |
| GET | /api/v1/templates/financial | 財務テンプレートDL |
| GET | /api/v1/templates/manufacturing | 製造テンプレートDL |
| GET | /api/v1/manufacturing | 製造分析データ |
| GET | /api/v1/finance | 財務分析データ |

## 環境変数

| 変数名 | 説明 | 必須 |
|--------|------|------|
| SUPABASE_URL | Supabase プロジェクトURL | Yes |
| SUPABASE_ANON_KEY | Supabase Anon Key | Yes |
| SUPABASE_SERVICE_ROLE_KEY | Supabase Service Role Key | Yes |
| JWT_SECRET | JWT 署名用シークレット | Yes |
| APP_ENV | 環境（development/production） | No |
| DEBUG | デバッグモード（true/false） | No |
| ALLOWED_ORIGINS | CORS許可オリジン | No |

## ディレクトリ構造

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPIエントリーポイント
│   ├── core/
│   │   ├── config.py           # 環境変数管理
│   │   └── security.py         # JWT検証ロジック
│   ├── api/
│   │   ├── deps.py             # 依存注入
│   │   └── endpoints/          # 各エンドポイント
│   ├── services/               # ビジネスロジック
│   └── schemas/                # Pydanticモデル
├── Dockerfile
├── .dockerignore
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## デプロイ

### Cloud Run へのデプロイ

```bash
# Google Cloud プロジェクト設定
gcloud config set project YOUR_PROJECT_ID

# Cloud Build でビルド & デプロイ
gcloud run deploy maruoka-kpi-backend \
  --source . \
  --region asia-northeast1 \
  --allow-unauthenticated
```

## ライセンス

社内利用限定
