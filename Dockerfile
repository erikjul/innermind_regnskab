FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 REGNSKAB_DATA_DIR=/data REGNSKAB_BACKUP_DIR=/backup
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd -r -u 10001 regnskab && mkdir -p /data /backup && chown regnskab:regnskab /data /backup
USER regnskab
VOLUME ["/data", "/backup"]
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/sundhed').status==200 else 1)"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
