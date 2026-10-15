# Autoguard — stdlib-only Python. One process: web dashboard + built-in scan scheduler.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 AUTOGUARD_DB=/data/autoguard.db PORT=8095
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin autoguard && mkdir -p /data && chown 1000:1000 /data
WORKDIR /app
COPY autoguard /app/autoguard
USER 1000:1000
VOLUME /data
EXPOSE 8095
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8095/healthz',timeout=4)"
CMD ["python", "-m", "autoguard"]
