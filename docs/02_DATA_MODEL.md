# Data Model

## candidate_profiles
id, name, is_active, years_experience, target_roles_json, role_synonyms_json, skills_json, preferred_locations_json, work_modes_json, minimum_salary, salary_currency, excluded_keywords_json, notes, timestamps.

## profile_suggestions
id, profile_id, suggestion_type(skill|role), value, rationale, status(pending|accepted|rejected), created_at. AI never directly mutates profile.

## resumes
id, profile_id, name, file_path/storage ref, extracted_text, is_primary, timestamps.

## companies
id, name, website_url, careers_url, provider_type, provider_identifier, discovery_source, is_active, provider_supported, last_scanned_at, last_success_at, total_jobs_seen, timestamps.

## jobs
id, company_id, source_type, source_job_id, canonical_url, title, normalized_title, location_text, city, state, country, remote_type, employment_type, description, description_hash, salary_min, salary_max, salary_currency, experience_min, experience_max, skills_json, posted_at, discovered_at, last_seen_at, consecutive_missing_scans, lifecycle_status(open|possibly_closed|closed), bounded source_payload_json optional, timestamps.

Use connector-specific uniqueness, canonical URL, and fallback dedupe signature.

## job_matches
id, job_id, profile_id, ai_provider, ai_model, scoring_version, overall_score, role_score, skills_score, experience_score, location_score, freshness_score, seniority_score, salary_score nullable, recommendation_label, matching_skills_json, missing_skills_json, concerns_json, explanation, suggested_resume_id nullable, source_job_hash, scored_at.

## job_user_state
id, job_id, profile_id, state(new|saved|applied|ignored), applied_at nullable, resume_id nullable, note nullable, updated_at.

## scan_runs
id, trigger_type(manual|scheduled), started_at, finished_at, status(running|success|partial|failed), companies_checked, sources_checked, jobs_fetched, jobs_new, jobs_updated, jobs_scored, strong_matches, errors_count, summary.

## scan_source_results
id, scan_run_id, company_id nullable, source_type, started_at, finished_at, status, jobs_fetched, jobs_new, jobs_updated, error_message, retry_count.

## notification_destinations
id, type(recommendation|application_activity|scan_summary), name, telegram_chat_id, is_enabled. Bot token stored as secret, not normal DB content.

## notification_log
id, destination_id, job_id nullable, scan_run_id nullable, event_key, status, sent_at, error_message. Used for idempotency/debugging.

## settings
Runtime configuration: scan interval default 4h, daily target default 10, Telegram threshold default 85, AI provider/model, search provider, concurrency limits, lifecycle missing threshold, approved runtime settings.

Secrets prefer environment variables.

## Backup
No elaborate table required. Export DB plus resume files/needed configuration into one archive.
