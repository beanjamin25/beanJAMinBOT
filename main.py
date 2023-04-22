import csv
import datetime
import logging
import os
import random
import time
from pprint import pprint

import simpleobsws
from dateutil.parser import isoparse
from threading import Thread

import irc.bot
import requests
import yaml

from clips import Clips
from obs_control import ObsControl
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

    clip_timeout = 30
    clip_last_called = 0

    custom_commands = dict()
    quotes = None

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

        self.clip_bot = Clips(channel=self.channel,
                              channel_name=self.channel_name,
                              twitch_api=self.twitch_api,
                              connection=self.connection)
        self.clip_bot.start()

        quotes_file = properties.get("quotes_file")
        if quotes_file is not None:
            self.quotes_path = os.path.join(data_directory, quotes_file)
            if os.path.exists(self.quotes_path):
                self.quotes = yaml.safe_load(open(self.quotes_path)) or list()

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

        self.obs_control = ObsControl(password='GlVRHdkopGW63tbZ', log_level=logging.DEBUG)
        self.obs_control.start()

        sfx_mappings = properties.get("sfx_mappings")
        if sfx_mappings is not None:
            sfx_mappings = yaml.safe_load(open(os.path.join(data_directory, sfx_mappings)))
            sfx_directory = os.path.join(data_directory, "sfx")
            self.twitch_eventsub = TwitchEvents(channel=self.channel,
                                                connection=self.connection,
                                                twitch_api=self.twitch_api,
                                                obs_control=self.obs_control,
                                                talk_config=tts_config,
                                                poke_game=self.poke_game,
                                                sfx_directory=sfx_directory,
                                                sfx_mappings=sfx_mappings)
            self.sfx_queue = self.twitch_eventsub.points_queue

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
            if d['key'] == "badges":
                if d['value'] is not None and "bits/" in d['value']:
                    return True
        return False

    @staticmethod
    def is_vip(event):
        for d in event.tags:
            if d['key'] == "badges":
                if d['value'] is not None and "vip/" in d['value']:
                    return True
        return False

    def check_if_live_target(self, interval=5):
        while True:
            stream_info = self.twitch_api.get_stream_info(self.channel_name)
            is_live = stream_info is not False
            if not self.watchtime.stream_flag and is_live:
                print(self.channel_name + " has gone LIVE!!! LETS GOOO!!!!!")
                self.clip_bot.init_clips_for_stream(started_at=stream_info.get("started_at"))
                self.watchtime.stream_flag = True
            elif self.watchtime.stream_flag and not is_live:
                print(self.channel_name + " has ended the stream!")
                self.clip_bot.reset_clips_for_stream()
                self.watchtime.stream_flag = False
            time.sleep(interval)

    def check_permissions(self, cmd, user, user_has_mod, is_vip):
        permissions = cmd['permission']
        if permissions == "broadcaster" and user == self.channel_name:
            return True
        elif permissions in ("moderator", "vip") and user_has_mod:
            return True
        elif permissions == "vip" and (user_has_mod or is_vip):
            return True
        return False

    def do_command(self, e, user, cmd, args):
        c = self.connection

        user_has_mod = self.is_mod(e) or user == self.channel_name
        print('received command: {cmd} with args: {args} from user: {user}({is_mod})'.format(
            cmd=cmd, args=args, user=user, is_mod=user_has_mod
        ))

        is_bits = self.is_bits(e)

        is_vip = self.is_vip(e)

        if cmd in self.custom_commands:
            count = self.custom_commands[cmd].get('count')
            if count is not None:
                self.custom_commands[cmd]['count'] = count + 1
                with open(self.custom_commands_path, 'w') as f:
                    yaml.dump(self.custom_commands, f)
            msg = self.custom_commands[cmd]['text'].format(*args, user=user, count=count)
            c.privmsg(self.channel, msg)

        elif cmd == "clip":
            if time.time() - self.clip_last_called < self.clip_timeout:
                return
            res = self.twitch_api.create_clip(self.channel_name)
            if res.status_code < 400:
                self.clip_last_called = time.time()
                clip_data = res.json().get("data")
                for clip in clip_data:
                    self.clip_bot.add_clip(clip['id'])
                    clip_url = clip['edit_url'].split("/edit")[0]
                    c.privmsg(self.channel, clip_url)
            else:
                print(res.content)

        elif cmd in ('commands', 'addcommand', 'updatecommand', 'removecommand') and (user_has_mod or is_vip):
            if cmd == "commands":
                if len(args) >= 1:
                    action = args[0]
                    args = args[1:]
                    if action == "add":
                        cmd = "addcommand"
                    elif action == "update":
                        cmd = "updatecommand"
                    elif action in ("delete", "remove"):
                        cmd = "removecommand"
                    else:
                        c.privmsg(self.channel, "The only valid actions on commands are ['add', 'update', 'remove'].")
                        return

            if cmd == "addcommand":
                if len(args) < 2:
                    c.privmsg(self.channel, "You need to have the new command do something, you silly goose!")
                    return
                new_cmd_arg = args[0].strip("!")
                if new_cmd_arg in self.custom_commands:
                    c.privmsg(self.channel, f"!{new_cmd_arg} is already a command! Use !updatecommand or !commands update to change it!")
                    return
                new_cmd_txt = " ".join(args[1:])
                permission = "moderator" if user_has_mod else "vip"
                new_cmd = {
                    "text": new_cmd_txt,
                    "permission": permission,
                    "user": user
                }
                if "{count}" in new_cmd_txt:
                    new_cmd['count'] = 0
                self.custom_commands[new_cmd_arg] = new_cmd
                with open(self.custom_commands_path, 'w') as f:
                    yaml.dump(self.custom_commands, f)
                c.privmsg(self.channel, f"Command '!{new_cmd_arg}' successfully added!")

            elif cmd == "updatecommand":
                if len(args) < 2:
                    c.privmsg(self.channel, "You need to have to give the command something to do, silly!")
                    return

                cmd_to_update = args[0].strip("!")
                if cmd_to_update not in self.custom_commands:
                    c.privmsg(self.channel, "You can't update a command that doesn't exist yet! Use !addcommand or !commands add to add the command first.")
                    return

                cmd_params = self.custom_commands[cmd_to_update]
                has_permission = self.check_permissions(cmd_params, user, user_has_mod, is_vip)
                if not has_permission:
                    c.privmsg(self.channel, "You dont have permission to do that!")
                    return
                cmd_params["text"] = " ".join(args[1:])
                self.custom_commands[cmd_to_update] = cmd_params
                with open(self.custom_commands_path, 'w') as f:
                    yaml.dump(self.custom_commands, f)
                c.privmsg(self.channel, f"Command '!{cmd_to_update}' successfully updated!")

            elif cmd == "removecommand":
                cmd_to_del = args[0].strip("!")
                if cmd_to_del not in self.custom_commands:
                    c.privmsg(self.channel, "You can't delete a command that doesn't exist!")
                    return
                cmd_params = self.custom_commands[cmd_to_del]
                has_permission = self.check_permissions(cmd_params, user, user_has_mod, is_vip)
                if has_permission:
                    self.custom_commands.pop(cmd_to_del)
                    with open(self.custom_commands_path, 'w') as f:
                        yaml.dump(self.custom_commands, f)
                    c.privmsg(self.channel, f"Command '!{cmd_to_del}' successfully removed.")
                else:
                    c.privmsg(self.channel, "You dont have permission to remove that command!")

        elif (cmd == "quote" or cmd == "quotes") and self.quotes is not None and len(self.quotes) > 0:
            if len(args) == 0:
                quote_id = random.randint(0, len(self.quotes)-1)
            else:
                try:
                    quote_id = int(args[0]) - 1
                except ValueError:
                    return
                if quote_id < 0 or quote_id > len(self.quotes) - 1:
                    return
            quote = self.quotes[quote_id]
            msg = f"{user}, Quote #{quote_id+1}: {quote}"
            c.privmsg(self.channel, msg)

        elif cmd == "addquote" and self.quotes is not None:
            if len(args) < 1:
                c.privmsg(self.channel, "You didn't give a quote, silly!")
                return
            quote = " ".join(args)
            channel_id = self.twitch_api.get_channel_id(self.channel_name)
            if not channel_id:
                return ""
            game = self.twitch_api.get_last_game_played(channel_id)
            now_str = datetime.datetime.now().strftime("[%m/%d/%Y %H:%M:%S]")
            final_quote = f"{quote} [{game}] {now_str}"
            self.quotes.append(final_quote)
            with open(self.quotes_path, 'w') as f:
                yaml.dump(self.quotes, f)
            quote_id = len(self.quotes)
            c.privmsg(self.channel, f"{user}, you have successfully added quote #{quote_id}.")

        elif (cmd == 'tts' or is_bits) and self.talk_bot is not None and len(args) > 0:
            msg = " ".join(args)
            payload = {
                "event": {
                    "reward": {
                        "title": "tts"
                    },
                    "user_input": msg
                }
            }
            self.sfx_queue.put(payload)

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

        elif cmd == 'followage':
            follow_age = self.twitch_api.get_followage(self.channel_name, user)
            if not follow_age:
                c.privmsg(self.channel, f"Silly {user}, you don't even follow {self.channel_name} yet! Go and give them a follow right now :-o")
                return
            msg = f"{user}, you have been following for "
            if follow_age.years:
                msg += f"{follow_age.years} year{'s' if follow_age.years != 1 else ''}, "
            if follow_age.months:
                msg += f"{follow_age.months} month{'s' if follow_age.months != 1 else ''}, "
            if follow_age.days or follow_age.months:
                msg += f"{follow_age.days} day{'s' if follow_age.days != 1 else ''}, "
            if follow_age.hours or follow_age.days:
                msg += f"{follow_age.hours} hour{'s' if follow_age.hours != 1 else ''}, "
            if follow_age.minutes or follow_age.hours:
                msg += f"{follow_age.minutes} minute{'s' if follow_age.minutes != 1 else ''}, "
            msg += f"{follow_age.seconds} second{'s' if follow_age.seconds != 1 else ''}"

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
            queue = "gachi"
            if len(args) > 0:
                queue = self.schedule.queue_mappings.get(args[0], "gachi")
            for q in ['gachi', 'league', 'regular']:
                if queue == "all" or q == queue:
                    c.privmsg(self.channel, self.schedule.get_maps(q))

        elif cmd in ['points', 'gamble', 'borrow', 'payback'] and self.gamble is not None:
            self.gamble.do_command(cmd, user, args)

        elif cmd in ['catch', 'pokedex', 'standings'] and self.poke_game is not None:
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
