Build Your Own AI Co-Founder — A 3-Day
Guide
Python · VSCode · Ubuntu · 100% Free (Ollama, no API key)
This guide takes you from an empty folder to a working, always-on AI agent that
can talk, remember, use tools, run in the background, and (optionally) listen and
speak. Every file has an exact save location, exact copy-paste steps, and every
link you need.
Editor: VSCode. Model & cost: Ollama, running a model locally on your machine

— no API key, no account, no bill, no rate limit.

How to Use This Guide
Every code block below is preceded by a line like:

📁

Save as: ~/projects/cofounder-agent/config.py — create new file

or, when you're editing something you already made:

📁

Edit: ~/projects/cofounder-agent/agent.py — replace entire contents

To create a new file in VSCode:

1. Look at the left sidebar (the Explorer). You should see your cofounderagent folder listed.

2. Hover your mouse over the folder name — a row of small icons appears on
the right of it. Click the New File icon (looks like a page with a + ).
3. Type the exact filename shown in the "Save as" line (e.g. config.py ) and
press Enter. A new empty tab opens.
4. Go to the code block in this guide, click anywhere inside it, then hover over its
top-right corner — a small clipboard/copy icon appears. Click it to copy the

whole block. (If no icon appears, click inside the block and press Ctrl+A
then Ctrl+C .)
5. Click back inside the empty file tab in VSCode and press Ctrl+V to paste.
6. Press Ctrl+S to save.

To edit a file you already created: click its name in the Explorer sidebar to open it,

press Ctrl+A to select everything currently in it, press Delete , then paste the
new version the same way and save.
To run any command shown in a gray "bash" box: open VSCode's built-in terminal

