import datetime
import threading
import time

from twitch_rest_api import TwitchRestApi


class Clips(threading.Thread):

    def __init__(self, channel=None, channel_name=None, connection=None, bot_name=None, twitch_api: TwitchRestApi=None):
        threading.Thread.__init__(self)
        self.daemon = True

        self.channel = channel
        self.channel_name = channel_name
        self.connection = connection
        self.bot_name = bot_name
        self.twitch = twitch_api

        self.clips_this_stream: set = None
        self.stream_started_at: str = None

    def init_clips_for_stream(self, started_at):
        self.stream_started_at = started_at
        self.clips_this_stream = set(clip['id'] for clip in self.twitch.get_clips(self.channel_name, started_at=started_at))
        print(self.clips_this_stream)

    def reset_clips_for_stream(self):
        self.clips_this_stream = None

    def add_clip(self, clip_id):
        self.clips_this_stream.add(clip_id)

    def run(self) -> None:
        while True:
            try:
                if self.clips_this_stream is None:
                    continue

                clips = self.twitch.get_clips(self.channel_name, started_at=self.stream_started_at)
                for clip in clips:
                    if clip['id'] not in self.clips_this_stream and clip['creator_name'].lower() != self.bot_name:
                        clip_url = clip.get("url")
                        self.connection.privmsg(self.channel, clip_url)
                        self.clips_this_stream.add(clip['id'])

            except Exception as e:
                print("error:", e)
            finally:
                time.sleep(1)


if __name__ == "__main__":
    twitch_rest_api = TwitchRestApi(auth_filename="config/botjamin_auth.yaml")
    clip_bot = Clips(channel="#beanjamin25", channel_name="beanjamin25", twitch_api=twitch_rest_api, connection=None)

    start = time.time()
    clip_bot.start()
    while time.time() - start < 25:
        if 20 > time.time() - start > 5 and clip_bot.clips_this_stream is None:
            print("yo")
            a_week_ago = datetime.datetime.utcnow() - datetime.timedelta(days=7)
            a_week_ago_str = a_week_ago.strftime("%Y-%m-%dT00:00:00Z")
            clip_bot.init_clips_for_stream(started_at=a_week_ago_str)
        elif time.time() - start > 20:
            clip_bot.reset_clips_for_stream()
        print(time.time())
        time.sleep(1)