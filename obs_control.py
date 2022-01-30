import sys
import threading
import time

import simpleobsws
import asyncio
import logging


logging.basicConfig(level=logging.DEBUG)
class ObsControl:

    __loop = None
    __thread = None
    _running = False

    ws = None
    __callbacks = {}

    def __init__(self, url='ws://localhost:4444', password='', log_level=logging.ERROR):

        self.url = url
        self.password = password

        formatter = logging.Formatter("[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s")
        self.__logger = logging.getLogger(__name__)
        self.__logger.setLevel(log_level)
        local_handler = logging.StreamHandler(stream=sys.stdout)
        local_handler.setFormatter(formatter)
        self.__logger.addHandler(local_handler)

        # obs_log = logging.getLogger('simpleobsws')
        # obs_log.setLevel(log_level)
        # obs_handler = logging.StreamHandler(stream=sys.stdout)
        # obs_handler.setFormatter(formatter)
        # obs_log.addHandler(obs_handler)

    def __run_hook(self):
        self.__logger.debug("starting")
        self.__loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.__loop)
        parameters = simpleobsws.IdentificationParameters(ignoreNonFatalRequestChecks=False)
        self.ws = simpleobsws.WebSocketClient(url=self.url,
                                              password=self.password,
                                              identification_parameters=parameters)
        self.__loop.run_until_complete(self.__connect())
        self.__logger.debug("started?")
        try:
            self.__loop.run_forever()
        except Exception as e:
            self.__logger.debug(e)

    def start(self):
        if self._running:
            raise RuntimeError("already Running")

        self.__thread = threading.Thread(target=self.__run_hook, daemon=True)
        self._running = True
        self.__thread.start()

    def stop(self):
        tasks = {t for t in asyncio.all_tasks(loop=self.__loop) if not t.done()}
        for task in tasks:
            task.cancel()

        self.__loop.run_until_complete(self.ws.disconnect())
        self.__loop.call_soon_threadsafe(self.__loop.stop)
        self._running = False

    def call(self, request: simpleobsws.Request):
        print(f"making call: {request.requestType}")
        future = asyncio.run_coroutine_threadsafe(self.ws.call(request), self.__loop)
        return future.result()

    def register_callback(self, callback, event):
        self.ws.register_event_callback(callback, event)

    async def __connect(self):
        await self.ws.connect()
        await self.ws.wait_until_identified()



    async def getSceneItemId(self, sceneName, sourceName):
        print("getting sceneitemid")
        request = simpleobsws.Request("GetSceneItemId", {
            "sceneName": sceneName,
            "sourceName": sourceName
        })
        ret = await self.ws.call(request)
        if ret.ok():
            print("got a result?")
            return int(ret.responseData.get("sceneItemId"))
        return False


async def hide_finished_media(eventData):
    print("hiding finished media?")
    input_name = eventData.get("inputName")
    print(f"input name: {input_name}")
    input_id = await obs.getSceneItemId("Main Scene", input_name)
    print(f"input id: {input_id}")
    await obs.ws.call(simpleobsws.Request("SetSceneItemEnabled", {
        "sceneName": "Main Scene", "sceneItemId": input_id, "sceneItemEnabled": False
    }))


async def on_switchscenes(eventData):
    print(f"f{eventData}")

async def on_replaybuffer_saved(eventData):
    print("replay buffer is saved?")
    sceneItemId = await obs.getSceneItemId("Main Scene", "instant replay")
    print(f"sceneItemId: {sceneItemId}")
    await asyncio.sleep(0.5)
    res = await obs.ws.call(simpleobsws.Request("SetSceneItemEnabled", {
        "sceneName": "Main Scene", "sceneItemId": sceneItemId, "sceneItemEnabled": True
    }))
    print(res)

if __name__ == "__main__":
    obs = ObsControl(password='GlVRHdkopGW63tbZ', log_level=logging.DEBUG)
    obs.start()
    time.sleep(1)
    obs.register_callback(on_replaybuffer_saved, "ReplayBufferSaved")
    obs.register_callback(hide_finished_media, "MediaInputPlaybackEnded")
    time.sleep(1)
    request = request = simpleobsws.Request('TriggerHotkeyByName', {'hotkeyName': 'instant_replay.trigger'})
    print(obs.call(request))
    time.sleep(100)
    obs.stop()
    # loop = asyncio.get_event_loop()
    # loop.run_until_complete(make_request())
    # ws.register_event_callback(on_switchscenes, 'CurrentProgramSceneChanged')
    # ws.register_event_callback(hide_finished_media, "MediaInputPlaybackEnded")
    # ws.register_event_callback(on_replaybuffer_saved, "ReplayBufferSaved")
    # loop.run_forever()

