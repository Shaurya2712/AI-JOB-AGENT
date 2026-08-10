# V2 Portal Behavior

## LinkedIn
Required:
- generate/use LinkedIn-targeted search queries
- accept useful LinkedIn job URLs in the portal-discovery path
- normalize/persist portal discovery data
- integrate with deduplication
- show useful results in dashboard

Do not:
- make LinkedIn a company-career source
- require LinkedIn credentials
- automate LinkedIn login
- implement autonomous scraping of authenticated LinkedIn pages
- bypass CAPTCHA/anti-bot/access controls

## Naukri
Required:
- generate/use Naukri-targeted search queries
- accept useful Naukri job URLs in portal discovery
- normalize/persist discovery data
- integrate with deduplication
- show useful results in dashboard

Do not:
- require Naukri credentials
- automate login
- add anti-bot bypass tooling

## Indeed
Required:
- generate/use Indeed-targeted search queries
- accept useful Indeed job URLs in portal discovery
- normalize/persist discovery data
- integrate with deduplication
- show useful results in dashboard

Keep architecture capable of supporting an authorized/official Indeed adapter later without changing downstream job logic.

That future adapter is not required unless the current project already has approved access/credentials.

## Search Query Generation
Reuse existing profile data.

Generate useful variations across:
- target role
- role synonyms
- location
- remote preferences
- portal domain

Avoid combinatorial explosion.

Codex should inspect existing query generation and extend it minimally.

## Result Validation
Reject obviously irrelevant portal search results such as:
- portal home pages
- generic search landing pages with no specific job
- company profiles
- recruiter profiles
- articles
- help pages
- unrelated pages

Only job-specific results should enter the job pipeline.

## Open Job Handling
Portal results should represent currently discoverable/open opportunities where reasonably determinable.

Do not claim a job is confirmed open if available metadata does not establish that.

Reuse the existing lifecycle engine where practical.

## Dashboard
Existing job list should support source filtering for:
- LinkedIn
- Naukri
- Indeed
- existing V1 sources

Keep source labels compact.

Partial data should be understandable without developer logs.

## Original Link
Every portal-discovered job must retain the original URL.

User flow remains:

```text
Job Agent
→ review/rank
→ Open Original Job
→ apply manually
→ return to dashboard
→ Mark Applied
```
