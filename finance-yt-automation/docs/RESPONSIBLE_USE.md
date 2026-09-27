# Responsible use for a finance channel

This is guidance, **not legal advice**. Rules differ by country. In the US,
the SEC, FINRA, and FTC rules may apply. In the UK, the FCA financial
promotions regime may apply. If you monetise heavily or promote financial
products, talk to a professional.

## What the pipeline enforces

1. **Education, not advice.** Prompts forbid personalised advice and named
   buy/sell recommendations. The scanner flags phrases like "you should buy TSLA".
2. **No promised returns.** "Guaranteed", "risk-free", and "can't lose" are
   critical findings. Long-run returns must be framed as historical or assumed.
3. **Numbers from code.** Chart values come from `finance_math.py`. The review
   pass corrects narration to match.
4. **A render gate.** An unresolved critical finding blocks the render
   (`compliance.block_on_violation`).
5. **Disclosures.** A spoken disclaimer, a description disclaimer, an AI
   disclosure, and YouTube's synthetic-media flag are all on by default.
6. **Private drafts.** Uploads default to `private`.

## What you still have to do

- **Check the fact-check list** in `python pipeline.py jobs` before publishing.
  Year-specific figures such as tax brackets and contribution limits go stale.
- **Watch every video.** AI scripts can be subtly wrong even after review.
- **Disclose affiliate links** by setting `compliance.affiliate_disclosure`.
- **Don't imply credentials** you don't hold, such as "as a financial advisor".
- **Avoid spam patterns.** Mass-producing near-identical videos can breach
  YouTube's repetitive-content and Partner Program policies. Vary topics and
  formats, and add real insight.
- **Use licensed assets only.** Stock footage has its own licence terms, and
  background music must be royalty-free or licensed.
- **Higgsfield output** must follow Higgsfield's terms. Keep YouTube's
  synthetic-media disclosure on for realistic AI footage.

## Bottom line

Automation scales whatever goes into it, including mistakes. Keep uploads
private until you have reviewed them.
