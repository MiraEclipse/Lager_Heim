# Lager Heim – Container-Image (läuft auf ARM64/Raspberry Pi und x86_64)
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LAGER_DATA=/data \
    LAGER_PORT=8443

WORKDIR /opt/lager
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && useradd --uid 1000 --create-home --shell /usr/sbin/nologin lager \
 && mkdir -p /data && chown lager:lager /data

COPY app ./app

USER lager
VOLUME ["/data"]
EXPOSE 8443

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import ssl,urllib.request;urllib.request.urlopen('https://127.0.0.1:8443/',context=ssl._create_unverified_context(),timeout=4)"

CMD ["python", "-m", "app.cli", "serve"]
