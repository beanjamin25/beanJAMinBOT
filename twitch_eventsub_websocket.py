import json
import logging
import sys
import asyncio
import threading
import time

import websockets

from twitch_rest_api import TwitchRestApi


class TwitchEventsubWebsocket:

    subscription_list: list = list()
    callbacks: dict = dict()
    ws: websockets.WebSocketClientProtocol
    __twitch: TwitchRestApi = None


    def __init__(self,
                 twitch: TwitchRestApi,
                 url="wss://eventsub.wss.twitch.tv/ws",
                 log_level=logging.ERROR):
        self.url = url

        self.__twitch = twitch

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
        self.__loop.run_until_complete(self.__connect())
        self.__logger.debug("started?")
        try:
            self.__loop.run_forever()
        except Exception as e:
            self.__logger.debug(e)

    async def __connect(self):
        self.__logger.debug("started connect method")
        self.ws = await websockets.connect(self.url)
        self.recv_task = self.__loop.create_task(self._ws_recv_task())
        self.__logger.debug("finished connect method")

    async def _ws_recv_task(self):
        while self.ws.open:
            message = ''
            try:
                message = await self.ws.recv()
                if not message:
                    continue
                incoming_payload = json.loads(message)
                metadata = incoming_payload.get("metadata")
                payload = incoming_payload.get("payload")
                message_type = metadata.get("message_type")
                if message_type == "session_welcome":
                    self.__loop.create_task(self.on_welcome(payload))
                elif message_type == "session_keepalive":
                    continue
                elif message_type == "notification":
                    self.__loop.create_task(self.handle_callback(payload))
                self.__logger.debug(json.dumps(incoming_payload, indent=2))
            except (websockets.exceptions.ConnectionClosed, websockets.exceptions.ConnectionClosedError, websockets.exceptions.ConnectionClosedOK):
                self.__logger.debug('The WebSocket connection was closed. Code: {} | Reason: {}'.format(self.ws.close_code, self.ws.close_reason))
                break
            except json.JSONDecodeError:
                continue

    async def handle_callback(self, payload):
        self.__logger.debug("handling callback!")
        subscription_id = payload.get("subscription", {}).get("id")
        callback = self.callbacks.get(subscription_id)
        if callback is None:
            self.__logger.error(f"event received for unkown sub with ID {subscription_id}")
        else:
            await callback(payload)

    async def on_welcome(self, payload):
        self.__logger.info("on welcome")
        session = payload["session"]
        self.session_id = session.get('id')
        self.__twitch.delete_all_eventsub_subscriptions_websocket()
        for (sub_type, condition, callback, version) in self.subscription_list:
            response = self.__twitch.eventsub_add_subscription_websocket(
                condition,
                sub_type,
                self.session_id,
                version
            )
            result = response.json()
            error = result.get("error")
            if error is not None:
                self.__logger.debug(f"error for sub {sub_type}: {result}")
                self.__logger.debug(response.request.body)
                return

            subscription_id = result['data'][0]['id']
            self.callbacks[subscription_id] = callback

        response = self.__twitch.get_eventsub_subscriptions_websocket()
        self.__logger.debug(json.dumps(response, indent=2))
        self.__logger.debug(self.callbacks)
        self.__logger.info("websockets listening")


    def start(self):
        self.__thread = threading.Thread(target=self.__run_hook, daemon=True)
        self.__thread.start()

    def stop(self):
        self.__twitch.delete_all_eventsub_subscriptions_websocket()

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
        self._subscribe("channel.follow", condition, callback, version=2)

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