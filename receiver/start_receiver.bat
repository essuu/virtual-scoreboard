@echo off
rem Starts the scoreboard receiver using the RTL-SDR.
rem Extra options can be added after the script name, e.g.  --gain 30
rem If OBS's WebSocket server has a password, add  --obs-password YOURPASSWORD
cd /d "%~dp0"
python ecs_receiver.py
pause
