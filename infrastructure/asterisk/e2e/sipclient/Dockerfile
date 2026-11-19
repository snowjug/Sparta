# Headless SIP caller for the Sparta end-to-end test: baresip (a mature open-source SIP user agent, BSD-3-Clause) driven by
# client.py. Used only by infrastructure/asterisk/e2e/docker-compose.yml; never part of the product image.
#
# It runs as root on purpose: client.py taps this container's own network interface (a raw packet socket needs CAP_NET_RAW,
# which Docker grants to root by default) to time every RTP packet the caller receives. It is a throwaway test container on an
# isolated compose network, with no published ports and no secrets other than the per-run SIP password in its scenario file.
FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends baresip-core python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY client.py /opt/client/client.py
WORKDIR /data
ENTRYPOINT ["python3", "-W", "ignore::DeprecationWarning", "/opt/client/client.py"]
