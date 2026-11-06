import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { parseSkillManifest } from '../core/skill-foundry';

const ROOT = join(process.cwd(), 'skills');
const EXPECTED = [
  'verified-skill-intake',
  'nexus-evidence-verification',
  'agent-evaluation-lab',
  'commercial-signal-fusion',
  'saas-release-guardian',
  'marketplace-trust-pilot',
];

describe('bundled Agent Skills format', () => {
  test('contains exactly six original, portable skill packages', () => {
    const names = readdirSync(ROOT)
      .filter(name => statSync(join(ROOT, name)).isDirectory());
    expect(names.sort()).toEqual([...EXPECTED].sort());
  });

  test.each(EXPECTED)('%s has valid name, description and no broken local references', name => {
    const folder = join(ROOT, name);
    const content = readFileSync(join(folder, 'SKILL.md'), 'utf8');
    const manifest = parseSkillManifest(content, name);
    expect(manifest.name).toBe(name);
    expect(manifest.description.length).toBeGreaterThan(15);

    const referencePattern = /\]\((references\/[^)]+)\)/g;
    for (const match of content.matchAll(referencePattern)) {
      const relativeReference = match[1];
      expect(relativeReference).toBeDefined();
      if (relativeReference) {
        expect(existsSync(join(folder, relativeReference))).toBe(true);
      }
    }
  });

  test('all skills are instructions rather than executable directories', () => {
    for (const name of EXPECTED) {
      expect(existsSync(join(ROOT, name, 'scripts'))).toBe(false);
    }
  });
});