with Ctrl+` (backtick) or via the top menu Terminal → New Terminal, then type
or paste the command there and press Enter.

File Map — where everything lives
All project files live in one folder: ~/projects/cofounder-agent/ . The only
exception is the systemd service file on Day 3, which has its own required
location.

File

config.py

memory.py

agent.py

main.py

tools.py

watcher.py

specialists.py

voice.py

Full path

~/projects/cofounderagent/config.py
~/projects/cofounderagent/memory.py
~/projects/cofounderagent/agent.py
~/projects/cofounderagent/main.py
~/projects/cofounderagent/tools.py
~/projects/cofounderagent/watcher.py
~/projects/cofounderagent/specialists.py

Created

—

Day 1

Day 2

Day 1

Day 2

Day 1

—

Day 2

—

Day 2

—

Day 3

—

~/projects/cofounder-

Day 3
(optional)

cofounder-

~/.config/systemd/user/cofounderagent.service

again

Day 1

agent/voice.py

agent.service

Edited

Day 3

—

—

Day 0 — Environment Setup (30 minutes)
Step 1 — Open a terminal. Press Ctrl+Alt+T on Ubuntu, or search "Terminal" in

your app menu.
Step 2 — Install system packages. Paste this whole block into the terminal and

press Enter:
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git curl

Step 3 — Install VSCode.
sudo snap install --classic code

If that doesn't work on your system, download the .deb installer directly from
https://code.visualstudio.com/download and double-click it to install.
Step 4 — Install Ollama (this is what makes it free).
curl -fsSL https://ollama.com/install.sh | sh

This installer is from https://ollama.com/download — that page also has manual
download options if the script doesn't work for you.
Step 5 — Download a model. This pulls the actual AI model weights onto your

disk (a few GB) so it can run offline forever after this.
ollama pull qwen2.5:1.5b

Browse other free models at https://ollama.com/library — qwen2.5:1.5b is a good
faster/smaller option if your machine is modest.
Step 6 — Create the project folder and Python environment.
mkdir -p ~/projects/cofounder-agent && cd ~/projects/cofounderagent
python3 -m venv venv
source venv/bin/activate

Note: every time you open a new terminal to work on this project, you must run
cd ~/projects/cofounder-agent && source venv/bin/activate again first —

this activates the isolated Python environment. You'll know it worked because
your terminal prompt will start with (venv) .
Step 7 — Install Python libraries into that environment.
pip install ollama rich requests schedule

Recommended: put those packages in a requirements.txt file so the setup is
repeatable on a fresh machine, then install with:
pip install -r requirements.txt

Step 8 — Open the folder in VSCode.
code .

This opens VSCode with ~/projects/cofounder-agent loaded as your
workspace — you should see it in the left sidebar. Keep this VSCode window
open for the rest of the guide.
Step 9 — Install the Python extension in VSCode. Click the square icon on the

far-left activity bar (Extensions), search "Python", click the one published by
Microsoft, click Install.
Step 10 — Create .gitignore . Back in the terminal (make sure you're still in
~/projects/cofounder-agent ):
echo "venv/" > .gitignore
echo "data/" >> .gitignore
echo "logs/" >> .gitignore

Optional but recommended before your first run: add a quick preflight check so
the agent fails fast if the environment is missing something.

Run these checks before python main.py:
python3 - <<'PY'
from pathlib import Path
import shutil
import subprocess
import sys

model_name = "qwen2.5:1.5b"  # change this if you choose a different model

if not Path("venv").exists():
	sys.exit("Missing venv directory")
if not shutil.which("ollama"):
	sys.exit("Ollama is not installed or not on PATH")

models = subprocess.check_output(["ollama", "list"], text=True)
if model_name not in models:
	sys.exit(f"Model '{model_name}' is not installed yet")

print("Preflight OK")
PY

You're set up. Everything from here happens inside this one VSCode window.

Day 1 — The Brain: A Real Conversation Loop
Goal: an agent with a personality and persistent memory across sessions.

File 1 of 4

📁

Save as: ~/projects/cofounder-agent/config.py — create new file

(follow the steps in "How to Use This Guide" above)
MODEL = "qwen2.5:1.5b"

# swap for qwen2.5:1.5b if this feels slow on

your machine
AGENT_NAME = "Nova"

# name your agent

SYSTEM_PROMPT = f"""You are {AGENT_NAME}, a personal AI co-founder
for the user.

You are brief, direct, and useful — you don't pad answers with
filler.
You have opinions and you share them. You proactively flag risks
and
blind spots instead of just agreeing. When you don't know
something,
say so plainly."""

File 2 of 4

📁

Save as: ~/projects/cofounder-agent/memory.py — create new file

import json
from pathlib import Path
from config import SYSTEM_PROMPT
HISTORY_FILE = Path("data/conversation.json")
HISTORY_FILE.parent.mkdir(exist_ok=True)
def load_history() -> list:
if HISTORY_FILE.exists():
return json.loads(HISTORY_FILE.read_text())
return [{"role": "system", "content": SYSTEM_PROMPT}]
def save_history(messages: list) -> None:
HISTORY_FILE.write_text(json.dumps(messages, indent=2))

File 3 of 4

📁

Save as: ~/projects/cofounder-agent/agent.py — create new file

import ollama
from config import MODEL
def chat(user_input: str, messages: list) -> str:
messages.append({"role": "user", "content": user_input})
response = ollama.chat(model=MODEL, messages=messages)
reply_text = response.message.content
messages.append({"role": "assistant", "content": reply_text})
return reply_text

File 4 of 4

📁

Save as: ~/projects/cofounder-agent/main.py — create new file

from rich.console import Console
from agent import chat
from memory import load_history, save_history
from config import AGENT_NAME
console = Console()
def main():
messages = load_history()
console.print(f"[bold cyan]{AGENT_NAME} is online.[/] (type
'exit' to quit)\n")
while True:
user_input = console.input("[bold green]you>[/] ")
if user_input.strip().lower() in {"exit", "quit"}:
save_history(messages)
break
reply = chat(user_input, messages)
console.print(f"[bold cyan]{AGENT_NAME}>[/] {reply}\n")
save_history(messages)
if __name__ == "__main__":
main()

Run it
Open the terminal in VSCode ( Ctrl+` ). Make sure (venv) shows in your
prompt — if not, run source venv/bin/activate first. Then:
python main.py

The first reply will be slow (the model is loading into memory for the first time);
after that it's much faster. Type exit to quit — your conversation is saved to
data/conversation.json automatically.

✅

Checkpoint: you now have 4 files, all inside ~/projects/cofounder-agent/ ,

and a working chat agent that remembers you across restarts, running entirely
offline.

Day 2 — Giving It Senses and Hands: Tools

Goal: an agent that can act — read files, check a repo, remember durable facts.

New file

📁

Save as: ~/projects/cofounder-agent/tools.py — create new file

import subprocess
import requests
# Commands we allow run_shell to execute. Everything else is
refused.
SAFE_COMMANDS = {"ls", "git", "cat", "pwd", "wc", "df", "du"}
def read_file(path: str) -> str:
"""Read the contents of a text file from disk.
Args:
path: Path to the file to read.
"""
try:
return open(path).read()[:4000]
except Exception as e:
return f"Error: {e}"
def list_dir(path: str) -> str:
"""List files in a directory.
Args:
path: Path to the directory to list.
"""
import os
try:
return "\n".join(os.listdir(path))
except Exception as e:
return f"Error: {e}"
def run_shell(command: str) -> str:
"""Run a read-only shell command such as git status, ls, cat,
pwd.
Never used for destructive commands.
Args:
command: The shell command to run.
"""
first_word = command.strip().split()[0] if command.strip()
else ""
if first_word not in SAFE_COMMANDS:

