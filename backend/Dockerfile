FROM python:3.11-slim AS comskip-builder

WORKDIR /tmp/comskip

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    yasm \
    pkg-config \
    autoconf \
    automake \
    libtool \
    libargtable2-dev \
    libavcodec-dev \
    libavformat-dev \
    libavutil-dev \
    libswscale-dev \
    libpostproc-dev \
  && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch fancybits https://github.com/fancybits/Comskip . \
  && ./autogen.sh \
  && ./configure \
  && make

FROM python:3.11-slim

WORKDIR /app/backend

# Runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libargtable2-0 \
    gosu \
  && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application + tools
COPY backend /app/backend
COPY backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY tools /app/tools
COPY comskip.ini /app/comskip.ini

# Copy comskip binary from builder
COPY --from=comskip-builder /tmp/comskip/comskip /usr/local/bin/comskip
RUN chmod +x /usr/local/bin/comskip

# Ensure repo-provided tools are executable if present
RUN chmod +x /app/tools/bin/*/ffmpeg /app/tools/bin/*/ffprobe /app/tools/bin/*/comskip 2>/dev/null || true

# Create data directories
RUN mkdir -p /app/downloads /app/config \
  && chmod +x /usr/local/bin/docker-entrypoint.sh

# Expose port
EXPOSE 8000

# Run the application
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
