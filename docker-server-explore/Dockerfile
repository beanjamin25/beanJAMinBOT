FROM registry.access.redhat.com/ubi9/ubi-minimal

RUN microdnf install -y \
        nginx \
        python3 \
        python3-pip \
        krb5-workstation \
    && microdnf clean all

# Nginx on UBI doesn't use sites-enabled; drop config into conf.d
RUN mkdir -p /etc/nginx/conf.d

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app.py .
COPY start.sh .
COPY kinit-renew.sh .
COPY nginx.conf /etc/nginx/conf.d/bottle.conf

EXPOSE 443

CMD ["/app/start.sh"]
