import assert from "node:assert/strict";
import { ProviderHttpError } from "./providers/http.js";
import { ProviderRouter } from "./providers/router.js";
function provider(name, actions) {
    let index = 0;
    return {
        name,
        model: `${name}-sb021-selftest`,
        async runAgent(agent, task) {
            const action = actions[Math.min(index++, actions.length - 1)] ?? "ok";
            if (action === "server")
                throw new ProviderHttpError(name, 503, "temporary outage");
            if (action === "auth")
                throw new ProviderHttpError(name, 401, "invalid credential");
            return { text: `${agent}:${task}`, provider: name, model: this.model, latencyMs: 1 };
        }
    };
}
async function main() {
    const retryRouter = new ProviderRouter([provider("openai", ["server", "ok"]), provider("anthropic", ["ok"])], { strategy: ["openai", "anthropic"] }, { resilience: { retryBaseDelayMs: 0, maxAttemptsPerProvider: 2 } });
    const retryResult = await retryRouter.runAgent("strategy", "retry");
    assert.equal(retryResult.provider, "openai");
    assert.equal(retryResult.attempts, 2);
    const failoverRouter = new ProviderRouter([provider("openai", ["auth"]), provider("anthropic", ["ok"])], { strategy: ["openai", "anthropic"] }, { resilience: { retryBaseDelayMs: 0, maxAttemptsPerProvider: 3 } });
    const failoverResult = await failoverRouter.runAgent("strategy", "failover");
    assert.equal(failoverResult.provider, "anthropic");
    assert.equal(failoverResult.attempts, 2);
    const payload = {
        milestone: "SB-021",
        offline_resilience_selftest: "passed",
        retries: true,
        failover: true,
        terminal_auth_errors_are_not_retried: true,
        automatic_live_provider_claim: false
    };
    process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
}
main().catch(error => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
});
