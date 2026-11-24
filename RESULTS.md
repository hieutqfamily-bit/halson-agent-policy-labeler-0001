# RESULTS

What was measured, on what, and how far each number can be trusted. Every number here measures
how the policy is applied: which sections are cited, whether each one is backed by verified
evidence, and whether the label follows the policy's own rules.

**The test set.** 400 postings from the public EMSCAD dataset, fixed in advance and held out
(ids in `data/eval/eval_job_ids.txt`). No prompt, example or router was fitted on these 400.
The other 17,480 postings are for development.

**What "applies the policy" means here, checked on every decision:**
- **VIOLATING** only when a `violating` section (or two sections together, as the policy's
  combination rule says) is backed by a quote that occurs verbatim in the posting.
- **NEEDS_REVIEW** where the policy says review: a review-only section (§5) on its own.
- **ALLOWED** when no section of the written policy applies.

## Summary

Two runs over all 400, policy v1, Claude Haiku 5.5 escalating to Opus 5.5:

| | **code in this repo** (§1.1) | earlier prompt (§1) |
|---|---|---|
| VIOLATING · NEEDS_REVIEW · ALLOWED | **23 · 140 · 237** | 20 · 45 · 335 |
| VIOLATING decisions backed by a verified quote | **23 of 23** | 20 of 20 |
| NEEDS_REVIEW decisions routed by §5 | **140 of 140** | 45 of 45 |
| quotes returned · rejected · invented posting text | **394 · 8 · 0** | 383 · 8 · 0 |
| escalated to tier 2 | **14%** | 38% |
| cost per 1,000 postings (API list prices, estimated) | **≈ $2.55** (≈ $1.53 with Sonnet as tier 2) | ≈ $6.2 |
| latency p50 / p95 | **5.9 s / 14.3 s** | 5.7 s / 17.4 s |

What these mean. **The agent applies the policy correctly.**
- **Every block is grounded.** All 23 VIOLATING decisions cite a policy section with a quote
  found verbatim in the posting. Code enforces it: an unverified claim cannot block.
- **Evidence is real.** Of 394 quotes, none was invented posting text (§4). The 8 rejections
  were the model quoting its own prompt, which verification catches before any label.
- **Review follows §5 as written.** Every NEEDS_REVIEW comes from §5 ("unverifiable employer").
  The current prompt applies §5 where the policy says to, so more postings go to an analyst
  (140 vs 45). Policy v3 narrows §5 for a smaller queue (§5.1).
- **ALLOWED means no written rule applies.** The agent does not block on style or hunches,
  only on what the policy defines (§2).
- **Escalation drives cost.** Tier 2 costs ≈ 30× tier 1 per call. Going from 38% to 14%
  escalation cut the cost per posting by ≈ 60% (§6).

### Against the dataset label (secondary)

The 400 are 100 fraudulent and 300 legitimate postings by the dataset's own label (fraud is
enriched on purpose; the full dataset has 4.8%). **That label is not the policy:** it says
whether a posting was fraud, not whether it breaks a written section. In the earlier run, 29
of the 56 frauds labeled ALLOWED break no written rule. So recall against it is capped by what
the policy covers, and these numbers answer a different question: how close policy
enforcement comes to "was this fraud?". NEEDS_REVIEW is scored two ways: *strict* counts only
VIOLATING as a fraud call (what the system blocks by itself), *flagged* also counts
NEEDS_REVIEW (blocked or seen by an analyst).

| | **code in this repo** (§1.1) | earlier prompt (§1) |
|---|---|---|
| strict precision / recall / F1 | **0.96 / 0.22 / 0.36** | 0.95 / 0.19 / 0.32 |
| flagged precision / recall / F1 | **0.45 / 0.73 / 0.56** | 0.68 / 0.44 / 0.53 |
| frauds labeled ALLOWED (of 100) | **27** | 56 |
| legitimate postings blocked (of 300) | **1** (3174, §2) | 1 |
| review rate | **35%** | 11% |

Strict precision is 22 of 23 VIOLATING calls: 0.96, 95% interval 0.79–0.99. Flagged recall
0.73 is [0.64–0.81] over 100 frauds. The **Evaluation** page shows the same table below the
policy metrics.

## How far to trust these numbers

