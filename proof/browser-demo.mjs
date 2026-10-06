import { createRequire } from 'node:module';
import { spawnSync } from 'node:child_process';
import { mkdir, copyFile, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(process.env.PROOF_PLAYWRIGHT_PACKAGE || path.join(root, 'frontend', 'package.json'));
const { chromium } = require('playwright');
const { expect } = require('@playwright/test');
const compose = process.argv.includes('--compose');
const out = path.join(root, 'proof-results', 'browser');
await mkdir(out, { recursive: true });
const credentials = compose
  ? Object.fromEntries((await readFile(path.join(root, '.env.proof'), 'utf8')).trim().split(/\r?\n/).map(line => {
    const split = line.indexOf('='); return [line.slice(0, split), line.slice(split + 1)];
  }))
  : process.env;

function step(name) {
  const executable = compose ? 'docker' : process.env.PROOF_PYTHON || path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const args = compose
    ? ['compose', '--env-file', '.env.proof', '-f', 'compose.proof.yml', 'exec', '-T', '-e', 'PROOF_API_URL=http://api:8000', 'api', 'python', '/src/proof/demo_step.py', name]
    : [path.join(root, 'proof', 'demo_step.py'), name];
  const result = spawnSync(executable, args, { cwd: compose ? root : path.join(root, 'backend'), encoding: 'utf8', env: process.env, timeout: 30_000 });
  if (result.status !== 0) throw new Error(`Controlled ${name} step failed: ${result.error?.message || result.stderr}`);
  console.log(name, result.stdout.trim());
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 960 }, recordVideo: { dir: out, size: { width: 1440, height: 960 } } });
const page = await context.newPage();
const errors = [];
page.on('pageerror', error => errors.push(error.message));
const refresh = () => page.getByRole('button', { name: 'Refresh evidence' }).click();
try {
  await page.goto('http://127.0.0.1:8090/proof');
  await page.locator('input[name=username]').fill(credentials.FIRST_SUPERUSER);
  await page.locator('input[name=password]').fill(credentials.FIRST_SUPERUSER_PASSWORD);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('button', { name: 'Refresh evidence' }).waitFor();
  step('happy'); await refresh();
  await expect(page.locator('#deliveries .delivered')).toHaveCount(1);
  step('duplicate'); await refresh();
  await expect(page.locator('#deliveries tr')).toHaveCount(1);
  step('lost'); await refresh();
  await expect(page.locator('#deliveries .retry')).toHaveCount(1);
  await page.screenshot({ path: path.join(out, 'lost-response.png'), fullPage: true });
  step('recover'); await refresh();
  await expect(page.locator('#deliveries .delivered')).toHaveCount(2);
  step('reject'); await refresh();
  await expect(page.locator('#deliveries .dead')).toHaveCount(1);
  page.once('dialog', dialog => dialog.accept('Inspected partner rejection and corrected test configuration'));
  const replay = page.waitForResponse(response => response.url().endsWith('/replay') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Replay', exact: true }).click();
  expect((await replay).status()).toBe(200);
  step('recover'); await refresh();
  await expect(page.locator('#deliveries .delivered')).toHaveCount(3);
  await expect(page.locator('#deliveries .dead')).toHaveCount(0);
  await page.screenshot({ path: path.join(out, 'delivery-console.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: path.join(out, 'mobile-console.png'), fullPage: true });
  await page.getByRole('button', { name: 'Sign out' }).click();
  await page.getByRole('button', { name: 'Sign in', exact: true }).waitFor();
  expect(errors).toEqual([]);
  await writeFile(path.join(out, 'result.json'), JSON.stringify({ outcome: 'PASS', environment: compose ? 'Docker Compose + PostgreSQL + real HTTP' : 'local PostgreSQL + real HTTP', checks: ['login', 'duplicate input', 'lost response', 'idempotent recovery', 'rejection', 'audited manual replay', 'mobile overflow', 'logout', 'no page errors'] }, null, 2));
} catch (error) {
  await page.screenshot({ path: path.join(out, 'failure.png'), fullPage: true }).catch(() => {});
  throw error;
} finally {
  await context.close();
  await copyFile(await page.video().path(), path.join(out, 'recovery-demo.webm'));
  await browser.close();
}
console.log('Browser PASS: full delivery recovery scenario; evidence in proof-results/browser');
