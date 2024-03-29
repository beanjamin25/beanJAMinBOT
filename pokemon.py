import csv
import heapq
import pprint
import random
import time
from collections import defaultdict

from streamlabs_api import StreamlabsApi

import yaml

CAUGHT = "caught"
SHINY = "shiny"
NAME = "identifier"

COOLDOWN = 1


class NoMorePokeballsException(Exception):
    pass


class CooldownException(Exception):
    pass


class PokemonChatGame:

    def __init__(self, channel, connection, pokedb, pokedex, sfx_url_base, auth_filename, streamlabs_alerts=False):
        self.channel = channel
        self.connection = connection

        self.user_pokedex = Pokedex(pokedex)
        self.pokeDB = PokeDB(pokedb)

        self.pokeballs_by_user = dict()
        self.init_pokeballs = 5

        self.shiny_odds = 256

        self.streamlabs = None
        if streamlabs_alerts:
            self.streamlabs = StreamlabsApi(auth_filename, sfx_url_base)

        self.cooldown_dict = defaultdict(float)

    def do_command(self, cmd, user):
        c = self.connection

        if cmd == "catch":
            try:
                pokemon, first_caught, is_shiny, is_shiny_first = self.catch(user)
                p_name = pokemon.get(NAME).title()
                msg = f"{user}, you caught"
                if first_caught:
                    msg += f" a {p_name}!"
                else:
                    msg += f" another {p_name}!"

                if is_shiny:
                    msg += " and it was a shiny!"

                msg += " " + self.pokedex_statement(user)

                c.privmsg(self.channel, msg)
            except (CooldownException, NoMorePokeballsException) as e:
                c.privmsg(self.channel, str(e))

        elif cmd == "pokedex":
            c.privmsg(self.channel, self.pokedex_statement(user))

        elif cmd == "standings":
            c.privmsg(self.channel, self.pokedex_standings_statement())

    def catch(self, user):

        if time.time() - self.cooldown_dict[user] < COOLDOWN:
            raise CooldownException(f"{user}, you need to wait {COOLDOWN} seconds between throwing pokeballs!")

        self.cooldown_dict[user] = time.time()
        remaining_pokeballs = self.pokeballs_by_user.get(user, self.init_pokeballs)
        if remaining_pokeballs == 0:
            raise NoMorePokeballsException(f"{user}, you do not have any pokeballs left! BibleThump")

        self.pokeballs_by_user[user] = remaining_pokeballs - 1

        is_shiny = random.randint(1, self.shiny_odds) == 1
        pokemon = self.pokeDB.catch()
        first_caught, is_shiny_first = self.user_pokedex.add_pokemon_to_user(user, pokemon, is_shiny=is_shiny)

        if first_caught or is_shiny:
            alert_message = f"*{user}* caught *{pokemon.get(NAME).title()}*"
            if is_shiny:
                alert_message += " and it was a *shiny*"
            alert_message += "!"
            if self.streamlabs is not None:
                self.streamlabs.poke_alert(alert_message, poke_id=int(pokemon.get("id")))

        return pokemon, first_caught, is_shiny, is_shiny_first

    def add_pokeballs(self, user):
        if user not in self.pokeballs_by_user:
            self.pokeballs_by_user[user] = self.init_pokeballs

        self.pokeballs_by_user[user] += self.init_pokeballs
        self.connection.privmsg(self.channel, f"{user}, you now have {self.pokeballs_by_user[user]} pokeballs!")


    def pokedex_statement(self, user):
        pokedex = self.user_pokedex.get_user_pokedex(user)
        num_caught = len(pokedex.get(CAUGHT))
        num_shiny = len(pokedex.get(SHINY))

        completion = 100 * (num_caught / len(self.pokeDB.pokedex))

        remaining_pokeballs = self.pokeballs_by_user.get(user, self.init_pokeballs)

        msg = f"{user}, your Pokedex is {completion:.3f}% complete"
        if num_shiny > 0:
            msg += f" and you have caught {num_shiny} shinies!"
        msg += f" and you have {remaining_pokeballs} pokeballs left!"
        return msg

    def pokedex_standings_statement(self, num=5):
        num_most_pokemon = self.user_pokedex.pokedex_standings(num)

        statement = f"Current standings: "
        rank = 0
        for info in num_most_pokemon:
            rank += 1
            statement += f"{rank}: {info[2]} with {info[0]} pokemon"
            if info[1] > 0:
                statement += f" and {info[1]} shinies!"
            statement += "\t"

        return statement

class Pokedex:

    def __init__(self, pokedex_filename):
        self.pokedex_filename = pokedex_filename
        with open(self.pokedex_filename) as f:
            self.pokedex_by_user = yaml.load(f, Loader=yaml.FullLoader)

        if self.pokedex_by_user is None:
            self.pokedex_by_user = dict()

    def add_pokemon_to_user(self, user, pokemon, is_shiny=False):
        if user not in self.pokedex_by_user:
            self.pokedex_by_user[user] = {
                CAUGHT: set(),
                SHINY: set()
            }
        pokemon_name = pokemon.get(NAME)
        first_caught = pokemon_name not in self.pokedex_by_user[user][CAUGHT]
        self.pokedex_by_user[user][CAUGHT].add(pokemon_name)

        is_shiny_first = False
        if is_shiny:
            is_shiny_first = pokemon_name not in self.pokedex_by_user[user][SHINY]
            self.pokedex_by_user[user][SHINY].add(pokemon_name)

        with open(self.pokedex_filename, 'w') as f:
            yaml.dump(self.pokedex_by_user, f)

        return first_caught, is_shiny_first

    def get_user_pokedex(self, user):
        return self.pokedex_by_user.get(user, {CAUGHT: set(), SHINY: set()})

    def pokedex_standings(self, num=None):
        pokedex_heap = list()
        for user, pokemon in self.pokedex_by_user.items():
            pokedex_heap.append((len(pokemon.get(CAUGHT)), len(pokemon.get(SHINY)), user))
        if num:
            return heapq.nlargest(num, pokedex_heap)
        return heapq.nlargest(len(pokedex_heap), pokedex_heap)


class PokeDB:

    def __init__(self, pokedb_filename):
        self.pokedex = dict()
        self.gen_index = defaultdict(list)
        self.name_index = dict()
        with open(pokedb_filename) as f:
            for pokemon in csv.DictReader(f):
                self.pokedex[int(pokemon.get('id'))] = pokemon
                self.name_index[pokemon.get('name')] = int(pokemon.get('id'))
                self.gen_index[int(pokemon.get('generation_id'))].append(int(pokemon.get('id')))

    def get_pokemon(self, poke_id):
        return self.pokedex[poke_id]

    def catch(self, gen_id=None):
        catchable = list(self.pokedex.keys())
        if gen_id is not None:
            catchable = self.gen_index.get(gen_id)

        return self.pokedex.get(random.choice(catchable))


if __name__ == "__main__":
    poke_game = PokemonChatGame(pokedb="data/pokemon/pokeDB.csv", pokedex="data/pokemon/pokedex.yaml",auth_filename="botjamin_auth.yaml",sfx_url_base="",channel="",connection="")
    pokedex_standings = poke_game.pokedex_standings_statement()
    print(pokedex_standings)