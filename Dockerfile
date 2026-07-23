# Stage 1: build the React video composition into a static bundle.
FROM node:20-slim AS render-build
WORKDIR /render
COPY render/package.json render/package-lock.json ./
RUN npm ci
COPY render/ ./
RUN npm run build

# Stage 2: the actual app — Python + Playwright's Chromium + ffmpeg (bundled
# by the imageio-ffmpeg pip package, no separate apt install needed).
FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium

COPY . .
COPY --from=render-build /render/dist ./render/dist
COPY --from=render-build /render/node_modules/katex/dist ./render/node_modules/katex/dist

RUN mkdir -p jobs

ENV PORT=7864
EXPOSE 7864

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
