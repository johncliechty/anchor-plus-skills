function getContextExplanation(swarm) {
    if (!swarm || !swarm.processes || swarm.processes.length === 0) {
        return "No processes in swarm.";
    }
    const rule = swarm.violatedRule || "Unknown heuristic";
    return `Violation: ${rule}. This swarm contains ${swarm.processes.length} rogue processes that have been flagged for neutralization.`;
}

class BulkApprovalGUI {
    constructor(ipcClient = null) {
        this.swarms = [];
        this.openAccordionId = null;
        this.ipcClient = ipcClient; // For dispatching commands
    }

    setSwarms(swarms) {
        this.swarms = swarms;
    }

    toggleContext(swarmId) {
        if (this.openAccordionId === swarmId) {
            this.openAccordionId = null; // Auto-close if already open
        } else {
            this.openAccordionId = swarmId; // Auto-close others
        }
    }

    async dispatchKill(swarmId) {
        if (this.ipcClient) {
            // Dispatch the Soft Freeze/Kill command for the entire unified swarm
            return await this.ipcClient.send('kill_swarm', { swarmId });
        }
    }

    render() {
        let html = '<div class="collapsible-tree-view">\n';
        for (const swarm of this.swarms) {
            html += `  <div class="swarm-group" id="swarm-${swarm.id}">\n`;
            html += `    <div class="swarm-parent-row">\n`;
            html += `      <span class="swarm-name">${swarm.name}</span>\n`;
            html += `      <button class="kill-button" onclick="dispatchKill('${swarm.id}')">Kill</button>\n`;
            html += `      <button class="show-context-toggle" onclick="toggleContext('${swarm.id}')">Show Context</button>\n`;
            html += `    </div>\n`;
            
            if (this.openAccordionId === swarm.id) {
                html += `    <div class="inline-accordion context-explanation">\n`;
                html += `      ${getContextExplanation(swarm)}\n`;
                html += `    </div>\n`;
            }
            html += `  </div>\n`;
        }
        html += '</div>';
        return html;
    }
}

module.exports = { getContextExplanation, BulkApprovalGUI };
