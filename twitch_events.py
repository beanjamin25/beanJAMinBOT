import logging
import os

import simpleobsws
from playsound import playsound

from obs_control import ObsControl
from twitch_eventsub import TwitchEventsub
from twitch_rest_api import TwitchRestApi

URL = "127.0.0.1"
PORT = "5555"

RAID = "channel.raid"
FOLLOW = "channel.follow"
POINTS = "channel.channel_points_custom_reward_redemption.add"

sfx_dir = "data/sfx"

class TwitchEvents:

    def __init__(self,
                 channel=None,
                 connection=None,
                 twitch_api: TwitchRestApi=None,
                 obs_control: ObsControl=None,
                 sfx_directory="data/sfx", sfx_mappings={}):
        self.channel = channel
        self.connection = connection
        self.sfx_directory = sfx_directory
        self.sfx_mappings = sfx_mappings

        self.obs_control = obs_control

        self.eventsub = TwitchEventsub(port=8008,
                                       twitch=twitch_api,
                                       log_level=logging.DEBUG)

        user_id = twitch_api.get_channel_id(channel.strip("#"))
        self.eventsub.start()
        self.eventsub.unsubscribe_all()
        self.eventsub.listen_channel_follow(user_id, self.on_follow)
        self.eventsub.listen_channel_raid(user_id, self.on_raid)
        self.eventsub.listen_channel_points_redeem(user_id, self.on_points)

    async def on_follow(self, data):
        event = data.get("event", {})
        new_follower = event['user_name']
        new_follow_msg = f"Thank you for following {new_follower}, welcome to the Bean Squad!"
        self.connection.privmsg(self.channel, new_follow_msg)

    async def on_raid(self, data):
        event = data.get("event", {})
        raider = event['from_broadcaster_user_name']
        num_viewers = event['viewers']
        raided_msg = f"{raider} just raided the channel with {num_viewers} viewers! Welcome raiders the Bean Stream!"
        self.connection.privmsg(self.channel, raided_msg)

    async def on_points(self, data):
        event = data.get("event", {})
        reward = event['reward']
        reward_name = reward['title']
        reward_sfx = self.sfx_mappings.get(reward_name)
        if reward_sfx:
            sfx_path = os.path.join(self.sfx_directory, reward_sfx)
            playsound(sfx_path)

        elif reward_name == "Instant Replay":
            ret = self.obs_control.call(simpleobsws.Request("TriggerHotkeyByName",{
                "hotkeyName": "instant_replay.trigger"
            }))
