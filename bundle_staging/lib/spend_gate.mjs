export class LimitExceeded extends Error {
    constructor(message) {
        super(message);
        this.name = 'LimitExceeded';
    }
}

export class SpendGate {
    constructor({ maxTokens, maxDollars }) {
        this.maxTokens = maxTokens;
        this.maxDollars = maxDollars;
        this.spentTokens = 0;
        this.spentDollars = 0;
    }

    recordSpend(tokens, dollars) {
        if (this.maxTokens !== undefined && this.spentTokens + tokens > this.maxTokens) {
            throw new LimitExceeded('Token limit exceeded');
        }
        if (this.maxDollars !== undefined && this.spentDollars + dollars > this.maxDollars) {
            throw new LimitExceeded('Dollar limit exceeded');
        }
        this.spentTokens += tokens;
        this.spentDollars += dollars;
    }
}

export function scrubCredentials(env) {
    if (env.CRUCIBLE_ALLOW_SPEND !== '1') {
        delete env.ANTHROPIC_API_KEY;
        delete env.OPENAI_API_KEY;
        delete env.GEMINI_API_KEY;
    }
}

export function logCredentialSource(driverName, source) {
    // Console log to satisfy "every driver logs its resolved credential source at init"
    console.log(`[${driverName}] Credential source: ${source}`);
}
