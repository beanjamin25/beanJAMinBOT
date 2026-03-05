# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

beanJAMinBOT is a Twitch chat bot built on `irc.bot.SingleServerIRCBot`. It provides chat commands, channel point reward handling, a Pokemon catching game, a gambling system, OBS integration, TTS, and automatic clip announcements.

## Running the Bot

```bash
pip install -r requirements.txt
python main.py
```

Configuration lives in `config/bot.conf` (YAML). Auth tokens are in `config/botjamin_auth.yaml` (not committed). See `config/example.conf` and `config/example_auth.yaml` for templates.

## Architecture

### Core Flow

`main.py` is the entry point. The bot class extends `SingleServerIRCBot`, connects to Twitch IRC, and spawns several daemon threads:

- **EventSub WebSocket** (`twitch_eventsub.py`) — connects to Twitch EventSub via WebSocket, handles follows, raids, channel point redemptions, and subscriptions. Reconnects with exponential backoff (1s–120s).
- **Twitch Events** (`twitch_events.py`) — processes EventSub notifications via a `queue.Queue`. Handles SFX playback, OBS scene changes, TTS, and Pokemon reward integration.
- **Watchtime Tracker** (`watchtime.py`) — polls the chatters API on an interval, tracks per-stream and cumulative watchtime.
- **Clips Monitor** (`clips.py`) — polls for new clips during streams and announces them in chat.
- **OBS Control** (`obs_control.py`) — async WebSocket client for OBS scene/source visibility and replay buffer.
- **TTS** (`tts.py`) — queue-based text-to-speech via pyttsx3.

### Chat Commands

IRC messages flow through `on_pubmsg()` → `do_command()` in `main.py`. There is a permission hierarchy: broadcaster > moderator > VIP > user.

**Custom commands** are stored in `data/custom_commands.yaml` and support format strings (`{user}`, `{args[n]}`, `{count}`).

### Error Handling & Logging

- `exceptions.py` — Domain-specific exception hierarchy (TwitchAPIError, GambleError, OBSError, AuthenticationError). API methods raise exceptions instead of returning `False`.
- `logging_config.py` — Centralized logging configuration with `get_logger()` helper. Replaces scattered `print()` statements.

### API Layer

- `twitch_rest_api.py` — Twitch Helix API client with OAuth token management (obtain, validate, refresh). Handles channel info, followers, subscribers, clips, and EventSub subscription creation. Raises `TwitchAPIError` and subclasses on failures.
- `twitch_oauth.py` — OAuth2 callback web server for user authentication.
- `streamlabs_api.py` — Streamlabs alerts for Pokemon catches.

### Game Modules

- `pokemon.py` — Pokemon catching game with CSV-based Pokemon database (`data/pokemon/pokeDB.csv`), YAML-based user pokedex, shiny mechanics, and pokeball economy.
- `gamble.py` — Channel points gambling with JSON-based bank (`data/beanBOTbank.json`), borrowing/payback system.

### Data Storage

All persistent data uses flat files:
- **YAML**: config, custom commands, quotes, SFX mappings, pokedex
- **JSON**: gamble bank, watchtime
- **CSV**: Pokemon database

### Threading Model

The bot uses a main IRC thread plus multiple daemon threads. Inter-thread communication for channel point redemptions uses `queue.Queue`. The EventSub WebSocket runs its own `asyncio` event loop in a separate thread.

## Key Dependencies

- `irc` — IRC bot framework
- `websockets` — EventSub WebSocket connection
- `simpleobsws` — OBS WebSocket control
- `playsound` — SFX audio playback
- `pyttsx3` — Text-to-speech
- `aiohttp` — OAuth callback server
- `PyYAML` — Config/data file parsing

## Docker Server Exploration

The `docker-server-explore/` directory is a standalone exploration area for containerized deployment, separate from the bot codebase.

- **Two-container architecture** — A Bottle web app (`bottle/`) in a non-root UBI9 container (`portaluser`), and the official `nginx` image for SSL termination. Nginx config is in `nginx-conf/` and bind-mounted at runtime. Kerberos ticket renewal via a background loop (`kinit-renew.sh`).
- **Ansible deployment** (`docker-server-explore/ansible/`) — Two approaches using the `community.docker` Ansible collection:
  - `deploy.yml` + `bottle_nginx` role — Direct container management via `docker_container` + `docker_network`
  - `deploy-compose.yml` + `bottle_nginx_compose` role — Compose-based via `docker_compose_v2` with a templated compose file
- **Branch:** `claude/bottle-nginx-docker-setup-MBZaV`

## Current Branch Context

The `feature/eventsub-websocket` branch completed migration from EventSub webhooks to WebSockets with automatic reconnection support. Also includes standardized error handling refactoring (exceptions instead of returning `False`, centralized logging).