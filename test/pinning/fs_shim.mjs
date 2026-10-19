export class FsShim {
    constructor() {
        this.calls = [];
        this.files = new Map();
        this._errorMocks = {};
    }

    record(method, args) {
        this.calls.push({ method, args });
    }

    async open(path, flags) {
        this.record('open', [path, flags]);
        if (flags === 'wx' && this.files.has(path)) {
            const e = new Error('EEXIST');
            e.code = 'EEXIST';
            throw e;
        }
        if (flags === 'wx' || flags === 'w') {
            this.files.set(path, '');
        }
        return {
            write: async (data) => {
                this.record('write', [path, data]);
                if (flags === 'wx' || flags === 'w') {
                    this.files.set(path, data);
                }
            },
            fsync: async () => {
                this.record('fsync', [path]);
                if (this._errorMocks.fsync) {
                    const err = this._errorMocks.fsync(path);
                    if (err) throw err;
                }
            },
            close: async () => {
                this.record('close', [path]);
            }
        };
    }

    async rename(oldPath, newPath) {
        this.record('rename', [oldPath, newPath]);
        if (this._errorMocks.rename) {
            const err = this._errorMocks.rename(oldPath, newPath);
            if (err) throw err;
        }
        if (this.files.has(oldPath)) {
            this.files.set(newPath, this.files.get(oldPath));
            this.files.delete(oldPath);
        }
    }

    async rm(path, options = {}) {
        this.record('rm', [path, options]);
        if (this._errorMocks.rm) {
            const err = this._errorMocks.rm(path, options);
            if (err) throw err;
        }
        this.files.delete(path);
        for (const [key] of this.files.entries()) {
            if (key.startsWith(path + '/')) {
                this.files.delete(key);
            }
        }
    }

    async unlink(path) {
        this.record('unlink', [path]);
        this.files.delete(path);
    }

    async appendFile(path, data) {
        this.record('appendFile', [path, data]);
        const current = this.files.get(path) || '';
        this.files.set(path, current + data);
    }

    async readFile(path, encoding) {
        this.record('readFile', [path, encoding]);
        if (!this.files.has(path)) {
            const e = new Error('ENOENT');
            e.code = 'ENOENT';
            throw e;
        }
        return this.files.get(path);
    }

    mockError(method, fn) {
        this._errorMocks[method] = fn;
    }
}
