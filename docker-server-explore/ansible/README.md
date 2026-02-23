# Ansible Deployment for Bottle + Nginx

Deploys the Bottle + Nginx Docker container using the `community.docker` Ansible collection. Two approaches are provided for comparison.

## Prerequisites

- Ansible 2.14+
- SSH access to target host(s)
- Docker installed on target (or let the playbook install it)

## Setup

Install the required Ansible collection:

```bash
ansible-galaxy collection install -r requirements.yml
```

## Configuration

1. Edit `inventory/hosts.yml` with your target host(s).
2. Adjust variables in `inventory/group_vars/all.yml`:
   - `ssl_cert_path`, `ssl_key_path`, `keytab_path` — host paths to mount
   - `krb5_principal` — Kerberos principal name
   - `bottle_image_tag` — image version to build/deploy

## Approaches

### 1. Direct Container Management (`deploy.yml`)

Uses `community.docker.docker_container` to manage the container directly from Ansible. Each container setting (ports, volumes, env) is defined as Ansible variables.

```bash
ansible-playbook -i inventory/hosts.yml deploy.yml
```

**Role:** `bottle_nginx`

**Pros:**
- Full Ansible-native control over every container parameter
- No compose file needed on the remote host
- Easier to integrate conditional logic per-task

**Cons:**
- Container config lives in Ansible vars rather than a standard compose file
- Harder to run/debug manually on the remote host

### 2. Docker Compose (`deploy-compose.yml`)

Uses `community.docker.docker_compose_v2` to deploy via a templated `docker-compose.yml` on the remote host.

```bash
ansible-playbook -i inventory/hosts.yml deploy-compose.yml
```

**Role:** `bottle_nginx_compose`

**Pros:**
- Compose file on the remote host makes manual debugging easy (`docker compose ps`, `docker compose logs`)
- Closer to how the project is already structured with its existing `docker-compose.yml`
- Scales naturally if you add more services later

**Cons:**
- Extra templating step to generate the compose file
- Compose must be installed on the remote host (bundled with Docker 20.10+)

## Dry Run

Both playbooks support check mode:

```bash
ansible-playbook -i inventory/hosts.yml deploy.yml --check --diff
ansible-playbook -i inventory/hosts.yml deploy-compose.yml --check --diff
```
