import zmq
import threading
import os

from playsound import playsound

URL = "127.0.0.1"
PORT = "5555"

RAID = "channel.raid"
FOLLOW = "channel.follow"
POINTS = "channel.channel_points_custom_reward_redemption.add"

sfx_dir = "data/sfx"

class TwitchEvents(threading.Thread):

    def __init__(self, channel=None, connection=None, sfx_directory="data/sfx", sfx_mappings={}):
        threading.Thread.__init__(self)
        self.daemon = True

        self.channel = channel
        self.connection = connection
        self.sfx_directory = sfx_directory
        self.sfx_mappings = sfx_mappings

        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REP)
        # We can connect to several endpoints if we desire, and receive from all.
        self.socket.bind(f'tcp://{URL}:{PORT}')


    def run(self) -> None:
        c = self.connection
        while True:
            message = self.socket.recv_json()
            self.socket.send_json({"response": "ok"})
            print(message)
            event_type = message.get("subscription", {}).get("type")
            event = message['event']
            if event_type == FOLLOW:
                new_follower = event['user_name']
                new_follow_msg = f"Thank you for following {new_follower}, welcome to the Bean Squad!"
                c.privmsg(self.channel, new_follow_msg)

            elif event_type == RAID:
                raider = event['from_broadcaster_user_name']
                if raider.lower() == self.channel.lower():
                    continue
                num_viewers = event['viewers']
                raided_msg = f"{raider} just raided the channel with {num_viewers} viewers! Welcome raiders the Bean Stream!"
                c.privmsg(self.channel, raided_msg)

            elif event_type == POINTS and self.sfx_mappings is not None:
                reward = event['reward']
                reward_name = reward['title']
                reward_sfx = self.sfx_mappings.get(reward_name)
                if reward_sfx:
                    sfx_path = os.path.join(self.sfx_directory, reward_sfx)
                    playsound(sfx_path)


