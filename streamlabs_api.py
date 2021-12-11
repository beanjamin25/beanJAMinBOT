import yaml
from authlib.integrations.requests_client import OAuth2Session


STREAMLABS = "streamlabs"

AUTH_URL = "https://streamlabs.com/api/v1.0/authorize"
TOKEN_URL = "https://streamlabs.com/api/v1.0/token"

API_URL = "https://streamlabs.com/api/v1.0/"
TOKEN_URL = API_URL + "token"
AUTH_URL = API_URL + "authorize"

CLIENT_ID = "client_id"
CLIENT_SECRET = "client_secret"
REDIRECT_URI = "redirect_uri"
ACCESS_TOKEN = "access_token"

SCOPES = "scopes"

class StreamlabsApi:

    def __init__(self, auth_filename=None, sfx_url_base=None):
        self.auth_filename = auth_filename
        self.props = yaml.safe_load(open(self.auth_filename)).get(STREAMLABS)
        self.client_id = self.props[CLIENT_ID]
        self.client_secret = self.props[CLIENT_SECRET]
        self.redirect_uri = self.props[REDIRECT_URI]
        self.scopes = self.props[SCOPES]
        self.client = OAuth2Session(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            scope=self.scopes
        )
        self.access_token = self.props[ACCESS_TOKEN]
        self.client.token = {
            "access_token": self.access_token,
            "token_type": "bearer",
            "scope": self.scopes
        }

        self.sfx_url_base = sfx_url_base

    def get_auth_url(self):
        uri, state = self.client.create_authorization_url(AUTH_URL)

        self.state = state

        return uri

    def get_token(self, auth_resp):
        print("getting token from: " + auth_resp)
        token = self.client.fetch_token(TOKEN_URL, authorization_response=auth_resp)
        self.token = token
        self.access_token = self.token.get("access_token")
        return token

    def poke_alert(self, message, poke_id):
        url = API_URL + "alerts"
        params = {
            "type": "merch",
            "message": message,
            "special_text_color": "orange",
            "duration": 5000,
            "user_message": " ",
            "sound_href": self.sfx_url_base + "pokesound.ogg",
            "image_href": f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{poke_id}.png"
        }
        resp = self.client.post(url, params=params)
