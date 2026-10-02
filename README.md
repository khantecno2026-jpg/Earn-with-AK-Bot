# Earn with AK — Telegram Earning Bot MVP

Black + Gold themed Telegram earning/reward bot.

## Included
- User registration
- Black/gold styled menus (Telegram buttons themselves cannot be recolored)
- Task list
- Referral links and referral bonus
- Balance + earning ledger
- Withdrawal requests: bKash, Nagad, Rocket
- Minimum withdrawal: 110 BDT
- Admin commands for adding tasks and approving/rejecting withdrawals
- Telegram join-task verification when the bot is an administrator in the target channel
- SQLite database

## Important
Do not advertise a task as verified unless the advertiser/source actually provides a verifiable completion signal.
Website visits, ad views, app installs and surveys normally need a third-party offer/CPA API or postback to verify completion. This MVP does not fake those verifications.

## Run
1. Create a bot with @BotFather and copy the token.
2. Copy `.env.example` to `.env`.
3. Put your Telegram numeric ID in ADMIN_IDS.
4. Install dependencies:
   `pip install -r requirements.txt`
5. Run:
   `python bot.py`

## Admin commands
/addtask | title | reward | type | target
Example:
/addtask | Join our channel | 5 | telegram_join | @YourChannel

For non-Telegram tasks, use a target URL:
 /addtask | Visit website | 2 | website | https://example.com

Approve withdrawal:
/approve WD123

Reject withdrawal:
/reject WD123 reason

Add balance manually (use carefully):
/credit TELEGRAM_ID AMOUNT reason

The payment payout itself is intentionally manual in this MVP. Automated bKash/Nagad/Rocket payout should only be connected after you have the provider's official merchant/API access and credentials.
