import time

import pyttsx3
import queue
from threading import Thread

# using pyttsx3 for voices
# more info at: https://github.com/nateshmbhat/pyttsx3


class TalkBot:

    def __init__(self, config=None):
        if config is None:
            config = {}

        self.engine = pyttsx3.init()
        self.engine.setProperty('voice', config.get('voice', 'english_rp+f3'))
        self.engine.setProperty('rate', config.get('rate', 150))
        self.kill_flag = False
        self.queue = queue.Queue()
        self.speaking_thread = Thread(target=self.read_msg_thread, daemon=True)
        self.speaking_thread.start()

    def stop(self):
        self.kill_flag = True

    def add_msg_to_queue(self, msg):
        self.queue.put(msg)

    def read_msg_thread(self):
        while not self.kill_flag:
            msg_to_speak = self.queue.get()
            time.sleep(0.5)
            self.engine.say(msg_to_speak)
            self.engine.runAndWait()
            self.queue.task_done()

    def read_msg(self, msg):
        time.sleep(0.5)
        self.engine.say(msg)
        self.engine.runAndWait()