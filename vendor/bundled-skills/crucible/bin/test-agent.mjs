import { buildLiveCrucibleAgent } from './enhanced.mjs';
async function run() {
  const { agent } = await buildLiveCrucibleAgent({ env: { ...process.env, CRUCIBLE_AGENT_LIVE: '1' } });
  console.log('Sending test prompt to agent...');
  const res = await agent('Return {"test": 1}', { role: 'default' });
  console.log('Result:', res);
}
run().catch(console.error);
