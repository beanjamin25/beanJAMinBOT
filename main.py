import csv
import datetime
import os
import time
from pprint import pprint

from dateutil.parser import isoparse
from threading import Thread

import irc.bot
import requests
import yaml

from twitch_rest_api import TwitchRestApi
from gamble import SimpleGamble
from watchtime import Watchtime
from tts import TalkBot
from pokemon import PokemonChatGame
from schedule import Schedule
from twitch_events import TwitchEvents


CHANNEL_NAME = "channel_name"
BOT_NAME = "bot_name"


class TwitchBot(irc.bot.SingleServerIRCBot):

    watchtime = None
    talk_bot = None
    gamble = None
    poke_game = None
    schedule = Schedule()
    map_timeout = 300
    map_last_called = 0

    custom_commands = dict()

    def __init__(self, properties):
        try:
            self.auth_filename = properties["token_file"]
            self.twitch_api = TwitchRestApi(self.auth_filename)
            self.channel_name = properties[CHANNEL_NAME]
            self.bot_name = properties[BOT_NAME]
            self.channel = '#' + self.channel_name
        except KeyError as e:
            print("Missing a property in the config file", e)
            exit(1)

        self.twitch_api.validate_oauth_token()
        server = "irc.chat.twitch.tv"
        port = 6667
        irc.bot.SingleServerIRCBot.__init__(self, [(server, port, "oauth:"+self.twitch_api.oauth_token)],
                                            self.channel_name, self.bot_name)

        current_dir = os.getcwd()
        data_directory = os.path.join(current_dir, properties.get('data_directory', 'data'))

        custom_commands_file = properties.get('custom_command_file', None)
        self.custom_commands_path = os.path.join(data_directory, custom_commands_file)
        if os.path.exists(self.custom_commands_path):
            self.custom_commands = yaml.safe_load(open(self.custom_commands_path))

        watchtime_config = properties.get('watchtime', dict())
        if watchtime_config.get("enabled", False):
            interval = watchtime_config.get('interval', 5)
            db = watchtime_config.get('db_file', None)
            if db is not None:
                db = os.path.join(data_directory, db)
            self.watchtime = Watchtime(channel=self.channel_name, interval=interval, db=db)
            self.watchtime.start()
            self.check_if_live_thread = Thread(target=self.check_if_live_target, args=(5,), daemon=True)
            self.check_if_live_thread.start()

        tts_config = properties.get('tts', dict())
        if tts_config.get("enabled", False):
            self.talk_bot = TalkBot(config=tts_config)

        gamble_config = properties.get('gamble', dict())
        if gamble_config.get("enabled", False):
            db = gamble_config.get('db_file', None)
            if db is not None:
                db = os.path.join(data_directory, db)
            self.gamble = SimpleGamble(self.channel, self.connection, db=db)

        pokegame_config = properties.get("pokegame", dict())
        if pokegame_config.get("enabled", False):
            pokeDB = pokegame_config.get("pokeDB", None)
            user_pokedex = pokegame_config.get("user_pokedex", None)
            alert_sound_url = pokegame_config.get("alert_sound_url", "")
            if pokeDB is not None and user_pokedex is not None:
                poke_dir = os.path.join(data_directory, "pokemon")
                pokeDB = os.path.join(poke_dir, pokeDB)
                user_pokedex = os.path.join(poke_dir, user_pokedex)
                self.poke_game = PokemonChatGame(self.channel,
                                                 self.connection,
                                                 pokeDB, user_pokedex,
                                                 alert_sound_url,
                                                 self.auth_filename,
                                                 streamlabs_alerts=pokegame_config.get('streamlabs_alerts', False))

        sfx_mappings = properties.get("sfx_mappings")
        if sfx_mappings is not None:
            sfx_mappings = yaml.safe_load(open(os.path.join(data_directory, sfx_mappings)))
            sfx_directory = os.path.join(data_directory, "sfx")
            self.twitch_eventsub = TwitchEvents(channel=self.channel,
                                                connection=self.connection,
                                                twitch_api=self.twitch_api,
                                                sfx_directory=sfx_directory,
                                                sfx_mappings=sfx_mappings)

    def on_welcome(self, c, e):
        print("Welcome!")
        print(e)
        print("Joining channel: " + self.channel + "...")
        c.cap('REQ', ':twitch.tv/membership')
        c.cap('REQ', ':twitch.tv/tags')
        c.cap('REQ', ':twitch.tv/commands')
        c.join(self.channel)

        r = requests.get("https://tmi.twitch.tv/group/user/" + self.channel_name + "/chatters").json()
        print(r)

    def on_pubmsg(self, c, e):
        print(e)
        user_msg = e.arguments[0]
        user = self.get_username(e)
        if not user_msg.startswith("!"):
            print(user, "said", '"' + user_msg + '"')
            return
        parsed_cmd = user_msg.split(" ")
        cmd = parsed_cmd[0].replace('!', '')
        cmd_args = parsed_cmd[1:]
        self.do_command(e, user, cmd, cmd_args)

    @staticmethod
    def get_username(msg):
        user = [d['value'] for d in msg.tags if d['key'] == 'display-name'][0]
        return user.lower()

    @staticmethod
    def is_mod(event):
        is_mod = [d['value'] for d in event.tags if d['key'] == 'mod'][0]
        return is_mod == '1'

    @staticmethod
    def is_bits(event):
        for d in event.tags:
            if d['key'] == "bits":
                return True
        return False

    @staticmethod
    def is_vip(event):
        for d in event.tags:
            if d['key'] == "badges":
                if "vip/" in d['value']:
                    return True
        return False

    def check_if_live_target(self, interval=5):
        while True:
            is_live = self.twitch_api.get_stream_info(self.channel_name) is not False
            if not self.watchtime.stream_flag and is_live:
                print(self.channel_name + " has gone LIVE!!! LETS GOOO!!!!!")
                self.watchtime.stream_flag = True
            elif self.watchtime.stream_flag and not is_live:
                print(self.channel_name + " has ended the stream!")
                self.watchtime.stream_flag = False
            time.sleep(interval)

    def do_command(self, e, user, cmd, args):
        c = self.connection

        user_has_mod = self.is_mod(e) or user == self.channel_name
        print('received command: {cmd} with args: {args} from user: {user}({is_mod})'.format(
            cmd=cmd, args=args, user=user, is_mod=user_has_mod
        ))

        is_bits = self.is_bits(e)

        is_vip = self.is_vip(e)

        if cmd in self.custom_commands:
            msg = self.custom_commands[cmd]['text']
            c.privmsg(self.channel, msg)

        elif cmd in ('addcommand', 'removecommand') and (user_has_mod or is_vip):
            if cmd == "addcommand":
                if len(args) < 2:
                    c.privmsg(self.channel, "You need to have the new command do something, you silly goose!")
                    return
                new_cmd_arg = args[0].strip("!")
                if new_cmd_arg in self.custom_commands:
                    c.privmsg(self.channel, f"!{new_cmd_arg} is already a command!")
                    return
                new_cmd_txt = " ".join(args[1:])
                permission = "moderator" if user_has_mod else "vip"
                new_cmd = {
                    "text": new_cmd_txt,
                    "permission": permission,
                    "user": user
                }
                self.custom_commands[new_cmd_arg] = new_cmd
                with open(self.custom_commands_path, 'w') as f:
                    yaml.dump(self.custom_commands, f)
                c.privmsg(self.channel, f"Command '!{new_cmd_arg}' successfully added!")

            elif cmd == "removecommand":
                cmd_to_del = args[0].strip("!")
                if cmd_to_del not in self.custom_commands:
                    c.privmsg(self.channel, "You can't delete a command that doesn't exist!")
                    return
                cmd_params = self.custom_commands[cmd_to_del]
                permissions = cmd_params['permission']
                has_permission = False
                if permissions == "broadcaster" and user == self.channel_name:
                    has_permission = True
                elif permissions in ("moderator", "vip") and user_has_mod:
                    has_permission = True
                elif permissions == "vip" and (user_has_mod or is_vip):
                    has_permission = True
                if has_permission:
                    self.custom_commands.pop(cmd_to_del)
                    with open(self.custom_commands_path, 'w') as f:
                        yaml.dump(self.custom_commands, f)
                    c.privmsg(self.channel, f"Command '!{cmd_to_del}' successfully removed.")
                else:
                    c.privmsg(self.channel, "You dont have permission to remove that command!")

        if (cmd == 'tts' or is_bits) and self.talk_bot is not None:
            msg = " ".join(args)
            self.talk_bot.add_msg_to_queue(msg)

        elif cmd == 'watchtime' and self.watchtime is not None:
            if len(args) == 0:
                watchtime = self.watchtime.get_user_watchtime(user)
            elif user_has_mod:
                watchtime = self.watchtime.get_user_watchtime(args[0])
            else:
                return
            hours = int(watchtime / 3600)
            minutes = int((watchtime - (hours * 3600)) / 60)
            seconds = int(watchtime - (hours * 3600) - (minutes * 60))
            msg = f"{user} has watched for {hours} hours, {minutes} minutes, and {seconds} seconds"
            c.privmsg(self.channel, msg)

        elif cmd == 'so' and user_has_mod:
            streamer = args[0].replace('@', '')
            shoutout_msg = self.shoutout(streamer)
            c.privmsg(self.channel, shoutout_msg)

        elif cmd == 'uptime':
            stream_info = self.twitch_api.get_stream_info(self.channel_name)
            if stream_info:
                start = isoparse(stream_info.get('started_at'))
                uptime = datetime.datetime.now().timestamp() - start.timestamp()
                hours = int(uptime / 3600)
                minutes = int((uptime - (hours * 3600)) / 60)
                seconds = int(uptime - (hours * 3600) - (minutes * 60))
                msg = f"The stream has been going for {hours} hours, {minutes} minutes, and {seconds} seconds"
                c.privmsg(self.channel, msg)

        elif cmd in ("map", "maps", "schedule"):
            if time.time() - self.map_last_called < self.map_timeout:
                return
            self.map_last_called = time.time()
            queue = None
            if len(args) > 0:
                queue = self.schedule.queue_mappings.get(args[0])
            for q in ['gachi', 'league', 'regular']:
                if queue is None or q == queue:
                    c.privmsg(self.channel, self.schedule.get_maps(q))

        elif cmd in ['points', 'gamble', 'borrow', 'payback'] and self.gamble is not None:
            self.gamble.do_command(cmd, user, args)

        elif cmd in ['catch', 'pokedex'] and self.poke_game is not None:
            self.poke_game.do_command(cmd, user)

    def shoutout(self, twitch_channel):
        shoutout_msg = "Go checkout {user} at twitch.tv/{user}! They were last playing {game}!"
        channel_id = self.twitch_api.get_channel_id(twitch_channel)
        if not channel_id:
            return ""
        last_game = self.twitch_api.get_last_game_played(channel_id)
        return shoutout_msg.format(user=twitch_channel, game=last_game)


if __name__ == '__main__':
    print("Starting Bot...")
    properties = yaml.safe_load(open("config/bot.conf"))
    print(properties)
    bot = TwitchBot(properties)

    try:
        bot.start()
    except KeyboardInterrupt:
        bot.twitch_eventsub.eventsub.stop()
        print("viewers this stream [%s]" % ", ".join(bot.watchtime.this_stream))
