import os
import sys
import threading
import time

import simpleobsws
import asyncio
import logging


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

        threading.Thread(target=self.wait_until_started, daemon=True).start()


    def wait_until_started(self, timeout=None):
        start = time.time()
        while True:
            if self.ws is not None and self.ws.is_identified():
                self.register_callback(self.hide_finished_media, "MediaInputPlaybackEnded")
                self.register_callback(self.on_replaybuffer_saved, "ReplayBufferSaved")
                return
            if timeout is not None and time.time() - start > timeout:
                raise TimeoutError
            time.sleep(0.1)

    def stop(self):
        tasks = {t for t in asyncio.all_tasks(loop=self.__loop) if not t.done()}
        for task in tasks:
            task.cancel()

        self.__loop.run_until_complete(self.ws.disconnect())
        self.__loop.call_soon_threadsafe(self.__loop.stop)
        self._running = False

    def call(self, request: simpleobsws.Request):
        self.__logger.debug(f"making call: {request.requestType}")
        future = asyncio.run_coroutine_threadsafe(self.ws.call(request), self.__loop)
        return future

    def show_source(self, source_name):
        sourceId = asyncio.run_coroutine_threadsafe(self.getSceneItemId("Main Scene", source_name), self.__loop).result()
        self.__logger.debug(f"sourceId: {sourceId}")
        asyncio.run_coroutine_threadsafe(self.show_media(sourceId), self.__loop)

    def register_callback(self, callback, event):
        self.ws.register_event_callback(callback, event)

    async def __connect(self):
        while not self.ws.is_identified():
            try:
                await self.ws.connect()
                await self.ws.wait_until_identified()
            except ConnectionRefusedError:
                self.__logger.error("OBS is not on, trying again in 5 secs...")
                await asyncio.sleep(5)

    async def getSceneItemId(self, sceneName, sourceName):
        request = simpleobsws.Request("GetSceneItemId", {
            "sceneName": sceneName,
            "sourceName": sourceName
        })
        ret = await self.ws.call(request)
        if ret.ok():
            return int(ret.responseData.get("sceneItemId"))
        return False

    async def hide_finished_media(self, eventData):
        input_name = eventData.get("inputName")
        input_id = await self.getSceneItemId("Main Scene", input_name)
        self.__logger.debug(f"making call SetSceneItemEnabled: {input_id} false")
        await self.ws.call(simpleobsws.Request("SetSceneItemEnabled", {
            "sceneName": "Main Scene", "sceneItemId": input_id, "sceneItemEnabled": False
        }))

    async def show_media(self, sourceId):
        self.__logger.debug(f"making call SetSceneItemEnabled: {sourceId} true")
        await self.ws.call(simpleobsws.Request("SetSceneItemEnabled", {
            "sceneName": "Main Scene", "sceneItemId": sourceId, "sceneItemEnabled": True
        }))


    async def on_replaybuffer_saved(self, eventData):
        self.__logger.debug(eventData)
        full_path = eventData.get("savedReplayPath")
        dir = os.path.dirname(full_path)
        filename = full_path.strip(dir)
        for replay in os.listdir(dir):
            if replay.startswith("Replay") and replay != filename:
                os.remove(os.path.join(dir, replay))
        sceneItemId = await self.getSceneItemId("Main Scene", "instant replay")
        await asyncio.sleep(1)
        await self.show_media(sceneItemId)


# async def hide_finished_media(eventData):
#     print("hiding finished media?")
#     input_name = eventData.get("inputName")
#     print(f"input name: {input_name}")
#     input_id = await obs.getSceneItemId("Main Scene", input_name)
#     print(f"input id: {input_id}")
#     await obs.ws.call(simpleobsws.Request("SetSceneItemEnabled", {
#         "sceneName": "Main Scene", "sceneItemId": input_id, "sceneItemEnabled": False
#     }))
#
#
# async def on_switchscenes(eventData):
#     print(f"f{eventData}")
#
# async def on_replaybuffer_saved(eventData):
#     print("replay buffer is saved?")
#     sceneItemId = await obs.getSceneItemId("Main Scene", "instant replay")
#     print(f"sceneItemId: {sceneItemId}")
#     await asyncio.sleep(0.5)
#     res = await obs.ws.call(simpleobsws.Request("SetSceneItemEnabled", {
#         "sceneName": "Main Scene", "sceneItemId": sceneItemId, "sceneItemEnabled": True
#     }))
#     print(res)
#
# if __name__ == "__main__":
#     obs = ObsControl(password='GlVRHdkopGW63tbZ', log_level=logging.DEBUG)
#     obs.start()
#     #obs.wait_until_started()
#     print("identified!")
#     obs.register_callback(on_replaybuffer_saved, "ReplayBufferSaved")
#     obs.register_callback(hide_finished_media, "MediaInputPlaybackEnded")
#     time.sleep(1)
#     request = request = simpleobsws.Request('TriggerHotkeyByName', {'hotkeyName': 'instant_replay.trigger'})
#     print(obs.call(request))
#     t