return f"Refused: '{first_word}' is not in the allowed
command list."
try:
result = subprocess.run(
command, shell=True, capture_output=True, text=True,
timeout=10
)
return result.stdout[:2000] or result.stderr[:2000]
except Exception as e:
return f"Error: {e}"
def github_repo_status(owner: str, repo: str) -> str:
"""Get open issue count and default branch for a public GitHub
repo.
Args:
owner: The GitHub username or org that owns the repo.
repo: The repository name.
"""
try:
r =
requests.get(f"https://api.github.com/repos/{owner}/{repo}",
timeout=10)
data = r.json()
return f"Stars: {data.get('stargazers_count')}, Open
issues: {data.get('open_issues_count')}, Default branch:
{data.get('default_branch')}"
except Exception as e:
return f"Error: {e}"
TOOLS = [read_file, list_dir, run_shell, github_repo_status]
DISPATCH = {fn.__name__: fn for fn in TOOLS}

( github_repo_status calls GitHub's public REST API, documented at
https://docs.github.com/en/rest — no login needed for public repos, though
unauthenticated requests are rate-limited to 60/hour.)
Safety note: keep SAFE_COMMANDS short. Never let an agent run rm , sudo , or

anything destructive without asking you first.

Edit an existing file

📁

Edit: ~/projects/cofounder-agent/agent.py — click it in the sidebar,

Ctrl+A , Delete , then paste this entire replacement, then Ctrl+S

import ollama
from config import MODEL
from tools import TOOLS, DISPATCH
def chat(user_input: str, messages: list) -> str:
messages.append({"role": "user", "content": user_input})
while True:
response = ollama.chat(model=MODEL, messages=messages,
tools=TOOLS)
messages.append(response.message)
if not response.message.tool_calls:
return response.message.content
for tool_call in response.message.tool_calls:
fn = DISPATCH.get(tool_call.function.name)
if fn:
result = fn(**tool_call.function.arguments)
else:
result = f"Unknown tool:
{tool_call.function.name}"
messages.append({
"role": "tool",
"content": str(result),
"name": tool_call.function.name,
})

Test it by running python main.py again and asking something like "list the files
in my project folder" — watch it call the list_dir tool.

Small local models are noticeably slower at tool calling than hosted ones — one
tool-using turn on an 8B model, CPU-only, can take 20-40 seconds. If that's too
slow, run ollama pull qwen2.5:1.5b in the terminal, then keep MODEL =
"qwen2.5:1.5b" in config.py (edit it the same way:

click it, change that one line, Ctrl+S ).

Edit an existing file

📁

Edit: ~/projects/cofounder-agent/memory.py — open it, click at the very

