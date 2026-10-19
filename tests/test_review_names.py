"""Exact revision naming bindings must preserve identity and fail closed."""
import json
import subprocess
from pathlib import Path


def test_registered_names_preserve_review_identity_and_reject_ambiguous_bindings():
    source = (Path(__file__).parents[1] / 'steward_cockpit/static/shared.js').read_text(encoding='utf8')
    start = source.index('  function registeredReviewNames(')
    end = source.index('  async function renderDeliverablesTile()', start)
    helper = source[start:end]
    script = helper + r'''
const assert = require('node:assert/strict');
const hash='a'.repeat(64), path='deliverables/bank/'+hash+'.pdf';
const managed={managed:true,step:'quiz',product_id:'bank',revision_id:'r3',path,hash,
  what:'bank',is_current:true,phase:'awaiting_review',presentation_id:'p3',history:[]};
const alias={managed:false,openable:true,step:'quiz',owner_step_id:'quiz',
  path:'Quiz 1 - Question Bank - Draft 3.pdf',what:'Quiz 1 Question Bank Draft 3',
  where_text:'`Quiz 1 - Question Bank - Draft 3.pdf` review: `'+path+'`'};
const input=[managed,alias], frozen=JSON.stringify(input);
const result=registeredReviewNames(input,[],[{act:'Review',item:managed}]);
assert.equal(result.items.length,1);
assert.equal(result.items[0].open_path,alias.path);
assert.equal(result.items[0].what,alias.what);
for(const key of ['path','hash','revision_id','product_id','step','presentation_id','phase'])
  assert.equal(result.items[0][key],managed[key]);
assert.equal(result.acts[0].item.open_path,alias.path);
assert.equal(JSON.stringify(input),frozen);
for(const bad of [
  {...alias,owner_step_id:'another'}, {...alias,openable:false},
  {...alias,path:'../escape.pdf'}, {...alias,path:'C:/escape.pdf'},
  {...alias,path:'\\server\\escape.pdf'}, {...alias,path:'wrong.html'},
  {...alias,where_text:'`anything`'},
]) assert.equal(registeredReviewNames([managed,bad]).items[0].open_path,undefined);
assert.equal(registeredReviewNames([managed,alias,{...alias,path:'Different Draft.pdf'}])
  .items[0].open_path,undefined);
assert.equal(registeredReviewNames([{...managed,hash:'wrong'},alias]).items[0].open_path,undefined);
const earlier={...managed,is_current:false};
assert.equal(registeredReviewNames([earlier,alias]).items.length,2);
console.log(JSON.stringify({pass:true}));
'''
    result = subprocess.run(['node','-e',script],capture_output=True,text=True,encoding='utf8',timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['pass']
