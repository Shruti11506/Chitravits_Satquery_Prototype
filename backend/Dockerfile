FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libexpat1 \
    libgomp1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# SatQuery agent source (vendored and committed for inspection at backend/satquery).
# Imported directly from /app/satquery at runtime -- no pip install, so there is
# no duplicate copy in site-packages. Every satquery runtime dependency is already
# pinned in requirements.txt above.
COPY satquery ./satquery

COPY app ./app

EXPOSE 8000

# Hosts like Render/Railway/Cloud Run inject $PORT; locally it stays 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