end of the existing text (don't delete anything this time), press Enter twice,

then paste this addition, then Ctrl+S
import sqlite3

DB = sqlite3.connect("data/memory.db", check_same_thread=False)
DB.execute("CREATE TABLE IF NOT EXISTS facts (key TEXT PRIMARY
KEY, value TEXT)")
DB.commit()
def remember(key: str, value: str) -> None:
"""Store a durable fact the agent should always know."""
DB.execute("REPLACE INTO facts VALUES (?, ?)", (key, value))
DB.commit()
def recall_all() -> dict:
return dict(DB.execute("SELECT key, value FROM
facts").fetchall())

To actually use this, add remember to the TOOLS list in tools.py (open
tools.py , change the line to TOOLS = [read_file, list_dir, run_shell,
github_repo_status, remember] , and add from memory import remember at

the top of that file).

New file

📁

Save as: ~/projects/cofounder-agent/watcher.py — create new file

# watcher.py
import schedule, time, logging
from tools import github_repo_status
logging.basicConfig(filename="logs/watcher.log",
level=logging.INFO)
def check_repo():
status = github_repo_status("your-username", "your-repo")
logging.info(status)
schedule.every(30).minutes.do(check_repo)
if __name__ == "__main__":
while True:
schedule.run_pending()
time.sleep(60)

Before running this one, create the logs folder it writes to:
mkdir -p ~/projects/cofounder-agent/logs

Then edit "your-username", "your-repo" in the code to a real GitHub repo
(e.g. "ollama", "ollama" ), and try it: python watcher.py — leave it running in
a terminal, check logs/watcher.log after 30 minutes (or temporarily change
every(30).minutes to every(10).seconds just to see it work faster, then

change it back).

✅

Checkpoint: the agent can read your files, inspect a repo, run safe shell

commands, remembers durable facts, and can watch things in the background.

Day 3 — High-End: Orchestration, Voice, and Always-On
New file

📁

Save as: ~/projects/cofounder-agent/specialists.py — create new

file
import ollama
from config import MODEL
SPECIALISTS = {
"code": "You are a senior code reviewer. Be terse and specific
about bugs and risks.",
"research": "You are a research analyst. Cite what you find,
flag uncertainty.",
}
def ask_specialist(role: str, prompt: str) -> str:
"""Delegate a question to a specialist sub-agent.
Args:
role: Which specialist to use — 'code' or 'research'.
prompt: The question or task to hand to the specialist.
"""
response = ollama.chat(
model=MODEL,
messages=[
{"role": "system", "content": SPECIALISTS[role]},
{"role": "user", "content": prompt},
],
)
return response.message.content

To wire it in, open tools.py , add from specialists import ask_specialist
at the top, and add ask_specialist to the TOOLS list.

Optional: voice interface (fully local, no extra cost)
This section is optional and depends on an online speech-to-text service for
recognize_google. Skip it if you want the rest of the agent to stay fully local.
Install the extra system and Python packages first, in the terminal:
sudo apt install -y espeak portaudio19-dev
pip install SpeechRecognition pyttsx3 pyaudio

📁

Save as: ~/projects/cofounder-agent/voice.py — create new file

# voice.py
import speech_recognition as sr
import pyttsx3
recognizer = sr.Recognizer()
tts = pyttsx3.init()
def listen() -> str:
with sr.Microphone() as source:
audio = recognizer.listen(source)
try:
return recognizer.recognize_google(audio)

# free public

speech-to-text endpoint
except sr.UnknownValueError:
return ""
def speak(text: str) -> None:
tts.say(text)
tts.runAndWait()
recognize_google here uses a free public speech-to-text endpoint over the

internet (Ollama itself doesn't do speech). For a fully offline voice pipeline
instead, look up the vosk library — also free, runs locally.
To actually use it, open main.py , add from voice import listen, speak at
the top, then replace the line user_input = console.input("[bold green]you>
[/] ") with user_input = listen() , and replace console.print(f"[bold
cyan]{AGENT_NAME}>[/] {reply}\n") with the same line plus speak(reply)

underneath it.

Always-on background service

This file goes in a special system location, not your project folder, so create it
directly from the terminal instead of VSCode's file explorer:
mkdir -p ~/.config/systemd/user
nano ~/.config/systemd/user/cofounder-agent.service

This opens the nano text editor inside your terminal. Paste in the block below
(right-click in most terminals pastes clipboard content, or use Ctrl+Shift+V ):

📁

Paste this into nano:

[Unit]
Description=Personal AI Co-Founder Agent
[Service]
WorkingDirectory=/home/YOUR_USER/projects/cofounder-agent
ExecStart=/home/YOUR_USER/projects/cofounder-agent/venv/bin/python /home/YOUR_USER/projects/cofounder-agent/watcher.py
Restart=always
[Install]
WantedBy=default.target

Before saving, replace both instances of YOUR_USER with your actual Ubuntu

username (find it by running whoami in another terminal tab). Then save and exit
nano: press Ctrl+O , then Enter to confirm the filename, then Ctrl+X to exit.
Now enable and start it:
systemctl --user daemon-reload
systemctl --user enable --now cofounder-agent.service
journalctl --user -u cofounder-agent -f

That last command tails the live logs — press Ctrl+C to stop watching (the
service keeps running in the background either way).
Ollama itself already runs as its own system service in the background (it was set
up automatically in Day 0), so as long as your machine is on, both the model and
your agent's watcher are alive.

Final checklist before you call it "high-end"
[ ] run_shell whitelist in tools.py stays short; no destructive commands
without confirmation

[ ] ollama list (run in terminal) shows the model(s) you're using and their
disk size
[ ] logs/watcher.log is getting new lines every 30 minutes
[ ] data/ folder is git-ignored so your conversation history and facts db don't
end up in a public repo
[ ] At least one specialist sub-agent ( ask_specialist ) is wired into TOOLS in
tools.py

All Links in One Place
VSCode download: https://code.visualstudio.com/download
Ollama download/install: https://ollama.com/download
Ollama model library (browse other free models): https://ollama.com/library
GitHub REST API docs (used by github_repo_status ):
https://docs.github.com/en/rest
Model Context Protocol (mentioned as a next step):
https://modelcontextprotocol.io

You now have a persistent, tool-using, background-running agent with delegated
specialists — running entirely on your own Ubuntu machine, for free, forever.

