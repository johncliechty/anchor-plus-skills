class ForensicsAnalyzer {
    constructor(daemon) {
        this.daemon = daemon;
        this.pastZombies = [];
        this.isAnalyzing = false;
        
        // Resource limits
        this.MAX_CPU_PERCENT = 5;
        this.MAX_RAM_MB = 250;
    }

    analyzeHistoricalData() {
        if (this.isAnalyzing) return;
        this.isAnalyzing = true;
        
        const allRecords = this.daemon.getSuspicious(); 
        
        // Group into 1-hour chunk windows
        // record.timestamp is typically "YYYY-MM-DD HH:MM:SS"
        const chunks = {};
        for (const record of allRecords) {
            if (!record.timestamp) continue;
            // The first 13 characters represent "YYYY-MM-DD HH"
            const chunkKey = record.timestamp.substring(0, 13);
            
            if (!chunks[chunkKey]) chunks[chunkKey] = [];
            chunks[chunkKey].push(record);
        }
        
        for (const [chunk, records] of Object.entries(chunks)) {
            // Correlate within the chunk to find swarms
            const swarms = {};
            for (const record of records) {
                const swarmKey = `${record.name}|${record.executablePath}`;
                if (!swarms[swarmKey]) swarms[swarmKey] = [];
                swarms[swarmKey].push(record);
            }
            
            for (const [key, swarmRecords] of Object.entries(swarms)) {
                // If there are multiple instances in this hour, consider it a past zombie swarm
                if (swarmRecords.length >= 2) { 
                    this.pastZombies.push({
                        id: `swarm-${chunk}-${swarmRecords[0].name}`.replace(/[^a-zA-Z0-9-]/g, '-'),
                        name: swarmRecords[0].name,
                        processCount: swarmRecords.length,
                        chunkWindow: chunk,
                        firstSeen: swarmRecords[0].timestamp,
                        lastSeen: swarmRecords[swarmRecords.length - 1].timestamp
                    });
                }
            }
        }
        
        this.isAnalyzing = false;
        return this.pastZombies;
    }
    
    // Validates that the offline analysis background thread is staying within bounds
    checkResourceLimits(currentCpuPercent, currentRamMb) {
        return currentCpuPercent <= this.MAX_CPU_PERCENT && currentRamMb <= this.MAX_RAM_MB;
    }
}

class ForensicsGUI {
    constructor() {
        this.zombies = [];
    }

    setZombies(zombies) {
        this.zombies = zombies;
    }

    render() {
        let html = '<div class="retrospective-analysis-view">\n';
        html += '  <h2>Historical Forensics</h2>\n';
        if (this.zombies.length === 0) {
            html += '  <p>No past zombies identified.</p>\n';
        } else {
            for (const zombie of this.zombies) {
                html += `  <div class="past-zombie" id="${zombie.id}">\n`;
                html += `    <span class="zombie-name">${zombie.name}</span>\n`;
                html += `    <span class="zombie-count">Processes: ${zombie.processCount}</span>\n`;
                html += `    <span class="zombie-window">Window: ${zombie.chunkWindow}:00</span>\n`;
                html += `  </div>\n`;
            }
        }
        html += '</div>';
        return html;
    }
}

// ── Incident collapsing + pressure timeline (human-meaningful forensics) ──
// The raw hourly list (one row per swarm per hour) is a wall of noise. These
// helpers fold consecutive hours of the same swarm into ONE incident (span +
// peak + duration + severity) and roll the whole history into a per-day peak.

function buildIncidents(pastZombies) {
  // pastZombies: [{ name, processCount, chunkWindow: "YYYY-MM-DD HH", ... }]
  const byName = {};
  for (const z of pastZombies || []) {
    (byName[z.name] ??= []).push(z);
  }
  const incidents = [];
  for (const [name, rows] of Object.entries(byName)) {
    rows.sort((a, b) => (a.chunkWindow < b.chunkWindow ? -1 : 1));
    let cur = null;
    const hourMs = 3600 * 1000;
    const toDate = (w) => new Date(w.replace(' ', 'T') + ':00:00');
    for (const r of rows) {
      if (cur && (toDate(r.chunkWindow) - toDate(cur.endWindow)) <= 2 * hourMs) {
        cur.endWindow = r.chunkWindow;
        cur.hours += 1;
        cur.peak = Math.max(cur.peak, r.processCount);
      } else {
        if (cur) incidents.push(cur);
        cur = { name, startWindow: r.chunkWindow, endWindow: r.chunkWindow, hours: 1, peak: r.processCount };
      }
    }
    if (cur) incidents.push(cur);
  }
  for (const inc of incidents) {
    const score = inc.peak * inc.hours;
    inc.severity = score >= 1000 ? 'critical' : score >= 120 ? 'moderate' : 'low';
    inc.score = score;
  }
  // worst first
  incidents.sort((a, b) => b.score - a.score);
  return incidents;
}

function buildPressure(pastZombies, days = 7) {
  // per-day peak process count, oldest→newest, last `days` days
  const byDay = {};
  for (const z of pastZombies || []) {
    const day = (z.chunkWindow || '').slice(0, 10);
    if (!day) continue;
    byDay[day] = Math.max(byDay[day] || 0, z.processCount);
  }
  return Object.entries(byDay)
    .map(([day, peak]) => ({ day, peak }))
    .sort((a, b) => (a.day < b.day ? -1 : 1))
    .slice(-days);
}

module.exports = { ForensicsAnalyzer, ForensicsGUI, buildIncidents, buildPressure };
