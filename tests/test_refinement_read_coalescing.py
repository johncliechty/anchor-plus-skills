import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from steward_cockpit import steward_campaign as campaign


def test_concurrent_reads_share_one_spine_result_without_sharing_mutable_state(tmp_path, monkeypatch):
    path=tmp_path/'roadmap.json';path.write_text('{}')
    entered=threading.Event();release=threading.Event();calls=[]
    def read(root):
        calls.append(root);entered.set();assert release.wait(5)
        return {'ok':True,'state':{'value':len(calls)}}
    monkeypatch.setattr(campaign,'_read_refinement_uncached',read)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(campaign.read_refinement,str(tmp_path)) for _ in range(4)]
        assert entered.wait(5);release.set();results=[f.result() for f in futures]
    assert len(calls)==1
    results[0]['state']['value']=999
    assert campaign.read_refinement(str(tmp_path))['state']['value']==1
    path.write_text('{"new_event":true}')
    assert campaign.read_refinement(str(tmp_path))['state']['value']==2


def test_finished_index_changes_and_expiry_recheck_external_damage(tmp_path,monkeypatch):
    (tmp_path/'roadmap.json').write_text('{}');clock=[1.0];calls=[]
    monkeypatch.setattr(campaign.time,'monotonic',lambda:clock[0])
    def read(root):calls.append(root);return {'ok':True,'state':{'reads':len(calls)}}
    monkeypatch.setattr(campaign,'_read_refinement_uncached',read)
    assert campaign.read_refinement(str(tmp_path))['state']['reads']==1
    folder=tmp_path/'Finished Deliverables';folder.mkdir();(folder/'index.json').write_text('{}')
    assert campaign.read_refinement(str(tmp_path))['state']['reads']==2
    (folder/'.steward-approved-pending.json').write_text('{}')
    assert campaign.read_refinement(str(tmp_path))['state']['reads']==3
    clock[0]+=2.01
    assert campaign.read_refinement(str(tmp_path))['state']['reads']==4


def test_change_during_read_is_not_cached(tmp_path,monkeypatch):
    p=tmp_path/'roadmap.json';p.write_text('{}');original=p.stat();calls=[]
    def read(root):
        calls.append(root);p.write_text(json.dumps({'event':len(calls)}))
        return {'ok':True,'sequence':len(calls)}
    monkeypatch.setattr(campaign,'_read_refinement_uncached',read)
    assert campaign.read_refinement(str(tmp_path))['sequence']==1
    # Restore the starting fingerprint: a torn result must not have been stored.
    p.write_text('{}');os.utime(p,ns=(original.st_atime_ns,original.st_mtime_ns))
    assert campaign.read_refinement(str(tmp_path))['sequence']==2


def test_failures_are_retried_after_short_ttl(tmp_path,monkeypatch):
    (tmp_path/'roadmap.json').write_text('{}');clock=[1.0];calls=[]
    monkeypatch.setattr(campaign.time,'monotonic',lambda:clock[0])
    def read(root):calls.append(root);return {'ok':False,'error':'temporary'}
    monkeypatch.setattr(campaign,'_read_refinement_uncached',read)
    campaign.read_refinement(str(tmp_path));campaign.read_refinement(str(tmp_path))
    assert len(calls)==1
    clock[0]+=.26
    campaign.read_refinement(str(tmp_path))
    assert len(calls)==2


def test_page_reads_answer_stale_and_recheck_once_in_the_background(tmp_path,monkeypatch):
    # 2026-10-02: a page past the two seconds is answered from the last good read while the
    # sources are unchanged; ONE background read rechecks it; a changed record is read at once
    (tmp_path/'roadmap.json').write_text('{}');clock=[1.0];calls=[];release=threading.Event()
    monkeypatch.setattr(campaign.time,'monotonic',lambda:clock[0])
    def read(root):
        calls.append(root)
        if len(calls)==2: assert release.wait(5)
        return {'ok':True,'state':{'reads':len(calls)}}
    monkeypatch.setattr(campaign,'_read_refinement_uncached',read)
    assert campaign.read_refinement(str(tmp_path),stale_ok=True)['state']['reads']==1
    clock[0]+=5
    assert campaign.read_refinement(str(tmp_path),stale_ok=True)['state']['reads']==1
    assert campaign.read_refinement(str(tmp_path),stale_ok=True)['state']['reads']==1
    release.set()
    for t in [t for t in threading.enumerate() if t.name=='refinement-recheck']: t.join(5)
    assert len(calls)==2
    assert campaign.read_refinement(str(tmp_path),stale_ok=True)['state']['reads']==2
    (tmp_path/'roadmap.json').write_text('{"new_event":true}')
    assert campaign.read_refinement(str(tmp_path),stale_ok=True)['state']['reads']==3
    # an act never takes the stale answer
    clock[0]+=5
    assert campaign.read_refinement(str(tmp_path))['state']['reads']==4


def test_a_recheck_that_raises_drops_the_stale_answer(tmp_path,monkeypatch):
    # Grok 2026-10-02: the recheck guards damage the fingerprint cannot see; when it fails the page reads at once
    (tmp_path/'roadmap.json').write_text('{}');clock=[1.0];calls=[]
    monkeypatch.setattr(campaign.time,'monotonic',lambda:clock[0])
    def read(root):
        calls.append(root)
        if len(calls)==2: raise RuntimeError('spine down')
        return {'ok':True,'state':{'reads':len(calls)}}
    monkeypatch.setattr(campaign,'_read_refinement_uncached',read)
    assert campaign.read_refinement(str(tmp_path),stale_ok=True)['state']['reads']==1
    clock[0]+=5
    assert campaign.read_refinement(str(tmp_path),stale_ok=True)['state']['reads']==1
    for t in [t for t in threading.enumerate() if t.name=='refinement-recheck']: t.join(5)
    assert campaign.read_refinement(str(tmp_path),stale_ok=True)['state']['reads']==3
