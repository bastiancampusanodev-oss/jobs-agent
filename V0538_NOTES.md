# v0.5.38 — Safe native submit confirmation

Get on Board can present a native browser `confirm()` before the actual
application send, with the standard Privacy Policy notice. Without a
Playwright `dialog` listener, native dialogs are automatically dismissed,
leaving the application as a draft.

This version:

- installs a dialog guard before the submit click;
- accepts only the known Get on Board Privacy Policy confirmation;
- rejects/dismisses every unknown dialog, including CAPTCHA/MFA/identity
  verification signals;
- never retries the submit click;
- preserves `CONFIRMATION_REQUIRED` for unknown confirmations;
- does not change CandidateTruth, salary, CV, CUSTOM, daemon or systemd.
