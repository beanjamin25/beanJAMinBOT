FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends nginx openssl && \
    rm -rf /var/lib/apt/lists/*

# Remove the default nginx site
RUN rm -f /etc/nginx/sites-enabled/default

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY start.sh .
COPY generate-certs.sh .
COPY nginx.conf /etc/nginx/sites-enabled/bottle.conf

EXPOSE 443

CMD ["/app/start.sh"]
