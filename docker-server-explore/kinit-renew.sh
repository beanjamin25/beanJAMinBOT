#!/bin/sh
# Periodically renew Kerberos ticket.
# Expects env vars: KRB5_PRINCIPAL, KRB5_KEYTAB
#
# NOTE: This script is kept in the repo as a standalone alternative
# to the cron-based approach used by start.sh. It is not currently
# invoked at container startup.

INTERVAL=${KINIT_INTERVAL_SEC:-86400}   # default: 24 hours
MAX_RETRIES=3
RETRY_DELAY=60                          # seconds between retries

while true; do
    attempt=1
    while [ "$attempt" -le "$MAX_RETRIES" ]; do
        echo "$(date): Renewing Kerberos ticket for ${KRB5_PRINCIPAL} (attempt ${attempt}/${MAX_RETRIES})"
        if kinit "${KRB5_PRINCIPAL}" -kt "${KRB5_KEYTAB}"; then
            echo "$(date): kinit succeeded"
            break
        fi

        echo "$(date): kinit failed (attempt ${attempt}/${MAX_RETRIES})"
        attempt=$((attempt + 1))
        if [ "$attempt" -le "$MAX_RETRIES" ]; then
            sleep "$RETRY_DELAY"
        fi
    done

    if [ "$attempt" -gt "$MAX_RETRIES" ]; then
        echo "$(date): WARNING - kinit failed after ${MAX_RETRIES} attempts, will retry next cycle"
    fi

    sleep "$INTERVAL"
done
