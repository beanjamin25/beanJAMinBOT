import requests
from datetime import datetime


class Schedule:

    maps_url = "https://splatoon2.ink/data/schedules.json"
    salmon_url = "https://splatoon2.ink/data/coop-schedules.json"

    headers = {"User-Agent": "botJAMin2000 - twitch.tv/beanjamin25"}

    time_format = "%I:%M %p"

    queue_mappings = {
        "gachi": "gachi",
        "solo": "gachi",
        "soloq": "gachi",
        "ranked": "gachi",
        "league": "league",
        "turf": "regular",
        "regular": "regular"
    }

    def get_maps(self, queue="gachi"):
        queue = self.queue_mappings.get(queue, "gachi")
        schedule = requests.get(self.maps_url, headers=self.headers).json()
        now = datetime.now().timestamp()
        now_plus_two = now + 7200
        schedules = schedule.get(queue)
        for mode in schedules:
            if mode['start_time'] <= now < mode['end_time']:
                current_mode = mode
            if mode['start_time'] <= now_plus_two < mode['end_time']:
                next_mode = mode
        if queue == "gachi" or queue == "league":
            statement = self.ranked_map_statement(current_mode, queue=queue) + self.ranked_map_statement(next_mode, queue=queue, when="next")
        if queue == "regular":
            statement = self.turf_map_statement(current_mode) + self.turf_map_statement(next_mode, when="next")

        return statement

    def ranked_map_statement(self, mode, queue="gachi", when="current"):
        if queue == "gachi":
            queue = "ranked"
        mode_start = datetime.fromtimestamp(mode['start_time']).strftime(self.time_format)
        mode_end = datetime.fromtimestamp(mode['end_time']).strftime(self.time_format)
        statement = f"The {when} __{queue}__ rotation is **{mode['rule']['name']}**."
        statement += f" It starts at {mode_start} and ends at {mode_end}."
        statement += f" The maps are {mode['stage_a']['name']} and {mode['stage_b']['name']}. "

        return statement

    def turf_map_statement(self, mode, when="current"):
        mode_start = datetime.fromtimestamp(mode['start_time']).strftime(self.time_format)
        mode_end = datetime.fromtimestamp(mode['end_time']).strftime(self.time_format)
        statement = f"The {when} __turf__ roation starts at {mode_start} and ends at {mode_end}."
        statement += f" The maps are {mode['stage_a']['name']} and {mode['stage_b']['name']}. "

        return statement


if __name__ == "__main__":
    sched = Schedule()
    sched.get_maps("solo")
    print()
    sched.get_maps("league")
    print()
    sched.get_maps("turf")
