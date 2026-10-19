import sys
import shutil
import platform
import os
import subprocess
from pathlib import Path

def get_node_version():
    node = shutil.which("node")
    if not node:
        return None
    try:
        proc = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=2, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        return proc.stdout.strip()
    except Exception:
        return None

def run_doctor(argv=None):
    print("Anchor Doctor — System Check\n")
    issues = []
    
    # Python
    py_ver = sys.version_info
    if (py_ver.major, py_ver.minor) < (3, 8):
        issues.append(f"Python version is too old. Requires >= 3.8. Current: {py_ver.major}.{py_ver.minor}.{py_ver.micro}. Install from python.org.")

    # Node
    node_ver = get_node_version()
    if not node_ver:
        issues.append("Node.js is MISSING. It is required for running Crucible/Foreman. Install Node.js from nodejs.org.")
    else:
        try:
            ver_num = int(node_ver.lstrip('v').split('.')[0])
            if ver_num < 16:
                issues.append(f"Node.js version is too old. Requires >= 16. Current: {node_ver}. Install from nodejs.org.")
        except Exception:
            pass

    # Capability Probe / CLIs
    claude = shutil.which("claude")
    gemini = shutil.which("agy") or shutil.which("gemini")
    
    if not claude and not gemini:
        issues.append("No Claude or Gemini CLI detected. Install via npm (e.g. npm install -g @anthropic-ai/claude-code).")
        
    # Interrupted update transaction
    try:
        import update_transaction
        txn = update_transaction.UpdateTransaction()
        marker = txn.read_marker()
        if marker is not None:
            phase = marker.get("phase", 0)
            issues.append(f"Interrupted update transaction detected at phase {phase}.\n  To resume or rollback, run: python anchor.py update")
    except Exception:
        pass

    if issues:
        print("Doctor found the following issues to fix:\n")
        for i, iss in enumerate(issues, 1):
            print(f"{i}. {iss}")
        print("\nAll prescriptions above use standard environment installs or anchor commands — NO manual git or openssl surgery is required.")
        return 1
    else:
        print("All prerequisites met. System is healthy.")
        return 0

if __name__ == "__main__":
    sys.exit(run_doctor())
