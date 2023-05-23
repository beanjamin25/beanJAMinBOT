import time

import requests
import threading
import json

from collections import defaultdict

from twitch_rest_api import TwitchRestApi


class Watchtime(threading.Thread):

    def __init__(self, channel, interval=5, db=None, twitch: TwitchRestApi=None):
        threading.Thread.__init__(self)
        self.daemon = True
        self.channel = channel
        self.interval = interval
        self.viewers = defaultdict(float)
        self.current_viewers = list()
        self.this_stream = set()
        self.db = db
        self.twich = twitch
        self.stream_flag = False

        if self.db is not None:
            with open(db, 'r') as f:
                for viewer, watchtime in json.load(f).items():
                    self.viewers[viewer] = watchtime

    def get_user_watchtime(self, user):
        if user not in self.viewers:
            return 0
        return self.viewers.get(user)

    def run(self) -> None:
        start = time.time()
        while True:
            try:
                r = self.twich.get_chatters(self.channel)
                delta = time.time() - start
                start = time.time()
                chatters = r.get("data", {})
                self.current_viewers = list()
                for viewer in chatters:
                    viewer_name = viewer.get("user_login")
                    self.viewers[viewer_name] += delta
                    self.current_viewers.append(viewer_name)
                    self.this_stream.add(viewer_name)
                if self.db is not None and self.stream_flag:
                    with open(self.db, 'w') as f:
                        json.dump(
                            {k: v for k, v in reversed(sorted(self.viewers.items(), key=lambda item: item[1]))},
                            f,
                            indent=4
                        )
            except Exception as e:
                print(e)
            finally:
                print("current viewers", sorted(self.current_viewers))
                time.sleep(self.interval)



if __name__ == "__main__":
    try:
        watchtimes = Watchtime("beanjamin25", db="watchtime.db")
        watchtimes.start()
        start = time.time()
        while time.time() - start < 30000:
            print(watchtimes.current_viewers)
            time.sleep(5)
    except KeyboardInterrupt:
        print(watchtimes.this_stream)
    print(watchtimes.this_stream)
    print("done!")