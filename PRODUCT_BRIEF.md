# Casebook: product brief

**One line.** An AI agent that labels job postings against a written, versioned fraud policy.
Every decision names the rule it applies and quotes the posting as proof, so analysts can trust
it, check it in seconds, and change the rules without a code change.

## Target users

- **Trust & Safety analysts** at a job marketplace (primary). They clear a queue of suspicious
  postings every day and must justify each removal.
- **Policy owners** (T&S lead, legal). They write the rules and change them about weekly, as
  scammers adapt.
- **The marketplace platform** reads labels through an API to hide or hold postings.

## Pain points

1. **Scams hurt job seekers.** Fake recruiters collect ID copies, charge "starter kit" fees and
   recruit money mules. There are too many postings to review them all by hand.
2. **A risk score is not a decision.** "0.87 fraud" does not say which rule is broken or where.
   An analyst cannot enforce it or defend it when the employer appeals.
3. **Rule changes are slow and blind.** When the policy lives in code or in a prompt, every
   change becomes an engineering ticket, and nobody knows how many postings it will flip until
   it ships.
4. **LLMs sound sure even when wrong.** A model can cite text that is not in the posting, or
   fail silently. An unverifiable "VIOLATING" is worse than no label.

## Solution, and why this shape

For each posting the agent returns `VIOLATING / NEEDS_REVIEW / ALLOWED`, the policy sections
that apply, verbatim quotes as evidence, a short rationale and a confidence.

| Decision | Why |
|---|---|
| **The model proposes, code decides.** The LLM suggests sections and quotes. Code checks that every quote really is in the posting, drops sections without proof, and computes the label from the policy's own rules. | A block always rests on real text an analyst can see highlighted. Fabricated evidence cannot turn into enforcement. |
| **The policy is a versioned document, read at run time.** | Policy owners edit, shadow-run on known postings, see exactly which decisions would flip, publish, and roll back. No code change, no redeploy. |
| **A cheap model first, a strong model only on logged triggers** (low confidence, dropped evidence, disagreement with a risk router). | Most postings are easy. Escalating 14% instead of 38% cut the estimated cost per posting by ~60%. |
| **A failure is a label.** A model error or malformed answer becomes `NEEDS_REVIEW` with a reason. | Nothing is silently allowed and nothing is silently dropped. |

**Main workflows:** (1) triage a case with its highlighted evidence and decision trail, then
agree or overturn it with a reason (stored beside the agent's label, never over it);
(2) change the policy safely: draft, shadow-run, impact diff, publish, re-label, roll back;
(3) bring in postings in bulk, watch the queue, and check quality on a fixed evaluation set.
**Edge cases handled:** invented quotes are rejected; model failure becomes review; empty
postings skip the model; text that tries to instruct the AI can never be cleared automatically.

## Success criteria

Measured on a fixed held-out set of 400 postings from the public EMSCAD dataset, policy v1,
Claude Haiku 5.5 escalating to Opus 5.5, with the code in this repo (RESULTS.md §1.1). Each
decision is checked against the policy's own rules.

| Criterion | Target | Now |
|---|---|---|
| Blocks grounded in a policy section and a verified quote | 100% | **100%** (23 of 23), enforced by code |
| Evidence that is real posting text | 100% | **100%**: of 394 quotes, 8 were rejected (all quoted the prompt's metadata line); none invented posting text |
| Reviews routed by a review-only section of the policy | 100% | **100%** (140 of 140, all §5) |
| Share of postings sent to an analyst (review rate) | ≤ 15% | **35%**: §5 applied as written; v3 narrows it (see below) |
| Policy change live without code, with impact shown first | yes | **yes** (v2 adds a section, v3 narrows one) |
| Label latency p95 / cost per 1,000 postings | < 60 s / < $3 | **14.3 s / ≈ $2.55** (estimate, see RESULTS.md) |

Against the dataset's fraud label (secondary; it says "was fraud", not "breaks the policy"):
blocking precision **0.96** (22 of 23 blocks are fraud), and **0.73** of frauds are blocked or
sent to review (RESULTS.md, Summary).

The Evaluation page shows an earlier run of the same set (RESULTS.md §1); both are reported.

In production the main signal is the **share of decisions analysts uphold**, per label and
policy version (built: agree / overturn on each case, counted on the Evaluation page), plus
analyst minutes per case and appeal outcomes.

## Assumptions and limitations

- **Assumed scale:** ~200k postings a day, 5× peaks, weekly policy changes, a label within 60 s
  (sized in DESIGN.md). **Data:** public EMSCAD (CC0) only.
- **Cloned listings and impersonation** are not covered by any written rule yet. A new section
  and a "similar postings" tool would cover them.
- **Review volume follows §5.** §5 ("unverifiable employer") routes postings without a company
  profile to analysts, including postings that name the employer in the text. v3 narrows §5 to
  postings that never name the employer.
- **Shadow-run diffs are noisy:** the same policy re-run flipped 4 of 20 §5 calls, so an impact
  diff must be read against a same-policy rerun. **Policy owners edit YAML** (validated live); a
  form editor comes next.
- **Not built:** authentication and an audit log, calibrated confidence, diff-aware re-labeling.
  **Cost and latency are estimates** from token counts at list prices (runs used the Claude CLI).
