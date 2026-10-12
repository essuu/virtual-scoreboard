@echo off
rem Runs the receiver as normal AND saves the raw radio signal to a timestamped .cu8 file
rem in the recordings folder, so a test session can be replayed or shared later.
rem Every message is also shown on the status page with its field number.
cd /d "%~dp0"
if not exist recordings mkdir recordings
for /f %%t in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmmss"') do set TS=%%t
echo Recording to recordings\test_%TS%.cu8  (about 2 MB per second - stop with Ctrl+C)
start "" http://127.0.0.1:8765/status
python ecs_receiver.py --record "recordings\test_%TS%.cu8" %*
pause
