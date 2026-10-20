"""
Jarvis launcher — thin wrapper around the FastAPI app in jarvis.web.server.

Run with:  python launch_app.py   (or ./start.sh)
"""

from jarvis.web.server import run

if __name__ == "__main__":
    run()
