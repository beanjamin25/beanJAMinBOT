#!/bin/sh
set -e

# --- Kerberos ---
# Persist env vars so the cron job can source them.
echo "export KRB5_PRINCIPAL=\"${KRB5_PRINCIPAL}\"" >  /app/kinit.env
echo "export KRB5_KEYTAB=\"${KRB5_KEYTAB}\""       >> /app/kinit.env

# Obtain an initial ticket.
kinit "${KRB5_PRINCIPAL}" -kt "${KRB5_KEYTAB}"

# Install a cron job to renew the ticket daily at 2:00 AM.
echo "0 2 * * * /app/kinit-cron.sh >> /var/log/kinit.log 2>&1" | crontab -

# Start crond in the background.
crond

# --- Bottle app ---
python3 /app/app.py &

# --- Nginx (foreground) ---
nginx -g "daemon off;"
