import asyncio
import logging
import sys
import uuid
import webbrowser
from time import sleep
from concurrent.futures._base import CancelledError
from logging import getLogger
from threading import Thread

import requests
from aiohttp import web

from twitch_rest_api import TwitchRestApi


TWITCH_AUTH_BASE_URL = "https://id.twitch.tv/"

class TwitchOauth:

    __page = """<!DOCTYPE hmtl>
    <hmtl lang="en">
    <head>
      <meta charset="UTF-8">
      <title>beanJAMinBOT Oauth</title>
    <head>
    <body>
      <h1>You are now authenticated with the beanJAMinBOT!!!</h1>
      You can now close this page.
    </body>
    </html>"""

    __twitch: TwitchRestApi = None

    port = 17526
    url = "http://localhost:17526"
    host = '0.0.0.0'
    scopes = list()
    __state = str(uuid.uuid4())
    __logger = None

    __client_id = None
    __callback = None

    __server_running = False
    __loop = None
    __runner = None
    __thread = None

    __user_token = None

    __can_close = False

    def __init__(self,
                 twitch: TwitchRestApi,
                 url="http://localhost:17526",
                 log_level=logging.ERROR):

        self.__twitch = twitch
        self.__client_id = twitch.client_id
        self.scopes = twitch.scopes
        self.url = url

        formatter = logging.Formatter("[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s")

        self.__logger = getLogger("TwitchOauth")
        self.__logger.setLevel(log_level)
        local_handler = logging.StreamHandler(stream=sys.stdout)
        local_handler.setFormatter(formatter)
        self.__logger.addHandler(local_handler)

        aio_logger = getLogger("aiohttp.access")
        aio_logger.setLevel(log_level)
        aio_handler = logging.StreamHandler(stream=sys.stdout)
        aio_handler.setFormatter(formatter)
        aio_logger.addHandler(aio_handler)

    def __build_auth_url(self):
        params = {
            'client_id': self.__client_id,
            'redirect_uri': self.url,
            'response_type': 'code',
            'scope': " ".join(self.scopes),
            'state': self.__state
        }
        final_url = requests.Request('GET', TWITCH_AUTH_BASE_URL + 'oauth2/authorize', params=params).prepare()
        self.__logger.debug(final_url.url)
        return final_url.url

    def __build_runner(self):
        app = web.Application()
        app.add_routes([web.get('/', self.__handle_callback)])
        return web.AppRunner(app)

    async def __run_check(self):
        while not self.__can_close:
            try:
                await asyncio.sleep(1)
            except (CancelledError, asyncio.CancelledError):
                pass
        for task in asyncio.all_tasks(self.__loop):
            task.cancel()

    def __run(self, runner: 'web.AppRunner'):
        self.__runner = runner
        self.__loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.__loop)
        self.__loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, self.host, self.port)
        self.__loop.run_until_complete(site.start())
        self.__server_running = True
        self.__logger.info("running oauth WebServer")
        try:
            self.__loop.run_until_complete(self.__run_check())
        except (CancelledError, asyncio.CancelledError):
            pass

    def __start(self):
        self.__thread = Thread(target=self.__run, args=(self.__build_runner(),))
        self.__thread.start()

    def stop(self):
        self.__can_close = True

    async def __handle_callback(self, request: 'web.Request'):
        val = request.rel_url.query.get('state')
        self.__logger.debug(f'got callback with state: {val}')

        if val != self.__state:
            return web.Response(status=401)

        self.__user_token = request.rel_url.query.get('code')
        if self.__user_token is None:
            return web.Response(status=400)

        if self.__callback is not None:
            self.__callback(self.__user_token)
        return web.Response(text=self.__page, content_type='text/html')

    def return_auth_url(self):
        return self.__build_auth_url()

    def authenticate(self, callback=None, user_token=None):
        self.__callback = callback

        if user_token is None:
            self.__start()
            while not self.__server_running:
                sleep(0.01)
                webbrowser.open(self.__build_auth_url(), new=2)
                while self.__user_token is None:
                    sleep(0.01)
        else:
            self.__user_token = user_token

        param = {
            'client_id': self.__client_id,
            'client_secret': self.__twitch.client_secret,
            'code': self.__user_token,
            'grant_type': 'authorization_code',
            'redirect_uri': self.url
        }
        response = requests.post(TWITCH_AUTH_BASE_URL + 'oauth2/token', params=param)
        data = response.json()
        if callback is None:
            self.stop()
            if data.get('access_token') is None:
                raise Exception(f"Authentication Failed:\n{str(data)}")
            return data['access_token'], data['refresh_token']
        elif user_token is not None:
            self.__callback(user_token)


if __name__ == "__main__":
    twitch_api = TwitchRestApi(auth_filename="config/botjamin_auth.yaml")

    auth = TwitchOauth(twitch=twitch_api, log_level=logging.DEBUG)

    token, refresh = auth.authenticate()

    print("token:", token)
    print("refresh:", refresh)