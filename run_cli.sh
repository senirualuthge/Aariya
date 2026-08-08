#!/bin/bash
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "Warning: venv not found. Continuing with system python..."
fi

# Function to clean up background processes on exit
cleanup() {
    echo "Stopping server..."
    kill $SERVER_PID 2>/dev/null
    exit
}

trap cleanup SIGINT SIGTERM EXIT

echo "Starting AI Girl Brain Server..."
uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload &
SERVER_PID=$!

echo "Waiting for server to initialize..."
sleep 5

echo "Starting Interactive Client..."
python interactive_client.py
