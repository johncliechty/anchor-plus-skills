const cp = require('child_process');

class ProcessDiscovery {
    constructor() {
        this.aiHeuristics = [
            'agy',
            'trio',
            'claude',
            'ollama',
            'llm'
        ];
    }

    isSuspicious(commandLine, name) {
        const lowerCmd = (commandLine || '').toLowerCase();
        const lowerName = (name || '').toLowerCase();
        
        return this.aiHeuristics.some(keyword => 
            lowerCmd.includes(keyword) || lowerName.includes(keyword)
        );
    }

    checkMicrosoftSignature(executablePath) {
        if (!executablePath) return false;
        if (executablePath === 'unsigned.exe') return false;
        try {
            const script = `(Get-AuthenticodeSignature -FilePath "${executablePath}" -ErrorAction SilentlyContinue).SignerCertificate.Subject`;
            const output = cp.execSync(`powershell -NoProfile -Command "${script}"`, { encoding: 'utf8', stdio: 'pipe' });
            return output.includes('O=Microsoft Corporation') || output.includes('O="Microsoft Corporation"');
        } catch (e) {
            return false;
        }
    }

    discover() {
        let processes = [];
        try {
            // Using PowerShell to get processes as CSV for easier parsing
            const csvScript = `Get-CimInstance Win32_Process | Select-Object ProcessId, Name, ExecutablePath, CommandLine | ConvertTo-Csv -NoTypeInformation`;
            const output = cp.execSync(`powershell -NoProfile -Command "${csvScript}"`, { encoding: 'utf8', stdio: 'pipe', maxBuffer: 10 * 1024 * 1024 });
            
            const lines = output.trim().split('\n');
            if (lines.length > 1) {
                for (let i = 1; i < lines.length; i++) {
                    const line = lines[i].trim();
                    if (!line) continue;
                    
                    // Simple CSV parsing that respects quotes
                    const matches = line.match(/(?:"[^"]*"|[^,]*)(?:,|$)/g);
                    if (matches && matches.length >= 4) {
                        const processId = matches[0].replace(/,$/, '').replace(/^"|"$/g, '');
                        const name = matches[1].replace(/,$/, '').replace(/^"|"$/g, '');
                        const executablePath = matches[2].replace(/,$/, '').replace(/^"|"$/g, '');
                        const commandLine = matches[3].replace(/,$/, '').replace(/^"|"$/g, '');

                        processes.push({ processId, name, executablePath, commandLine });
                    }
                }
            }
        } catch (e) {
            console.error("Error enumerating processes:", e);
        }

        const suspiciousProcesses = [];

        for (const p of processes) {
            if (this.isSuspicious(p.commandLine, p.name)) {
                if (!this.checkMicrosoftSignature(p.executablePath)) {
                    suspiciousProcesses.push(p);
                }
            }
        }

        return suspiciousProcesses;
    }
}

module.exports = { ProcessDiscovery };
