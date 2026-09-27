import { describe, it } from "node:test";
import assert from "node:assert/strict";

function hasProperty(value: unknown, key: string): boolean {
  if (value === null || value === undefined) return false;
  return key.split(".").every((part, index, parts) => {
    let current: any = value;
    for (let i = 0; i <= index; i++) {
      if (current === null || current === undefined || !(parts[i] in Object(current))) return false;
      current = current[parts[i]];
    }
    return true;
  });
}

function partialMatch(actual: any, expected: any): void {
  if (expected && typeof expected === "object" && !Array.isArray(expected)) {
    assert.ok(actual && typeof actual === "object", "actual is not an object");
    for (const [key, value] of Object.entries(expected)) {
      assert.ok(key in actual, `missing property: ${key}`);
      partialMatch(actual[key], value);
    }
    return;
  }
  assert.deepStrictEqual(actual, expected);
}

function syncMatchers(actual: any) {
  return {
    toBe(expected: any) { assert.strictEqual(actual, expected); },
    toEqual(expected: any) { assert.deepStrictEqual(actual, expected); },
    toMatchObject(expected: any) { partialMatch(actual, expected); },
    toHaveLength(expected: number) { assert.strictEqual(actual?.length, expected); },
    toHaveProperty(key: string) { assert.ok(hasProperty(actual, key), `expected property ${key}`); },
    toContain(expected: any) {
      if (typeof actual === "string") assert.ok(actual.includes(expected));
      else assert.ok(actual?.includes?.(expected));
    },
    toBeGreaterThan(expected: number) { assert.ok(actual > expected, `${actual} is not > ${expected}`); },
    toThrow(expected?: RegExp | string) {
      let thrown: unknown;
      try { actual(); } catch (error) { thrown = error; }
      assert.ok(thrown, "expected function to throw");
      if (expected) {
        const message = thrown instanceof Error ? thrown.message : String(thrown);
        const pattern = expected instanceof RegExp ? expected : new RegExp(expected);
        assert.match(message, pattern);
      }
    }
  };
}

export function expect(actual: any) {
  const positive = syncMatchers(actual);
  const negative = {
    toHaveProperty(key: string) { assert.ok(!hasProperty(actual, key), `did not expect property ${key}`); },
    toContain(expected: any) {
      if (typeof actual === "string") assert.ok(!actual.includes(expected));
      else assert.ok(!actual?.includes?.(expected));
    }
  };
  const rejects = {
    async toThrow(expected?: RegExp | string) {
      let thrown: unknown;
      try { await actual; } catch (error) { thrown = error; }
      assert.ok(thrown, "expected promise to reject");
      if (expected) {
        const message = thrown instanceof Error ? thrown.message : String(thrown);
        const pattern = expected instanceof RegExp ? expected : new RegExp(expected);
        assert.match(message, pattern);
      }
    }
  };
  return { ...positive, not: negative, rejects };
}

export { describe, it };
