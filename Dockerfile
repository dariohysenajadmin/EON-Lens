# Lens deployment image for Render (or any Docker host).
# Streamlit Cloud uses packages.txt for apt and requirements.txt for pip.
# Render needs an explicit Dockerfile so we install ffmpeg ourselves.

FROM python:3.11-slim

# System dependencies:
#   ffmpeg  - video frame extraction + audio conversion
#   curl    - useful for health checks
#   ca-certificates - for HTTPS to Groq, Anthropic, Supadata, YouTube
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better layer caching)
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the app
COPY . .

# Render injects PORT but defaults to 10000 if unset
ENV PORT=10000
EXPOSE 10000

# Streamlit defaults assume a desktop browser session; on a server we need:
#   --server.address=0.0.0.0  bind to all interfaces (Render needs this)
#   --server.port=$PORT       use the port Render assigns
#   --server.headless=true    don't try to open a browser
#   --browser.gatherUsageStats=false  no telemetry
CMD streamlit run app.py \
    --server.port=$PORT \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.enableCORS=false \
    --browser.gatherUsageStats=false
