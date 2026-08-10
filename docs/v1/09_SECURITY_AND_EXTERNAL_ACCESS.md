# Security and External Access

Secrets via environment: AI API keys, search provider key if needed, Telegram bot token. Never commit .env, log keys, render secrets, or include secrets in unencrypted backup.

Prefer public/structured ATS endpoints then public career pages then limited HTML extraction.

Never bypass CAPTCHA, login, rate/access controls, or anti-bot protections. Unsupported sources are logged and skipped.

Generic HTML collector protections: timeouts, response-size limit, content-type validation, URL/domain validation, bounded link extraction, no uncontrolled recursive crawl, no script execution.

Treat job descriptions/web text as untrusted data; delimit it as data in AI prompts so page content cannot override system instructions.

Resume uploads: needed formats only, size limit, safe filenames, controlled storage, no execution.
