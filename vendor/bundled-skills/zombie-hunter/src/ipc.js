const net = require('net');

class IPCServer {
    constructor(daemon, pipeName = '\\\\.\\pipe\\zombie-hunter-ipc') {
        this.daemon = daemon;
        this.pipeName = pipeName;
        this.server = net.createServer((stream) => {
            stream.on('data', (data) => {
                try {
                    const req = JSON.parse(data.toString());
                    if (req.command === 'relaunch_sweep') {
                        if (this.daemon.discoveryModule) {
                            const processes = this.daemon.discoveryModule.discover();
                            for (const p of processes) {
                                this.daemon.logSuspicious(p);
                            }
                        }
                        const suspicious = this.daemon.getSuspicious();
                        stream.write(JSON.stringify({ status: 'ok', data: suspicious }));
                        stream.end();
                    }
                } catch (e) {
                    stream.write(JSON.stringify({ status: 'error', message: e.message }));
                    stream.end();
                }
            });
        });
    }

    start() {
        return new Promise((resolve) => {
            this.server.listen(this.pipeName, () => {
                resolve();
            });
        });
    }

    stop() {
        return new Promise((resolve) => {
            this.server.close(() => {
                resolve();
            });
        });
    }
}

class IPCClient {
    constructor(pipeName = '\\\\.\\pipe\\zombie-hunter-ipc') {
        this.pipeName = pipeName;
    }

    send(command, payload = {}) {
        return new Promise((resolve, reject) => {
            const client = net.createConnection(this.pipeName, () => {
                client.write(JSON.stringify({ command, ...payload }));
            });

            let data = '';
            client.on('data', (chunk) => {
                data += chunk.toString();
            });

            client.on('end', () => {
                try {
                    resolve(JSON.parse(data));
                } catch (e) {
                    reject(e);
                }
            });

            client.on('error', (err) => {
                reject(err);
            });
        });
    }
}

module.exports = { IPCServer, IPCClient };
