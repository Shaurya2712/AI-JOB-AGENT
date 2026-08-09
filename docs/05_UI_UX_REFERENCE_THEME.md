# UI/UX — Reference-Inspired Minimal Editorial Theme

## Visual Reference
Primary design reference:

`https://168hd5iyr2czx.space.minimax.io/`

The application should feel visually similar to this reference website, while adapting the pattern to an operational job-search dashboard.

Do not copy branding, content, logos, or unrelated page text. Reuse only the broad visual language and interaction principles.

## Design Direction
The UI should feel like a polished, modern editorial/documentation product rather than a generic SaaS admin template.

Key characteristics to reproduce:
- strong typographic hierarchy
- editorial/documentation-style page composition
- restrained color use
- generous but controlled whitespace
- thin borders/dividers rather than heavy shadows
- compact section labels and numbering where useful
- readable dense tables/lists
- simple top-level navigation
- subtle surface contrast
- minimal visual noise
- little or no decorative animation

The reference page uses a clearly structured contents/section model and compact information-heavy presentation. Adapt that structure to job-search workflows.

## Important Change From Earlier Spec
The earlier Solarized Light requirement is CANCELLED.

Do NOT implement Solarized Light simply because an older file, commit, or generated code mentions it.

This reference-inspired theme is the current source of truth.

## Color System
Do not force a traditional Solarized palette.

At implementation time, inspect the reference site and derive a small semantic palette that visually resembles it. Keep the palette intentionally small:
- page background
- primary surface
- secondary/subtle surface
- primary text
- muted text
- border/divider
- primary accent
- success
- warning
- error

Rules:
- avoid gradients
- avoid neon color overload
- avoid large saturated color blocks
- avoid glassmorphism
- avoid heavy drop shadows
- prefer border + spacing hierarchy

## Typography
Typography should carry most of the hierarchy.

Use:
- a clean modern sans-serif or similarly neutral web-safe/system stack
- large, confident page titles
- small eyebrow/section labels when useful
- compact but readable table text
- clear numeric emphasis for scores/counts

Avoid:
- multiple unrelated font families
- oversized dashboard KPI typography
- excessive bold text

If the exact reference font is unavailable or licensed, use a visually compatible open/system alternative. Do not bundle proprietary font files.

## Layout
Desktop browser is primary.

Recommended shell:
```text
┌─────────────────────────────────────────────────────────────┐
│ Brand/Job Agent          Jobs Profiles Companies Scans ... │
├─────────────────────────────────────────────────────────────┤
│ Small context / section label                              │
│ Main page title                            [ Search Now ]   │
│ Short supporting line                                      │
├─────────────────────────────────────────────────────────────┤
│ Main content                                                │
│                                                             │
│ editorial sections / compact metrics / lists / tables       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

Use a sensible max-width so the page remains readable on large monitors, but job tables may use a wider content region when necessary.

## Navigation
Primary navigation remains exactly:
- Dashboard
- Jobs
- Profiles
- Companies
- Scans
- Settings

Use a simple horizontal header on desktop. Do not introduce a large enterprise sidebar unless a real usability issue requires it.

## Dashboard
The dashboard should NOT look like a grid of oversized SaaS cards.

Use an editorial hierarchy:

### Header area
- page label / context
- `Job Search Dashboard`
- last successful scan
- next scheduled scan
- prominent but restrained `Search Now` action

### Compact status strip
Show:
- Apply Today
- Strong Matches
- New Jobs
- Applied
- Scan Health

These may be compact bordered cells/stat blocks, not giant cards.

### Section 01 — Apply Today
This is the most important section.

Show the configurable daily queue as a ranked list/table:
- rank
- score
- job title
- company
- location
- salary if known
- source
- status/action

### Section 02 — Strong Matches
Compact list of newly found high-match jobs.

### Section 03 — Latest Scan
Simple scan summary with counts and errors.

## Jobs Page
Favor a dense, readable table similar to a reference/cheat-sheet data presentation.

Columns:
- Match
- Role
- Company
- Location
- Salary
- Source
- Discovered/Posted
- Status

Use filters in a restrained top filter bar or compact expandable section.

Filters must include only those defined in product scope.

Rows should use:
- thin separators
- subtle hover feedback
- minimal badges
- clear score emphasis

Avoid turning every row into a card.

## Job Detail
Use a reading-oriented layout.

Suggested hierarchy:
```text
JOB / COMPANY / SOURCE CONTEXT

Role Title
Company · Location · Work mode
[Open Original Job]

MATCH 91% — Excellent

01 Match Summary
02 Matching Skills
03 Gaps / Concerns
04 Salary & Experience
05 Job Description

[Save] [Mark Applied] [Ignore]
```

The detailed JD should be comfortable to read, with clear headings and reasonable line length.

## Profiles Page
Use simple editorial forms, not complicated settings cards.

Sections:
- Profile Basics
- Target Roles
- Skills
- Experience
- Locations
- Salary
- Exclusions
- Resumes
- AI Suggestions

AI suggestions should appear as compact bordered rows with:
- suggestion
- rationale
- Accept
- Reject

## Companies Page
Use a table:
- Company
- Career Page
- Provider
- Support Status
- Last Scan
- Jobs
- Health

## Scans Page
Use a chronological operational log:
- Trigger
- Started
- Duration
- Result
- Sources
- Jobs Found
- New
- Scored
- Errors

Failure details can expand inline or open a simple detail page.

## Settings Page
Keep it sparse and grouped by section:
01 Search
02 Matching
03 AI Provider
04 Web Search Provider
05 Telegram
06 Backup

Secrets display only configuration state, never secret values.

## Components
Keep the reusable component set small:
- page header
- section header
- stat cell
- data table
- badge/status pill
- button
- input/select
- filter bar
- inline alert
- empty state
- pagination
- modal only when actually needed

Do not introduce a large design-system dependency solely for appearance.

## Interaction
- fast server-rendered navigation
- HTMX for targeted updates
- clear loading state for Search Now
- filters should feel immediate
- destructive/irreversible actions should be obvious
- status updates should not require a full SPA

## Responsive Behavior
Desktop is primary, but the interface must remain usable on tablet/mobile.

On narrower widths:
- navigation may collapse
- tables may horizontally scroll or convert selected columns
- primary job information must remain visible

Do not spend excessive development time on pixel-perfect mobile layouts.

## Accessibility
- semantic HTML
- visible focus states
- keyboard-accessible actions
- adequate text/background contrast
- do not encode job status solely through color

## Performance
No appearance choice may compromise the 8 GB Linux target.

Avoid:
- heavy animation libraries
- large JS frameworks for styling
- huge icon libraries if a tiny subset will do
- client-side rendering of the whole dataset

## Acceptance Criteria
The theme is complete when:
1. the UI visually follows the reference website's clean editorial/documentation character
2. no Solarized-specific theme remains
3. Dashboard is not a generic card-heavy admin template
4. job tables are compact and readable
5. Job Detail is optimized for reading and decision-making
6. pages share one consistent typography/spacing/border system
7. UI stays fast on the target Linux laptop
8. all functional modules remain unchanged by the theme update
