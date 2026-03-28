@echo off
:: ============================================================
::  MeetFlow Auto-Startup Script
::  Runs automatically on Windows login via Task Scheduler
:: ============================================================

:: Change to the directory of this batch file
cd /d "%~dp0"

:: Create logs folder if missing
if not exist logs mkdir logs

:: Wait 15 seconds for internet to connect after boot
echo [MeetFlow] Waiting for internet...
timeout /t 15 /nobreak >nul

:: ── 1. Start WhatsApp Bot Server (Flask) ──────────────────
echo [MeetFlow] Starting WhatsApp Bot Server...
start "MeetFlow-BotServer" /min cmd /c "python whatsapp_bot_server.py >> logs\bot_server.log 2>&1"

:: Wait for Flask to start
timeout /t 5 /nobreak >nul

:: ── 2. Start ngrok tunnel ─────────────────────────────────
echo [MeetFlow] Starting ngrok...
start "MeetFlow-ngrok" /min cmd /c "ngrok http 5000 >> logs\ngrok.log 2>&1"

:: Wait for ngrok to get a public URL
timeout /t 8 /nobreak >nul

:: ── 3. Auto-update Twilio webhook with new ngrok URL ──────
echo [MeetFlow] Updating Twilio webhook...
python update_twilio_webhook.py >> logs\webhook_update.log 2>&1

:: ── 4. Start Meet Joiner ──────────────────────────────────
echo [MeetFlow] Starting Meet Joiner (Automation Master)...
echo   - Meeting joins automatically at scheduled time
echo   - Captions captured -> AI analysis -> Report saved (.txt)
echo   - 📲 WhatsApp report sent via Twilio (Auto-Send)
echo   - 📝 VTU Internship Diary updated (Auto-Fill)
echo   - 💬 Query past reports anytime via WhatsApp ("today", "list", etc.)
start "MeetFlow-MeetJoiner" /min cmd /c "python meet_joiner.py >> logs\meet_joiner.log 2>&1"

echo.
echo ============================================================
echo   ALL SYSTEMS GO! 🚀
echo ============================================================
echo   - Check logs\ folder for background output.
echo   - Use WhatsApp to query reports anytime.
echo   - VTU Diary will update automatically after meetings.
echo ============================================================
