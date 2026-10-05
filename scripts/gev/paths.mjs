/**
 * Path anchors for the GEV QA harnesses.
 *
 * The harnesses used to live in `src/gev/scripts/` and treated their own parent
 * directory as the app root. They now live in `scripts/gev/`, so the app root is
 * two levels up and then into `src/gev` — a difference that is easy to get
 * silently wrong, which is why it is named in exactly one place.
 */
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));

/** Repository root (package.json lives here). */
export const REPO_ROOT = path.resolve(HERE, '..', '..');

/** The GEV app root: index.html, style.css, js/, docs/. */
export const GEV_ROOT = path.join(REPO_ROOT, 'src', 'gev');

/** GEV source directory, repo-relative — the old layout called this `src`. */
export const GEV_SOURCE_DIR = path.join('src', 'gev', 'js');

/** The GEV vite config, which is shared with the main app config. */
export const GEV_VITE_CONFIG = path.join(REPO_ROOT, 'vite.gev.config.js');

/** Build artifacts / QA screenshots, kept out of the source tree. */
export const QA_SHOTS_DIR = path.join(REPO_ROOT, 'qa-shots');