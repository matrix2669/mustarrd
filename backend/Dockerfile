FROM ghcr.io/linuxserver/baseimage-ubuntu:noble AS comskip-builder

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

FROM lscr.io/linuxserver/ffmpeg:latest AS lsffmpeg

FROM ghcr.io/linuxserver/baseimage-ubuntu:noble

WORKDIR /app/backend

# Runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
    libargtable2-0 \
    vainfo \
    libva2 \
    libva-drm2 \
    libdrm2 \
    mesa-va-drivers \
    gosu \
  && if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
       apt-get install -y --no-install-recommends i965-va-driver intel-media-va-driver libigdgmm12; \
     fi \
  && rm -rf /var/lib/apt/lists/*

ENV \
    LIBVA_DRIVERS_PATH="/usr/local/lib/x86_64-linux-gnu/dri:/usr/local/lib/aarch64-linux-gnu/dri:/usr/lib/x86_64-linux-gnu/dri:/usr/lib/aarch64-linux-gnu/dri" \
    LD_LIBRARY_PATH="/usr/local/lib:/usr/local/lib/x86_64-linux-gnu:/usr/local/lib/aarch64-linux-gnu" \
    CATCHUP_FFMPEG_PATH="/usr/local/bin/ffmpegwrapper.sh"

# Install dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application + tools
COPY backend /app/backend
COPY backend/ffmpegwrapper.sh /usr/local/bin/ffmpegwrapper.sh
COPY scripts /app/scripts
COPY backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY tools /app/tools
COPY comskip.ini /app/comskip.ini

# Copy comskip binary from builder
COPY --from=comskip-builder /tmp/comskip/comskip /usr/local/bin/comskip
RUN chmod +x /usr/local/bin/comskip

# Copy ffmpeg + drivers from LinuxServer ffmpeg image
COPY --from=lsffmpeg /usr/local/bin/ffmpeg /usr/local/bin/ffmpeg
COPY --from=lsffmpeg /usr/local/bin/ffprobe /usr/local/bin/ffprobe
COPY --from=lsffmpeg /usr/local/lib/ /usr/local/lib/
COPY --from=lsffmpeg /usr/local/share/ /usr/local/share/

# Ensure repo-provided tools are executable if present
RUN chmod +x /app/tools/bin/*/ffmpeg /app/tools/bin/*/ffprobe /app/tools/bin/*/comskip 2>/dev/null || true
RUN chmod +x /app/scripts/qa/*.sh 2>/dev/null || true
RUN chmod +x /usr/local/bin/ffmpegwrapper.sh

# Create data directories
RUN mkdir -p /app/downloads /app/config \
  && chmod +x /usr/local/bin/docker-entrypoint.sh

# Expose port
EXPOSE 8000

# Run the application
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