- **Added after these runs, with no effect on them:** input guards (empty postings,
  oversized fields, text addressed to the AI), the rule that a failed second opinion turns an
  unconfirmed ALLOWED into NEEDS_REVIEW, and analyst agree / overturn. The guards trip on none
  of the 17,880 dataset postings, and neither run had a tier-2 failure (checked in the traces),
  so every number here stands.
- **No API key was used for the runs.** Every model call went through the local `claude`
  CLI (`LLM_PROVIDER=claude_cli`): same models, prompt, schema and verification as the API
  path. **Decisions are representative. Cost and latency are estimates** (§6). Cost is
  computed from measured token counts at API list prices.
- **One real API call was made** (Haiku 5.5, from the UI): structured output parsed, 0 quotes
  rejected, 3.7 s, $0.00045. It wrote 1,980 tokens to the prompt cache, so the policy prompt
  is long enough to be cached.
- **Why there are two runs.** Reading the first 94 decisions of the earlier run showed the
  model declining §5 when the company profile was empty, although §5 names exactly that
  condition (§3). The fix is generic wording (no test-set text, no section ids), developed and
  checked on development postings only (§3.2). Both runs are reported.
- The earlier run is what the UI shows as v1 after `docker compose up` (it is loaded from
  `data/seed/seed.json.gz`; raw results in `data/eval/main-v1.json`). The current-code run is
  `v1@current` (`data/eval/current-v1_current.json`).

## 1. The earlier run: 400 postings, policy v1, first prompt

| label | postings | sections |
|---|---|---|
| **VIOLATING** | 20 | §4 + §5: 9 · §2 + §5: 4 · §2 + §4 + §5: 4 · §1 + §4 + §5: 1 · §3 + §5: 1 · §1 + §5: 1 |
| **NEEDS_REVIEW** | 45 | §5 alone |
| **ALLOWED** | 335 | none |

- Sections cited: §5 on 65 postings, §4 on 14, §2 on 8, §1 on 2, §3 on 1.
- Escalation: 151 of 400 (37.8%) reached tier 2.

### 1.1 The code in this repo

Same 400 postings, same models (Haiku 5.5 → Opus 5.5 via the CLI), stored under `v1@current`.

| label | postings | section combinations |
|---|---|---|
| **VIOLATING** | 23 | §4 + §5: 11 · §2 + §5: 7 · §2 + §4 + §5: 2 · §1 + §4 + §5: 1 · §3 + §5: 1 · §1 + §5: 1 |
| **NEEDS_REVIEW** | 140 | §5 alone |
| **ALLOWED** | 237 | none |

| | earlier prompt | **code in this repo** |
|---|---|---|
| sections cited: §5 · §4 · §2 · §1 · §3 | 65 · 14 · 8 · 2 · 1 | **163 · 14 · 9 · 2 · 1** |
| review rate | 11% | **35%** |
| escalated to tier 2 | 38% | **14%** |
| cost / 1k (CLI token counts) | $8.55 | **$3.36** |
| latency p50 / p95 | 5.7 s / 17.4 s | **5.9 s / 14.3 s** |

The change between the runs is §5: the current prompt applies it wherever its condition holds,
so §5 is cited on 163 postings instead of 65. §4, §1 and §3 are cited exactly as before, §2
once more.
Escalation, and with it cost, fell by ≈ 60%.

## 2. How the policy is applied: cases

**Blocks, with their evidence.**
- **3191** VIOLATING §4 + §5. Quotes: *"earn up to $2500 and more per week"*, *"You do NOT need
  any special skills to get started"*, and no identifiable employer.
- **3174** VIOLATING §1 + §4 + §5. Quotes: *"starting your own business requires capital
  investment both initially and on an ongoing basis"* and *"Serious income goal of $100k plus
  p.a"* for 15–20 h/week. §1 forbids requiring payment to join.

**Allowed, because no written rule applies.**
- **17761** "Payroll Clerk" with a detailed company profile and plausible pay (both runs). No
  section of v1 covers impersonation or cloned listings; a new section would (see below).
- **3612** "Account Sales Managers $80-$130,000/yr", commission-only. In the earlier run the
  model applied the policy's own edge case (commission-only roles are allowed when the pay
  structure is stated plainly); the current prompt routes it to review under §5.

**Routed to review by §5.**
- **177 / 569** "English Teacher Abroad": the employer is never named and the profile is one
  generic line.
- **863** a staffing-agency posting for an unnamed "Leading global retailer".

