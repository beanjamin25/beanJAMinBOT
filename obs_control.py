import simpleobsws
import asyncio
import logging
logging.basicConfig(level=logging.DEBUG)
obs_log = logging.getLogger('simpleobsws')
#obs_log.setLevel(logging.DEBUG)

import websockets


parameters = simpleobsws.IdentificationParameters(ignoreNonFatalRequestChecks=False)

ws = simpleobsws.WebSocketClient(url='ws://localhost:4444', password="GlVRHdkopGW63tbZ", identification_parameters=parameters)

async def make_request():
    await ws.connect()
    res = await ws.wait_until_identified()

    if res is False:
        print(f"{res} identified?")
        await ws.disconnect()
        return

    request = simpleobsws.Request('TriggerHotkeyByName', {'hotkeyName': 'instant_replay.trigger'})
    ret = await ws.call(request)
    print(f"status: {ret.ok()}")
    print(f"data: {ret.responseData}")


async def getSceneItemId(sceneName, sourceName):
    request = simpleobsws.Request("GetSceneItemId", {
        "sceneName": sceneName,
        "sourceName": sourceName
    })
    ret = await ws.call(request)
    if ret.ok():
        return int(ret.responseData.get("sceneItemId"))
    return False

async def hide_finished_media(eventData):
    input_name = eventData.get("inputName")
    input_id = await getSceneItemId("Main Scene", input_name)
    await ws.call(simpleobsws.Request("SetSceneItemEnabled", {
        "sceneName": "Main Scene", "sceneItemId": input_id, "sceneItemEnabled": False
    }))


async def on_switchscenes(eventData):
    print(f"f{eventData}")

async def on_replaybuffer_saved(eventData):
    sceneItemId = await getSceneItemId("Main Scene", "instant replay 2")
    print(f"sceneItemId: {sceneItemId}")
    await ws.call(simpleobsws.Request("SetSceneItemEnabled", {
        "sceneName": "Main Scene", "sceneItemId": sceneItemId, "sceneItemEnabled": True
    }))


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(make_request())
    ws.register_event_callback(on_switchscenes, 'CurrentProgramSceneChanged')
    ws.register_event_callback(hide_finished_media, "MediaInputPlaybackEnded")
    ws.register_event_callback(on_replaybuffer_saved, "ReplayBufferSaved")
    loop.run_forever()

