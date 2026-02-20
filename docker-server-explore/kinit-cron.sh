#!/bin/sh
# Called by cron to renew the Kerberos ticket.
# Environment variables are written to /app/kinit.env by start.sh
# so they are available to the cron environment.

. /app/kinit.env

echo "$(date): Renewing Kerberos ticket for ${KRB5_PRINCIPAL}"
if kinit "${KRB5_PRINCIPAL}" -kt "${KRB5_KEYTAB}"; then
    echo "$(date): kinit succeeded"
else
    echo "$(date): kinit failed"
fi
