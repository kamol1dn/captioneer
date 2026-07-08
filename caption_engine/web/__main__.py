"""Launch the caption engine's local web UI: ``python -m caption_engine.web``.

Starts Flask (threaded, so long transcribe/render jobs don't block the UI) and
opens the default browser at the app. This is what ``run.bat`` calls.
"""
import os
import threading
import webbrowser

from .server import app

HOST = "127.0.0.1"
PORT = int(os.environ.get("CAPTIONEER_PORT", "8765"))


def main():
    url = f"http://{HOST}:{PORT}/"
    # Open the browser shortly after the server starts accepting connections.
    # Guard against the Werkzeug reloader double-run (not used here, but cheap).
    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"\n  Caption Engine — open {url} in your browser\n")
    # threaded=True: one thread per request so SSE streams and background jobs
    # run concurrently with new requests. use_reloader=False so the browser only
    # opens once and background jobs aren't killed on file changes.
    app.run(host=HOST, port=PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
