@echo off
rem Try the accounts and Free/Pro flow with a PRETEND account service: no Supabase or Stripe needed.
rem   - Create an account (any email, password of 8+ characters), then press Upgrade to "pay" on a pretend page.
rem   - The pretend service forgets everything each time, and this script clears the test sign-in before and after.
rem   - Replays and settings are your real ones; nothing is deleted.
cd /d "%~dp0"

python dev_tools\clean_test_account.py
echo Starting the pretend account service...
start "RL Analyser pretend account service" /min python dev_tools\fake_service.py
timeout /t 2 /nobreak >nul

set RLA_SUPABASE_URL=http://127.0.0.1:8765
set RLA_SUPABASE_KEY=pretend
python rl_analyser.py

echo Cleaning up...
taskkill /fi "WINDOWTITLE eq RL Analyser pretend account service" /f >nul 2>&1
python dev_tools\clean_test_account.py
