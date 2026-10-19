# Anchor

**Important Notice:** The instructions below are a convenience copy of the out-of-band trust ceremony payload. This document states verbatim it is normatively void and the out-of-band message governs.

## First-Contact Trust Ceremony Template

1. **Git Provenance Step**:
   Ensure you have a clean, trusted `git` binary and preinstalled `ssh-keygen`.

2. **Allowed-Signers Pinning**:
   Pin the public key provided in the out-of-band message:
   ```bash
   mkdir -p .anchor
   echo "⟨ALLOWED_SIGNERS_PUBKEY⟩" > .anchor/allowed_signers
   git config gpg.ssh.allowedSignersFile .anchor/allowed_signers
   ```

3. **Clone + tag -v Verification**:
   Clone the repository and verify the SSH signature on the release tag:
   ```bash
   git clone ⟨REPO_URL⟩ anchor
   cd anchor
   git tag -v ⟨RELEASE_TAG⟩
   ```

4. **Commit-Hash Confirmation**:
   Verify the commit hash against the out-of-band value: ⟨COMMIT_HASH⟩.
   ```bash
   git rev-parse HEAD
   ```

5. **Stop-and-Delete**:
   If the signature verification fails, or the commit hash does not match, STOP immediately and delete the cloned repository. Do not execute any code.
