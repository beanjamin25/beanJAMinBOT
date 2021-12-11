import time

import requests
import threading
import json

from collections import defaultdict



class Watchtime(threading.Thread):

    def __init__(self, channel, interval=5, db=None):
        threading.Thread.__init__(self)
        self.daemon = True
        self.channel = channel
        self.interval = interval
        self.viewers = defaultdict(float)
        self.current_viewers = list()
        self.this_stream = set()
        self.db = db
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
                r = requests.get("https://tmi.twitch.tv/group/user/" + self.channel + "/chatters").json()
                delta = time.time() - start
                start = time.time()
                chatters = r.get("chatters")
                self.current_viewers = list()
                for viewers in chatters.values():
                    for viewer in viewers:
                        self.viewers[viewer] += delta
                        self.current_viewers.append(viewer)
                        self.this_stream.add(viewer)
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
                print("current viewers", self.current_viewers)
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