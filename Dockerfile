# Barcode decoder for browsers without a built-in one (iPhone Safari, Firefox).
FROM node:22-alpine AS vendor
WORKDIR /v
RUN npm pack @zxing/library@0.21 >/dev/null && tar xzf zxing-library-*.tgz \
 && cp package/umd/index.min.js /v/zxing.min.js

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY --from=vendor /v/zxing.min.js ./app/static/vendor/zxing.min.js
RUN useradd --system --uid 1000 local-tracker && mkdir -p /data && chown local-tracker /data
USER local-tracker
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
