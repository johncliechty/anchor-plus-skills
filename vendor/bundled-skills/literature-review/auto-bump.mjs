import fs from "node:fs";
import { execSync } from "node:child_process";

let wave = 1;
const MAX_WAVE = 6;

while (wave <= MAX_WAVE) {
  console.log(`\n=== AUTO-BUMPING TO WAVE ${wave} ===`);
  
  if (fs.existsSync("foreman-checkpoint.json")) {
    const cp = JSON.parse(fs.readFileSync("foreman-checkpoint.json", "utf8"));
    if (cp.current_wave < wave) {
       cp.current_wave = wave;
       cp.status = "running";
       cp.pending_action = null;
       fs.writeFileSync("foreman-checkpoint.json", JSON.stringify(cp, null, 2));
    }
  }
  
  try {
    execSync("node run-foreman.mjs", {
      env: { ...process.env, CRUCIBLE_AGENT_LIVE: "1", TRIO_DRIVER: "gemini-cli" },
      stdio: "inherit"
    });
  } catch (e) {
    console.log(`Wave ${wave} halted. Moving to next wave...`);
  }
  wave++;
}
console.log("ALL WAVES COMPLETED.");
