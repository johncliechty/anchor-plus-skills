import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import './flow-diagram.js';
import './layer-library.js';

const data = JSON.parse(fs.readFileSync(new URL('./maps.json', import.meta.url), 'utf8'));
const {renderFlowDiagram, legend, TYPES} = globalThis.FoundryFlowDiagram;
const {buildLayers, renderLayerLibrary} = globalThis.FoundryLayerLibrary;

test('the diagram draws every typed step, every edge and the disagreement badges', () => {
  const svg = renderFlowDiagram(data.process, {selected: 'probe'});
  // Native pixel size: the drawing declares width/height and no style shrinks
  // it to the container, so nodes stay readable and the host pans instead.
  assert.match(svg, /^<svg class="flow-diagram" width="\d+" height="\d+" viewBox="0 0 /);
  assert.ok(!globalThis.FoundryFlowDiagram.style.includes('width:100%'), 'the diagram style must not shrink the drawing to fit');
  for (const step of data.process.steps) {
    assert.ok(Object.keys(TYPES).includes(step.display_type), step.id + ' is typed');
    assert.ok(svg.includes(`data-step="${step.id}"`), step.id + ' is drawn');
    assert.ok(svg.includes(`class="fd-node ${step.display_type}`), step.id + ' shows its type');
  }
  assert.equal((svg.match(/class="fd-edge/g) || []).length, data.process.edges.length);
  const flagged = new Set();
  for (const d of data.process.disagreements) for (const sid of d.step_ids) flagged.add(sid);
  assert.equal((svg.match(/fd-flag/g) || []).length, flagged.size);
  assert.ok(svg.includes('aria-current="step"'));
  assert.ok(flagged.size > 0, 'reconciliation items sit on map nodes');
});

test('the legend explains all five node types and what a gate means', () => {
  const html = legend();
  for (const label of Object.values(TYPES)) assert.ok(html.includes(label), label);
  assert.ok(html.includes('gate') && html.includes('APPROVE'), 'the legend says what a gate means');
});

test('every library resource is reachable through a layer path from the root', () => {
  const layers = buildLayers(data.knowledge, data.resources);
  for (const resource of data.resources) {
    const node = data.knowledge.nodes.find(n => n.resource_id === resource.id);
    assert.ok(node, resource.id + ' is on the knowledge map');
    const path = layers.pathTo(node.id);
    assert.equal(path[0], layers.root.id, resource.id + ' path starts at the root');
    assert.equal(path[path.length - 1], node.id);
    const html = renderLayerLibrary(data, {path}, {resourceLink: id => `<a data-resource="${id}">open</a>`});
    assert.ok(html.includes(`data-resource="${resource.id}"`), resource.id + ' is offered at its layer');
  }
});

test('levels summarize the four kinds as catalog counts, never frequency', () => {
  const layers = buildLayers(data.knowledge, data.resources);
  const distinct = new Set(data.knowledge.nodes.map(n => n.resource_id)).size;
  assert.equal(layers.root.catalog_total, distinct);
  const html = renderLayerLibrary(data, {path: [layers.root.id]}, {resourceLink: () => ''});
  assert.ok(html.includes('level-dial'), 'the level dial is the level control');
  assert.ok(html.includes('not use frequency'), 'counts are labeled as catalog counts');
  assert.ok(!html.includes('class="card'), 'tiles wait at the leaves');
  for (const child of layers.childrenOf(layers.root.id)) {
    assert.ok(html.includes(`data-layer-node="${child.id}"`), child.id + ' branch is offered');
  }
  // Every roll-up names all four kinds explicitly — zeros included — so a
  // missing kind reads as "0", never as silence.
  const rolls = [...html.matchAll(/class="ll-kinds">([^<]*)</g)].map(m => m[1]);
  assert.ok(rolls.length >= 1, 'at least one kind roll-up is shown');
  for (const roll of rolls) {
    for (const label of ['Reusable material', 'References', 'Tools', 'Skills']) {
      assert.ok(roll.includes(label), label + ' must be counted explicitly in: ' + roll);
    }
  }
});

test('a leaf shows its tile and search returns layer paths', () => {
  const layers = buildLayers(data.knowledge, data.resources);
  const leaf = data.knowledge.nodes.find(n => !data.knowledge.nodes.some(k => k.parent_id === n.id));
  const html = renderLayerLibrary(data, {path: layers.pathTo(leaf.id)},
    {resourceLink: id => `<a class="tile" data-resource="${id}">open</a>`});
  assert.ok(html.includes('class="card'), 'the chosen leaf shows a tile');
  assert.ok(html.includes(`data-resource="${leaf.resource_id}"`));
  const search = renderLayerLibrary(data, {path: [layers.root.id], query: 'judge'}, {resourceLink: () => ''});
  assert.ok(search.includes('data-layer-node='), 'search results jump to layers');
});
