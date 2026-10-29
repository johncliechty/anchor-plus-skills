"""Read-only live evidence capture; no Anchor imports, server, or production edits.

Adapted from the retained live walkthrough, with touch input, clipped-pixel
geometry, paint settling, full request/console monitoring, and separate failures.
Requires installed Python Playwright and Chromium. Run each viewport separately.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlencode

from playwright.sync_api import sync_playwright

PACKET = Path(__file__).resolve().parent
BUNDLE = PACKET.parent
BASE = 'http://127.0.0.1:8777'
PAGE = '/foundry?skill=researchprime'
EXPECTED_BUILD = '2229b5d+c934631'
ANCHOR = Path('C:/dev/Anchor')
ASSETS = ('adapter.js', 'flow-diagram.js', 'layer-library.js', 'display.css', 'skill-display.js')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def git(*args):
    run = subprocess.run(['git', '-C', str(ANCHOR), *args], capture_output=True,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if run.returncode:
        raise RuntimeError(run.stderr.decode('utf-8', errors='replace'))
    return run.stdout


def intersection(a, b):
    return max(0, min(a['x']+a['width'], b['x']+b['width'])-max(a['x'], b['x'])) * max(
        0, min(a['y']+a['height'], b['y']+b['height'])-max(a['y'], b['y']))


def in_frame(tab, selector, width, height):
    """Retained cited_line_in_view criterion, extended to horizontal clipping."""
    frame = tab.frame_locator('#resource-frame')
    frame.locator(selector).wait_for()
    for _ in range(50):
        hit = frame.locator(selector).bounding_box()
        box = tab.locator('#resource-frame').bounding_box()
        screen = dict(x=0, y=0, width=width, height=height)
        def contained(outer):
            return hit and hit['x']>=outer['x']-1 and hit['y']>=outer['y']-1 and hit['x']+hit['width']<=outer['x']+outer['width']+1 and hit['y']+hit['height']<=outer['y']+outer['height']+1
        if hit and box and contained(box) and contained(screen):
            return {'content': hit, 'iframe': box}
        tab.wait_for_timeout(100)
    raise AssertionError(f'content clipped/outside iframe or viewport: {hit}; frame {box}')


def paint(tab):
    """Wait for real paint/fonts, including the script-less source iframe."""
    # Evaluate only in the host: sandboxed source frames prohibit callbacks.
    # Locator geometry below separately proves the frame content is on screen.
    tab.evaluate('async () => {await document.fonts.ready; await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));}')
    tab.wait_for_timeout(150)


def diagram_pixels(tab):
    """Measure actual SVG labels and stroke segments after overflow clipping."""
    return tab.evaluate('''() => {
      const box=document.querySelector('.diagram-scroll').getBoundingClientRect();
      const clip={l:Math.max(0,box.left),r:Math.min(innerWidth,box.right),t:Math.max(0,box.top),b:Math.min(innerHeight,box.bottom)};
      const inside=(x,y)=>x>=clip.l+1&&x<=clip.r-1&&y>=clip.t+1&&y<=clip.b-1;
      const nodes=[...document.querySelectorAll('.fd-node')].filter(n=>{
        const r=n.getBoundingClientRect(); return inside(r.left,r.top)&&inside(r.right,r.bottom);
      }).map(n=>({id:n.dataset.step, titles:[...n.querySelectorAll('.fd-title')].map(t=>({text:t.textContent,px:parseFloat(getComputedStyle(t).fontSize)}))}));
      const edges=[...document.querySelectorAll('path.fd-edge')].map((e,index)=>{
        const length=e.getTotalLength(),m=e.getScreenCTM();let visible=0,last=null;
        for(let s=0;s<=length;s+=2){const q=e.getPointAtLength(s),p=new DOMPoint(q.x,q.y).matrixTransform(m);
          if(last&&inside(last.x,last.y)&&inside(p.x,p.y))visible+=Math.hypot(p.x-last.x,p.y-last.y);last=p;}
        return {index,visible_px:Math.round(visible),stroke:getComputedStyle(e).stroke};
      }).filter(e=>e.visible_px>=12&&e.stroke!=='none');
      return {clip,nodes,edges};
    }''')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--viewport', choices=('desktop', 'phone'), required=True)
    args = parser.parse_args()
    width, height = (1440, 1000) if args.viewport == 'desktop' else (390, 844)
    receipt = {'viewport':args.viewport, 'pixels':[width,height], 'started':utc(),
               'command':subprocess.list2cmdline([sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), '--viewport',args.viewport]),
               'tested_url':BASE+PAGE, 'checks':[], 'screenshots':{}, 'assets':{}, 'sources':[], 'downloads':{},
               'monitor':{'page_errors':[], 'console_errors':[], 'request_failures':[], 'http_errors':[], 'writes':[], 'injected_auth_headers':[]}}
    scratch = PACKET/'_scratch'
    scratch.mkdir(exist_ok=True)
    (PACKET/'screenshots').mkdir(exist_ok=True)
    data = json.loads((BUNDLE/'maps.json').read_text(encoding='utf-8-sig'))

    @contextmanager
    def check(name):
        row={'id':name, 'started':utc(), 'status':'pass', 'assertion_exit_code':0, 'evidence':{}}
        receipt['checks'].append(row)
        try:
            yield row['evidence']
        except Exception as exc:
            row.update(status='fail', assertion_exit_code=1, error=f'{type(exc).__name__}: {exc}')
        row['ended']=utc()
        (scratch/(args.viewport+'-receipt.json')).write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
        print(f"{args.viewport}: {name}: {row['status']} {row.get('error','')[:500]}", flush=True)

    with sync_playwright() as p:
        browser=p.chromium.launch()
        context=browser.new_context(viewport={'width':width,'height':height},
                                    has_touch=args.viewport=='phone', is_mobile=args.viewport=='phone',
                                    device_scale_factor=1, accept_downloads=True)
        tab=context.new_page()
        tab.set_default_timeout(10000)
        monitor=receipt['monitor']

        def shot(name):
            paint(tab)
            rel=f'screenshots/{args.viewport}-{name}.png'
            tab.screenshot(path=str(PACKET/rel), full_page=False)
            raw=(PACKET/rel).read_bytes()
            px=[int.from_bytes(raw[16:20],'big'),int.from_bytes(raw[20:24],'big')]
            assert px==[width,height] and len(raw)>4096
            receipt['screenshots'][rel]={'pixels':px,'bytes':len(raw),'sha256':digest(raw), 'captured':utc(), 'visually_inspected':False}
            return rel

        def open_process(step='entry'):
            tab.goto(BASE+PAGE+'#process/'+step)
            tab.locator('.flow-diagram').wait_for()
            paint(tab)

        def open_document(link, title):
            tab.goto(BASE+PAGE)
            tab.locator('.head .actions').get_by_role('link',name=link,exact=True).click()
            f=tab.frame_locator('#resource-frame')
            f.get_by_role('heading',name=title,exact=True).wait_for()
            paint(tab)
            return f

        with check('normal-authentication') as out:
            # Retained normal local login: only the Doctor document navigates;
            # its unrelated scripts/API follow-ups cannot wake another effort.
            tab.route('**/*',lambda r:r.continue_() if r.request.is_navigation_request() and urlsplit(r.request.url).path=='/doctor' else r.abort())
            r=tab.goto(BASE+'/doctor')
            tab.unroute('**/*')
            out['login_status']=r.status
            out['cookie_attributes']=[{k:c[k] for k in ('name','httpOnly','secure','sameSite')} for c in context.cookies()]
            assert r.status==200
            assert any(c['name']=='anchor_auth' and c['httpOnly'] for c in context.cookies())
            out['method']='server-issued HttpOnly cookie from normal local /doctor; no token extraction, set-cookie injection, or auth-header bypass'

        tab.on('pageerror',lambda e:monitor['page_errors'].append(str(e)))
        tab.on('console',lambda m:monitor['console_errors'].append({'text':m.text,'phase':receipt['checks'][-1]['id'],'time':utc()}) if m.type=='error' else None)
        tab.on('requestfailed',lambda r:monitor['request_failures'].append({'url':r.url,'failure':r.failure}))
        tab.on('response',lambda r:monitor['http_errors'].append({'url':r.url,'status':r.status}) if r.status>=400 else None)
        def request(r):
            if r.method!='GET': monitor['writes'].append({'method':r.method,'url':r.url})
            if 'x-anchor-token' in r.headers: monitor['injected_auth_headers'].append(r.url)
        tab.on('request',request)

        with check('live-build-assets-and-source-identities') as out:
            before=context.request.get(BASE+'/api/version').json()['version']
            receipt['live_build_start']=before
            assert before==EXPECTED_BUILD, f'expected {EXPECTED_BUILD}; got {before}'
            out['served_head']=git('rev-parse',before.split('+')[0]).decode().strip()
            out['contains_f9f1078']=subprocess.run(['git','-C',str(ANCHOR),'merge-base','--is-ancestor','f9f1078',before.split('+')[0]],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).returncode==0
            assert out['contains_f9f1078']
            tab.goto(BASE+PAGE)
            tab.get_by_role('heading',name='researchPrime',exact=True).wait_for()
            payload=tab.evaluate('window.FOUNDRY_SKILL_DISPLAY')
            assert payload['issues']==[] and payload['settings']['error'] is None
            assert payload['data']==data, 'live maps payload differs from the job bundle'
            out['maps_sha256']=digest((BUNDLE/'maps.json').read_bytes())
            out['counts']={k:len(v) for k,v in {'steps':data['process']['steps'],'edges':data['process']['edges'],'resources':data['resources'],'knowledge_nodes':data['knowledge']['nodes']}.items()}
            receipt['refinement']=data['refinement']
            receipt['lifecycle']=payload['data']['lifecycle']
            receipt['feedback']=payload['data']['review']
            out['settings']=payload['settings']
            scripts=tab.locator('script[src]').evaluate_all('(els)=>els.map(e=>e.getAttribute("src"))')
            out['loaded_scripts']=scripts
            for asset in ASSETS:
                url=BASE+'/static/foundry-display/'+asset
                r=context.request.get(url)
                assert r.status==200, f'{url}: {r.status}'
                raw=r.body(); committed=git('show',before.split('+')[0]+':static/foundry-display/'+asset)
                matches=raw.replace(b'\r\n',b'\n')==committed.replace(b'\r\n',b'\n')
                receipt['assets'][asset]={'url':url,'sha256':digest(raw),'commit_sha256':digest(committed),'matches_commit':matches,'comparison':'bytes' if raw==committed else 'newline-normalized'}
                assert matches, f'{asset} differs from reported served commit'
            for source in data['sources']:
                local=(BUNDLE/source['snapshot']).read_bytes()
                assert digest(local)==source['sha256'], source['id']
                declared=source['snapshot'].split('/')[-1]
                a=next((a for a in data['anchors'] if a['source_id']==source['id']),None)
                expected=Path('C:/dev/Skill Foundry/Foundry page and knowledge maps/researchprime')/source['snapshot']
                link=payload['hrefs']['anchors'][a['id']]['href'] if a else None
                status=None
                if link:
                    decoded=parse_qs(urlsplit(link).query)['path'][0]
                    assert Path(decoded.replace('\\','/')).resolve()==expected.resolve()
                    r=context.request.get(BASE+link)
                    status=r.status
                    assert status==200, f'{source["id"]} actual anchor HTTP {status}'
                artifact=payload['hrefs']['resources']['human-guide']['href'].rsplit('/resources/',1)[0]+'/'+source['snapshot']
                raw_response=context.request.get(BASE+artifact)
                assert raw_response.status==200 and raw_response.body()==local, f'live captured bytes differ: {source["id"]}'
                receipt['sources'].append({'id':source['id'],'snapshot':source['snapshot'],'sha256':digest(local),'live_sha256':digest(raw_response.body()),'declared_sha256':source['sha256'],'viewer_status':status,'source_href':link,'snapshot_href':artifact,'viewer_qualification':None if link else 'No declared clickable anchor for this source; snapshot bytes verified.'})
            out['source_count']=len(receipt['sources'])
            receipt['payload_hrefs']=payload['hrefs']

        with check('layered-library-zero-counts-and-real-dial') as out:
            tab.goto(BASE+PAGE+'#library')
            tab.locator('#level-dial').wait_for()
            out['levels']=[]
            for depth in range(4):
                paint(tab)
                text=tab.locator('#panel').inner_text()
                node=tab.locator('.ll-crumbs strong').inner_text()
                out['levels'].append({'depth':depth,'node':node,'summaries':tab.locator('.ll-kinds').all_text_contents()})
                assert tab.locator('.ll-dial output').inner_text().startswith(f'Level {depth} of ')
                current=next(n for n in data['knowledge']['nodes'] if n['title']==node)
                summary=' · '.join(f'{"Skills" if k=="Other skills" else k} {current["catalog"].get(k,0)}' for k in ('Reusable material','References','Tools','Other skills'))
                assert tab.locator('.ll-kinds').first.inner_text()==summary, 'four catalog kinds/counts (including zeros) differ from the current layer'
                if depth==0:
                    tab.locator('.ll-dial').scroll_into_view_if_needed()
                    out['root_screenshot']=shot('library-root')
                if not tab.locator('.ll-branch').count(): break
                tab.locator('.ll-branch').first.click()
            assert depth>=2, 'no real layered descent to a resource leaf'
            assert tab.locator('.card').count()==1 and 'Use frequency unknown' in tab.locator('.card').inner_text()
            tab.locator('.card').scroll_into_view_if_needed()
            out['leaf_screenshot']=shot('library-leaf')
            dial=tab.locator('#level-dial')
            dial.scroll_into_view_if_needed()
            box=dial.bounding_box()
            tab.evaluate('window.__verificationTouchCount=0;document.addEventListener("touchstart",()=>window.__verificationTouchCount++,{passive:true})')
            if args.viewport=='phone':
                tab.touchscreen.tap(box['x']+4,box['y']+box['height']/2)
                assert tab.evaluate('window.__verificationTouchCount')>=1
                out['dial_input']='touchscreen.tap at minimum of native range control (no keyboard/input injection)'
                out['touchstart_events']=tab.evaluate('window.__verificationTouchCount')
            else:
                tab.mouse.click(box['x']+4,box['y']+box['height']/2)
                out['dial_input']='mouse.click at minimum of native range control'
            assert tab.locator('.ll-dial output').inner_text().startswith('Level 0 of ')
            assert tab.locator('#level-dial').input_value()=='0'
            out['dial_result_screenshot']=shot('library-dial')
            assert tab.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'page overflows viewport horizontally'

        with check('process-diagram-visible-nodes-edges-and-readability') as out:
            open_process()
            assert tab.locator('.fd-node').count()==len(data['process']['steps'])
            assert tab.locator('path.fd-edge').count()==len(data['process']['edges'])
            seen_nodes=set();seen_edges=set();samples=[]
            for step in data['process']['steps']:
                tab.locator(f'.fd-node[data-step="{step["id"]}"]').click()
                paint(tab)
                geometry=diagram_pixels(tab)
                ids={n['id'] for n in geometry['nodes']}
                assert step['id'] in ids, f'selected {step["id"]} clipped/offscreen: {geometry}'
                assert geometry['edges'], f'no actual visible edge strokes at {step["id"]}'
                assert all(t['px']>=11 for n in geometry['nodes'] for t in n['titles']), 'unreadably shrunken node labels'
                seen_nodes.update(ids);seen_edges.update(e['index'] for e in geometry['edges'])
                samples.append({'selected':step['id'],'visible_nodes':sorted(ids),'visible_edge_indices':[e['index'] for e in geometry['edges']]})
                if step['id'] in ('entry','judge'):
                    out[step['id']+'_geometry']=geometry
                    out[step['id']+'_screenshot']=shot('process-'+step['id'])
            out.update(node_coverage=len(seen_nodes),edge_segment_coverage=len(seen_edges),samples=samples)
            assert seen_nodes=={s['id'] for s in data['process']['steps']}
            assert len(seen_edges)==len(data['process']['edges']), 'some edge strokes never enter the clipped viewport'

        with check('disagreement-and-a108-line208-visible-in-iframe-and-screen') as out:
            open_process('judge')
            detail=tab.locator('#step-detail[data-step-id="judge"]')
            assert detail.get_attribute('open') is None
            detail.locator('> summary').click()
            difference=detail.locator('.difference').filter(has=tab.locator('[data-source="a108"]'))
            if not difference.count(): difference=detail.locator('.difference').first
            difference.locator('> summary').click()
            text=difference.inner_text()
            d=data['process']['disagreements'][0]
            assert d['instruction_says'] in text and d['code_does'] in text and d['follows'] in text
            difference.scroll_into_view_if_needed()
            out['reconciliation_screenshot']=shot('disagreement')
            links=detail.locator('.reconcile-node .anchor-list a[data-source]')
            links.first.click()
            out['geometry']=in_frame(tab,'.hit',width,height)
            hit=tab.frame_locator('#resource-frame').locator('.hit')
            assert hit.get_attribute('id')=='L208'
            assert next(a['quote'] for a in data['anchors'] if a['id']=='a108') in hit.inner_text()
            out['source_href']=tab.locator('#resource-frame').get_attribute('src')
            assert Path(parse_qs(urlsplit(out['source_href']).query)['path'][0].replace('\\','/')).name=='skill.md'
            out['source_screenshot']=shot('source-a108-L208')
            out['disagreement']=d
            response=context.request.get(BASE+out['source_href'])
            out['viewer_response_sha256']=digest(response.body())
            out['viewer_inline_scripts']=re.findall(r'<script[^>]*>(.*?)</script>',response.text(),re.S)

        with check('complete-cited-line-text-readable-without-horizontal-clipping') as out:
            frame_box=tab.locator('#resource-frame').bounding_box()
            # A block's box can fit while its preformatted text overflows.
            # Measure the actual text range, rather than that misleading box.
            text_box=tab.frame_locator('#resource-frame').locator('.hit').evaluate('el => {const r=document.createRange();r.selectNodeContents(el);const b=r.getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height}}')
            text_box['x']+=frame_box['x'];text_box['y']+=frame_box['y']
            out['text_range_geometry']=text_box
            out['iframe_geometry']=frame_box
            out['screenshot']=shot('source-a108-L208')
            area=text_box['width']*text_box['height']
            out['fully_visible']=intersection(text_box,frame_box)>=area-2 and intersection(text_box,dict(x=0,y=0,width=width,height=height))>=area-2
            assert out['fully_visible'], 'L208 highlight is visible, but the cited text extends beyond the iframe/screen horizontally'

        if tab.locator('#resource-dialog').is_visible():
            tab.locator('#close-resource').click()

        for rid,link,title,filename in (('human-guide','Human guide','Human guide','human.md'),('purpose','Original North Star','What researchPrime is for','skill.md')):
            with check('formatted-'+rid+'-download-and-navigation') as out:
                f=open_document(link,title)
                out['heading_geometry']=in_frame(tab,'h1',width,height)
                assert f.locator('.md').count()==1 and f.locator('.md h2, .md h3').count()>0
                if rid=='purpose':
                    assert 'LOCKED' in f.locator('body').inner_text()
                    assert 'C:\\dev\\trio\\researchPrime\\SKILL.md' in f.locator('.locus').inner_text()
                out['screenshot']=shot(rid)
                if rid=='purpose':
                    f.locator('.locus').scroll_into_view_if_needed()
                    out['location_geometry']=in_frame(tab,'.locus',width,height)
                    out['location_screenshot']=shot('north-star-location')
                href=tab.evaluate('window.FOUNDRY_SKILL_DISPLAY')['hrefs']['resources'][rid]['href']
                served=context.request.get(BASE+href).body()
                local=(BUNDLE/'resources'/('human-guide.html' if rid=='human-guide' else 'purpose.html')).read_bytes()
                assert served==local, 'formatted document bytes differ from registered bundle'
                out['formatted_document_sha256']=digest(served)
                with tab.expect_download() as download:
                    f.get_by_role('link',name='Download source',exact=True).click()
                dl=download.value
                assert dl.failure() is None and dl.suggested_filename==filename
                raw=Path(dl.path()).read_bytes();expected=(BUNDLE/'sources'/filename).read_bytes()
                assert raw==expected, 'actual browser download differs from source snapshot'
                receipt['downloads'][filename]={'bytes':len(raw),'sha256':digest(raw),'suggested_filename':dl.suggested_filename,'snapshot_sha256':digest(expected),'byte_identical':True}
                if rid=='human-guide':
                    f.get_by_role('link',name='← researchPrime Library',exact=True).click()
                    tab.locator('#level-dial').wait_for()
                else:
                    f.get_by_role('link',name='A question arrives',exact=True).click()
                    tab.locator('.flow-diagram').wait_for()
                assert not tab.locator('#resource-dialog').is_visible() and PAGE in tab.url
                out['normal_top_navigation_url']=tab.url

        with check('preserved-grade-B-and-open-lifecycle') as out:
            if tab.locator('#resource-dialog').is_visible(): tab.locator('#close-resource').click()
            tab.goto(BASE+PAGE+'#review')
            tab.get_by_role('link',name='Review record',exact=True).click()
            text=tab.locator('#panel').inner_text()
            assert 'Grade: B' in text and 'accepted: false' in text
            payload=tab.evaluate('window.FOUNDRY_SKILL_DISPLAY')
            assert payload['data']['review']==data['review'] and payload['data']['lifecycle']==data['lifecycle']
            assert payload['data']['lifecycle']['accepted'] is False and payload['data']['lifecycle']['closed'] is False
            tab.locator('#panel').scroll_into_view_if_needed()
            out['screenshot']=shot('review-record')

        with check('no-request-errors-page-exceptions-or-writes-and-stable-build') as out:
            receipt['live_build_end']=context.request.get(BASE+'/api/version').json()['version']
            assert receipt['live_build_end']==receipt.get('live_build_start')==EXPECTED_BUILD
            for category,events in monitor.items():
                if category!='console_errors': assert not events, f'{category}: {events}'
            out['monitoring']='all tested page GETs, HTTP responses, failed requests, page exceptions, and error-level console; Doctor login follow-ups intentionally blocked before monitoring'
            out['client']='Chromium '+browser.version
        with check('no-console-errors') as out:
            out['count']=len(monitor['console_errors'])
            out['unique_messages']=sorted({e['text'] for e in monitor['console_errors']})
            assert not monitor['console_errors'], f'console errors: {out["unique_messages"]}'
        browser.close()

    receipt['ended']=utc()
    receipt['exit_code']=int(any(c['status']=='fail' for c in receipt['checks']))
    (scratch/(args.viewport+'-receipt.json')).write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    return receipt['exit_code']


if __name__=='__main__':
    sys.exit(main())
