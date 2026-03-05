from bottle import Bottle, run

app = Bottle()


@app.route("/")
def index():
    return "<h1>Hello from Bottle behind Nginx!</h1>"


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    run(app, host="0.0.0.0", port=8080)
