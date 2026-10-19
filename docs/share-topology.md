# Dual-audience topology ops

Machine + human ops note for Shareable Anchor + Skills (W8).

## Source of truth

- Private pattern: `*-dev`
- Public role: **one-way-release-mirror** (one-way private → public).
- Public write: **bot-only**; human hand-edit forbidden.
- Allowed bot identities: github-actions[bot], mirror-bot, release-bot, share-publish-bot

## Feedback intake is separate from product write access

See [`share-feedback-intake.md`](share-feedback-intake.md). Sanitized friction is **not** a code contribution and never uses product-main write credentials.

## Mirror lag

Run `share_topology.check_mirror_lag(private_tags, public_publishes)`. Any private release tag without a matching public publish raises an alert; consumers remain pinned to the last public release artifact (never floating main).

## Policy snapshot

```
private_sot=*-dev
public_direction=private-to-public-one-way
bot_only_write=True
consumer_pin=release_artifacts
feedback_is_code=False
```

## Cadence checklist

- [ ] Freeze skill sources at agreed tags before public publish
- [ ] Release captain checklist green (see CAPTAIN_CHECKLIST_ITEMS)
- [ ] Publish private → public via bot only (no human public hand-edit)
- [ ] Run check_mirror_lag; alert if private tag lacks public publish
- [ ] Document consumer pin to release artifacts, not floating main
- [ ] SOURCES.md / skills_pin stamp matches published artifacts
