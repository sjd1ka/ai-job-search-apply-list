# Answer Bank

Reusable, candidate-confirmed answers for application forms, used by `/fill`. The candidate profile (`01-candidate-profile.md`, `CLAUDE.md`) owns facts; this file owns the exact wording used on forms. `/setup` fills it from the candidate's answers; everything not yet confirmed stays `PENDING`.

**Privacy:** this file holds work-authorization, salary and self-identification answers. It is tracked by git, so never push it to a public repository (see SETUP.md section 8).

Rules:
- Use an answer here only when the form's question means the same thing. If the wording differs in a way that could change the answer (e.g. "now **or in the future**", a specific country, a legal attestation), do not guess: put it on the pending list for the consolidated review.
- `PENDING` means the candidate has not confirmed it yet. Never fill a PENDING item; ask in the consolidated review, then record the confirmed answer here.
- When the candidate confirms a new reusable answer during `/fill`, add it to "Custom questions" in the same turn.

## Identity and contact

| Field | Answer |
|---|---|
| Legal name | PENDING |
| Email | PENDING |
| Phone | PENDING |
| City / Region / Country | PENDING |
| LinkedIn | PENDING |

## Work authorization

| Question pattern | Answer |
|---|---|
| Are you legally authorized / eligible to work in <country>? | PENDING |
| Do you **now** require sponsorship? | PENDING |
| Will you **now or in the future** require sponsorship? | PENDING |
| Permit type and expiry, if asked | PENDING |

## Compensation

- Required numeric field: PENDING (range, and a single number if only one is allowed)
- Free-text or optional field: "Negotiable, based on the full compensation package." Prefer this when the form allows it.
- Hourly contract roles: PENDING

## Availability and logistics

| Question pattern | Answer |
|---|---|
| Earliest start date / notice period | PENDING |
| Currently employed? | PENDING |
| Hybrid / onsite / remote | PENDING |
| Willing to relocate? | PENDING |
| Languages | As in the CLAUDE.md Languages table; never claim a language not listed there |

## Voluntary self-identification

Strategy: PENDING. The candidate chooses one: their own answers, or "Prefer not to say" everywhere. Answer only what the form asks; never volunteer one of these in a free-text field.

| Question | Answer |
|---|---|
| Gender | PENDING |
| Visible minority / race / ethnicity | PENDING |
| Indigenous identity | PENDING |
| Disability | PENDING |
| LGBTQ+ | PENDING |
| Veteran | PENDING |

## Legal and attestations

Background check consent, criminal record questions, non-compete or confidentiality agreements, and "I certify that the information is accurate" checkboxes: **never tick on the candidate's behalf**. List them in the consolidated review; the candidate ticks them personally.

## Custom questions

| Question pattern | Answer or pattern | When to customize |
|---|---|---|
| How did you hear about this role? | The portal the posting came from (LinkedIn / Indeed / company careers site), from the tracker `source` | Never |
| Why this company / role? | 2-3 sentences drawn from the cover letter's company paragraph for this application | Every application |
