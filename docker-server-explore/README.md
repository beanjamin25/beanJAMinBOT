# docker-server-explore

Bottle web app behind Nginx with TLS termination, running in a single
RHEL-based (UBI 9) Docker container. Kerberos tickets are renewed daily
via cron for IPA-authenticated services.

## Prerequisites

You will need three files from your environment:

| File | Description |
|------|-------------|
| `cert.pem` | TLS certificate |
| `key.pem` | TLS private key |
| `robot.keytab` | Kerberos keytab for the service principal |

## Building the image

The image should be built and tagged ahead of time:

```bash
docker build -t bottle-nginx:1.0.0 .
```

## Running with docker compose

1. Copy `.env.example` to `.env` and fill in the values (including `IMAGE_TAG`):

   ```
   cp .env.example .env
   ```

2. Start the container:

   ```
   docker compose up -d
   ```

3. Logs will appear in the `./logs/` directory on the host.

## Running with docker run

```bash
docker run -d -p 443:443 \
  -v /path/to/cert.pem:/etc/nginx/ssl/cert.pem:ro \
  -v /path/to/key.pem:/etc/nginx/ssl/key.pem:ro \
  -v /path/to/robot.keytab:/etc/krb5/robot.keytab:ro \
  -v ./logs:/var/log/app \
  -e KRB5_PRINCIPAL=my_robot_account \
  -e KRB5_KEYTAB=/etc/krb5/robot.keytab \
  bottle-nginx:1.0.0
```

## Logs

All logs are written to `/var/log/app/` inside the container, which
should be mounted to a host directory.

| Log file | Source |
|----------|--------|
| `nginx-access.log` | Nginx access log |
| `nginx-error.log` | Nginx error log |
| `bottle.log` | Bottle application output |
| `kinit.log` | Kerberos ticket renewal (cron) |

## Mount summary

| Container path | Purpose | Mode |
|----------------|---------|------|
| `/etc/nginx/ssl/cert.pem` | TLS certificate | read-only |
| `/etc/nginx/ssl/key.pem` | TLS private key | read-only |
| `/etc/krb5/robot.keytab` | Kerberos keytab | read-only |
| `/var/log/app` | All application logs | read-write |
