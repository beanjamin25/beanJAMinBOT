#!/bin/sh
set -e

# Generate self-signed certs if they don't already exist
if [ ! -f /etc/nginx/ssl/cert.pem ]; then
    /app/generate-certs.sh
fi

# Start the Bottle app in the background
python /app/app.py &

# Start nginx in the foreground
nginx -g "daemon off;"
