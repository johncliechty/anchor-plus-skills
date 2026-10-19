"""Session-owned local service recovery; never logs or stores authentication."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import urllib.request
import urllib.error
import winreg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
BASE = 'http://127.0.0.1:8777'
PROJECT = '31deac2da2944f4d8258f84f8c56bdc3'
EFFORT = 'Student Resources'

def token():
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Services\anchor\Parameters') as key:
        for name in ('AppEnvironmentExtra', 'AppEnvironment'):
            try:
                entries = winreg.QueryValueEx(key, name)[0]
            except FileNotFoundError:
                continue
            for entry in entries:
                if entry.startswith('ANCHOR_TOKEN='):
                    return entry.partition('=')[2]
    raise RuntimeError('Service authentication unavailable; no unauthenticated mutation attempted')

def request(path, body=None):
    req = urllib.request.Request(BASE + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Authorization': 'Bearer ' + token(), 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = json.load(exc)
        raise RuntimeError(f'HTTP {exc.code}: {detail.get("error", "request failed")}') from None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['inspect', 'restart', 'wait-ready', 'wake', 'turn-status', 'restore-dictation'])
    args = parser.parse_args()
    if args.action == 'restore-dictation':
        original = Path(r'C:\Users\john\.claude\projects\C--dev-Teaching-Math-541-Student-Resources\3a7882a7-e04d-497d-ac30-d822acea2abd.jsonl')
        entries = [json.loads(line) for line in original.read_text(encoding='utf-8').splitlines() if line.strip()]
        found = [entry for entry in entries if entry.get('uuid') == 'f09cf10a-54d1-4c38-8050-29998ceb8199']
        if len(found) != 1:
            raise RuntimeError('Original dictation could not be identified exactly; no restoration sent')
        words = '\n'.join(block['text'] for block in found[0]['message']['content'] if block.get('type') == 'text')
        destination = Path(r'C:\dev\Teaching\Math 541\Student Resources\RECOVERED-INSTRUCTIONS-2026-09-08.md')
        if words not in destination.read_text(encoding='utf-8'):
            raise RuntimeError('Durable project recovery copy differs; no restoration sent')
        receipt = Path(__file__).parent / 'math541-restoration-receipt.json'
        if receipt.exists():
            raise RuntimeError('Restoration has already been submitted; no automatic replay')
        message = ('RESTORED ORIGINAL DICTATION — John explicitly asked maintenance to recover this after the Claude-to-ChatGPT handoff omitted it. '
            'This is his complete original instruction, not a summary. Its requirements remain active. '
            'A verbatim durable copy is RECOVERED-INSTRUCTIONS-2026-09-08.md in this project. '
            'For THIS restoration turn, acknowledge that you have it and briefly restate the goal and deliverables. '
            'Do not begin coursework, run skills, or replay actions yet; wait for John to continue. '
            'Original dictated text follows:\n\n'+words)
        with receipt.open('x', encoding='utf-8') as handle:
            json.dump({'status':'submission_pending','source_message':found[0]['uuid'],'characters':len(words)}, handle)
        result = request('/api/steward/say', {'pid':PROJECT,'dir':EFFORT,'text':message})
        receipt.write_text(json.dumps({'status':'accepted' if result.get('ok') else 'not_accepted','source_message':found[0]['uuid'],
            'characters':len(words),'result':result},indent=2),encoding='utf-8')
        print(json.dumps({'restoration':result,'characters':len(words),'durable_verbatim_copy':True}))
        return
    if args.action == 'wake':
        print(json.dumps(request('/api/steward/engine', {'pid':PROJECT,'dir':EFFORT,'action':'wake'})))
        return
    if args.action == 'turn-status':
        from urllib.parse import quote
        data = request('/api/steward/events?pid='+PROJECT+'&dir='+quote(EFFORT)+'&since=0')
        state = data.get('state', {})
        print(json.dumps({'state':{k:state.get(k) for k in ('alive','busy','cli','selected_cli','session_id','model_policy','queued')},
            'events':[e for e in data.get('events', [])][-8:]}))
        return
    if args.action == 'wait-ready':
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                value = request('/api/version')
                print(json.dumps({'ready':True, **value}))
                return
            except (urllib.error.URLError, RuntimeError):
                time.sleep(2)
        raise RuntimeError('Service did not become ready in the bounded startup window')
    if args.action == 'restart':
        result = request('/api/steward/drain-all', {'pid':'2934ea6de8f64aca90c716d568298d75','dir':'Student Summaries'})
        if result.get('errors') or not result.get('ok'):
            raise RuntimeError('Cockpit drain did not verify; restart withheld')
        print(json.dumps({'parked':len(result.get('parked', [])), 'idle':len(result.get('idle', []))}))
        print(json.dumps(request('/api/restart', {})))
        return
    print(json.dumps({'version':request('/api/version')}))
    settings = request('/api/settings')
    print(json.dumps({'settings':{k:settings.get(k) for k in
        ('default_cli','coding_family','review_family','settings_revision')}}))
    for project in ('31deac2da2944f4d8258f84f8c56bdc3','2934ea6de8f64aca90c716d568298d75'):
        efforts = request('/api/steward/efforts?pid='+project).get('efforts', [])
        from urllib.parse import quote
        for effort in efforts:
            state = request('/api/steward/state?pid='+project+'&dir='+quote(effort['rel']))
            print(json.dumps({'project':project,'effort':effort['rel'],'state':{k:state.get(k) for k in
                ('alive','busy','cli','selected_cli','pending_switch','model_policy','settings_error')}}))

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'ok':False,'error':str(exc)}))
        raise SystemExit(2)
