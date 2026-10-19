import json
import os
import subprocess
import sys
from pathlib import Path

def run(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"Error running {' '.join(cmd)}: {proc.stderr}", file=sys.stderr)
        sys.exit(1)
    return proc.stdout.strip()

def main():
    if len(sys.argv) != 2:
        print("Usage: python release.py <tag>")
        sys.exit(1)
    tag = sys.argv[1]
    
    print(f"Tagging {tag} with SSH signature...")
    run(["git", "tag", "-s", tag, "-m", f"Release {tag}"])
    
    source_sha = run(["git", "rev-parse", "HEAD"])
    release_sha = run(["git", "rev-list", "-n", "1", tag])
    
    map_file = Path("release-map.json")
    if map_file.exists():
        with open(map_file, "r") as f:
            rmap = json.load(f)
    else:
        rmap = {}
        
    rmap[source_sha] = release_sha
    
    with open(map_file, "w") as f:
        json.dump(rmap, f, indent=2)
        f.write("\n")
        
    print(f"Recorded release mapping in release-map.json: {source_sha} -> {release_sha}")

if __name__ == "__main__":
    main()
