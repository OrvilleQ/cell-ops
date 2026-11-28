FROM debian:trixie-slim@sha256:8aa5a7bf5a1955bddbe7d74fcdd0b91ab30e74362a8b73af672b0481b35b44a0
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       postfix libsasl2-modules libsasl2-modules-db sasl2-bin ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY main.cf /etc/postfix/main.cf
COPY smtpd.conf /etc/postfix/sasl/smtpd.conf
COPY --chmod=0755 entrypoint.sh /usr/local/bin/postfix-relay
# smtpd must be able to read the SASL database outside the queue chroot.
RUN postconf -F smtp/inet/chroot=n
EXPOSE 25
ENTRYPOINT ["/usr/local/bin/postfix-relay"]
