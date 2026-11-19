# Sparta local-SIP Asterisk image.
#
# Asterisk 22 LTS built from the official source tarball (SHA-256 pinned below) with PJSIP and the AudioSocket media bridge,
# then run as an unprivileged user with a read-only root file system. Debian has no Asterisk package and Ubuntu 24.04 ships
# 20.6.0, so the tarball is built here (about 10 minutes the first time, cached afterwards).
#
#   docker build -t sparta-asterisk infrastructure/asterisk
#   docker compose --profile asterisk up --build        # the normal way: see infrastructure/asterisk/README.md
#
# Upgrading: change ASTERISK_VERSION and ASTERISK_SHA256 (the published checksum is at
# https://downloads.asterisk.org/pub/telephony/asterisk/asterisk-<version>.sha256) and, if the new release bundles another
# PJPROJECT (third-party/versions.mak), PJPROJECT_VERSION and PJPROJECT_SHA256. Then re-run scripts/sip_e2e.py.
#
# Asterisk is GPL-2.0. Sparta talks to it over network protocols only and does not link it. The source of exactly what is
# built here is the tarball named below; see /usr/share/doc/sparta-asterisk/SOURCE.

ARG DEBIAN_IMAGE=debian:bookworm-slim

# --------------------------------------------------------------------------------------------------------------------
FROM ${DEBIAN_IMAGE} AS build

ARG ASTERISK_VERSION=22.12.0
ARG ASTERISK_SHA256=f8b2ba98aac6c4ff3376bc0a2868bea6ed577ca684efb7ec739ae6e8ce6e35e2
ARG PJPROJECT_VERSION=2.17
ARG PJPROJECT_SHA256=04b2eb1f0f01aa0ad1945b167171843448a51aa6b7c3e806496d434f13a112b7
ARG MAKE_JOBS=4

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl bzip2 patch pkg-config \
        libssl-dev libxml2-dev libsqlite3-dev libjansson-dev uuid-dev libedit-dev libcurl4-openssl-dev \
        libncurses-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# The release tarball and the bundled PJPROJECT archive are verified against pinned SHA-256 values. (Asterisk itself only
# checks PJPROJECT against an MD5 it ships.) Pre-seeding the externals cache is not enough on its own: `make install` also
# downloads the sound and music-on-hold packages, with no checksum at all. The dialplan never plays a recorded sound, so
# menuselect below disables those categories, and the build fails if a single such file still ends up in the image.
RUN curl -fsSL --retry 3 -o asterisk.tar.gz \
        "https://downloads.asterisk.org/pub/telephony/asterisk/asterisk-${ASTERISK_VERSION}.tar.gz" \
    && echo "${ASTERISK_SHA256}  asterisk.tar.gz" | sha256sum -c - \
    && mkdir -p /ext \
    && curl -fsSL --retry 3 -o "/ext/pjproject-${PJPROJECT_VERSION}.tar.bz2" \
        "https://raw.githubusercontent.com/asterisk/third-party/master/pjproject/${PJPROJECT_VERSION}/pjproject-${PJPROJECT_VERSION}.tar.bz2" \
    && echo "${PJPROJECT_SHA256}  /ext/pjproject-${PJPROJECT_VERSION}.tar.bz2" | sha256sum -c - \
    && tar -xzf asterisk.tar.gz --strip-components=1 \
    && rm asterisk.tar.gz

# Nothing here may run a shell command or open a control API: those modules are not even built. (menuselect rejects a
# name that does not exist, so every name below was checked against the 22.12.0 source tree.) BUILD_NATIVE is off on
# purpose: `-march=native` ties the binaries to the CPU of the machine that built the image, so the same image would crash
# with "illegal instruction" on another CPU (and it also broke the bundled PJPROJECT build here).
RUN ./configure \
        --prefix=/usr --sysconfdir=/etc --localstatedir=/var \
        --with-pjproject-bundled --with-externals-cache=/ext \
        --disable-xmldoc --without-x11

RUN make menuselect.makeopts \
    && menuselect/menuselect \
        --disable BUILD_NATIVE \
        --disable app_system --disable func_shell --disable app_externalivr --disable app_originate \
        --disable res_agi --disable res_ari --disable res_ari_applications --disable res_ari_asterisk \
        --disable res_ari_bridges --disable res_ari_channels --disable res_ari_device_states --disable res_ari_endpoints \
        --disable res_ari_events --disable res_ari_mailboxes --disable res_ari_model --disable res_ari_playbacks \
        --disable res_ari_recordings --disable res_ari_sounds --disable res_stasis --disable app_stasis \
        --disable chan_websocket --disable res_http_websocket --disable res_websocket_client \
        --disable chan_iax2 --disable chan_dahdi --disable chan_unistim --disable pbx_ael --disable pbx_lua \
        --disable res_pjsip_outbound_registration \
        --disable-category MENUSELECT_CORE_SOUNDS --disable-category MENUSELECT_EXTRA_SOUNDS --disable-category MENUSELECT_MOH \
        menuselect.makeopts

