FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
RUN pip install --no-cache-dir . && playwright install chromium

ENV TIKSOCKET_HOME=/data \
    TIKSOCKET_HOST=0.0.0.0 \
    TIKSOCKET_PORT=8787
VOLUME ["/data"]
EXPOSE 8787

ENTRYPOINT ["tiksocket"]
CMD ["serve", "--listen"]
