import { defaultRunGemini } from './bin/drivers/driver-gemini.mjs';
async function test() {
  process.env.CRUCIBLE_AGENT_LIVE = '1';
  process.env.GEMINI_MODEL = 'Gemini 3.1 Pro';
  const res = await defaultRunGemini('Return a JSON object: {"hello": "world"}', 'test', { env: process.env, log: console.log });
  console.log('Result:', res);
}
test();
