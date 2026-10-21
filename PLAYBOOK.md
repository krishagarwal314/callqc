# Prompt-engineering playbook for Vaani

Patterns that measurably helped or hurt, each backed by an A/B run in [RESULTS.md](RESULTS.md)
(`make ab`, 30 simulated calls per persona per variant, seed 0, control `v1_baseline`).
Persona-level p-values are Fisher exact tests, not multiple-comparison corrected; variant-level ones are Holm-corrected.

> All results are from simulated callers whose hidden conditions encode these hypotheses. Treat each pattern
> as "the harness can detect this effect", and confirm it on a live holdout before you rely on the size of the lift.

## Helped

### 1. Acknowledge the objection explicitly before countering it (`v2_ack_objection`)
- **Change:** "That's a completely fair concern, and you're right to ask." before the rate/loan/trust answer,
  replacing a generic "I understand".
- **Result:** overall conversion 20.0% → 30.4% (+10.4 pp, 95% CI +2.5 to +17.9, Holm p = 0.023).
  Price-sensitive persona +50 pp (p = 0.0001), Hinglish persona +33 pp (p = 0.018).
  Objection-handling score 1.18 → 1.81, tone 1.25 → 1.75.
- **Why:** callers who object want to feel heard first. "I understand" reads as a script; naming the concern doesn't.
- **Guarded by:** regression case `rate-objection-acknowledged`.

### 2. Say the rate is indicative and subject to final approval (`v3_indicative`)
- **Change:** one sentence after every quoted rate/EMI.
- **Result:** conversion +12.9 pp (95% CI +5.0 to +20.8, Holm p = 0.006), driven by the distrustful persona
  (+63 pp, p < 0.0001). Mandatory-disclosures score 1.11 → 1.92; QC fail rate 5.0% → 2.5%.
- **Why:** it's a compliance requirement and it builds trust. Transparency reads as legitimacy to a caller
  who expects a scam.
- **Guarded by:** `offer-invented-rate`, `existing-loan-invented-saving`, `amount-correction-readback`.

### 3. Changes stack (`v5_combined`, now production)
- **Result:** conversion 20.0% → 43.3% (+23.3 pp, 95% CI +15.0 to +31.3, Holm p < 0.00001), rubric 11.77 → 14.40 /16,
  QC fail 5.0% → 0.8%.

## Neutral

### 4. A shorter consent line (`v4_concise`)
- **Change:** consent line cut from ~35 to ~17 words, keeping name, lender, purpose and the recording notice.
- **Result:** **no conversion lift** (+0.0 pp, 95% CI −7.5 to +7.1, Holm p = 1.0). It did raise the busy persona's
  callback rate (applied-or-callback +57 pp, p < 0.0001), and the rubric total change (+0.22) was not significant.
- **Lesson:** brevity saves calls that would otherwise drop, but it doesn't close sales. Keep it for the
  callback funnel and don't claim it as a conversion win.

## Hurt

### 5. Urgency, invented figures, no disclosures (`v0_sanity_bad`, never shipped)
- **Result:** conversion 3.3% (−16.7 pp), rubric 5.91 /16, QC fail rate 100%. Every call scored 0 on
  mandatory disclosures, and the invented "9.99 percent" was caught as a hallucinated figure in 167 of the 180 calls that reached the offer.
- **Lesson:** pressure doesn't even work on simulated callers, and every call fails QC. The variant
  stays in the repo as the CI harness self-test.

## Found by QC, not fixable by prompt
- **Barge-in during consent drops the recording notice.** When the interrupter persona cuts the consent line,
  Vaani never repeats the part that wasn't spoken. This is behind most of the baseline QC failures. It is tracked
  as the known-issue regression `consent-barge-in-disclosure`; the fix belongs in Vaani's engine (re-deliver
  unspoken mandatory text).
