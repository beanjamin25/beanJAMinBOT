import os
import threading
import time

import simpleobsws
import asyncio

from exceptions import OBSSceneItemNotFoundError
from logging_config import get_logger


class ObsControl:

    __loop = None
    __thread = None
    _running = False

    ws = None
    __callbacks = {}

    shown_media = set()

    def __init__(self, url='ws://localhost:4444', password=''):

        self.url = url
        self.password = password

        self.__logger = get_logger('obs_control')

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
        except asyncio.CancelledError:
            self.__logger.info("OBS event loop cancelled")
        except Exception:
            self.__logger.exception("Unexpected error in OBS event loop")

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
        try:
            source_id = asyncio.run_coroutine_threadsafe(self.get_scene_item_id("Main Scene", source_name), self.__loop).result()
        except OBSSceneItemNotFoundError:
            self.__logger.warning(f"Cannot show source {source_name}: not found")
            return
        self.__logger.debug(f"sourceId: {source_id}")
        asyncio.run_coroutine_threadsafe(self.show_media(source_id), self.__loop)

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

    async def get_scene_item_id(self, scene_name, source_name):
        """Get scene item ID. Raises OBSSceneItemNotFoundError if not found."""
        request = simpleobsws.Request("GetSceneItemId", {
            "sceneName": scene_name,
            "sourceName": source_name
        })
        ret = await self.ws.call(request)
        if ret.ok():
            return int(ret.responseData.get("sceneItemId"))
        self.__logger.warning(f"Scene item not found: {source_name} in {scene_name}")
        raise OBSSceneItemNotFoundError(scene_name, source_name)

    async def hide_finished_media(self, event_data):
        input_name = event_data.get("inputName")
        try:
            input_id = await self.get_scene_item_id("Main Scene", input_name)
        except OBSSceneItemNotFoundError:
            self.__logger.debug(f"Scene item {input_name} not found, skipping hide")
            return
        if input_id not in self.shown_media:
            self.__logger.debug(f"{input_name} is not in the previously shown media!")
            return
        self.shown_media.remove(input_id)
        self.__logger.debug(f"making call SetSceneItemEnabled: {input_name} false")
        await self.ws.call(simpleobsws.Request("SetSceneItemEnabled", {
            "sceneName": "Main Scene", "sceneItemId": input_id, "sceneItemEnabled": False
        }))

    async def show_media(self, source_id):
        self.__logger.debug(f"making call SetSceneItemEnabled: {source_id} true")
        self.shown_media.add(source_id)
        await self.ws.call(simpleobsws.Request("SetSceneItemEnabled", {
            "sceneName": "Main Scene", "sceneItemId": source_id, "sceneItemEnabled": True
        }))


    async def on_replaybuffer_saved(self, event_data):
        self.__logger.debug(event_data)
        full_path = event_data.get("savedReplayPath")
        directory = os.path.dirname(full_path)
        filename = os.path.basename(full_path)
        for replay in os.listdir(directory):
            if replay.startswith("Replay") and replay != filename:
                os.remove(os.path.join(directory, replay))
        try:
            scene_item_id = await self.get_scene_item_id("Main Scene", "instant replay")
        except OBSSceneItemNotFoundError:
            self.__logger.warning("Cannot show instant replay: scene item not found")
            return
        await asyncio.sleep(1)
        await self.show_media(scene_item_id)


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

