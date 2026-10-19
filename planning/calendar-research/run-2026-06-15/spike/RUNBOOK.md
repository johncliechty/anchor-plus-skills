# Auth Spike — Runbook (the parts that need your accounts)

~20 min of setup + a browser click, then one 30-second re-check 8+ days later. Pure stdlib — **no pip install needed for the spike.** All commands run from this `spike/` folder.

---

## Step 1 — Register a Google "Desktop app" (5 min)
1. https://console.cloud.google.com/ → create (or pick) a project.
2. **APIs & Services → Enable APIs** → enable **Google Calendar API**.
3. **APIs & Services → OAuth consent screen**: User type **External**; fill app name + your email. Add scope `.../auth/calendar`. Add yourself as a **Test user**.
   - ⚠️ Leave it in **Testing** for now to do the first consent. The durable-refresh test (Step 5) is exactly what tells us whether you must flip to **Production** to escape the 7-day token revoke — that's the finding we're proving.
4. **Credentials → Create credentials → OAuth client ID → Application type = Desktop app.** Copy the **Client ID** (no secret needed for the spike).

## Step 2 — Register an Azure / Microsoft public client (5 min)
1. https://entra.microsoft.com/ (or portal.azure.com → Microsoft Entra ID) → **App registrations → New registration.**
2. Supported account types: pick **"Accounts in any org directory and personal Microsoft accounts"** (so it works for both work and personal — this also answers the MSA-vs-work/school question).
3. **Redirect URI**: platform **"Mobile and desktop applications"**, value **`http://127.0.0.1`** (loopback; Azure allows the dynamic loopback port for public clients). Copy the **Application (client) ID**.
4. **Authentication → Advanced → Allow public client flows = Yes.**
5. **API permissions → Add → Microsoft Graph → Delegated → `Calendars.ReadWrite` + `offline_access`** → Add. (Personal-account consent happens at sign-in; no admin consent needed for delegated calendar.)

## Step 3 — Run the real Google flow
```
python pkce_loopback_spike.py --provider google --client-id <YOUR_GOOGLE_CLIENT_ID>
```
A browser opens → sign in → "Google hasn't verified this app" (expected; **Advanced → continue**) → allow. The console should print: token exchange OK, refresh_token=True, events list OK (N events), refresh token DPAPI-wrapped → `spike_token_google.bin`.

## Step 4 — Run the real Microsoft flow
```
python pkce_loopback_spike.py --provider microsoft --client-id <YOUR_AZURE_CLIENT_ID>
```
Same shape. Note which account you used (personal @outlook vs work/school) — tell me, it affects token reliability.

## Step 5 — The durable-refresh test (the important one) — **8+ days later**
Just leave it. On **2026-06-24 or later**, run:
```
python pkce_loopback_spike.py --provider google --refresh-check
```
- **`refresh redeemed: True`** → the Google app held a durable refresh token. ✅ The riskiest claim is OBSERVED-true.
- **An error / `invalid_grant`** → Testing-mode revoked it at day 7, confirming we MUST publish the OAuth app to **Production** (still unverified is fine for personal use). Either outcome is a clean, decisive answer — that's the point of the spike.
- (Optional) repeat with `--provider microsoft` to confirm MS rotation + survival.

## When you're done
Tell me the results (did consent work for both? did events list? day-8 refresh outcome? which MS account type?). I'll fold any surprises into the Crucible prompt before you run it. Delete `spike_token_*.bin` afterward (they're DPAPI-wrapped, but no reason to keep them).
