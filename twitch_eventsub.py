import json
import logging
import sys
import asyncio
import threading

import websockets

from twitch_rest_api import TwitchRestApi

DEFAULT_URL = "wss://eventsub.wss.twitch.tv/ws"
RECONNECT_BACKOFF_BASE = 1
RECONNECT_BACKOFF_MAX = 120


class TwitchEventsubWebsocket:

    def __init__(self,
                 twitch: TwitchRestApi,
                 url=DEFAULT_URL,
                 log_level=logging.ERROR):
        self.url = url
        self._connect_url = url

        self.__twitch = twitch
        self.__stopping = False
        self._keepalive_timeout = None

        self.subscription_list = []
        self.callbacks = {}

        formatter = logging.Formatter("[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s")
        self.__logger = logging.getLogger(__name__)
        self.__logger.setLevel(log_level)
        local_handler = logging.StreamHandler(stream=sys.stdout)
        local_handler.setFormatter(formatter)
        self.__logger.addHandler(local_handler)

    def __run_hook(self):
        self.__logger.debug("starting")
        self.__loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.__loop)
        self.__loop.run_until_complete(self.__run_with_reconnect())

    async def __run_with_reconnect(self):
        backoff = RECONNECT_BACKOFF_BASE
        while not self.__stopping:
            try:
                await self.__connect()
                await self._ws_recv_task()
            except Exception as e:
                self.__logger.error(f"WebSocket error: {e}")

            if self.__stopping:
                break

            self.__logger.info(f"reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, RECONNECT_BACKOFF_MAX)
            self._connect_url = self.url

    async def __connect(self):
        self.__logger.debug(f"connecting to {self._connect_url}")
        self.ws = await websockets.connect(self._connect_url)
        self.__logger.debug("connected")

    async def _ws_recv_task(self):
        while self.ws.open:
            try:
                timeout = self._keepalive_timeout + 5 if self._keepalive_timeout else None
                message = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
                if not message:
                    continue
                incoming_payload = json.loads(message)
                metadata = incoming_payload.get("metadata")
                payload = incoming_payload.get("payload")
                message_type = metadata.get("message_type")
                if message_type == "session_welcome":
                    await self.on_welcome(payload)
                elif message_type == "session_keepalive":
                    continue
                elif message_type == "session_reconnect":
                    await self._handle_reconnect(payload)
                    return
                elif message_type == "notification":
                    await self.handle_callback(payload)
                self.__logger.debug(json.dumps(incoming_payload, indent=2))
            except asyncio.TimeoutError:
                self.__logger.warning("keepalive timeout — connection is dead, reconnecting")
                await self.ws.close()
                return
            except (websockets.exceptions.ConnectionClosed,
                    websockets.exceptions.ConnectionClosedError,
                    websockets.exceptions.ConnectionClosedOK):
                self.__logger.debug('WebSocket closed. Code: {} | Reason: {}'.format(
                    self.ws.close_code, self.ws.close_reason))
                return
            except json.JSONDecodeError:
                continue

    async def _handle_reconnect(self, payload):
        session = payload.get("session", {})
        reconnect_url = session.get("reconnect_url")
        self.__logger.info(f"received session_reconnect, new url: {reconnect_url}")
        old_ws = self.ws
        self._connect_url = reconnect_url
        await self.__connect()
        # Wait for welcome on new connection, then close old one
        message = await self.ws.recv()
        incoming_payload = json.loads(message)
        metadata = incoming_payload.get("metadata")
        payload = incoming_payload.get("payload")
        if metadata.get("message_type") == "session_welcome":
            await self.on_welcome(payload)
        await old_ws.close()
        # Continue receiving on the new connection
        await self._ws_recv_task()

    async def handle_callback(self, payload):
        self.__logger.debug("handling callback!")
        subscription_id = payload.get("subscription", {}).get("id")
        callback = self.callbacks.get(subscription_id)
        if callback is None:
            self.__logger.error(f"event received for unknown sub with ID {subscription_id}")
        else:
            await callback(payload)

    async def on_welcome(self, payload):
        self.__logger.info("on welcome")
        session = payload["session"]
        self.session_id = session.get('id')
        self._keepalive_timeout = session.get('keepalive_timeout_seconds', 10)
        self.__twitch.delete_all_eventsub_subscriptions()
        self.callbacks.clear()
        for (sub_type, condition, callback, version) in self.subscription_list:
            response = self.__twitch.eventsub_add_subscription(
                condition,
                sub_type,
                self.session_id,
                version
            )
            result = response.json()
            error = result.get("error")
            if error is not None:
                self.__logger.error(f"error for sub {sub_type}: {result}")
                self.__logger.debug(response.request.body)
                continue

            subscription_id = result['data'][0]['id']
            self.callbacks[subscription_id] = callback

        response = self.__twitch.get_eventsub_subscriptions()
        self.__logger.debug(json.dumps(response, indent=2))
        self.__logger.debug(self.callbacks)
        self.__logger.info("websockets listening")

    def start(self):
        self.__stopping = False
        self.__thread = threading.Thread(target=self.__run_hook, daemon=True)
        self.__thread.start()

    def stop(self):
        self.__stopping = True
        self.__twitch.delete_all_eventsub_subscriptions()

        if hasattr(self, '_TwitchEventsubWebsocket__loop'):
            tasks = {t for t in asyncio.all_tasks(loop=self.__loop) if not t.done()}
            for task in tasks:
                task.cancel()
            self.__loop.call_soon_threadsafe(self.__loop.stop)

    def _subscribe(self, sub_type, condition, callback, version='1'):
        self.__logger.debug(f"subbing to {sub_type}")
        self.subscription_list.append((sub_type, condition, callback, version))

    def listen_channel_follow(self, broadcaster_user_id, callback):
        condition = {
            'broadcaster_user_id': broadcaster_user_id,
            'moderator_user_id': broadcaster_user_id
        }
        self._subscribe("channel.follow", condition, callback, version='2')

    def listen_channel_ban(self, broadcaster_user_id, callback):
        condition = {
            'broadcaster_user_id': broadcaster_user_id
        }
        self._subscribe('channel.ban', condition, callback)

    def listen_channel_unban(self, broadcaster_user_id, callback):
        condition = {
            'broadcaster_user_id': broadcaster_user_id
        }
        self._subscribe('channel.unban', condition, callback)

    def listen_channel_raid(self, broadcaster_user_id, callback):
        condition = {
            'to_broadcaster_user_id': broadcaster_user_id
        }
        self._subscribe('channel.raid', condition, callback)

    def listen_channel_points_redeem(self, broadcaster_user_id, callback):
        condition = {
            'broadcaster_user_id': broadcaster_user_id
        }
        self._subscribe('channel.channel_points_custom_reward_redemption.add', condition, callback)

    def listen_channel_subscription_message(self, broadcaster_user_id, callback):
        condition = {
            'broadcaster_user_id': broadcaster_user_id
        }
        self._subscribe('channel.subscription.message', condition, callback)


if __name__ == "__main__":
    twitch = TwitchRestApi(auth_filename="config/botjamin_auth.yaml")
    bean = twitch.get_channel_id("beanjamin25")
    eventsub_websockets = TwitchEventsubWebsocket(twitch, log_level=logging.DEBUG)
    eventsub_websockets.listen_channel_follow(bean, "hello")
    eventsub_websockets.start()
