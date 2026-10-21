import { createHmac, timingSafeEqual } from 'node:crypto';
import type { SkillMasterAuthorization, SkillMasterVerifier } from '../core/skill-runtime.js';

export type AuthorizedMasterCheck =
  (actorId: string, workspaceId: string) => Promise<boolean>;

// No signing endpoint is exposed here. Only the authenticated human approval
// service may issue a proof. A bearer token from Mission Control is insufficient.
export class HmacSkillMasterVerifier implements SkillMasterVerifier {
  private readonly key: Buffer;

  constructor(
    secret: Buffer,
    private readonly isAuthorizedMaster: AuthorizedMasterCheck,
  ) {
    if (secret.byteLength < 32 || typeof isAuthorizedMaster !== 'function') {
      throw new Error('Master verifier needs a 256-bit secret and an authoritative role check.');
    }
    this.key = Buffer.from(secret);
  }

  async verify(approval: Readonly<SkillMasterAuthorization>): Promise<boolean> {
    if (approval.action !== 'ACCEPT' ||
        !approval.actorId.trim() || !approval.workspaceId.trim() ||
        !/^[a-f0-9]{64}$/i.test(approval.intentDigest) ||
        !/^[a-f0-9]{64}$/i.test(approval.proof)) {
      return false;
    }
    const payload = JSON.stringify([
      'superbrain-skill-master-v1',
      approval.action, approval.actorId, approval.workspaceId,
      approval.planId, approval.intentDigest, approval.expiresAt,
    ]);
    const expected = createHmac('sha256', this.key).update(payload).digest();
    const supplied = Buffer.from(approval.proof, 'hex');
    if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) {
      return false;
    }
    // Resolve actual human membership/role on each verification; a static
    // cached flag or an LLM-generated ACCEPT note may never establish authority.
    return this.isAuthorizedMaster(approval.actorId, approval.workspaceId);
  }
}
