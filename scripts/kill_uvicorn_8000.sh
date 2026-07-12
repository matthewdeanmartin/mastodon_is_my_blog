#!/usr/bin/env bash
# kill_uvicorn_8000.sh
# Finds and kills any process listening on port 8100 (typically a stale uvicorn instance).
# Works on Linux, macOS, and Git Bash / WSL on Windows.

PORT=8100

echo "==> Looking for processes on port $PORT..."

# ----- Linux / macOS (lsof) -----
if command -v lsof &>/dev/null; then
    PIDS=$(lsof -ti tcp:"$PORT")
    if [[ -z "$PIDS" ]]; then
        echo "No process found on port $PORT (via lsof)."
    else
        echo "Found PID(s): $PIDS"
        for PID in $PIDS; do
            echo "  Killing PID $PID..."
            kill -9 "$PID" && echo "  PID $PID killed." || echo "  Failed to kill PID $PID."
        done
    fi

# ----- Windows (netstat + taskkill via Git Bash / WSL) -----
elif command -v netstat &>/dev/null; then
    # netstat on Windows prints lines like:
    #   TCP    0.0.0.0:8100   0.0.0.0:0   LISTENING   1234
    PIDS=$(netstat -ano | grep ":${PORT}" | grep "LISTENING" | awk '{print $NF}' | sort -u)
    if [[ -z "$PIDS" ]]; then
        echo "No process found on port $PORT (via netstat)."
    else
        echo "Found PID(s): $PIDS"
        for PID in $PIDS; do
            echo "  Killing PID $PID..."
            if command -v taskkill &>/dev/null; then
                taskkill //F //PID "$PID" && echo "  PID $PID killed." || echo "  Failed to kill PID $PID."
            else
                kill -9 "$PID" && echo "  PID $PID killed." || echo "  Failed to kill PID $PID."
            fi
        done
    fi

else
    echo "ERROR: Neither 'lsof' nor 'netstat' found. Cannot detect processes on port $PORT."
    exit 1
fi

echo "==> Done."
