@echo off
rem Replays a logic-analyser recording through the scoreboard (no radio needed).
rem Open http://127.0.0.1:8765/status in a browser while it runs.
cd /d "%~dp0"
start "" http://127.0.0.1:8765/status
python ecs_receiver.py --sr "..\captures\set - runs - wicket - runs.sr" --realtime
pause
