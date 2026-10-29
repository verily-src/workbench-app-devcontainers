FROM alpine:3.20

RUN apk add --no-cache dnsmasq bash

COPY wrapper.sh /usr/local/bin/wrapper.sh
COPY open.conf /etc/dnsmasq.d/open.conf
COPY allowlist.conf /etc/dnsmasq.d/allowlist.conf
RUN chmod +x /usr/local/bin/wrapper.sh

ENTRYPOINT ["/usr/local/bin/wrapper.sh"]
