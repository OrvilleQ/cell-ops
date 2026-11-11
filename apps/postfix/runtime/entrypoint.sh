#!/bin/sh
set -eu
: "${POSTFIX_HOSTNAME:?set the public SMTP hostname}"
case "$POSTFIX_HOSTNAME" in
  *[!a-zA-Z0-9.-]*|-*|.*|*.) echo "Invalid SMTP hostname" >&2; exit 1 ;;
esac
credentials=${POSTFIX_CREDENTIALS_DIR:-/run/secrets/postfix}
user=$(cat "$credentials/username")
password=$(cat "$credentials/password")
case "$user" in
  ''|-*|*[!a-zA-Z0-9_.-]*) echo "Invalid SASL username (use a local name)" >&2; exit 1 ;;
esac
test -n "$password"
rm -f /etc/sasldb2
printf '%s\n' "$password" | saslpasswd2 -p -c -f /etc/sasldb2 -u "$POSTFIX_HOSTNAME" "$user"
unset password
chown postfix:postfix /etc/sasldb2
chmod 0600 /etc/sasldb2
postconf -e "myhostname = $POSTFIX_HOSTNAME" "smtpd_sasl_local_domain = $POSTFIX_HOSTNAME"
postfix check
exec postfix start-fg
