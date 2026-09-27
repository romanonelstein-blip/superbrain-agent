#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const contractPath = path.join(root, 'shared', 'superbrain-mobile-contract.json');
const packagePath = path.join(root, 'package.json');
const apiPath = path.join(root, 'ios', 'SuperBrainMobile', 'MissionAPI.swift');
const projectPath = path.join(root, 'ios', 'SuperBrainMobile.xcodeproj', 'project.pbxproj');
const outputPath = path.join(root, 'ios', 'SuperBrainMobile', 'SuperBrainContract.generated.swift');

const contract = JSON.parse(fs.readFileSync(contractPath, 'utf8'));
const pkg = JSON.parse(fs.readFileSync(packagePath, 'utf8'));
const apiSource = fs.readFileSync(apiPath, 'utf8');
const projectSource = fs.readFileSync(projectPath, 'utf8');

function fail(message) {
  console.error(`iOS sync error: ${message}`);
  process.exit(1);
}

if (!Number.isInteger(contract.schemaVersion) || contract.schemaVersion < 1) {
  fail('schemaVersion must be a positive integer.');
}
if (!contract.apiVersion || !contract.iosClientVersion) {
  fail('apiVersion and iosClientVersion are required.');
}
if (!Array.isArray(contract.capabilities) || contract.capabilities.length === 0) {
  fail('At least one mobile capability is required.');
}

const ids = new Set();
for (const capability of contract.capabilities) {
  if (!capability.id || !capability.title || !capability.kind || !capability.mobileSupport) {
    fail('Every capability needs id, title, kind and mobileSupport.');
  }
  if (ids.has(capability.id)) fail(`Duplicate capability id: ${capability.id}`);
  ids.add(capability.id);

  if (capability.required && capability.mobileSupport !== 'native') {
    fail(`Required capability ${capability.id} must have native iOS support.`);
  }
  if (capability.kind === 'endpoint') {
    if (!capability.endpoint || !capability.method || !capability.verificationToken) {
      fail(`Endpoint capability ${capability.id} is incomplete.`);
    }
    if (!apiSource.includes(capability.verificationToken)) {
      fail(`MissionAPI.swift does not contain integration token for ${capability.id}: ${capability.verificationToken}`);
    }
  }

  if (capability.verificationFile || capability.verificationToken) {
    if (!capability.verificationFile || !capability.verificationToken) {
      fail(`Capability ${capability.id} must define verificationFile and verificationToken together.`);
    }
    const verificationPath = path.join(root, capability.verificationFile);
    if (!fs.existsSync(verificationPath)) {
      fail(`Verification file is missing for ${capability.id}: ${capability.verificationFile}`);
    }
    const verificationSource = fs.readFileSync(verificationPath, 'utf8');
    if (!verificationSource.includes(capability.verificationToken)) {
      fail(`${capability.verificationFile} does not contain verification token for ${capability.id}: ${capability.verificationToken}`);
    }
  }
}

const versionMatches = [...projectSource.matchAll(/MARKETING_VERSION = ([^;]+);/g)].map(match => match[1]);
if (versionMatches.length === 0 || versionMatches.some(version => version !== contract.iosClientVersion)) {
  fail(`Xcode MARKETING_VERSION must equal contract iosClientVersion ${contract.iosClientVersion}.`);
}

const swiftString = value => JSON.stringify(String(value));
const capabilities = contract.capabilities.map(capability => `        BundledCapability(
            id: ${swiftString(capability.id)},
            title: ${swiftString(capability.title)},
            kind: ${swiftString(capability.kind)},
            method: ${capability.method ? swiftString(capability.method) : 'nil'},
            endpoint: ${capability.endpoint ? swiftString(capability.endpoint) : 'nil'},
            mobileSupport: ${swiftString(capability.mobileSupport)},
            required: ${capability.required === true ? 'true' : 'false'}
        )`).join(',\n');

const generated = `// GENERATED FILE. DO NOT EDIT.
// Source: shared/superbrain-mobile-contract.json + package.json
import Foundation

struct BundledCapability: Identifiable, Hashable {
    let id: String
    let title: String
    let kind: String
    let method: String?
    let endpoint: String?
    let mobileSupport: String
    let required: Bool
}

enum SuperBrainContract {
    static let schemaVersion = ${contract.schemaVersion}
    static let coreVersion = ${swiftString(pkg.version)}
    static let apiVersion = ${swiftString(contract.apiVersion)}
    static let iosClientVersion = ${swiftString(contract.iosClientVersion)}

    static let capabilities: [BundledCapability] = [
${capabilities}
    ]

    static let requiredCapabilityIDs = Set(capabilities.filter(\\.required).map(\\.id))
}
`;

const check = process.argv.includes('--check');
if (check) {
  if (!fs.existsSync(outputPath)) fail('Generated Swift contract is missing. Run npm run ios:sync.');
  const existing = fs.readFileSync(outputPath, 'utf8');
  if (existing !== generated) fail('Generated Swift contract is stale. Run npm run ios:sync.');
  console.log(`iOS contract is synchronized: SuperBrain ${pkg.version}, iOS ${contract.iosClientVersion}, ${contract.capabilities.length} capabilities.`);
} else {
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, generated);
  console.log(`Updated ${path.relative(root, outputPath)}.`);
}
