# Prompt 13 — Security at rest

This patch adds an opt-in encryption-at-rest layer for local Money Manager user data.

## Security model

- Each user has one random 256-bit Data Encryption Key (DEK).
- The DEK encrypts sensitive JSON, CSV, and document bytes with AES-GCM.
- The user's password derives a Key Encryption Key (KEK) using PBKDF2-HMAC-SHA256 with a per-user salt and 600,000 iterations.
- The KEK only wraps/unwraps the DEK. It is not used directly for data files.
- The encrypted DEK is stored in `data/_system/security/users/{user_id}.json`.
- The raw DEK is never written to disk. It lives only in `session_vault.py` process memory while the user is logged in/unlocked.

## Encrypted file format

Encrypted files start with the magic marker `MMENC1` followed by a JSON envelope containing:

- `algorithm`: `AESGCM`
- `nonce`
- `content_type`
- `original_logical_name` / `original_filename`
- `created_at`
- `ciphertext`

The file extension is intentionally left unchanged, so `accounts.json` or `expenses.csv` remains in place but becomes unreadable in Explorer.

## What is encrypted by default

When encryption is enabled, the migration encrypts the registry-marked sensitive files, including profile/preferences, accounts, payment methods, contacts, document metadata, transaction CSVs, account ledger, settlements, debts/payables/receivables, project files, internal transfers, and uploaded documents.

## What remains plaintext

- `users.json` remains plaintext by design because the app must find users and verify password hashes before the vault is unlocked.
- `local_app.json`, `install_state.json`, update manifests, generated plots, and cache folders remain plaintext/non-sensitive by default.
- Logs are not encrypted by this patch; the security audit checks for obvious sensitive token leaks.

## Limitations

This is a local desktop app. Encryption prevents casual file reading from Windows Explorer. It cannot stop someone with full access to the PC from deleting, copying, rolling back, or corrupting files. It does not protect against malware or a user who knows the password.

If encryption is enabled and the password is lost, encrypted data cannot be decrypted unless a future recovery-key mechanism has been enabled.
