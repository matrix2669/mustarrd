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

FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./
RUN npm run build

FROM lscr.io/linuxserver/ffmpeg:latest AS lsffmpeg

FROM ghcr.io/linuxserver/baseimage-ubuntu:noble

WORKDIR /app/backend

# Runtime deps
RUN sed -i 's|http://ports.ubuntu.com/ubuntu-ports|https://ports.ubuntu.com/ubuntu-ports|g' /etc/apt/sources.list \
  && sed -i 's|http://archive.ubuntu.com/ubuntu|https://archive.ubuntu.com/ubuntu|g' /etc/apt/sources.list \
  && apt-get update -o Acquire::Retries=3 \
  && apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
    libavcodec60 \
    libavformat60 \
    libavutil58 \
    libswscale7 \
    libswresample4 \
    libpostproc57 \
    libargtable2-0 \
    libedit2 \
    libelf1 \
    libexpat1 \
    libglib2.0-0 \
    libgomp1 \
    libpciaccess0 \
    libv4l-0 \
    libwayland-client0 \
    libx11-6 \
    libx11-xcb1 \
    libxcb-dri2-0 \
    libxcb-dri3-0 \
    libxcb-present0 \
    libxcb-randr0 \
    libxcb-shape0 \
    libxcb-shm0 \
    libxcb-sync1 \
    libxcb-xfixes0 \
    libxcb1 \
    libxext6 \
    libxfixes3 \
    libxshmfence1 \
    libxml2 \
    ocl-icd-libopencl1 \
    gosu \
  && for pkg in vainfo libva2 libva-drm2 libdrm2 libasound2t64 libasound2 libllvm18; do \
       apt-get install -y --no-install-recommends -o Acquire::Retries=3 "$pkg" || true; \
     done \
  && if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
       for pkg in mesa-va-drivers i965-va-driver intel-media-va-driver libigdgmm12; do \
         apt-get install -y --no-install-recommends -o Acquire::Retries=3 "$pkg" || true; \
       done; \
     fi \
  && rm -rf /var/lib/apt/lists/*

ENV \
    LIBVA_DRIVERS_PATH="/usr/local/lib/x86_64-linux-gnu/dri:/usr/local/lib/aarch64-linux-gnu/dri:/usr/lib/x86_64-linux-gnu/dri:/usr/lib/aarch64-linux-gnu/dri" \
    LD_LIBRARY_PATH="/usr/local/lib:/usr/local/lib/x86_64-linux-gnu:/usr/local/lib/aarch64-linux-gnu" \
    CATCHUP_FFMPEG_PATH="/usr/local/bin/ffmpeg" \
    CATCHUP_FRONTEND_DIST="/app/frontend/dist"

# Install dependencies in a venv (PEP 668 safe)
ENV VENV_PATH="/opt/venv"
RUN python3 -m venv "$VENV_PATH"
ENV PATH="$VENV_PATH/bin:$PATH"
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application + tools
COPY backend /app/backend
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist
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
RUN mkdir -p /app/downloads /app/completed /app/config \
  && chmod +x /usr/local/bin/docker-entrypoint.sh

# Expose port
EXPOSE 4177

# Run the application
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "4177"]
