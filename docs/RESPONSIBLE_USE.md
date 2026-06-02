# Responsible use — read before you upload

This pipeline can publish to YouTube on your behalf. That power comes with real
legal and platform-policy responsibilities. This document is guidance, **not
legal advice** — when in doubt, consult a lawyer and read YouTube's own policies.

## The golden rule

**Only use source material you have the right to use.** That means one of:

1. **Content you created / own** — your own recordings, footage, narration.
2. **Content you've licensed** — you bought or were granted a license that
   permits this use.
3. **Royalty-free / Creative Commons** — stock or CC-licensed material, used
   within its license terms and **with attribution where required**.

Re-uploading someone else's video — even a clip — without permission can lead to:

- **Copyright strikes** (3 strikes = channel termination),
- **Content ID claims** (demonetization, blocking),
- **Legal liability**.

"It's only a short clip" and "I credited them" are **not** legal defenses on
their own. Fair use / fair dealing is narrow, fact-specific, and decided by
courts — not by a checkbox in a script.

## The rights gate

The `clip` command refuses to run without `--i-own-rights`. That flag is your
affirmation that the source falls into one of the three categories above. It is
intentionally a manual, per-source step. **Don't automate around it for content
you don't have rights to.**

```bash
# Will refuse:
python pipeline.py clip --input someone_elses_video.mp4

# Runs only after you affirm rights:
python pipeline.py clip --input my_own_recording.mp4 --i-own-rights
```

## Music & third-party assets

- Use only royalty-free / licensed music. Background music from songs you don't
  have rights to will get Content ID claims.
- Stock footage (Pexels/Pixabay) is royalty-free, but check each asset's license
  and attribution requirements.

## Draft-first by default

`upload.privacy` defaults to `private`. Keep it `private` or `unlisted` and
**review every video before making it public**:

- Is the information accurate? (AI-generated scripts can be wrong.)
- Does it comply with YouTube's policies (misinformation, spam, etc.)?
- Are all assets properly licensed?

Setting `upload.privacy: public` publishes with no human review. The pipeline
warns you when you do this. Don't, unless you fully trust the output.

## YouTube policies to know

- **Spam & deceptive practices** — mass-producing low-effort or duplicative
  uploads can violate the Repetitive/Spam content policy and the YouTube
  Partner Program rules.
- **Reused/inauthentic content** — channels built on others' content without
  transformation/commentary may not be eligible for monetization.
- **AI disclosure** — YouTube requires disclosing realistic
  altered/synthetic content in some cases. Use the "altered content" disclosure
  where applicable.
- **Automation & API terms** — comply with the YouTube API Services Terms of
  Service and Developer Policies.

## Disclosure

These videos are machine-assisted. Consider noting that in your descriptions
(the default config footer does). Be honest with your audience.

## Bottom line

Automation scales whatever you put into it — including mistakes. Own your
sources, review your output, keep uploads private until you've checked them, and
follow YouTube's policies. The tool gives you leverage; the responsibility is
yours.
