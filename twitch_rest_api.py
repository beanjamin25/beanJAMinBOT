import secrets
from pprint import pprint

import requests
import yaml

TWTICH = "twitch"

CLIENT_ID = "client_id"
CLIENT_SECRET = "client_secret"
REDIRECT_URI = "oauth_redirect_uri"
CALLBACK_URI = "eventsub_callback_uri"
OAUTH_TOKEN = "oauth_token"
REFRESH_TOKEN = "refresh_token"
APP_TOKEN = "app_token"
SCOPES = "scopes"
EVENTSUB_SECRET = "eventsub_secret"

API_BASE = "https://api.twitch.tv/helix/"

AUTH_API_BASE = "https://id.twitch.tv/oauth2/"


class TwitchRestApi:

    def __init__(self, auth_filename=None):
        self.auth_filename = auth_filename
        self.auth_props = yaml.safe_load(open(self.auth_filename))
        self.props = self.auth_props[TWTICH]
        self.client_id = self.props[CLIENT_ID]
        self.client_secret = self.props[CLIENT_SECRET]
        self.redirect_uri = self.props[REDIRECT_URI]
        self.callback_uri = self.props[CALLBACK_URI]

        self.oauth_token = self.props.get(OAUTH_TOKEN, "")
        self.refresh_token = self.props.get(REFRESH_TOKEN, "")

        self.app_token = self.props.get(APP_TOKEN, "")

        self.scopes = self.props.get(SCOPES, [])

        self.eventsub_secret = self.props.get(EVENTSUB_SECRET, "")
        if not self.eventsub_secret:
            self.eventsub_secret = secrets.token_urlsafe()
            self.props[EVENTSUB_SECRET] = self.eventsub_secret
            self.auth_props[TWTICH] = self.props
            with open(self.auth_filename, 'w') as f:
                yaml.dump(self.auth_props, f)


    def oauth_request_url(self):
        url = AUTH_API_BASE + "authorize"

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes)
        }
        final_url = requests.Request('GET', url, params=params).prepare()
        return final_url.url

    def get_oauth_token_from_code(self, code):
        url = AUTH_API_BASE + "token"

        params = {
            CLIENT_ID: self.client_id,
            CLIENT_SECRET: self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri
        }

        r = requests.post(url, params=params)
        data = r.json()
        if r.status_code == 200:
            self.oauth_token = data.get("access_token")
            self.refresh_token = data.get(REFRESH_TOKEN)
            self.props[OAUTH_TOKEN] = self.oauth_token
            self.props[REFRESH_TOKEN] = self.refresh_token
            self.auth_props[TWTICH] = self.props
            with open(self.auth_filename, 'w') as f:
                yaml.dump(self.auth_props, f)
            return True
        return False

    def validate_oauth_token(self):
        url = AUTH_API_BASE + "validate"
        headers = {"Authorization": "Bearer " + self.oauth_token}
        response = requests.get(url, headers=headers)
        if response != 200:
            self.refresh_oauth_token()
            return False
        return True

    def validate_app_token(self):
        url = AUTH_API_BASE + "validate"
        headers = {"Authorization": "Bearer " + self.app_token}
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            return self.refresh_app_token()
        return True

    def refresh_oauth_token(self):
        url = AUTH_API_BASE + "token"
        params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            REFRESH_TOKEN: self.refresh_token
        }
        r = requests.post(url, params=params)
        data = r.json()
        if r.status_code == 200:
            self.refresh_token = data.get(REFRESH_TOKEN)
            self.oauth_token = data.get("access_token")
            self.props[REFRESH_TOKEN] = self.refresh_token
            self.props[OAUTH_TOKEN] = self.oauth_token
            self.auth_props[TWTICH] = self.props
            with open(self.auth_filename, 'w') as f:
                yaml.dump(self.auth_props, f)
            return True
        return False

    def refresh_app_token(self):
        url = AUTH_API_BASE + "token"
        params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
            "scope": " ".join(self.scopes)
        }
        r = requests.post(url, params=params)
        data = r.json()

        if r.status_code == 200:
            self.app_token = data.get("access_token")
            self.props[APP_TOKEN] = self.app_token
            self.auth_props[TWTICH] = self.props
            with open(self.auth_filename, 'w') as f:
                yaml.dump(self.auth_props, f)
            return True
        return False

    def get_channel_id(self, channel_name):
        self.validate_app_token()
        url = API_BASE + "users?login=" + channel_name
        headers = {
            "Authorization": "Bearer " + self.app_token,
            "Client-Id": self.client_id
        }
        r = requests.get(url, headers=headers).json()
        try:
            return r['data'][0]['id']
        except (KeyError, IndexError):
            return False

    def get_last_game_played(self, channel_id):
        self.validate_app_token()
        url = API_BASE + "channels"
        headers = {
            "Authorization": "Bearer " + self.app_token,
            "Client-Id": self.client_id
        }
        r = requests.get(url, headers=headers, params={"broadcaster_id": channel_id}).json()
        try:
            return r['data'][0]['game_name']
        except (KeyError, IndexError):
            return False

    def get_stream_info(self, channel_name):
        self.validate_app_token()
        url = API_BASE + "streams"
        headers = {
            "Authorization": "Bearer " + self.app_token,
            "Client-Id": self.client_id
        }
        r = requests.get(url, headers=headers, params={"user_login": channel_name})
        if r.status_code == 200:
            data = r.json().get('data')
            if len(data) == 1:
                return data[0]
        return False


    def get_eventsub_subscriptions(self):
        self.validate_app_token()
        headers = {
            "Authorization": "Bearer " + self.app_token,
            "Client-Id": self.client_id
        }
        url = API_BASE + "eventsub/subscriptions"
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            return r.json()
        return False

    def delete_all_eventsub_subscriptions(self):
        self.validate_app_token()
        del_url = API_BASE + "eventsub/subscriptions"
        headers = {
            "Authorization": "Bearer " + self.app_token,
            "Client-Id": self.client_id
        }

        subscriptions = self.get_eventsub_subscriptions()
        pprint(subscriptions)
        for sub in subscriptions.get('data', {}):
            sub_id = sub.get('id')
            if sub.get('status') != 'enabled':
                r = requests.delete(del_url, headers=headers, params={"id": sub_id})
                print(r.status_code, r.content)

    def eventsub_delete_subscription(self, channel_name, subscription_type):
        self.validate_app_token()
        url = API_BASE + "eventsub/subscriptions"
        headers = {
            "Authorization": "Bearer " + self.app_token,
            "Client-Id": self.client_id
        }

        subscriptions = self.get_eventsub_subscriptions()
        pprint(subscriptions)
        channel_id = self.get_channel_id(channel_name)
        sub_to_delete = None
        for sub in subscriptions.get('data', {}):
            if sub['type'] == subscription_type:
                condition = sub['condition']
                if condition['broadcaster_user_id'] == channel_id:
                    sub_to_delete = sub['id']
                elif condition['to_broadcaster_user_id'] == channel_id:
                    sub_to_delete = sub['id']
                elif condition['from_broadcaster_user_id'] == channel_id:
                    sub_to_delete = sub['id']
            if sub_to_delete is not None:
                r = requests.delete(url, headers=headers, params={'id': sub_to_delete})
                print(r.status_code, r.content)
                return

    def eventsub_add_subscription(self, channel_name, subscription_type):
        self.validate_app_token()
        url = API_BASE + "eventsub/subscriptions"
        headers = {
            "Authorization": "Bearer " + self.app_token,
            "Client-ID": self.client_id,
            "Content-Type": "application/json"
        }

        channel_id = self.get_channel_id(channel_name)

        payload = {
            "type": subscription_type,
            "version": "1",
            "condition": {
                "broadcaster_user_id": channel_id
            },
            "transport": {
                "method": "webhook",
                "callback": self.callback_uri,
                "secret": self.eventsub_secret
            }
        }
        r = requests.post(url, headers=headers, json=payload)
        print(r.status_code)
        pprint(r.json())


if __name__ == "__main__":
    twitch_api = TwitchRestApi(auth_filename="botjamin_auth.yaml")
    res = twitch_api.eventsub_add_subscription("beanjamin25", "channel.subscription.gift")
    print(res)
