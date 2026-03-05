FROM registry.access.redhat.com/ubi9/ubi-minimal

RUN microdnf install -y \
        python3 \
        python3-pip \
        krb5-workstation \
        shadow-utils \
    && microdnf clean all

# Create non-root user
RUN useradd -r -u 1001 -m -s /sbin/nologin portaluser

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app.py .
COPY start.sh .
COPY kinit-renew.sh .
RUN chmod +x /app/start.sh /app/kinit-renew.sh

# Log directory writable by portaluser
RUN mkdir -p /var/log/app && chown portaluser:portaluser /var/log/app

RUN chown -R portaluser:portaluser /app

EXPOSE 8080

USER portaluser

CMD ["/app/start.sh"]
