#!/bin/sh
# Periodically renew Kerberos ticket.
# Expects env vars: KRB5_PRINCIPAL, KRB5_KEYTAB
set -e

INTERVAL=${KINIT_INTERVAL_SEC:-86400}   # default: 24 hours

while true; do
    echo "$(date): Renewing Kerberos ticket for ${KRB5_PRINCIPAL}"
    kinit "${KRB5_PRINCIPAL}" -kt "${KRB5_KEYTAB}"
    sleep "${INTERVAL}"
done
