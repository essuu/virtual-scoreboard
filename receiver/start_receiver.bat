@echo off
rem Starts the scoreboard receiver using the RTL-SDR.
rem Extra options can be added after the script name, e.g.  --gain 30
cd /d "%~dp0"
python ecs_receiver.py
pause
