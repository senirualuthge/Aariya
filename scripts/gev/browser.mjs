/**
 * Optional browser dependency loader for the GEV QA harnesses.
 *
 * The QA harnesses drive a real Chromium against the real app, but the pure
 * logic inside them (verdict classifiers, card harnesses, parsers) is unit
 * tested from the GEV `*.test.mjs` files. A static `import puppeteer` at the top
 * of a harness would make those unit tests require a browser download, so the
 * import is deferred to the moment a browser is actually launched.
 *
 * puppeteer is intentionally NOT in package.json: it is a heavyweight,
 * download-on-install tool that only the browser QA harnesses need. Install it
 * on demand when you intend to run one:
 *
 *     npm install --no-save puppeteer
 *
 * The harnesses already fall back to a system Chrome when puppeteer's pinned
 * Chrome-for-Testing is absent, so a system Chrome plus this loader is enough.
 */
export async function loadPuppeteer() {
  try {
    const mod = await import('puppeteer');
    return mod.default ?? mod;
  } catch (error) {
    if (error?.code === 'ERR_MODULE_NOT_FOUND') {
      throw new Error(
        'puppeteer is not installed. This harness drives a real browser; run '
        + '`npm install --no-save puppeteer` (or point PUPPETEER_EXECUTABLE_PATH '
        + 'at a Chrome-for-Testing binary). The pure logic in this module is '
        + 'unit tested without it.',
      );
    }
    throw error;
  }
}