import { createProviderRouterFromEnv } from "./providers/factory.js";
import { runNexusProviderMission } from "./nexus-bridge.js";
async function readInput() {
    const chunks = [];
    for await (const chunk of process.stdin)
        chunks.push(Buffer.from(chunk));
    return Buffer.concat(chunks).toString("utf8");
}
async function main() {
    const request = JSON.parse(await readInput());
    if (!request.task || typeof request.task !== "string") {
        throw new Error("A non-empty task string is required.");
    }
    const result = await runNexusProviderMission(createProviderRouterFromEnv(), request);
    process.stdout.write(JSON.stringify(result));
}
main().catch(error => {
    const message = error instanceof Error ? error.message : String(error);
    process.stderr.write(`Provider bridge failed: ${message}\n`);
    process.exitCode = 1;
});
