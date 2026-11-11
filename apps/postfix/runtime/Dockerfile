FROM debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       postfix libsasl2-modules sasl2-bin ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY main.cf /etc/postfix/main.cf
COPY smtpd.conf /etc/postfix/sasl/smtpd.conf
COPY --chmod=0755 entrypoint.sh /usr/local/bin/postfix-relay
# smtpd must be able to read the SASL database outside the queue chroot.
RUN postconf -F smtp/inet/chroot=n
EXPOSE 25
ENTRYPOINT ["/usr/local/bin/postfix-relay"]
