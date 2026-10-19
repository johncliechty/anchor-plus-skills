# Connecting mail and calendar

Three accounts you named:

| Account | What it is |
|---|---|
| Gmail | your personal Google account |
| Outlook · School | the school tenant |
| Outlook · Work | the work tenant |

You never send me a password. You create two “app registrations” (Google and Microsoft). Then you sign in three times in a browser that pops from Anchor.

---

## Google (Gmail + Google Calendar) — do this yourself, then tell me “done”

Use Chrome, already signed in as **that Gmail**.

### A. Open Google Cloud

1. Go to: https://console.cloud.google.com
2. If Google asks you to pick an account, pick that Gmail.
3. If it asks to agree to terms, agree.

### B. Make a project

1. At the top, click the project picker (it may say “Select a project”).
2. Click **New project**.
3. Name: `Anchor`
4. Click **Create**. Wait until the notifications bell says it is ready, then select **Anchor**.

### C. Turn on the two APIs

1. In the search bar at the top, type `Google Calendar API` → open it → **Enable**.
2. Search `Gmail API` → open it → **Enable**.

### D. Consent screen (Testing — only you)

1. Search `OAuth consent screen` → open **Google Auth platform** / **OAuth consent**.
2. User type: **External** → Create.
3. App name: `Anchor`. User support email: your Gmail. Developer contact: your Gmail. Save.
4. Scopes: add these four (or skip and we add them in code; adding here avoids a warning):
   - `.../auth/calendar.readonly`
   - `.../auth/calendar.events`
   - `.../auth/gmail.readonly`
   - `.../auth/gmail.send`
5. **Test users** → **Add users** → type your Gmail → Save.
6. Publishing status stays **Testing**. Do not click Publish. Testing is correct for a private tool.

### E. Desktop client ID (this is what I need)

1. Search `Credentials` → **Create credentials** → **OAuth client ID**.
2. Application type: **Desktop app** (not Web).
3. Name: `Anchor desktop`.
4. Create.
5. You will see a **Client ID** that looks like `xxxxx.apps.googleusercontent.com`.
6. Click **Download JSON**.

**Send me that JSON file** (or paste the Client ID). Put it anywhere convenient, e.g. Desktop. It is not a password. I will store it next to encrypted tokens, not in git.

Then, when the connector is built, you click **Connect Google** in Anchor, a Google window opens, you approve, done.

---

## Microsoft (Outlook School + Outlook Work)

Same Azure app, **two sign-ins** (two people as far as Microsoft is concerned).

### A. Register the app

1. Go to: https://portal.azure.com
2. Search **App registrations** → **New registration**.
3. Name: `Anchor`.
4. Supported account types: **Accounts in any organizational directory and personal Microsoft accounts**.
5. Redirect URI: platform **Public client/native (mobile & desktop)**, URI `http://127.0.0.1`
6. Register.

### B. Permissions

1. **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated**.
2. Add: `Calendars.Read`, `Calendars.ReadWrite`, `Mail.Read`, `Mail.Send`, `offline_access`, `openid`, `User.Read`.
3. **Authentication** → treat the app as a **public client** (yes). No secret.

### C. What I need

The **Application (client) ID** on the Overview page (a GUID). Email or paste that. Not a password.

### D. Two logins, later

When Connect exists in Anchor:

1. **Connect Outlook School** → sign in with the school account. If the school blocks it, their IT admin must allow this app; we cannot bypass that.
2. **Connect Outlook Work** → sign in with the work Outlook.

---

## After both IDs exist, I wire

- One Google token (mail + calendar).
- Two Microsoft tokens (School, Work).
- Poll every few minutes into a local cache. The dashboard never calls Google/Microsoft while drawing the page.
- Writes: only an Anchor-owned calendar on each provider; mail replies from the account that received the message.

I do not need your Gmail or Outlook passwords. I need the Google download JSON (or client ID) and the Azure application ID, then you at the machine for the three consent windows.
