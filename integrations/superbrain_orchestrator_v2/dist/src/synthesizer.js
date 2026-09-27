export function synthesize(task, results, verification, disagreements) {
    const body = results
        .filter(r => !["critic", "verifier"].includes(r.agent))
        .map(r => `### ${r.agent}\n${r.output}`)
        .join("\n\n");
    const review = verification.verified
        ? `Verification passed (${Math.round(verification.confidence * 100)}% confidence).`
        : `Verification found issues: ${verification.issues.join("; ")}`;
    const disagreementText = disagreements.length
        ? `\n\nDisagreements:\n- ${disagreements.join("\n- ")}`
        : "";
    return `Task: ${task}\n\n${body}\n\n${review}${disagreementText}`;
}