# The bundled PJPROJECT is built first and serially (`make third-party`): its makefiles are not safe under `make -j`, and a
# parallel build failed intermittently in a different library each time. Asterisk itself is then built in parallel.
RUN make third-party \
    && make -j"${MAKE_JOBS}" \
    && make install DESTDIR=/stage \
    # Nothing may have been downloaded by `make install` (see above): no sound, no music on hold.
    && test -z "$(find /stage/var/lib/asterisk/sounds /stage/var/lib/asterisk/moh -type f 2>/dev/null)" \
    # /var/run and /var/lock are symlinks in the runtime image; the empty directories `make install` creates would collide.
    && rm -rf /stage/var/run /stage/var/lock \
    && mkdir -p /stage/opt/sparta-asterisk /stage/usr/share/doc/sparta-asterisk \
    && cp configs/samples/indications.conf.sample /stage/opt/sparta-asterisk/indications.conf \
    && cp COPYING LICENSE /stage/usr/share/doc/sparta-asterisk/ \
    && printf 'Asterisk %s, built from https://downloads.asterisk.org/pub/telephony/asterisk/asterisk-%s.tar.gz\nsha256 %s\nbundled PJPROJECT %s sha256 %s\n' \
        "${ASTERISK_VERSION}" "${ASTERISK_VERSION}" "${ASTERISK_SHA256}" "${PJPROJECT_VERSION}" "${PJPROJECT_SHA256}" \
        > /stage/usr/share/doc/sparta-asterisk/SOURCE

# --------------------------------------------------------------------------------------------------------------------
FROM ${DEBIAN_IMAGE} AS runtime

ARG ASTERISK_VERSION=22.12.0
LABEL org.opencontainers.image.title="sparta-asterisk" \
      org.opencontainers.image.description="Asterisk ${ASTERISK_VERSION} with PJSIP and AudioSocket for Sparta local SIP calls (no PSTN)" \
      org.opencontainers.image.licenses="GPL-2.0-only"

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash ca-certificates iproute2 libssl3 libxml2 libsqlite3-0 libjansson4 libuuid1 libedit2 libcurl4 libncurses6 zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 asterisk \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /var/lib/asterisk --shell /usr/sbin/nologin asterisk

COPY --from=build /stage/ /

# Fail the build now, not at the first call, if a shared library the binaries need is missing from this image.
RUN set -eu; \
    missing="$(ldd /usr/sbin/asterisk /usr/lib/asterisk/modules/*.so 2>&1 | grep 'not found' | sort -u || true)"; \
    if [ -n "$missing" ]; then echo "missing runtime libraries:"; echo "$missing"; exit 1; fi

COPY asterisk.conf pjsip.conf.template extensions.conf rtp.conf modules.conf logger.conf http.conf manager.conf \
     /opt/sparta-asterisk/conf/
COPY entrypoint.sh healthcheck.sh /opt/sparta-asterisk/

# Tone definitions (ringback, busy) are the only sample configuration the dialplan needs; `make samples` is never run.
RUN mv /opt/sparta-asterisk/indications.conf /opt/sparta-asterisk/conf/indications.conf \
    && chmod 0755 /opt/sparta-asterisk/entrypoint.sh /opt/sparta-asterisk/healthcheck.sh \
    && mkdir -p /etc/asterisk /run/asterisk /var/lib/asterisk /var/log/asterisk /var/spool/asterisk \
    && chown -R asterisk:asterisk /etc/asterisk /run/asterisk /var/lib/asterisk /var/log/asterisk /var/spool/asterisk

USER asterisk
WORKDIR /var/lib/asterisk

# SIP over UDP and a small RTP range (see rtp.conf). Nothing else listens: no AMI, no ARI, no HTTP.
EXPOSE 5060/udp 10000-10019/udp

HEALTHCHECK --interval=10s --timeout=5s --retries=6 --start-period=20s CMD ["/opt/sparta-asterisk/healthcheck.sh"]

ENTRYPOINT ["/opt/sparta-asterisk/entrypoint.sh"]
# -n: no console colours. Otherwise every field of every log line is wrapped in terminal escape codes, which are noise in
# `docker compose logs` and break pattern matching on the log (fail2ban, the end-to-end test).
CMD ["asterisk", "-f", "-n", "-C", "/etc/asterisk/asterisk.conf"]
