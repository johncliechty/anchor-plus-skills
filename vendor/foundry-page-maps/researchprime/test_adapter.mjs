import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createDisplay, resolveDisplaySettings, seededPositions, recenter, summarizeUse, walkthrough} from './adapter.mjs';
const data = JSON.parse(fs.readFileSync(new URL('./maps.json', import.meta.url), 'utf8'));

test('the same ids support real links and host-resolved resource routes', () => {
  const seen = [];
  const display = createDisplay(data, {resolveTarget: p => {seen.push(p); return '/foundry/resources/'+p.resourceId;}});
  assert.equal(display.resourceTarget('purpose'), '/foundry/resources/purpose');
  assert.equal(seen[0].sourceHash.length, 64);
  assert.throws(() => display.resourceTarget('invented'));
  assert.ok(display.search('approval').length > 0);
  assert.notEqual(display.data, data);
});
test('invalid primary blocks fallback and absent primary permits mirror', () => {
  assert.throws(() => resolveDisplaySettings({primary: {exists:true,value:{}}, mirror:data.settings}));
  assert.throws(() => resolveDisplaySettings({primary: {exists:true,value:{...data.settings,model_policy:{mode:'old',effort:'low'}}}, mirror:data.settings}));
  assert.equal(resolveDisplaySettings({primary:{exists:false}, mirror:data.settings}).source, 'mirror');
});
test('selected persona preserves the approved walkthrough order', () => {
  assert.deepEqual(walkthrough(data.settings).map(x=>x.id), data.walkthrough);
  assert.ok(walkthrough(data.settings)[2].title.includes('Lamp'));
  assert.throws(() => walkthrough({...data.settings,steward_type:'jarvis'}));
  const jarvis = walkthrough({...data.settings,steward_type:'jarvis'}, {
    lamp:{title:'Project',icon:'/project.png'},cave:{title:'Portfolio',icon:'/portfolio.png'},star:{title:'Campaign',icon:'/campaign.png'}});
  assert.equal(jarvis[2].icon, '/project.png');
});
test('declared tree projects inside the disk; focus maps to the center', () => {
  const positions = seededPositions(data.knowledge.nodes);
  assert.equal(positions.size, data.knowledge.nodes.length);
  for (const p of positions.values()) assert.ok(Math.hypot(p.x,p.y)<1);
  const focus = positions.get('panel');
  assert.deepEqual(recenter(focus,focus), {x:0,y:0});
});
test('frequency needs verified explicit resource receipts and deduplicates runs', () => {
  const receipt = {run_id:'run-one', resource_ids:['purpose'], receipt_target:'evidence/one.json', sha256:'a'.repeat(64)};
  assert.throws(() => summarizeUse(['purpose'],[receipt]));
  assert.throws(() => summarizeUse(['purpose'],[receipt],()=>false));
  assert.throws(() => summarizeUse(['purpose'],[{...receipt,resource_ids:['fiction']}],()=>true));
  const result = summarizeUse(['purpose','scope'],[receipt,receipt],()=>true);
  assert.equal(result.purpose.count,1);
  assert.equal(result.scope.count,null);
  assert.equal(result.scope.status,'unknown');
});
test('unsafe paths, invented counts and invented learned geometry are rejected', () => {
  for (const mutate of [d=>d.resources[0].target='../secret',d=>d.resources[0].usage.count=99,
    d=>d.knowledge.learned=true,d=>d.process.steps[0].anchors=[],d=>d.knowledge.nodes[0].parent_id='answer']) {
    const d=structuredClone(data); mutate(d); assert.throws(()=>createDisplay(d));
  }
});
