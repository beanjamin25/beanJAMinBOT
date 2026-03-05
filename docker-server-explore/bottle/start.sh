#!/bin/sh
set -e

# --- Kerberos: initial ticket ---
kinit "${KRB5_PRINCIPAL}" -kt "${KRB5_KEYTAB}"

# --- Kerberos: background renewal loop ---
/app/kinit-renew.sh >> /var/log/app/kinit.log 2>&1 &

# --- Bottle app (foreground) ---
exec python3 /app/app.py
