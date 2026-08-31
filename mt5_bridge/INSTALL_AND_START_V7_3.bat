@echo off
cd /d %~dp0
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
py bridge_v7_3.py
pause
