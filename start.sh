#!/usr/bin/env bash
# Professional Launcher for Jarvis AI Assistant

# 1. Set working directory to where the script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "🚀 Starting Jarvis AI Assistant..."

# 2. Kill any existing server process (match the Jarvis command lines —
#    this minimal Fedora has neither lsof nor ss)
PID=$(pgrep -f 'launch_app\.py|uvicorn jarvis\.web\.server' | tr '\n' ' ')
if [ -n "$PID" ]; then
    echo "Stopping existing Jarvis instance (PID: $PID)..."
    kill -9 $PID 2>/dev/null
    sleep 1
fi

# 3. Activate virtual environment
if [ -d ".venv" ]; then
    echo "Activating virtual environment..."
    source .venv/bin/activate
else
    echo "❌ Error: .venv directory not found. Please create it first."
    exit 1
fi

# 4. Run the server in the background
echo "Launching server..."
nohup python3 launch_app.py > server.log 2>&1 &

# 5. Wait for the server to be ready
echo "Waiting for server to boot..."
MAX_RETRIES=10
COUNT=0
while ! curl -s http://localhost:8000/api/status > /dev/null; do
    sleep 1
    COUNT=$((COUNT + 1))
    if [ $COUNT -ge $MAX_RETRIES ]; then
        echo "❌ Error: Server failed to start in time. Check server.log for details."
        exit 1
    fi
done

# 6. Open the dashboard in the default browser
echo "✅ Jarvis is online! Opening dashboard..."
# Use xdg-open for Fedora/Linux
xdg-open "http://localhost:8000"

echo "--------------------------------------------------"
echo "Jarvis is now running in the background."
echo "Log file: $DIR/server.log"
echo "To stop Jarvis, run: pkill -f launch_app.py"
echo "--------------------------------------------------"
