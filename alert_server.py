import asyncio
import json
import threading
import uuid

import websockets

from logging_config import get_logger


class AlertServer:
    """WebSocket server that pushes alert events to connected OBS browser source clients.

    Follows the same threaded asyncio pattern as TwitchEventsub and ObsControl.
    The bot triggers alerts via send_alert() (or convenience methods), and
    connected browser-source clients render them.

    Protocol (server -> client):
        {
            "type": "alert",
            "alert_id": "<uuid>",
            "alert_type": "follow|raid|subscription|points|custom",
            "data": { ... alert fields ... }
        }

    Protocol (client -> server):
        {
            "type": "alert_complete",
            "alert_id": "<uuid>"
        }
    """

    def __init__(self, host='localhost', port=8765):
        self.host = host
        self.port = port
        self.clients = set()

        self._loop = None
        self._thread = None
        self._server = None
        self._running = False
        self._stopping = False

        self._logger = get_logger('alert_server')

    # ── lifecycle ────────────────────────────────────────────────────

    def start(self):
        if self._running:
            raise RuntimeError("AlertServer is already running")

        self._stopping = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._running = True
        self._thread.start()
        self._logger.info(f"Alert server starting on ws://{self.host}:{self.port}")

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self):
        self._server = await websockets.serve(
            self._handler, self.host, self.port
        )
        self._logger.info(f"Alert server listening on ws://{self.host}:{self.port}")
        try:
            await asyncio.Future()  # run forever
        except asyncio.CancelledError:
            pass

    def stop(self):
        if not self._running:
            return
        self._stopping = True
        if self._server:
            self._server.close()
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._running = False
        self._logger.info("Alert server stopped")

    # ── client connection handler ────────────────────────────────────

    async def _handler(self, websocket):
        self.clients.add(websocket)
        remote = websocket.remote_address
        self._logger.info(f"Client connected: {remote}")
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get('type')
                    if msg_type == 'alert_complete':
                        self._logger.debug(f"Alert completed: {data.get('alert_id')}")
                except json.JSONDecodeError:
                    self._logger.warning(f"Invalid JSON from client: {message}")
        except websockets.exceptions.ConnectionClosed:
            self._logger.info(f"Client disconnected: {remote}")
        finally:
            self.clients.discard(websocket)

    # ── broadcasting ─────────────────────────────────────────────────

    async def _broadcast(self, message):
        if not self.clients:
            self._logger.debug("No clients connected, alert not delivered")
            return
        disconnected = set()
        for client in self.clients.copy():
            try:
                await client.send(message)
            except websockets.exceptions.ConnectionClosed:
                disconnected.add(client)
        self.clients -= disconnected

    # ── public API: send alerts ──────────────────────────────────────

    def send_alert(self, alert_type, title="", message="",
                   image="", video="", sound="",
                   duration=5000,
                   animation_in="fadeInUp", animation_out="fadeOutDown",
                   text_color="#ffffff", font_size="32px",
                   accent_color="#00ff00"):
        """Send an alert to all connected browser-source clients.

        Args:
            alert_type:    Category string (follow, raid, subscription, points, custom, ...).
            title:         Large heading text.
            message:       Body / sub-text.
            image:         URL to an image or GIF.
            video:         URL to a video file.
            sound:         URL to a sound file.
            duration:      How long the alert stays on screen (ms).
            animation_in:  CSS animation class for entrance.
            animation_out: CSS animation class for exit.
            text_color:    CSS colour for message text.
            font_size:     CSS font-size for message text.
            accent_color:  Colour used for the title and accent highlights.
        """
        alert = {
            "type": "alert",
            "alert_id": str(uuid.uuid4()),
            "alert_type": alert_type,
            "data": {
                "title": title,
                "message": message,
                "image": image,
                "video": video,
                "sound": sound,
                "duration": duration,
                "animation_in": animation_in,
                "animation_out": animation_out,
                "text_color": text_color,
                "font_size": font_size,
                "accent_color": accent_color,
            }
        }
        self._logger.info(f"Sending alert: {alert_type} — {title}")
        if self._loop and self._running:
            asyncio.run_coroutine_threadsafe(
                self._broadcast(json.dumps(alert)), self._loop
            )
        else:
            self._logger.warning("Cannot send alert: server not running")

    # ── convenience helpers for common alert types ───────────────────

    def follow_alert(self, username, **kwargs):
        defaults = dict(
            alert_type="follow",
            title="New Follower!",
            message=f"{username} just followed!",
            duration=5000,
            accent_color="#6441a5",
        )
        defaults.update(kwargs)
        self.send_alert(**defaults)

    def raid_alert(self, username, viewer_count=0, **kwargs):
        defaults = dict(
            alert_type="raid",
            title="Incoming Raid!",
            message=f"{username} is raiding with {viewer_count} viewers!",
            duration=8000,
            accent_color="#ff4444",
        )
        defaults.update(kwargs)
        self.send_alert(**defaults)

    def subscription_alert(self, username, tier="1", months=1,
                           sub_message="", **kwargs):
        tier_name = {"1": "Tier 1", "2": "Tier 2", "3": "Tier 3"}.get(
            str(tier), f"Tier {tier}"
        )
        msg = f"{username} subscribed at {tier_name}!"
        if months > 1:
            msg = f"{username} resubscribed for {months} months at {tier_name}!"
        if sub_message:
            msg += f"\n{sub_message}"

        defaults = dict(
            alert_type="subscription",
            title="New Subscriber!",
            message=msg,
            duration=6000,
            accent_color="#ffd700",
        )
        defaults.update(kwargs)
        self.send_alert(**defaults)

    def points_alert(self, username, reward_name, user_input="", **kwargs):
        msg = f"{username} redeemed {reward_name}"
        if user_input:
            msg += f": {user_input}"

        defaults = dict(
            alert_type="points",
            title=reward_name,
            message=msg,
            duration=5000,
            accent_color="#9147ff",
        )
        defaults.update(kwargs)
        self.send_alert(**defaults)

    def custom_alert(self, **kwargs):
        """Fully custom alert — pass any send_alert() keyword args."""
        kwargs.setdefault("alert_type", "custom")
        self.send_alert(**kwargs)


if __name__ == "__main__":
    import time
    from logging_config import setup_logging
    setup_logging()

    server = AlertServer()
    server.start()

    print("Alert server running. Press Ctrl+C to stop.")
    print("Connect a browser to alerts/client.html to see alerts.")
    print()

    try:
        time.sleep(3)
        # Send a series of test alerts
        server.follow_alert("TestViewer42")
        time.sleep(7)
        server.raid_alert("BigStreamer", viewer_count=150)
        time.sleep(10)
        server.subscription_alert("LoyalFan", tier="1", months=6,
                                  sub_message="Love this stream!")
        time.sleep(8)
        server.points_alert("ChatUser", "Hydrate!",
                            user_input="drink some water")
        time.sleep(7)
        server.custom_alert(
            title="Custom Alert!",
            message="This is a fully custom alert",
            accent_color="#ff69b4",
            duration=5000,
        )
        # Keep alive so the alerts can finish
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
        print("\nStopped.")
