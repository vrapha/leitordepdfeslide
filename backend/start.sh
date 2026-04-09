#!/bin/bash
Xvfb :99 -screen 0 1280x800x24 -ac &
export DISPLAY=:99
sleep 1
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
