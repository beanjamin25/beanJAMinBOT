#!/bin/sh
set -e

# --- Kerberos ---
# Obtain an initial ticket, then start the renewal loop in the background.
kinit "${KRB5_PRINCIPAL}" -kt "${KRB5_KEYTAB}"
/app/kinit-renew.sh &

# --- Bottle app ---
python3 /app/app.py &

# --- Nginx (foreground) ---
nginx -g "daemon off;"
