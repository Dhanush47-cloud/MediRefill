FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr poppler-utils && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /var/data/private_uploads
EXPOSE 10000
CMD ["sh", "-c", "python -c 'import app; app.init_db()' && gunicorn app:app --workers 2 --bind 0.0.0.0:${PORT:-10000} --timeout 120"]
