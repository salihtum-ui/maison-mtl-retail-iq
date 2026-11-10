// Ensure src/fabric_config.ts exists before compiling. A fresh clone gets the placeholder; `python deploy.py app`
// overwrites it with the deployed IDs. The advisor answers "not configured" while placeholders are in place.
import { copyFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const target = resolve(root, 'src', 'fabric_config.ts');
if (!existsSync(target)) {
  copyFileSync(resolve(root, 'fabric_config.example.ts'), target);
  console.log('Created src/fabric_config.ts from fabric_config.example.ts (placeholder IDs).');
}
