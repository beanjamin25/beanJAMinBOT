# docker-server-explore

Bottle web app and Nginx reverse proxy running as two containers, orchestrated
with Docker Compose. The Bottle app runs in a custom UBI 9 container as a
non-root user (`portaluser`). Nginx uses the official `nginx` image with
config files mounted at runtime. Nginx handles TLS termination; Kerberos
tickets are renewed via a background loop in the app container.

## Architecture

```
                 ┌──────────────┐       ┌──────────────┐
  :443 ──────►   │    nginx     │──────►│   bottle     │
  (host)         │  :443 ssl    │ :8080 │  python app  │
                 │  (official)  │       │ (portaluser) │
                 └──────────────┘       └──────────────┘
                        Docker network: internal
```

## Prerequisites

| File | Description |
|------|-------------|
| `cert.pem` | TLS certificate |
| `key.pem` | TLS private key |
| `robot.keytab` | Kerberos keytab for the service principal |

## Building the image

Only the Bottle app image needs to be built:

```bash
docker build -t bottle-app:1.0.0 bottle/
```

Nginx uses the official `nginx` image directly — no build required.

## Running with docker compose

1. Copy `.env.example` to `.env` and fill in the values:

   ```
   cp .env.example .env
   ```

2. Start the containers:

   ```
   docker compose up -d
   ```

3. Logs appear in `./logs/bottle/` and `./logs/nginx/` on the host.

## Nginx configuration

The server block config is in `nginx-conf/bottle.conf` and is bind-mounted
into the container at `/etc/nginx/conf.d/bottle.conf`. Edit it in place —
no rebuild needed, just restart the nginx container.

## Logs

| Directory | Log file | Source |
|-----------|----------|--------|
| `logs/bottle/` | `bottle.log` | Bottle application output |
| `logs/bottle/` | `kinit.log` | Kerberos ticket renewal |
| `logs/nginx/` | `access.log` | Nginx access log |
| `logs/nginx/` | `error.log` | Nginx error log |

## Mount summary

### Bottle container

| Container path | Purpose | Mode |
|----------------|---------|------|
| `/etc/krb5/robot.keytab` | Kerberos keytab | read-only |
| `/var/log/app` | Application logs | read-write |

### Nginx container

| Container path | Purpose | Mode |
|----------------|---------|------|
| `/etc/nginx/conf.d/bottle.conf` | Nginx server block | read-only |
| `/etc/nginx/ssl/cert.pem` | TLS certificate | read-only |
| `/etc/nginx/ssl/key.pem` | TLS private key | read-only |
| `/var/log/nginx` | Nginx logs | read-write |
