import { spawn } from 'node:child_process';
import { makeAgentDriver } from '../wave-workflow.js';

export function extractJson(text) {
  if (typeof text !== 'string') return null;
  let t = text.trim();
  const fence = t.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fence) t = fence[1].trim();
  try { return JSON.parse(t); } catch { /* try substring */ }
  const m = t.match(/\{[\s\S]*\}/);
  if (m) { try { return JSON.parse(m[0]); } catch { /* fall through */ } }
  return null;
}

export function parseGeminiFrames(stdout, { label = '(unlabeled)', cli_status = null } = {}) {
  let finalEnv = null;
  let lastText = '';
  let servedModel = null;
  let tools = 0;
  
  for (const raw of String(stdout).split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    let o;
    try { o = JSON.parse(line); } catch { continue; }
    
    if (o.type === 'system' && typeof o.model === 'string' && o.model) {
      servedModel = servedModel || o.model;
    } else if (o.type === 'assistant' && o.message?.content) {
      if (typeof o.message.model === 'string' && o.message.model) {
        servedModel = o.message.model;
      }
      for (const x of o.message.content) {
        if (x.type === 'tool_use' || x.type === 'tool_call') {
          tools++;
        } else if (x.type === 'text' && x.text?.trim()) {
          lastText = x.text.trim();
        }
      }
    } else if (o.type === 'result') {
      finalEnv = o;
      if (typeof o.model === 'string' && o.model) {
        servedModel = o.model;
      }
    } else if (o.stats?.models) {
      finalEnv = o;
    }
  }

  let input_tokens = null;
  let output_tokens = null;
  let duration_ms = finalEnv?.duration_ms ?? null;
  
  if (finalEnv) {
    const stats = finalEnv.stats || {};
    const models = stats.models || {};
    const modelKeys = Object.keys(models);
    if (modelKeys.length > 0) {
      const modelStats = models[modelKeys[0]] || {};
      const tokens = modelStats.tokens || {};
      input_tokens = tokens.input || tokens.prompt || null;
      output_tokens = tokens.candidates || null;
      duration_ms = modelStats.api?.totalLatencyMs ?? duration_ms;
    }
  }

  const rec = {
    label,
    cli_status,
    ok: cli_status === 0,
    duration_ms,
    tools,
    output_tokens,
    input_tokens,
    cost_usd: finalEnv?.total_cost_usd ?? null,
    model_served: servedModel,
  };
  
  const text = finalEnv?.result ?? finalEnv?.response ?? lastText ?? '';
  return { text, rec };
}

export function defaultRunGemini(fullPrompt, label, {
  env = process.env,
  target = process.cwd(),
  log = () => {},
} = {}) {
  return new Promise((resolve) => {
    const args = ['--skip-trust', '-p', ' ', '--output-format', 'stream-json'];
    
    const mdl = env.GEMINI_MODEL || env.TRIO_MODEL;
    if (mdl) {
      args.push('-m', mdl);
    }
    
    const child = spawn('agy', args, { cwd: target, env, shell: false, windowsHide: true });
    
    let out = '', stderr = '';
    child.stdout.on('data', (d) => { out += d.toString(); });
    child.stderr.on('data', (d) => { stderr += d.toString(); });
    
    child.on('close', (code) => {
      const { text, rec } = parseGeminiFrames(out, { label, cli_status: code });
      if (code !== 0) {
        log(`!! ${label}: gemini exit ${code}. stderr=${stderr.slice(0, 300)}`);
      }
      resolve({ text, rec });
    });
    
    child.stdin.on('error', (err) => {
      log(`!! ${label}: stdin EPIPE - gemini likely exited early. err=${err.message}`);
    });
    
    child.stdin.write(fullPrompt);
    child.stdin.end();
  });
}

export function makeGeminiDriver(opts = {}) {
  const run = opts.runGemini || ((prompt, label) => defaultRunGemini(prompt, label, opts));
  const log = opts.log || (() => {});
  
  const agent = async (prompt, agentOpts = {}) => {
    const label = agentOpts.label || '(unlabeled)';
    const schemaSuffix = agentOpts.schema
      ? `\n\nRespond with ONLY a single raw JSON object (no markdown fences, no prose) ` +
        `that conforms to this JSON Schema:\n${JSON.stringify(agentOpts.schema)}`
      : '';
      
    const { text, rec } = await run(prompt + schemaSuffix, label);
    
    if (rec && opts.effortLog) {
      try {
        // Record latency and tokens to effort log if needed
      } catch (e) {}
    }
    
    if (!agentOpts.schema) return text;
    
    let obj = extractJson(text);
    if (!obj) {
      log(`   !! ${label} reply was not valid JSON — retrying once (strict reprompt)`);
      const strict = `${prompt}\n\nYour previous reply was NOT valid JSON. Respond with ONLY a single raw JSON ` +
        `object conforming to this JSON Schema — no prose, no fences:\n${JSON.stringify(agentOpts.schema)}`;
      const retryResult = await run(strict, `${label}#retry`);
      obj = extractJson(retryResult.text);
    }
    
    if (!obj) {
      log(`   !! ${label} still unparseable — ABSTAIN (answerable:no) → engine HALTs for human review`);
      return {
        answerable: 'no',
        note: `reviewer ${label} response was not parseable JSON after one retry — cannot verify findings; HALT for human review`,
        findings: []
      };
    }
    
    return obj;
  };
  
  return makeAgentDriver({ agent });
}

export default makeGeminiDriver;
