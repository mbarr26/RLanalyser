@echo off
rem Try the accounts and Free/Pro flow from source in DEMO mode: pretend accounts and payments, no Supabase or Stripe.
rem   - Create an account (any email, password of 8+ characters), then press Upgrade to "pay" on a pretend page.
rem   - Starts fresh every time (the pretend accounts are deleted first), and the test sign-in is cleared afterwards.
rem   - Replays and settings are your real ones; nothing of those is deleted.
cd /d "%~dp0"

python dev_tools\clean_test_account.py
if exist demo-accounts.json del demo-accounts.json

set RLA_DEMO=1
python rl_analyser.py

echo Cleaning up...
python dev_tools\clean_test_account.py
if exist demo-accounts.json del demo-accounts.json
