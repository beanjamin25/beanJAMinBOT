import logging
import os
import queue
import threading
import time

import simpleobsws
from playsound import playsound

import vlc

from obs_control import ObsControl
from tts import TalkBot
from pokemon import PokemonChatGame
from twitch_eventsub import TwitchEventsub
from twitch_rest_api import TwitchRestApi

URL = "127.0.0.1"
PORT = "5555"

RAID = "channel.raid"
FOLLOW = "channel.follow"
POINTS = "channel.channel_points_custom_reward_redemption.add"

sfx_dir = "data/sfx"

class TwitchEvents:

    talk_bot = None

    def __init__(self,
                 channel=None,
                 connection=None,
                 twitch_api: TwitchRestApi=None,
                 obs_control: ObsControl=None,
                 poke_game: PokemonChatGame=None,
                 talk_config=None,
                 sfx_directory="data/sfx", sfx_mappings={}):
        self.channel = channel
        self.connection = connection
        self.sfx_directory = sfx_directory
        self.sfx_mappings = sfx_mappings

        if talk_config:
            self.talk_bot = TalkBot(config=talk_config)

        self.poke_game = poke_game

        self.points_queue = queue.Queue()

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
        self.eventsub.listen_channel_subscription_message(user_id, self.on_sub_message)

        threading.Thread(target=self.points_worker, daemon=True).start()

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
        self.points_queue.put(data)

    async def on_sub_message(self, data):
        event = data.get("event", {})
        message = event['message']['text']
        event['user_input'] = message
        event['reward']['title'] = 'tts'
        self.points_queue.put(data)


    def points_worker(self):
        while True:
            data = self.points_queue.get()
            event = data.get("event", {})
            reward = event['reward']
            reward_name = reward['title']
            user_input = event.get("user_input")
            user = event.get("user_login")
            reward_sfx = self.sfx_mappings.get(reward_name)
            if reward_sfx:
                sfx_path = os.path.join(self.sfx_directory, reward_sfx)
                print("playing this sound: " + sfx_path)
                p = vlc.MediaPlayer(sfx_path)
                p.play()
                #playsound(sfx_path)
                print("played it")

            elif reward_name == "tts" and user_input is not None and self.talk_bot is not None:
                self.talk_bot.read_msg(user_input)

            elif reward_name == "Instant Replay":
                self.obs_control.call(simpleobsws.Request("TriggerHotkeyByName",{
                    "hotkeyName": "instant_replay.trigger"
                }))
                time.sleep(32)

            elif reward_name == "Lets Gooooooooo!":
                self.obs_control.show_source("lets go")
                time.sleep(5)

            elif reward_name == "Nooooooooo!":
                self.obs_control.show_source("nooooo")
                time.sleep(5)

            elif reward_name == "pokeballs" or reward_name == "first!":
                print(event)
                if self.poke_game is not None:
                    self.poke_game.add_pokeballs(user)

            self.points_queue.task_done()