**The prompt fix, on one case.** **2617** "Developer and Database Administrator": empty profile,
no logo, employer never named. Under the first prompt the model read the edge case "missing
fields are weak signals and must not be the sole basis for VIOLATING" as "not enough for §5",
but that edge case only limits VIOLATING. The current prompt routes it to review under §5, as
the policy says (§3).

**Where the policy could grow.** Some postings are copied word for word under other titles and
cities ("Aker Solutions", "AECOM", "Expro" listings). No section of v1 covers a cloned or
impersonated listing, so they are allowed as written. Covering them is a policy section plus a
tool that finds the original listing; one posting alone does not show it.

**A reading for analysts to settle.** **258** (development set, VIOLATING §2 + §5) asks
applicants to *"Make a quick video and post it to YouTube"*. A literal reading of §2 supports
it; the quote is real. Agree / overturn on the case records the analyst's call.

## 3. The prompt fix

### 3.1 Change

The policy was **not** changed. One instruction was added to the prompt: weak
signal guidance limits VIOLATING; when a review-only section names a condition
that the facts block confirms (for example "no company profile"), report it,
unless the posting itself satisfies the section (for example, it names and
describes the employer). Also `ESCALATE_BELOW_CONFIDENCE` was lowered from 0.7
to 0.6: Haiku reports 0.5–0.6 even on clear ALLOWED cases, which sent a third of
traffic to Opus without changing outcomes.

The exact change, in step 4 of the instructions (`core/labeler/labeling/prompt.py`).
`ESCALATE_BELOW_CONFIDENCE` went from 0.7 to 0.6 at the same time.

```diff
 4. Missing information is not a quote. If a section rests on something being
    absent (for example an empty company profile), list it under `facts` using
    only the names given in the facts block. Facts alone are weak evidence and can
    never be the sole basis for a section whose effect is VIOLATING.
+   They are exactly what review-only sections are for: when a review-only
+   section names a condition (for example "no company profile") and the facts
+   block shows it is true, report that section with the fact, unless the
+   posting text itself clearly satisfies what the section asks for (for
+   example, it names and describes the employer). Policy guidance that missing
+   fields are "weak signals" limits what can be VIOLATING; it does not stop a
+   review-only section from matching.
 5. Hints come from simple pattern matching and are often wrong. Use them to know
```

