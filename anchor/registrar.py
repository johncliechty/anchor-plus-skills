import os
import platform
import subprocess
from pathlib import Path

def generate_nssm_unit(target_executable: str, port: int, token: str) -> dict:
    # Windows NSSM generator
    return {
        "os": "Windows",
        "type": "nssm",
        "argv": ["nssm", "install", "AnchorService", target_executable, "anchor.server", str(port)],
        "env": {"ANCHOR_TOKEN": token},
        "restrictive_acl_requested": True
    }

def generate_systemd_unit(target_executable: str, port: int, token: str) -> dict:
    unit_text = f"""[Unit]
Description=Anchor Local Service
After=network.target

[Service]
ExecStart={target_executable} -m anchor.server {port}
Environment="ANCHOR_TOKEN={token}"
Restart=always

[Install]
WantedBy=default.target
"""
    return {
        "os": "Linux",
        "type": "systemd",
        "text": unit_text
    }

def generate_launchd_unit(target_executable: str, port: int, token: str) -> dict:
    unit_text = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.anchor.local</string>
    <key>ProgramArguments</key>
    <array>
        <string>{target_executable}</string>
        <string>-m</string>
        <string>anchor.server</string>
        <string>{port}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>ANCHOR_TOKEN</key>
        <string>{token}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
"""
    return {
        "os": "Darwin",
        "type": "launchd",
        "text": unit_text
    }

def build_registrar_unit(target_executable: str, port: int, token: str):
    system = platform.system()
    if system == "Windows":
        return generate_nssm_unit(target_executable, port, token)
    elif system == "Darwin":
        return generate_launchd_unit(target_executable, port, token)
    else:
        return generate_systemd_unit(target_executable, port, token)
