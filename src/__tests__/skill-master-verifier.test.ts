import { createHmac } from 'node:crypto';
import { jest } from '@jest/globals';
import { HmacSkillMasterVerifier } from '../workflow/skill-master-verifier';
import type { SkillMasterAuthorization } from '../core/skill-runtime';

const KEY = Buffer.from('superbrain-master-fixture-key-minimum-32-bytes', 'utf8');
const approved: SkillMasterAuthorization = {
  action: 'ACCEPT',
  actorId: 'human-owner',
  workspaceId: 'authorized-workspace',
  planId: 'one-time-plan',
  intentDigest: 'a'.repeat(64),
  expiresAt: '2026-10-21T13:00:00.000Z',
  proof: '',
};

function sign(input: SkillMasterAuthorization): SkillMasterAuthorization {
  const payload = JSON.stringify([
    'superbrain-skill-master-v1',
    input.action, input.actorId, input.workspaceId,
    input.planId, input.intentDigest, input.expiresAt,
  ]);
  return { ...input, proof: createHmac('sha256', KEY).update(payload).digest('hex') };
}

describe('HmacSkillMasterVerifier', () => {
  test('rejects insufficient secret strength', () => {
    expect(() => new HmacSkillMasterVerifier(Buffer.from('short'), async () => true))
      .toThrow('256-bit');
  });

  test('accepts correctly signed exact intent only for a currently authorized Master', async () => {
    const roleCheck = jest.fn(async (actorId: string, workspaceId: string) =>
      actorId === 'human-owner' && workspaceId === 'authorized-workspace');
    const verifier = new HmacSkillMasterVerifier(KEY, roleCheck);
    expect(await verifier.verify(sign(approved))).toBe(true);
    expect(roleCheck).toHaveBeenCalledWith('human-owner', 'authorized-workspace');
  });

  test.each(['workspaceId', 'actorId', 'planId', 'intentDigest', 'expiresAt'] as const)(
    'rejects a signature replay after changing %s', async field => {
      const verifier = new HmacSkillMasterVerifier(KEY, async () => true);
      const original = sign(approved);
      const changed = { ...original, [field]: field === 'intentDigest' ? 'b'.repeat(64) : 'different' };
      expect(await verifier.verify(changed)).toBe(false);
    },
  );

  test('rejects unsigned approval and mistaken Mobile Control ACCEPT', async () => {
    const verifier = new HmacSkillMasterVerifier(KEY, async () => true);
    expect(await verifier.verify(approved)).toBe(false);
    expect(await verifier.verify({ ...approved, proof: 'f'.repeat(64) })).toBe(false);
  });

  test('blocks a valid signature if current Master membership is revoked', async () => {
    const verifier = new HmacSkillMasterVerifier(KEY, async () => false);
    expect(await verifier.verify(sign(approved))).toBe(false);
  });

  test('blocks signed OVERRIDE even if it is from the rightful human', async () => {
    const verifier = new HmacSkillMasterVerifier(KEY, async () => true);
    expect(await verifier.verify(sign({ ...approved, action: 'OVERRIDE' }))).toBe(false);
  });
});
