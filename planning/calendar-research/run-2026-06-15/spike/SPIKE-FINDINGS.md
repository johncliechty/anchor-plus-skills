# Auth Spike — Findings (2026-06-16)

Goal: upgrade the riskiest research feasibility claims from CORROBORATED (docs) → OBSERVED (ran on this machine), before committing the Crucible plan.

## OBSERVED on this machine (ran live, `.\john`, Python 3.13.13, OpenSSL 3.0.19)
| # | Claim under test | Result |
|---|---|---|
| 1 | Python stdlib (`ssl`+`urllib`) can TLS-handshake + GET Google's & Microsoft's REAL OAuth endpoints | ✅ **TLS 1.3 / AES-256-GCM to BOTH**; discovery docs HTTP 200; live auth+token endpoints parsed (`probe_endpoints.py`) |
| 2 | PKCE S256 verifier/challenge via stdlib `secrets`+`hashlib`+`base64` | ✅ generates valid 86-char verifier + S256 challenge |
| 3 | A transient loopback `http.server` on an ephemeral port catches the `?code=&state=` redirect and never collides with 8777 | ✅ port 51035, captured `code`, **state-CSRF echo validated** (`pkce_loopback_spike.py --mock`) |
| 4 | Token-at-rest via DPAPI through pure `ctypes` (no pywin32), user scope | ✅ wrap→unwrap round-trips; ciphertext≠plaintext (278 bytes for a short secret) |

## Useful quirk caught (would have bitten mid-build)
- **Microsoft's `common` v2.0 discovery doc does NOT advertise `code_challenge_methods_supported`** (the probe shows `S256 supported: False`). Microsoft Graph **does** support PKCE-S256 — the field is simply absent from the discovery metadata. **Build rule: do NOT gate PKCE on the Microsoft discovery field**; assume S256 for Microsoft. (Google advertises it correctly = True.)

## STILL PENDING — needs John's accounts + wall-clock (cannot be done headlessly)
These require app registrations John creates, an interactive browser consent, and 8 days of elapsed time. The runnable script + steps are in `RUNBOOK.md`.
- ⏳ **Real consent + token exchange + events list** against John's actual Google + Microsoft accounts (`pkce_loopback_spike.py --provider <p> --client-id <id>`).
- ⏳ **Durable-refresh proof** — the single riskiest claim: that a Google OAuth app in **Production** (but unverified, personal use) keeps a refresh token alive past the 7-day Testing-mode cutoff. Run `--refresh-check` >7 days after the consent (`RUNBOOK.md` step 5).
- ⏳ **MSA vs work/school** — which Microsoft account type John connects (changes refresh-token reliability + `/common` vs `/consumers` authority).

## Net
The infrastructure-level feasibility (TLS, PKCE, loopback catcher, DPAPI) is now **OBSERVED, not assumed** — no surprises. The remaining unknowns are policy/account-shaped (consent UX, Google Production durable refresh, MS account type), all addressed by the runbook. **Safe to proceed to Crucible**; the durable-refresh check runs in parallel with planning and only gates the actual Phase-with-write-back, not the planning itself.
