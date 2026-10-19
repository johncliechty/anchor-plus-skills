import { parentPort, workerData } from 'node:worker_threads';

const intervalMs = workerData?.intervalMs || 60000;

let lastCpuUsage = process.cpuUsage();
let lastHrTime = process.hrtime.bigint();

const intervalId = setInterval(() => {
  const currentCpuUsage = process.cpuUsage();
  const currentHrTime = process.hrtime.bigint();
  
  const elapCpu = process.cpuUsage(lastCpuUsage);
  const elapTime = currentHrTime - lastHrTime; // nanoseconds
  
  const elapTimeUs = Number(elapTime) / 1000;
  let cpuUsagePercent = 0;
  if (elapTimeUs > 0) {
    cpuUsagePercent = ((elapCpu.user + elapCpu.system) / elapTimeUs) * 100;
  }
  
  const memoryUsage = process.memoryUsage().heapUsed;
  
  parentPort.postMessage({
    type: 'telemetry_tick',
    cpu: Math.min(100, Math.max(0, cpuUsagePercent)),
    memory: memoryUsage,
    timestamp: Date.now()
  });
  
  lastCpuUsage = currentCpuUsage;
  lastHrTime = currentHrTime;
}, intervalMs);

parentPort.on('message', (msg) => {
  if (msg === 'stop') {
    clearInterval(intervalId);
    process.exit(0);
  }
});
