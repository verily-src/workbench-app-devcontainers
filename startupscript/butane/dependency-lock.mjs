#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const versions = ['flatcar', 'devcontainer_cli', 'compose', 'buildx', 'nvidia_driver', 'nvidia_runtime', 'node'];
const artifacts = ['devcontainer_cli', 'compose', 'buildx', 'nvidia_runtime', 'node'];
const referencePattern = /([\w./:-]+)@(sha256:[a-f0-9]{64})/g;
const versionPattern = /^\d+\.\d+\.\d+$/;
const digestPattern = /^sha256:[a-f0-9]{64}$/;
const readJSON = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const sortedObject = value => Object.entries(value ?? {}).sort(([a], [b]) => a.localeCompare(b));
const key = row => `${row.file}\0${row.reference}`;

function requireValue(condition, message) {
  if (!condition) throw new Error(message);
}

function safeFile(root, relative) {
  requireValue(typeof relative === 'string' && /^(src|features|startupscript)\//.test(relative), 'invalid covered file');
  requireValue(!relative.split('/').includes('..') && !relative.includes('\\'), 'invalid covered path');
  const target = path.resolve(root, relative);
  requireValue(target.startsWith(path.resolve(root) + path.sep), 'covered path escapes repository');
  requireValue(fs.realpathSync(target) === target && fs.statSync(target).isFile(), `covered file is not a regular file: ${relative}`);
  return target;
}

export function collectDigests(root) {
  root = fs.realpathSync(root);
  const files = execFileSync('git', ['-C', root, 'ls-files', '-z', 'src', 'features', 'startupscript'], {encoding: 'utf8'}).split('\0').filter(Boolean);
  const found = new Map();
  for (const file of files) {
    if (!/\.(jsonc?|ya?ml|sh)$/.test(file) && !path.basename(file).includes('Dockerfile')) continue;
    const content = fs.readFileSync(safeFile(root, file), 'utf8');
    for (const match of content.matchAll(referencePattern)) {
      const row = {file, reference: match[1], digest: match[2]};
      requireValue(!found.has(key(row)) || found.get(key(row)).digest === row.digest, `conflicting digest selector: ${file} ${row.reference}`);
      found.set(key(row), row);
    }
  }
  return [...found.values()].sort((a, b) => key(a).localeCompare(key(b)));
}

export function validateLock(lock) {
  requireValue(lock?.schema_version === 1 && lock.source_contract === 1, 'unsupported dependency lock contract');
  requireValue(Object.keys(lock).every(k => ['schema_version', 'source_contract', 'host_versions', 'host_artifacts', 'digests', 'unpinned_risks'].includes(k)), 'unknown dependency lock field');
  requireValue(lock.host_versions && Object.keys(lock.host_versions).length === versions.length, 'all host versions are required');
  for (const name of versions) requireValue(versionPattern.test(lock.host_versions[name]), `invalid ${name} version`);
  requireValue(lock.host_artifacts && Object.keys(lock.host_artifacts).length === artifacts.length, 'all host artifacts are required');
  for (const name of artifacts) {
    const artifact = lock.host_artifacts[name];
    requireValue(artifact && typeof artifact === 'object', `missing ${name} artifact`);
    if (name === 'devcontainer_cli') {
      const native = artifact.package_lock_json;
      requireValue(native?.lockfileVersion === 3 && native.packages?.['node_modules/@devcontainers/cli']?.version === lock.host_versions.devcontainer_cli, 'CLI native lock disagrees with selected version');
      requireValue(JSON.stringify(sortedObject(artifact.package_json?.dependencies)) === JSON.stringify(sortedObject(native.packages?.['']?.dependencies)), 'CLI package.json disagrees with native lock');
      requireValue(Object.keys(artifact.package_json.dependencies).sort().join(',') === '@devcontainers/cli,jsonc-parser', 'CLI lock must contain only host installer dependencies');
      for (const [location, dependency] of Object.entries(native.packages)) {
        if (!location) continue;
        requireValue(typeof dependency.integrity === 'string' && /^sha(256|512)-/.test(dependency.integrity), `missing npm integrity: ${location}`);
        requireValue(dependency.resolved?.startsWith('https://registry.npmjs.org/'), `unsupported npm source: ${location}`);
      }
    } else {
      const url = new URL(artifact.url);
      requireValue(url.protocol === 'https:' && !url.username && !url.password && !url.hash, `invalid ${name} artifact URL`);
      requireValue(/^[a-f0-9]{64}$/.test(artifact.sha256), `invalid ${name} artifact checksum`);
    }
  }
  requireValue(Array.isArray(lock.digests) && lock.digests.length > 0, 'digest selectors are required');
  const keys = new Set();
  for (const row of lock.digests) {
    requireValue(row && typeof row.file === 'string' && /^(src|features|startupscript)\//.test(row.file) && !row.file.split('/').includes('..') && !row.file.includes('\\'), 'invalid digest file');
    requireValue(typeof row.reference === 'string' && /^[\w./:-]+$/.test(row.reference) && digestPattern.test(row.digest), 'invalid OCI digest');
    requireValue(!keys.has(key(row)), 'duplicate digest selector');
    keys.add(key(row));
  }
  requireValue(Array.isArray(lock.unpinned_risks) && lock.unpinned_risks.every(value => typeof value === 'string'), 'unpinned risks must be strings');
  return lock;
}

export function exportLock(root, host) {
  const install = fs.readFileSync(path.join(root, 'startupscript/butane/010-install-node.sh'), 'utf8');
  const nodeVersion = install.match(/NODE_VERSION="v([\d.]+)"/)?.[1];
  const nodeChecksum = install.match(/(?:NODE_SHA256=")?([a-f0-9]{64})/)?.[1];
  const native = readJSON(path.join(root, 'startupscript/butane/package-lock.json'));
  return validateLock({
    schema_version: 1, source_contract: 1,
    host_versions: {node: nodeVersion, devcontainer_cli: native.packages['node_modules/@devcontainers/cli'].version, ...host.host_versions},
    host_artifacts: {node: {url: `https://storage.googleapis.com/bkt-workbench-artifacts/mirror/node-v${nodeVersion}-linux-x64.tar.gz`, sha256: nodeChecksum},
      devcontainer_cli: {package_json: readJSON(path.join(root, 'startupscript/butane/package.json')), package_lock_json: native}, ...host.host_artifacts},
    digests: collectDigests(root),
    unpinned_risks: ['In-container APT/APK/DNF/Conda/pip/npm installs are outside this lock.', 'Mutable tags and downloads outside the covered host artifacts and existing OCI digests may drift.'],
  });
}

export function applyHostLock(lock, hostDirectory) {
  validateLock(lock);
  hostDirectory = fs.realpathSync(hostDirectory);
  const selected = lock.digests.filter(row => row.file.startsWith('startupscript/butane/'));
  const changes = new Map();
  for (const row of selected) {
    requireValue(row.file.endsWith('.sh'), 'unsupported host digest selector');
    const target = path.join(hostDirectory, path.basename(row.file).replace(/^\d{3}-/, ''));
    requireValue(fs.realpathSync(target) === target && fs.statSync(target).isFile(), `invalid installed host script: ${target}`);
    const content = changes.get(target) ?? fs.readFileSync(target, 'utf8');
    const references = [...content.matchAll(referencePattern)];
    requireValue(references.some(match => match[1] === row.reference), `host digest contract changed: ${target}`);
    requireValue(references.every(match => selected.some(pin => pin.file === row.file && pin.reference === match[1])), `new host digest contract: ${target}`);
    changes.set(target, content.replace(referencePattern, (whole, reference, digest) => reference === row.reference ? `${reference}@${row.digest}` : whole));
  }
  for (const [target, content] of changes) {
    const temporary = `${target}.dependency-lock-${process.pid}`;
    fs.writeFileSync(temporary, content, {mode: fs.statSync(target).mode});
    fs.renameSync(temporary, target);
  }
  return {files: changes.size, digests: selected.length};
}

export function applyLock(root, lock, hostDirectory) {
  root = fs.realpathSync(root);
  if (hostDirectory) hostDirectory = fs.realpathSync(hostDirectory);
  validateLock(lock);
  const current = collectDigests(root);
  const selected = new Map(lock.digests.map(row => [key(row), row]));
  requireValue(current.length === selected.size && current.every(row => selected.has(key(row))), 'source digest contract changed; test and promote a new weekly lock');
  const changes = new Map();
  for (const row of current) {
    const file = safeFile(root, row.file);
    const content = changes.get(file) ?? fs.readFileSync(file, 'utf8');
    changes.set(file, content.split(`${row.reference}@${row.digest}`).join(`${row.reference}@${selected.get(key(row)).digest}`));
  }
  if (hostDirectory) {
    for (const [file, content] of [...changes]) {
      const relative = path.relative(root, file);
      if (!relative.startsWith('startupscript/butane/') || !relative.endsWith('.sh')) continue;
      const target = path.join(hostDirectory, path.basename(relative).replace(/^\d{3}-/, ''));
      requireValue(fs.existsSync(target) && fs.realpathSync(target) === path.resolve(target), `installed host script missing: ${target}`);
      const hostContent = fs.readFileSync(target, 'utf8');
      const original = fs.readFileSync(file, 'utf8');
      requireValue(hostContent === original || hostContent === content, `installed host script differs from selected source: ${target}`);
      changes.set(target, content);
    }
  }
  for (const [file, content] of changes) {
    const mode = fs.statSync(file).mode;
    const temporary = `${file}.dependency-lock-${process.pid}`;
    fs.writeFileSync(temporary, content, {mode});
    fs.renameSync(temporary, file);
  }
  return {files: changes.size, digests: current.length};
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const [command, ...args] = process.argv.slice(2);
    if (command === 'export' && args.length === 3) {
      fs.writeFileSync(args[2], JSON.stringify(exportLock(path.resolve(args[0]), readJSON(args[1])), null, 2) + '\n');
    } else if (command === 'validate' && args.length === 1) {
      validateLock(readJSON(args[0]));
    } else if (command === 'apply-host' && args.length === 2) {
      console.log(JSON.stringify(applyHostLock(readJSON(args[0]), args[1])));
    } else if (command === 'apply' && (args.length === 2 || args.length === 3)) {
      console.log(JSON.stringify(applyLock(path.resolve(args[0]), readJSON(args[1]), args[2])));
    } else {
      throw new Error('usage: dependency-lock.mjs export ROOT HOST_JSON OUTPUT | validate LOCK | apply-host LOCK HOST_DIR | apply ROOT LOCK [HOST_DIR]');
    }
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
