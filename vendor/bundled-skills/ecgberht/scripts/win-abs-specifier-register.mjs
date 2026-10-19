/**
 * Register the Windows absolute-path ESM resolve hook for this process tree.
 * Loaded via `node --import <this-file>` or NODE_OPTIONS so child workers
 * (spawnSync -e) inherit the same rewrite.
 */

import { register } from 'node:module';

register('./win-abs-specifier-hooks.mjs', import.meta.url);
