from pprint import pprint
from datetime import datetime
from dateutil.relativedelta import relativedelta

import requests
import yaml

from exceptions import (
    TwitchAPIRequestError,
    TwitchResourceNotFoundError,
    TokenValidationError,
    TokenRefreshError,
    TokenExchangeError,
)
from logging_config import get_logger

logger = get_logger('twitch_rest_api')

TWTICH = "twitch"

CLIENT_ID = "client_id"
CLIENT_SECRET = "client_secret"
REDIRECT_URI = "oauth_redirect_uri"
OAUTH_TOKEN = "oauth_token"
REFRESH_TOKEN = "refresh_token"
USER_OAUTH = "user_oauth"
USER_REFRESH = "user_refresh"
APP_TOKEN = "app_token"
SCOPES = "scopes"

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

        self.oauth_token = self.props.get(OAUTH_TOKEN, "")
        self.refresh_token = self.props.get(REFRESH_TOKEN, "")

        self.user_oauth = self.props.get(USER_OAUTH, "")
        self.user_refresh = self.props.get(USER_REFRESH, "")

        self.app_token = self.props.get(APP_TOKEN, "")

        self.scopes = self.props.get(SCOPES, [])

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
        if r.status_code != 200:
            logger.error(f"Failed to exchange code for token: {data}")
            raise TokenExchangeError(f"Failed to exchange auth code: {data.get('message', 'Unknown error')}")

        self.oauth_token = data.get("access_token")
        self.refresh_token = data.get(REFRESH_TOKEN)
        self.props[OAUTH_TOKEN] = self.oauth_token
        self.props[REFRESH_TOKEN] = self.refresh_token
        self.auth_props[TWTICH] = self.props
        with open(self.auth_filename, 'w') as f:
            yaml.dump(self.auth_props, f)

    def validate_oauth_token(self, user=False):
        """Validate OAuth token, refreshing if needed. Raises TokenRefreshError if refresh fails."""
        token = self.user_oauth if user else self.oauth_token
        url = AUTH_API_BASE + "validate"
        headers = {"Authorization": "Bearer " + token}
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            logger.info("OAuth token invalid, attempting refresh")
            self.refresh_oauth_token(user=user)

    def validate_app_token(self):
        """Validate app token, refreshing if needed. Raises TokenRefreshError if refresh fails."""
        url = AUTH_API_BASE + "validate"
        headers = {"Authorization": "Bearer " + self.app_token}
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            logger.info("App token invalid, attempting refresh")
            self.refresh_app_token()

    def refresh_oauth_token(self, user=False):
        """Refresh OAuth token. Raises TokenRefreshError on failure."""
        refresh = self.user_refresh if user else self.refresh_token
        url = AUTH_API_BASE + "token"
        params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            REFRESH_TOKEN: refresh
        }
        r = requests.post(url, params=params)
        data = r.json()
        if r.status_code != 200:
            token_type = "user" if user else "bot"
            logger.error(f"Failed to refresh {token_type} OAuth token: {data}")
            raise TokenRefreshError(f"Failed to refresh {token_type} OAuth token: {data.get('message', 'Unknown error')}")

        refresh = data.get(REFRESH_TOKEN)
        token = data.get("access_token")
        if user:
            self.props[USER_REFRESH] = refresh
            self.props[USER_OAUTH] = token
            self.user_refresh = refresh
            self.user_oauth = token
        else:
            self.props[REFRESH_TOKEN] = refresh
            self.props[OAUTH_TOKEN] = token
            self.refresh_token = refresh
            self.oauth_token = token
        self.auth_props[TWTICH] = self.props
        with open(self.auth_filename, 'w') as f:
            yaml.dump(self.auth_props, f)
        logger.info(f"Successfully refreshed {'user' if user else 'bot'} OAuth token")

    def refresh_app_token(self):
        """Refresh app token. Raises TokenRefreshError on failure."""
        url = AUTH_API_BASE + "token"
        params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
            "scope": " ".join(self.scopes)
        }
        r = requests.post(url, params=params)
        data = r.json()

        if r.status_code != 200:
            logger.error(f"Failed to refresh app token: {data}")
            raise TokenRefreshError(f"Failed to refresh app token: {data.get('message', 'Unknown error')}")

        self.app_token = data.get("access_token")
        self.props[APP_TOKEN] = self.app_token
        self.auth_props[TWTICH] = self.props
        with open(self.auth_filename, 'w') as f:
            yaml.dump(self.auth_props, f)
        logger.info("Successfully refreshed app token")

    def get_app_token(self):
        self.validate_app_token()
        return self.app_token

    def get_oauth_token(self):
        self.validate_oauth_token()
        return self.oauth_token

    def get_user_oauth(self):
        self.validate_oauth_token(user=True)
        return self.user_oauth

    def get_channel_id(self, channel_name):
        """Get channel ID for a username. Raises TwitchResourceNotFoundError if not found."""
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
            logger.warning(f"Channel not found: {channel_name}")
            raise TwitchResourceNotFoundError(f"Channel '{channel_name}' not found")

    def get_last_game_played(self, channel_id):
        """Get last game played by channel. Raises TwitchResourceNotFoundError if not found."""
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
            logger.warning(f"Channel info not found for ID: {channel_id}")
            raise TwitchResourceNotFoundError(f"Channel info not found for ID: {channel_id}")

    def get_stream_info(self, channel_name):
        """Get stream info. Returns None if stream is offline, raises on API error."""
        self.validate_app_token()
        url = API_BASE + "streams"
        headers = {
            "Authorization": "Bearer " + self.app_token,
            "Client-Id": self.client_id
        }
        r = requests.get(url, headers=headers, params={"user_login": channel_name})
        if r.status_code != 200:
            logger.error(f"Failed to get stream info: {r.status_code}")
            raise TwitchAPIRequestError(f"Failed to get stream info", status_code=r.status_code)
        data = r.json().get('data')
        if len(data) == 1:
            return data[0]
        return None  # Stream is offline

    def get_clips(self, channel_name, started_at: str=None) -> list:
        self.validate_app_token()
        url = API_BASE + "clips"
        headers = {
            "Authorization": "Bearer " + self.app_token,
            "Client-Id": self.client_id
        }
        channel_id = self.get_channel_id(channel_name)
        params = {
            "broadcaster_id": channel_id,
            "started_at": started_at
        }
        r = requests.get(url, headers=headers, params=params)
        if r.status_code == 200:
            return r.json()['data']

    def create_clip(self, channel_name):
        self.validate_oauth_token()
        url = API_BASE + "clips"
        headers = {
            "Authorization": "Bearer " + self.oauth_token,
            "Client-Id": self.client_id
        }
        channel_id = self.get_channel_id(channel_name)
        params = {
            "broadcaster_id": channel_id,
        }
        r = requests.post(url, headers=headers, params=params)
        return r

    def get_eventsub_subscriptions(self):
        """Get EventSub subscriptions. Raises TwitchAPIRequestError on failure."""
        self.validate_oauth_token(user=True)
        headers = {
            "Authorization": "Bearer " + self.user_oauth,
            "Client-Id": self.client_id
        }
        url = API_BASE + "eventsub/subscriptions"
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            logger.error(f"Failed to get EventSub subscriptions: {r.status_code}")
            raise TwitchAPIRequestError("Failed to get EventSub subscriptions", status_code=r.status_code)
        return r.json()

    def delete_all_eventsub_subscriptions(self):
        self.validate_oauth_token(user=True)
        del_url = API_BASE + "eventsub/subscriptions"
        headers = {
            "Authorization": "Bearer " + self.user_oauth,
            "Client-Id": self.client_id
        }

        subscriptions = self.get_eventsub_subscriptions()
        print(subscriptions)
        for sub in subscriptions.get('data', {}):
            sub_id = sub.get('id')
            requests.delete(del_url, headers=headers, params={"id": sub_id})

    def eventsub_delete_subscription(self, subscription_id):
        self.validate_oauth_token(user=True)
        url = API_BASE + "eventsub/subscriptions"
        headers = {
            "Authorization": "Bearer " + self.user_oauth,
            "Client-Id": self.client_id
        }

        r = requests.delete(url, headers=headers, params={'id': subscription_id})
        return r

    def eventsub_add_subscription(self, condition, subscription_type, session_id, version='1'):
        self.validate_oauth_token(user=True)
        url = API_BASE + "eventsub/subscriptions"
        headers = {
            "Authorization": "Bearer " + self.user_oauth,
            "Client-ID": self.client_id,
            "Content-Type": "application/json"
        }

        payload = {
            "type": subscription_type,
            "version": version,
            "condition": condition,
            "transport": {
                "method": "websocket",
                "session_id": session_id
            }
        }
        r = requests.post(url, headers=headers, json=payload)
        return r

    def get_subscribers(self, channel_name):
        self.validate_oauth_token(user=True)
        url = API_BASE + "subscriptions"
        headers = {
            "Authorization": "Bearer " + self.user_oauth,
            "Client-ID": self.client_id,
            "Content-Type": "application/json"
        }
        channel_id = self.get_channel_id(channel_name)

        r = requests.get(url, headers=headers, params={"broadcaster_id": channel_id})
        return r.json()

    def get_followage(self, channel_name, follower_name) -> relativedelta:
        """
        Get follow age for a user.
        Raises TwitchResourceNotFoundError if user doesn't follow the channel.
        """
        self.validate_oauth_token()
        url = API_BASE + "channels/followers"
        headers = {
            "Authorization": "Bearer " + self.oauth_token,
            "Client-ID": self.client_id,
            "Content-Type": "application/json"
        }
        channel_id = self.get_channel_id(channel_name)
        follower_id = self.get_channel_id(follower_name)

        parameters = {
            "broadcaster_id": channel_id,
            "user_id": follower_id
        }
        r = requests.get(url, headers=headers, params=parameters).json()
        if len(r['data']) == 0:
            raise TwitchResourceNotFoundError(f"User '{follower_name}' does not follow '{channel_name}'")
        followed_at = r['data'][0]['followed_at']

        datetime_format = "%Y-%m-%dT%H:%M:%SZ"
        followed_datetime = datetime.strptime(followed_at, datetime_format)
        follow_age = relativedelta(datetime.now(), followed_datetime)
        return follow_age

    def get_chatters(self, channel_name):
        self.validate_oauth_token(user=True) # use broadcaster id
        url = API_BASE + "chat/chatters"

        headers = {
            "Authorization": "Bearer " + self.user_oauth,
            "Client-ID": self.client_id
        }
        channel_id = self.get_channel_id(channel_name)
        parameters = {
            "broadcaster_id": channel_id,
            "moderator_id": channel_id
        }
        r = requests.get(url, headers=headers, params=parameters).json()
        return r

if __name__ == "__main__":
    twitch_api = TwitchRestApi(auth_filename="config/botjamin_auth.yaml")
    res = twitch_api.get_chatters("beanjamin25")
    pprint(res)
