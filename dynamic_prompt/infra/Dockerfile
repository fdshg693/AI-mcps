FROM python:3.13-slim

WORKDIR /app

# uv をインストール
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 依存関係を先にインストール (キャッシュ効率化)
COPY dynamic_prompt/pyproject.toml dynamic_prompt/pyproject.toml
RUN cd dynamic_prompt && uv sync --no-dev --no-install-project

# アプリケーションコードをコピー
COPY dynamic_prompt/ dynamic_prompt/
RUN cd dynamic_prompt && uv sync --no-dev

# 環境変数のデフォルト
ENV TRANSPORT=http
ENV HOST=0.0.0.0
ENV PORT=8080
ENV DB_PATH=/data/vocab.db

EXPOSE 8080

CMD ["uv", "run", "--project", "dynamic_prompt", "dynamic_prompt"]
