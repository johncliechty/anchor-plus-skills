import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
import sys

import paths as _paths
import foundry_integrity as _integrity

_logger = logging.getLogger("update_transaction")

def _git(repo, args):
    """Run git -C <repo> <args> and return (ok, stdout, stderr)."""
    cmd = ["git", "-C", str(repo)] + [str(a) for a in args]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            creationflags=_paths.NO_WINDOW
        )
    except OSError as exc:
        return False, "", f"Update command failed: {exc}"
    return proc.returncode == 0, proc.stdout or "", proc.stderr or ""

def _git_raise(repo, args):
    ok, out, err = _git(repo, args)
    if not ok:
        raise RuntimeError(f"Update command failed: {' '.join(args)} error: {err}")
    return out

class UpdateTransaction:
    def __init__(self, anchor_dir=None):
        if anchor_dir is None:
            override = os.environ.get("ANCHOR_UPDATE_TARGET")
            anchor_dir = override if override else _paths.CODE_DIR
        self.anchor_dir = Path(anchor_dir).resolve()
        self.config_root = self.anchor_dir / ".anchor"
        self.marker_file = self.config_root / "update_marker.json"
        
    def read_marker(self):
        if not self.marker_file.exists():
            return None
        return json.loads(self.marker_file.read_text(encoding="utf-8"))
        
    def write_marker(self, phase: int, data: dict):
        self.config_root.mkdir(parents=True, exist_ok=True)
        doc = {"phase": phase, "data": data}
        self.marker_file.write_text(json.dumps(doc), encoding="utf-8")
        
    def clear_marker(self):
        if self.marker_file.exists():
            self.marker_file.unlink()

    def _get_current_commit(self):
        return _git_raise(self.anchor_dir, ["rev-parse", "HEAD"]).strip()

    def run(self):
        marker = self.read_marker()
        start_phase = marker["phase"] if marker else 0
        data = marker["data"] if marker else {}

        try:
            if start_phase <= 0:
                print("Step 0: Preflight")
                self._step0_preflight(data)
                self.write_marker(1, data)
                start_phase = 1

            if start_phase == 1:
                print("Step 1: Write transaction marker")
                # already written
                self.write_marker(2, data)
                start_phase = 2

            if start_phase == 2:
                print("Step 2: Capture diverged commits")
                self._step2_capture_commits(data)
                self.write_marker(3, data)
                start_phase = 3
                
            if start_phase == 3:
                print("Step 3: Capture working tree (stash)")
                self._step3_capture_tree(data)
                self.write_marker(4, data)
                start_phase = 4

            if start_phase == 4:
                print("Step 4: Offline FF merge")
                self._step4_ff_merge(data)
                self.write_marker(5, data)
                start_phase = 5
                
            if start_phase == 5:
                print("Step 5: Restore or park")
                self._step5_restore_or_park(data)
                self.write_marker(6, data)
                start_phase = 6
                
            if start_phase == 6:
                print("Step 6: Verify final tree")
                self._step6_verify(data)
                self.write_marker(7, data)
                start_phase = 7
                
            if start_phase == 7:
                print("Step 7: Reverify / Park (placeholder)")
                self._step7_park_and_reverify(data)
                self.write_marker(8, data)
                start_phase = 8
                
            if start_phase == 8:
                print("Step 8: Cleanup")
                self._step8_cleanup(data)
                self.write_marker(9, data)
                start_phase = 9
                
            if start_phase == 9:
                self.clear_marker()
                print("Update complete")
        except Exception as e:
            msg = _check_output_for_git(str(e))
            print(f"Update failed at phase {start_phase}: {msg}")
            self.rollback()
            raise

    def rollback(self):
        print("Rolling back update offline")
        marker = self.read_marker()
        if not marker:
            print("No transaction marker found, nothing to rollback.")
            return
        data = marker["data"]
        
        # Clean up any potential conflict markers
        _git(self.anchor_dir, ["reset", "--hard", "HEAD"])

        base_sha = data.get("base_sha")
        vN_sha = data.get("vN_sha")
        
        if base_sha and data.get("diverged"):
            print(f"Resetting to base {base_sha}")
            _git(self.anchor_dir, ["reset", "--hard", base_sha])
        elif vN_sha:
            print(f"Resetting to {vN_sha}")
            _git(self.anchor_dir, ["reset", "--hard", vN_sha])
        
        # Restore stash
        stashed = data.get("stashed")
        if stashed:
            print("Restoring stash")
            _git(self.anchor_dir, ["stash", "apply"])
            _git(self.anchor_dir, ["stash", "drop"])

        # Restore diverged commit backup
        backup_branch = data.get("backup_branch")
        if backup_branch:
            print(f"Restoring diverged commit from {backup_branch}")
            # Mixed reset to vN_sha keeps the uncommitted edits in working tree while restoring HEAD
            if base_sha and data.get("diverged") and vN_sha:
                _git(self.anchor_dir, ["reset", vN_sha])
        
        self.clear_marker()
        print("Rollback complete.")
        
    def _step0_preflight(self, data):
        # Fetching latest
        ok, _, err = _git(self.anchor_dir, ["fetch", "origin", "--tags"])
        if not ok:
            print(f"Network error during fetch: {err}. Treating as offline/injected failure.")
        
        ok, out, err = _git(self.anchor_dir, ["describe", "--tags", "--abbrev=0", "FETCH_HEAD"])
        if not ok:
            target = "FETCH_HEAD"
        else:
            target = out.strip()
            
        data["target_ref"] = target
        
        pinned_signers = self.config_root / "allowed_signers"
        if pinned_signers.exists():
            ok, _, err = _git(self.anchor_dir, ["verify-tag", target])
            if not ok:
                raise RuntimeError("Tag signature verification failed. Stop and delete if you suspect tampering.")
            print("Verified tag signature against pinned signers.")
        
        # Divergence detect: check if local HEAD is not ancestor of target
        ok, _, _ = _git(self.anchor_dir, ["merge-base", "--is-ancestor", "HEAD", target])
        data["diverged"] = not ok

    def _step2_capture_commits(self, data):
        data["vN_sha"] = self._get_current_commit()
        if data.get("diverged"):
            branch_name = f"backup-update-{data['vN_sha'][:8]}"
            _git(self.anchor_dir, ["branch", branch_name])
            data["backup_branch"] = branch_name
            ok, base, _ = _git(self.anchor_dir, ["merge-base", "HEAD", data["target_ref"]])
            if ok:
                base = base.strip()
                data["base_sha"] = base
                _git(self.anchor_dir, ["format-patch", base, "-o", str(self.config_root)])
                _git_raise(self.anchor_dir, ["reset", base])
        
    def _step3_capture_tree(self, data):
        # Auto-stash including untracked and ignored files
        ok, out, _ = _git(self.anchor_dir, ["stash", "push", "--all", "-m", "Anchor update auto-stash"])
        data["stashed"] = "Saved working directory and index state" in out
        
    def _step4_ff_merge(self, data):
        if os.environ.get("INJECT_STEP4_FAILURE"):
            raise RuntimeError("Injected step-4 failure for testing resume.")
        _git_raise(self.anchor_dir, ["merge", data["target_ref"], "--ff-only"])
        
    def _step5_restore_or_park(self, data):
        if data.get("stashed"):
            ok, out, err = _git(self.anchor_dir, ["stash", "apply"])
            if not ok:
                # Clean up conflict markers and park the stash
                _git(self.anchor_dir, ["reset", "--hard", "HEAD"])
                print("Anchor update parked some conflicting local edits.")
                print("Run 'anchor edits restore' to resolve them.")
                data["parked_stash"] = True
            else:
                data["parked_stash"] = False
            
    def _step6_verify(self, data):
        if os.environ.get("INJECT_STEP6_FAILURE"):
            raise RuntimeError("Injected step-6 failure for testing rollback.")
            
        try:
            _integrity.verify_at_boot(self.anchor_dir)
        except SystemExit:
            raise RuntimeError("Skill hash verify failed. Triggering rollback.")
            
    def _step7_park_and_reverify(self, data):
        pass
        
    def _step8_cleanup(self, data):
        if data.get("stashed") and not data.get("parked_stash"):
            _git(self.anchor_dir, ["stash", "drop"])

