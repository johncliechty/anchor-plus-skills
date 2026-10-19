"""
Auth spike — PART 1 (no accounts needed): prove Python stdlib can TLS-handshake and
talk to Google's and Microsoft's REAL OAuth/OIDC endpoints, and that PKCE crypto works.

This converts the research finding "stdlib ssl/urllib negotiates fine with the providers"
from CORROBORATED (docs) -> OBSERVED (ran on this machine). Pure stdlib, no deps.

Run:  python probe_endpoints.py
"""
import ssl, json, base64, hashlib, secrets, socket, urllib.request

DISCOVERY = {
    "Google": "https://accounts.google.com/.well-known/openid-configuration",
    "Microsoft (common)": "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
}

def tls_version(host, port=443):
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=10) as raw:
        with ctx.wrap_socket(raw, server_hostname=host) as s:
            return s.version(), s.cipher()[0]

def fetch_json(url):
    # default context => system trust store + TLS1.2/1.3 + SNI, exactly what the product would use
    req = urllib.request.Request(url, headers={"User-Agent": "anchor-calendar-spike/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status, json.loads(r.read().decode("utf-8"))

def pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge

def main():
    print("=== PKCE crypto (stdlib secrets+hashlib+base64) ===")
    v, c = pkce_pair()
    print(f"  code_verifier  ({len(v)} chars): {v[:24]}...")
    print(f"  code_challenge (S256)        : {c}")
    print(f"  OK: verifier/challenge generated\n")

    all_ok = True
    for name, url in DISCOVERY.items():
        host = url.split("/")[2]
        print(f"=== {name} — {host} ===")
        try:
            ver, cipher = tls_version(host)
            print(f"  TLS: {ver}  cipher: {cipher}")
            status, doc = fetch_json(url)
            print(f"  GET discovery: HTTP {status}")
            print(f"  authorization_endpoint: {doc.get('authorization_endpoint')}")
            print(f"  token_endpoint        : {doc.get('token_endpoint')}")
            scopes = doc.get("scopes_supported", [])
            print(f"  S256 PKCE supported   : {'S256' in doc.get('code_challenge_methods_supported', [])}")
            print(f"  OK: real endpoint reachable over pure-stdlib TLS\n")
        except Exception as e:
            all_ok = False
            print(f"  FAIL: {type(e).__name__}: {e}\n")

    print("=== VERDICT ===")
    print("  stdlib ssl+urllib reached BOTH providers' live OAuth endpoints"
          if all_ok else "  One or more endpoints unreachable (see FAIL above)")

if __name__ == "__main__":
    main()
