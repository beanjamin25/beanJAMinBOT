import hashlib
import hmac


import zmq

from flask import Flask, request, abort, redirect

from pprint import pprint

from twitch_rest_api import TwitchRestApi
from streamlabs_api import StreamlabsApi

twitch_api = TwitchRestApi(auth_filename="botjamin_auth.yaml")
streamlabs = StreamlabsApi(auth_filename="botjamin_auth.yaml")

context = zmq.Context()

app = Flask(__name__,
            static_url_path='/sfx',
            static_folder='data/sfx')

@app.route("/", methods=['GET', 'POST'])
def hello_world():
    if request.method == 'POST':

        request_data = request.get_json()
        pprint(request_data)
        print(request.headers)
        if "challenge" in request_data and verify_signature(request):
            print("responding to challenge", request_data['challenge'])
            return request_data["challenge"]
        if request.headers.get("Twitch-Eventsub-Message-Id") and verify_signature(request):
            print("got a notification")
            socket = context.socket(zmq.REQ)
            socket.connect("tcp://127.0.0.1:5555")
            socket.send_json(request_data)
            return "thank you"

    print(request.headers)
    if "code" in request.args:
        if twitch_api.get_oauth_token_from_code(request.args['code']):
            return "<p>Credentials Updated!</p>"
        abort(500, description="Failed to update oauth token")

    return "<p>Hello, Worlds!</p>"

@app.route("/get_token/<app_name>")
def get_token(app_name):
    if app_name == "twitch":
        return "<a href=" + twitch_api.oauth_request_url() + ">Get Twitch Token</a>"
    if app_name == "streamlabs":
        return "<a href=" + streamlabs.get_auth_url() + ">Get Streamlabs Token</>"

    return "We only provide login for twitch and streamlabs"

@app.route("/subscriptions")
def get_subscriptions():
    subscriptions = twitch_api.get_eventsub_subscriptions()
    if subscriptions is False:
        abort(500, description="Failed to get subscriptions")
    return subscriptions

@app.route("/oauth/<app_name>")
def oauth_callback(app_name):
    print("app name is: " + app_name)
    if "code" in request.args and app_name == "twitch":
        print("doing twitch")
        if twitch_api.get_oauth_token_from_code(request.args['code']):
            return "<p>Credentials Updated!</p>"
        abort(500, description="Failed to update oauth token")
    if "code" in request.args and app_name == "streamlabs":
        print("doing streamlabs")
        token = streamlabs.get_token(auth_resp=request.url)
        return "<p>Token is: " + token.get("access_token") + "</p>"

    return redirect("/")


def verify_signature(req):
    message_id = bytes(req.headers['Twitch-Eventsub-Message-Id'], 'utf-8')
    message_timestamp = bytes(req.headers['Twitch-Eventsub-Message-Timestamp'], 'utf-8')
    hmac_message = message_id + message_timestamp + req.data
    digester = hmac.new(bytes(twitch_api.eventsub_secret, 'utf-8'), hmac_message, hashlib.sha256)
    calculated_signature = digester.hexdigest()
    provided_signature = req.headers['Twitch-Eventsub-Message-Signature'].split("sha256=")[1]
    print(calculated_signature)
    print(provided_signature)
    return calculated_signature == provided_signature

