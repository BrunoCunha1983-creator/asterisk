ARG BUILD_FROM=debian:bookworm-slim

FROM ${BUILD_FROM} AS builder
ARG ASTERISK_VERSION=22.11.0
ARG CHAN_DONGLE_REPO=https://github.com/wdoekes/asterisk-chan-dongle.git
ARG CHAN_DONGLE_REF=31eb619600d5ce93237cd440c72db0bc33d7adfe
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential autoconf automake libtool pkg-config git ca-certificates wget patch bzip2 \
    libedit-dev libjansson-dev libxml2-dev libsqlite3-dev uuid-dev libssl-dev libncurses-dev \
    libcurl4-openssl-dev libsrtp2-dev libopus-dev libspeex-dev libspeexdsp-dev libgsm1-dev \
    libogg-dev libvorbis-dev libnewt-dev liburiparser-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

ARG ASTERISK_SHA256=3bd5ee040509a3d3cd9b1ba9520c18e6ec0a7e7981ca68c457dcd36ba3c54d94
WORKDIR /src
RUN wget -q "https://downloads.asterisk.org/pub/telephony/asterisk/asterisk-${ASTERISK_VERSION}.tar.gz" -O /tmp/asterisk.tar.gz \
    && echo "${ASTERISK_SHA256}  /tmp/asterisk.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/asterisk.tar.gz \
    && mv asterisk-${ASTERISK_VERSION} asterisk \
    && rm /tmp/asterisk.tar.gz
WORKDIR /src/asterisk
RUN ./configure --with-pjproject-bundled --with-jansson-bundled \
    && make menuselect.makeopts \
    && menuselect/menuselect \
       --enable chan_pjsip \
       --enable res_pjsip \
       --enable res_pjsip_endpoint_identifier_ip \
       --enable res_http_websocket \
       --enable res_ari \
       --enable res_ari_channels \
       --enable res_ari_bridges \
       --enable res_ari_endpoints \
       --enable res_ari_recordings \
       --enable res_ari_playbacks \
       --enable app_queue \
       --enable app_confbridge \
       --enable app_voicemail \
       --enable app_mixmonitor \
       --enable app_chanspy \
       --enable app_page \
       --enable res_parking \
       --enable res_musiconhold \
       --enable cdr_csv \
       --enable cel_custom \
       --enable codec_alaw \
       --enable codec_ulaw \
       --enable codec_g722 \
       --enable codec_gsm \
       --enable codec_opus \
       --enable format_wav \
       --enable format_wav_gsm \
       --enable format_gsm \
       menuselect.makeopts || true \
    && make -j"$(nproc)" \
    && make install DESTDIR=/stage

RUN git clone "$CHAN_DONGLE_REPO" /src/chan_dongle \
    && cd /src/chan_dongle \
    && git checkout "$CHAN_DONGLE_REF" \
    && ./bootstrap \
    && DESTDIR=/stage/usr/lib/asterisk/modules ./configure \
       --with-asterisk=/src/asterisk/include \
       --with-astversion="$ASTERISK_VERSION" \
    && make -j"$(nproc)" \
    && cp chan_dongle.so /stage/usr/lib/asterisk/modules/chan_dongle.so

FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates python3 curl jq usbutils usb-modeswitch usb-modeswitch-data udev fail2ban nftables \
    libedit2 libxml2 libxslt1.1 libsqlite3-0 libuuid1 libssl3 libncurses6 libcurl4 libsrtp2-1 \
    libopus0 libspeex1 libspeexdsp1 libgsm1 libogg0 libvorbis0a libvorbisenc2 libvorbisfile3 \
    liburiparser1 libnewt0.52 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /stage/usr/ /usr/
COPY --from=builder /stage/var/lib/asterisk/ /var/lib/asterisk/
COPY rootfs/ /

RUN set -eu; \
    chmod +x /usr/local/bin/asterisk-ha-start; \
    mkdir -p /config /share/asterisk-recordings /var/log/asterisk /var/log/asterisk/cdr-csv /var/log/asterisk/cdr-custom /var/log/asterisk/cel-custom /var/spool/asterisk /run/asterisk /run/fail2ban /data/fail2ban; \
    missing="$( { ldd /usr/sbin/asterisk; find /usr/lib/asterisk/modules -type f -name '*.so' -exec ldd {} \; ; } 2>/dev/null | grep 'not found' || true )"; \
    if [ -n "$missing" ]; then echo "Unresolved runtime libraries:"; echo "$missing"; exit 1; fi; \
    /usr/sbin/asterisk -V; \
    fail2ban-client -V

EXPOSE 8099/tcp 5038/tcp 8088/tcp 5060/udp 5061/tcp 4569/udp
ENTRYPOINT ["/usr/local/bin/asterisk-ha-start"]
