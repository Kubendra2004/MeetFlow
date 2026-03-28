@echo off
cd /d "C:\Users\Suhas\Downloads\MeetFlow-master\MeetFlow-master"
echo ============================================================
echo   MeetFlow WhatsApp Bot Server
echo ============================================================
echo.
echo Starting Flask server on port 5000...
start "Flask Server" cmd /k "python whatsapp_bot_server.py"

timeout /t 3 /nobreak >nul

echo Starting ngrok tunnel...
start "ngrok Tunnel" cmd /k "ngrok http 5000"

echo.
echo ============================================================
echo   Both are running!
echo   1. Copy the ngrok https URL (e.g. https://xxxx.ngrok.io)
echo   2. Go to Twilio Sandbox settings:
echo      https://console.twilio.com/us1/develop/sms/settings/whatsapp-sandbox
echo   3. Set "WHEN A MESSAGE COMES IN" to:
echo      https://xxxx.ngrok.io/whatsapp
echo.
echo   Then WhatsApp these commands to +1 415 523 8886:
echo     help          - see all commands
echo     today         - today's meeting report
echo     yesterday     - yesterday's report
echo     list          - all available report dates
echo     2026-03-28    - specific date report
echo     stats         - all-time totals
echo ============================================================
pause