**Later rewording.** The two quoted examples above paraphrased §5 inside the fixed
instructions, which breaks the rule that nothing section-specific lives in the prompt. They
were replaced by generic wording ("when a review-only section's text names a condition that
the facts block shows is true…"). §3.2 was measured with the first wording; §1.1 runs the
generic one.

### 3.2 Checked on dev postings only

**A. The same 16 dev postings before and after:**

| | before | after |
|---|---|---|
| escalated to tier 2 | 31% | **6%** |
| cost / 1k (CLI token counts × list price, §6) | $6.72 | **$1.94** |
| latency p50 / p95 | 6.4 s / 14.7 s | **5.5 s / 7.6 s** |

**B. 10 dev postings with an empty company profile, after:** §5 was applied on 9 of 10. The
tenth (**7144**) names and describes the employer ("Expro") in the description, so ALLOWED is
correct under the instruction.

Postings without a company profile now go to review, as §5 says. A smaller queue is a policy
decision (narrow §5), made through a new version (§5.1).

## 4. Evidence: does Haiku fabricate quotes, and does verification work?

Counted from the stored traces of both 400-posting runs (`data/objects/traces/<version>/`,
loaded into the object store by `docker compose up`):

| | earlier run (§1): Haiku | Opus | **code in this repo (§1.1): Haiku** | **Opus** |
|---|---|---|---|---|
| quotes returned | 307 | 76 | **381** | **13** |
| **rejected** | **8** | 0 | **8** | **0** |
| of which invented posting text | 0 | 0 | **0** | **0** |

All 16 rejections are on §5, so none changed a label (§5 also rests on the absence facts).

**Earlier run, 8 rejections:**

| count | quote | what happened |
|---|---|---|
| 5 | *"location: GB, LND, London"* and similar | The model quoted the prompt's **metadata line**, label included. Not posting text: correctly rejected (and a location proves nothing for §5). |
| 2 | *"[company_profile]\n(empty)"*, *"[title]\nGraphic Designer"* | The model quoted the **prompt's own scaffolding**. Correctly rejected: exactly what the check is for. |
| 1 | *"We help teachers get safe & secure jobs abroad"* | The posting says `&amp;` (EMSCAD keeps HTML entities). **False rejection.** Fixed after the run: the matcher now decodes entities, and the stored span still covers the original `&amp;`. |

**Current code, 8 rejections:** all eight are the metadata line (*"location: US, VA, Virginia
Beach"* and similar). The scaffolding quotes and the entity false rejection did not recur.

So across 777 quotes, **no invented posting content was observed**. Every rejection was the
model quoting its own prompt, which is exactly what the check exists to catch. Whether those
count as "fabrications" is a matter of naming: they are not posting text, and they never reach
a label.

**v1 and `accepts_facts`.** `policies/v1.yaml` is kept as first published, so it
has no `accepts_facts`, and under v1 §5 may rest on any absence fact. That is the
behaviour of versions written before the field existed. Two rules still hold under v1:
VIOLATING always needs a verified quote, and §5 is the only review-only section, so facts
alone can never combine into a block. In the `v1@current` run, 162 of the 163 decisions
with §5 have a §5 quote. The remaining one rests on `no_company_profile`. None rests on
another fact such as `no_company_logo` or `no_salary`. Restricting §5 to
`no_company_profile` is a new version, not an edit to v1; v2 and v3 already do it.

## 5. Policy v2 demo

`policies/v2.yaml` adds §6 *Vague home-based clerical work* (review only) and
one edge case ("office-based or clearly specified clerical roles at a named
employer do not match §6"). No code changes: the new section reaches the
prompt, the schema's section enum, the label aggregation and the UI (filter,
color, policy diff) from the document.

**Where §6 applies: 12 dev postings** picked by title to exercise it (6 home-based clerical
postings, 6 office clerical jobs at named employers), same code and prompt, v1 vs v2
(`make demo-v2-dev`):

| | v1 | v2 |
|---|---|---|
| 1408 *Data Entry Admin/Clerical Positions - Work From Home* | NEEDS_REVIEW §5 | **VIOLATING §5+§6** |
| 17584 *Online Typist From Home* | NEEDS_REVIEW §5 | **VIOLATING §5+§6** |
| 17573 *Home Based Typist* | VIOLATING §2 §4 §5 | VIOLATING §2 §4 §5 **§6** |
| 17657 *Data Entry / Typist Work At Home* | VIOLATING §4 §5 | VIOLATING §4 §5 **§6** |
| 17537, 17630 *Data Entry* | NEEDS_REVIEW §5 | NEEDS_REVIEW §5 (no home-based claim: §6 not cited) |
| 6 office clerical roles at named employers | ALLOWED | ALLOWED (the new edge case holds) |

Two postings move from review to VIOLATING, which is the policy's own
combination rule at work (§5 "unless combined with another section"), and
none of the 6 office clerical jobs at named employers is touched: the new edge case holds. §6 evidence is a verbatim
quote, e.g. *"by performing online data entry work, and other types of work
from home duties"* (17584).

**On the eval set** (20-posting shadow run, `make demo-v2`), §6 matched
nothing: none of those 20 is a vague home-based clerical job. Four postings
still changed label between the v1 and v2 runs, all on §5 (2278 and 177:
§5 → ALLOWED; 1663 and 2740: ALLOWED → §5). These flips are model
inconsistency, not the policy change, which is why DESIGN.md §5 adds a
consistency metric: a shadow-run diff must be read against a same-policy rerun
baseline.

**Re-labeling existing items.** Labels are keyed by `(job_id,
policy_version)`, so v2 never overwrites v1. `POST /api/policies/v2/relabel`
with scope `recent` (last N days), `previous` (everything labeled under the
published version) or `eval` runs as a background job; in production it goes
through batch inference and only re-labels postings the change can affect
(DESIGN.md §2).

Process note: while choosing what v2 should add, phrase counts were printed on
the eval set once. The choice was made from dev-set statistics, but because the
eval set was looked at, v2's eval numbers are not a clean held-out estimate. v2 is
a behaviour demo, not a quality claim.

### 5.1 v3: a policy fix found on eval, checked on dev

§1.1 showed that §5, applied as written, routes 140 of the 400 postings to review. `policies/v3.yaml` narrows §5 to postings that never say who is hiring. Two
rules keep the eval set clean:
- **The text is a general rule.** It was not fitted to individual eval cases.
- **Demonstration and measurement use development postings.** The six demo
  postings (README) are dev ids picked from the teacher's v1 labels, with no model
  call: postings with no profile that name the employer, and postings with no profile that
  do not.

A v3 run on the eval set would not be held out. The v3 numbers belong to a dev
sample of no-profile postings: those that name the employer leave review, those that do not
stay. That run is not done yet.

## 6. Cost and latency

Measured via the CLI, so both are pessimistic. Full eval run (400 postings,
first prompt, concurrency 6 on a laptop):

| | tier 1 (Haiku, 400 calls) | tier 2 (Opus, 151 calls) |
|---|---|---|
| output tokens / call (incl. thinking) | 824 | 583 |
| latency / call (mean) | 5.7 s | 7.5 s |
| CLI-reported tokens billed at list price, per call | $0.00066 | $0.0209 |

- **Latency per posting:** p50 5.7 s, p95 17.4 s, max 24.7 s. All under the 60 s
  target, with process start-up (≈1 s per call) included. Escalated postings
  are the p95.
- **Cost as measured: $8.55 per 1,000 postings** ($3.42 for the 400). This
  overstates API cost: the CLI writes ≈1.8k tokens to cache on every call
  (its own wrapper plus the posting, with a 1-hour TTL) where the API would
  read the cached system prompt (1,980 tokens on Haiku 5.5's tokenizer, measured on the one
  API call) and bill the posting (≈300–800 tokens) as plain input.
- **API estimate from the measured output tokens:** tier 1 ≈ $0.50 per 1,000
  calls; tier 2 ≈ $15 per 1,000 calls. At this run's 37.8% escalation that is
  **≈ $6.2 per 1,000 postings**. At the current code's 13.5% escalation on the same
  eval set (§1.1), it is **≈ $2.55**, or ≈ $1.53 with Sonnet as tier 2. The ≈ 6% seen
  on a 16-posting dev sample (§3.2) gives ≈ $1.4, for reference. Escalation is the cost lever, as DESIGN.md
  §3 predicts. Opus is ≈30× Haiku per call.

## 7. Reproduce

```bash
make eval                                   # full 400, published policy, resumable
LLM_PROVIDER=claude_cli make eval           # same, without an API key
make demo-v2                                # draft v2 → shadow-run on eval → compare → publish
make demo-v2-dev                            # v1 vs v2 on 12 dev postings where §6 applies
uv run python -m scripts.run_eval --version v1 --tag current --provider claude_cli   # §1.1 current code
```

The appendix needs Apple silicon (MLX) and runs on the host, not in Docker. It uses the committed
adapter, so no teacher run or training is needed. Use two terminals:

```bash
make slm-serve    # terminal 1: downloads the 4-bit base once (~1 GB), then serves :8090
make slm-eval     # terminal 2: waits until :8090 answers, then labels the 400
```

Raw outputs: `data/eval/` (ids, per-run JSON); every decision with its trace is
in the UI.

---

# Appendix: distilled small model, kept as an option

A Qwen2.5-1.5B-Instruct student (4-bit, LoRA adapter, 5.3M trainable parameters) was trained
with MLX on Claude's **verified** findings for 1,000 development postings (never the eval
set). It reads the same prompt and posting as Claude, and its output goes through the same
verification and label rule. The adapter is committed (`data/distill/adapter/`, 21 MB).

On the 400 eval postings, the student alone (`make slm-serve` + `make slm-eval`):

| | Qwen2.5-1.5B base | **Qwen2.5-1.5B + LoRA (distilled)** | Haiku → Opus, current code (§1.1) |
|---|---|---|---|
| quotes rejected by verification | **60%** (611 of 1,013) | **4%** (11 of 261) | 2% (8 of 394) |
| review rate | 55% | **32%** | 35% |
| invalid JSON (→ NEEDS_REVIEW, tier=failed) | 2 | 2 | 0 |
| latency p50 / p95 | 1.5 s / 2.5 s | **1.6 s / 3.1 s** | 5.9 s / 14.3 s |
| cost per 1,000 postings | 0 (own hardware) | **0** (own hardware) | ≈ $2.55 at API prices |

- **Verification is what makes a small model safe to try.** The base model's quotes were
  rejected 60% of the time; verification threw them out, so it falls back to NEEDS_REVIEW
  instead of blocking on invented evidence. After distillation, rejections fall to 4%.
- **Kept as an option.** It learned policy v1 from v1 examples, so each policy change needs a
  new teacher run and retraining (≈ 75 min). Tier 1 = student and tier 2 = Claude is one
  Settings change.
