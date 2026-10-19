from copy import deepcopy
import json
import subprocess
from pathlib import Path
import pytest
from codex_catalog import reconcile_codex_catalog
import model_policy as policy

def row(name, rank, **kw):
    return {'slug':name,'priority':rank,'visibility':'list',
            'supported_reasoning_levels':[{'effort':'high'},{'effort':'ultra'}],**kw}

def catalog(*rows): return {'models':list(rows)}

def test_installed_priority_resolves_native_tie_without_changing_effort_or_input():
    native=catalog(row('old',1),row('frontier',1))
    bundle=catalog(row('frontier',1,supported_reasoning_levels=[{'effort':'low'}]),row('old',6))
    before=deepcopy(native)
    merged=reconcile_codex_catalog(native,bundle)
    selected=policy.select_model('chatgpt',policy.normalize_catalog('chatgpt',merged))
    assert selected['model']=='frontier' and selected['effort']=='ultra'
    assert selected['selection_evidence']=='installed_cli_priority+native_capabilities'
    assert native==before and not selected['model_attested']

def test_unique_fresher_provider_model_wins_even_if_absent_from_bundle():
    native=catalog(row('unknown-future-name',0),row('bundled-frontier',1))
    assert reconcile_codex_catalog(native,{'broken':True}) is native
    assert policy.select_model('chatgpt',policy.normalize_catalog('chatgpt',native))['model']=='unknown-future-name'

def test_bundled_probe_failure_does_not_withhold_unique_native_model(monkeypatch):
    monkeypatch.setattr(policy.shutil,'which',lambda *a,**k:'codex-stub')
    def runner(argv,env):
        if '--bundled' in argv:raise OSError('synthetic probe failure')
        return json.dumps(catalog(row('new-native',0)))
    rows,_=policy.discover('chatgpt',env={},runner=runner)
    assert policy.select_model('chatgpt',rows)['model']=='new-native'

@pytest.mark.parametrize('bundle',[
    catalog(row('old',1)), catalog(row('old',1),row('frontier',1)),
    catalog(row('old',1),row('frontier',0,hidden=True)),
    catalog(row('old',1),row('frontier',False)),
    catalog(row('old',1),row('frontier',0),row('frontier',0)),
])
def test_unresolved_ties_never_fall_back_to_array_order(bundle):
    native=catalog(row('old',1),row('frontier',1))
    assert reconcile_codex_catalog(native,bundle) is native
    with pytest.raises(policy.PolicyUnavailable,match='ambiguous'):
        policy.select_model('chatgpt',policy.normalize_catalog('chatgpt',native))

def test_python_and_javascript_catalog_reconciliation_agree():
    helper=Path(__file__).resolve().parents[2]/'trio/drivers/codex-catalog.mjs'
    # Standalone Anchor exports need not include a sibling Trio checkout.
    if not helper.is_file(): pytest.skip('cross-repository conformance gate')
    cases=[
        [catalog(row('old',1),row('new',1)),catalog(row('old',6),row('new',1))],
        [catalog(row('future',0),row('old',1)),catalog(row('old',1))],
        [catalog(row('old',1),row('new',1)),catalog(row('old',1),row('new',1))],
        [catalog(row('old',1),row('new',1)),catalog(row('old',1),row('new',0,selectable=False))],
    ]
    code="import {reconcileCodexCatalog} from "+json.dumps(helper.as_uri())+"; let s='';for await(const c of process.stdin)s+=c;process.stdout.write(JSON.stringify(JSON.parse(s).map(([a,b])=>reconcileCodexCatalog(a,b))));"
    result=subprocess.run(['node','--input-type=module','-e',code],input=json.dumps(cases),text=True,capture_output=True,check=True,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert json.loads(result.stdout)==[reconcile_codex_catalog(a,b) for a,b in cases]
