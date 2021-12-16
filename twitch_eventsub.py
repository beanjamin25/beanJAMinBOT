import hashlib
import hmac
import logging
import random
import string
import sys
import time
from concurrent.futures._base import CancelledError

import requests

from aiohttp import web

import threading
import asyncio

from logging import getLogger, Logger
from twitch_rest_api import TwitchRestApi, API_BASE as TWITCH_API_BASE


class TwitchEventsub:

    secret = "".join(random.choice(string.ascii_lowercase) for i in range(20))
    callback_url = None
    wait_for_subscription_confirm: bool = True
    wait_for_subscription_confirm_timeout: int = 30
    unsubscribe_on_stop: bool = True

    _port: int = 88
    _host: str = '0.0.0.0'

    __loop = None
    __runner = None
    __thread = None
    _running = False

    __logger = None

    __twitch: TwitchRestApi = None
    __client_id: str = None

    __callbacks = {}
    __active_subs = {}

    def __init__(self,
                 port: int,
                 twitch: TwitchRestApi,
                 log_level=logging.ERROR):

        self._port = port
        self.__twitch = twitch
        self.callback_url = self.__twitch.callback_uri

        formatter = logging.Formatter("[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s")

        self.__logger = getLogger("TwitchEventsub")
        self.__logger.setLevel(log_level)
        local_handler = logging.StreamHandler(stream=sys.stdout)
        local_handler.setFormatter(formatter)
        self.__logger.addHandler(local_handler)

        aio_logger = getLogger("aiohttp.access")
        aio_logger.setLevel(log_level)
        aio_handler = logging.StreamHandler(stream=sys.stdout)
        aio_handler.setFormatter(formatter)
        aio_logger.addHandler(aio_handler)

    def __build_runner(self):
        app = web.Application()
        app.add_routes([web.post("/callback", self.__handle_callback),
                        web.get("/", self.__handle_default)])

        return web.AppRunner(app)

    def __run_hook(self, runner: 'web.AppRunner'):
        self.__runner = runner
        self.__loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.__loop)
        self.__loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, str(self._host), self._port)
        self.__loop.run_until_complete(site.start())
        self.__logger.info(f"started Eventsub listener on port {self._port}")
        try:
            self.__loop.run_forever()
        except (CancelledError, asyncio.CancelledError):
            self.__logger.debug('cancel culture run amok')

    def start(self):
        if self._running:
            raise RuntimeError("already running")

        self.__thread = threading.Thread(target=self.__run_hook, args=(self.__build_runner(),), daemon=True)
        self._running = True
        self.__thread.start()

    def stop(self):
        if self.__runner is not None and self.unsubscribe_on_stop:
            self.__logger.info("would delete all subs if we are live")
            self.unsubscribe_all_listen()

        tasks = {t for t in asyncio.all_tasks(loop=self.__loop) if not t.done()}
        for task in tasks:
            task.cancel()

        self.__loop.call_soon_threadsafe(self.__loop.stop)
        self.__runner = None
        self._running = False

    ########## HELPERS ####################################

    def __request_headers(self):
        token = self.__twitch.get_app_token()
        return {
            'Client-ID': self.__twitch.client_id,
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}'
        }

    def __post(self, url, data=None):
        headers = self.__request_headers()
        return requests.post(url, headers=headers, json=data)

    def __get(self, url, params=None):
        headers = self.__request_headers()
        return requests.get(url, headers=headers, params=params)

    def __delete(self, url, params=None):
        headers = self.__request_headers()
        return requests.delete(url, headers=headers, params=params)

    def __add_callback(self, callback_id, callback):
        self.__callbacks[callback_id] = {'id': callback_id, 'callback': callback, 'active': False}

    def __enable_callback(self, callback_id):
        self.__callbacks[callback_id]['active'] = True

    def _subscribe(self, sub_type, condition, callback):
        self.__logger.debug(f"subscribe to {sub_type} with condtion {condition}")

        sub_data = {
            'type': sub_type,
            'version': "1",
            'condition': condition,
            'transport': {
                'method': 'webhook',
                'callback': f'{self.callback_url}/callback',
                'secret': self.secret
            }
        }

        response = self.__post(TWITCH_API_BASE + "eventsub/subscriptions", data=sub_data)
        result = response.json()

        error = result.get('error')
        if error is not None:
            self.__logger.error(result)
            return

        subscription_id = result['data'][0]['id']
        self.__add_callback(subscription_id, callback)

        timeout = 0
        while timeout < 30:
            if self.__callbacks[subscription_id]['active']:
                return subscription_id
            time.sleep(0.01)
            timeout += 0.01
        self.__callbacks.pop(subscription_id, None)
        raise Exception(f"Failed to subscribe to {sub_type}")

    def _unsubscribe(self, subscription_id):
        self.__logger.debug(f"unsubscribing from sub id {subscription_id}")

        result = self.__delete(TWITCH_API_BASE + "eventsub/subscriptions", params={'id': subscription_id})
        return result.status_code == 204

    async def _verify_signature(self, request: "web.Request") -> bool:
        message_id = request.headers['Twitch-Eventsub-Message-Id']
        message_timestamp = request.headers['Twitch-Eventsub-Message-Timestamp']
        hmac_message = message_id + message_timestamp + await request.text()
        digester = hmac.new(bytes(self.secret, 'utf-8'), bytes(hmac_message, 'utf-8'), hashlib.sha256)
        calculated_signature = digester.hexdigest()
        provided_signature = request.headers['Twitch-Eventsub-Message-Signature'].split("sha256=")[1]

        return calculated_signature == provided_signature

    ########## HANDLERS ###################################

    async def __handle_default(self, request: 'web.Request'):
        self.__logger.info("hit default")
        return web.Response(text="hello there!")

    async def __handle_challenge(self, request: 'web.Request', data):
        self.__logger.debug(f'challenge for subscription {data.get("subscription").get("id")}')
        if not await self._verify_signature(request):
            return web.Response(status=403)

        self.__enable_callback(data.get("subscription").get("id"))
        return web.Response(text=data.get("challenge"))

    async def __handle_callback(self, request: 'web.Request'):
        data: dict = await request.json()
        if data.get("challenge") is not None:
            return await self.__handle_challenge(request, data)

        if not await self._verify_signature(request):
            self.__logger.warning(f'mismatched signature!')
            return web.Response(status=403)

        subscription_id = data.get("subscription", {}).get("id")
        callback = self.__callbacks.get(subscription_id)
        if callback is None:
            self.__logger.error(f"event received for unknown sub with ID {subscription_id}")
        else:
            self.__loop.create_task(callback['callback'](data))

        return web.Response(status=200)

    def unsubscribe_all(self):
        res = self.__twitch.get_eventsub_subscriptions()
        if res:
            for sub in res.get('data', {}):
                sub_id = sub.get('id')
                self._unsubscribe(sub_id)

    def unsubscribe_all_listen(self):
        for sub_id, callback in self.__callbacks.items():
            self.__logger.debug(f"unsubscribing from event {sub_id}")
            res = self._unsubscribe(sub_id)
            if not res:
                self.__logger.warning(f"failed to unsubscribe from {sub_id}")
        self.__callbacks.clear()

    def unsubscrube_topic(self, topic_id):
        res = self._unsubscribe(topic_id)
        if res:
            self.__callbacks.pop(topic_id, None)
        else:
            self.__logger.warning(f"failed to unsubscribe from {topic_id}")

    def listen_channel_follow(self, broadcaster_user_id, callback):
        condition = {
            'broadcaster_user_id': broadcaster_user_id
        }
        return self._subscribe("channel.follow", condition, callback)

    def listen_channel_ban(self, broadcaster_user_id, callback):
        condition = {
            'broadcaster_user_id': broadcaster_user_id
        }
        return self._subscribe('channel.ban', condition, callback)

    def listen_channel_unban(self, broadcaster_user_id, callback):
        condition = {
            'broadcaster_user_id': broadcaster_user_id
        }
        return self._subscribe('channel.unban', condition, callback)

    def listen_channel_raid(self, broadcaster_user_id, callback):
        condition = {
            'to_broadcaster_user_id': broadcaster_user_id
        }
        return self._subscribe('channel.raid', condition, callback)

    def listen_channel_points_redeem(self, broadcaster_user_id, callback):
        condition = {
            'broadcaster_user_id': broadcaster_user_id
        }
        return self._subscribe('channel.channel_points_custom_reward_redemption.add', condition, callback)

