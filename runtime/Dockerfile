FROM python:3.11-slim-bookworm

ARG TARGETARCH
ARG MIHOMO_VERSION=v1.19.32
# Keep in step with RUNTIME_VERSION in workbench/runtime.py.
LABEL org.opencontainers.image.title="browser-workbench runtime" \
      org.opencontainers.image.version="0.8.0" \
      org.opencontainers.image.source="https://github.com/abnormalphty/browser-workbench" \
      workbench.runtime="0.8.0"
ENV DEBIAN_FRONTEND=noninteractive DISPLAY=:99 PYTHONUNBUFFERED=1 LANG=C.UTF-8

# Mirrors reached through flaky proxies drop connections mid-download; retry.
RUN printf 'Acquire::Retries "8";\nAcquire::http::Timeout "60";\nAcquire::https::Timeout "60";\n' > /etc/apt/apt.conf.d/80-retries

# A proxy that keeps resetting connections can still fail an index or a few downloads after apt's own
# retries: apt-install retries the update and the downloads, keeping what was already fetched.
COPY --chmod=755 apt-install.sh /usr/local/sbin/apt-install
RUN apt-install \
    ca-certificates curl xvfb x11vnc openbox novnc websockify wmctrl \
    fonts-noto-cjk fonts-noto-color-emoji libgtk-3-0 libdbus-glib-1-2 \
    libasound2 libx11-xcb1 libxt6 libxcomposite1 libxdamage1 libxrandr2 \
    libgbm1 libnss3 libdrm2 libpango-1.0-0 libatk1.0-0 tini

RUN pip install --no-cache-dir fastapi==0.136.1 uvicorn==0.46.0 PyYAML==6.0.3 httpx==0.28.1

RUN curl -fsSL --retry 5 --retry-all-errors --retry-delay 10 "https://github.com/MetaCubeX/mihomo/releases/download/${MIHOMO_VERSION}/mihomo-linux-${TARGETARCH}-${MIHOMO_VERSION}.gz" \
    -o /tmp/mihomo.gz && gzip -dc /tmp/mihomo.gz > /usr/local/bin/mihomo \
    && chmod 755 /usr/local/bin/mihomo && rm /tmp/mihomo.gz \
    && useradd --create-home --uid 1000 browser \
    && chown -R browser:browser /home/browser

WORKDIR /app
RUN apt-install firefox-esr firefox-esr-l10n-zh-cn xdotool xclip
COPY entrypoint.py browser.py native_firefox.py desktop_clipboard.py welcome.html /app/
EXPOSE 6080 8081
ENTRYPOINT ["/usr/bin/tini", "--", "python", "/app/entrypoint.py"]