def _check_output_for_git(text):
    if "git " in text or "openssl " in text:
        return text.replace("git ", "anchor ").replace("openssl ", "anchor ")
    return text

def run_update(args):
    tx = UpdateTransaction()
    try:
        if "--resume" in args:
            print("Resuming interrupted update...")
            tx.run()
        elif "--rollback" in args:
            tx.rollback()
        else:
            tx.run()
    except Exception as e:
        msg = _check_output_for_git(str(e))
        print(f"Error: {msg}", file=sys.stderr)
        sys.exit(1)

def run_edits(args):
    target = os.environ.get("ANCHOR_UPDATE_TARGET") or _paths.CODE_DIR
    anchor_dir = Path(target).resolve()
    
    if not args:
        print("Usage: anchor edits [diff|restore|drop]")
        return
        
    cmd = args[0]
    if cmd == "diff":
        ok, out, _ = _git(anchor_dir, ["stash", "show", "-p"])
        if out:
            print(out)
        else:
            print("No parked edits.")
    elif cmd == "restore":
        ok, out, err = _git(anchor_dir, ["stash", "pop"])
        if not ok:
            print(f"Conflicts during restore. Please resolve them manually.")
        else:
            print("Parked edits restored.")
    elif cmd == "drop":
        ok, _, err = _git(anchor_dir, ["stash", "drop"])
        if ok:
            print("Parked edits dropped.")
        else:
            print(f"Failed to drop parked edits.")
    else:
        print(f"Unknown edits command: {cmd}")

