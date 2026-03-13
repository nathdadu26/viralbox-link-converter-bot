# ── Base image ──────────────────────────────────────────────────────────────
FROM python:3.11-slim

# ── Working directory ────────────────────────────────────────────────────────
WORKDIR /app

# ── Install dependencies ─────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Copy source files ────────────────────────────────────────────────────────
COPY bot.py .
COPY health_check.py .

# ── Koyeb health check port ──────────────────────────────────────────────────
EXPOSE 8000

# ── Start bot ────────────────────────────────────────────────────────────────
CMD ["python", "bot.py"]
