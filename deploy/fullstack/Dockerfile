FROM node:24-bookworm-slim AS node_runtime

FROM python:3.14-slim-bookworm
COPY --from=node_runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node_runtime /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && apt-get update \
 && apt-get install -y --no-install-recommends libstdc++6 procps tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10001 --create-home studio
WORKDIR /studio
COPY backend/requirements-lock.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements-lock.txt
COPY --chown=studio:studio frontend/package.json frontend/package-lock.json ./frontend/
USER studio
RUN npm --prefix frontend ci --no-audit
COPY --chown=studio:studio frontend ./frontend
COPY --chown=studio:studio backend ./backend
COPY --chown=studio:studio scripts ./scripts
COPY --chown=studio:studio tests ./tests
COPY --chown=studio:studio deploy/cloudflare/worker.mjs ./deploy/cloudflare/worker.mjs
ENV NEXT_TELEMETRY_DISABLED=1
CMD ["python","scripts/local_fullstack.py","verify"]
