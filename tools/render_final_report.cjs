// Presentation only: npm install playwright@1.62.1 and install its Chromium.
// Run after build_final_report.py --html. No network requests are allowed here.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const root = path.resolve(__dirname, '..');
(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.REPORT_CHROMIUM_PATH ? {executablePath: process.env.REPORT_CHROMIUM_PATH} : {})});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 900}});
    await page.route(/^https?:\/\//, route => route.abort());
    await page.goto(pathToFileURL(path.join(root, 'docs/submission-report-2026-10-24.html')).href);
    await page.evaluate(() => document.fonts.ready);
    const layout = await page.evaluate(() => ({
      horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
      images: Array.from(document.images).map(i => ({loaded: i.complete && i.naturalWidth > 0})),
      sections: document.querySelectorAll('h2').length,
      tables: document.querySelectorAll('table').length,
    }));
    if (layout.horizontalOverflow || layout.images.some(i => !i.loaded)) throw new Error(JSON.stringify(layout));
    const dir = path.join(root, 'output/pdf');
    fs.mkdirSync(dir, {recursive: true});
    await page.pdf({
      path: path.join(dir, 'sciresearch-thinking-r1-report-20261025.pdf'),
      format: 'A4', printBackground: true, preferCSSPageSize: true,
      displayHeaderFooter: true, headerTemplate: '<span></span>',
      footerTemplate: '<div style="font:9px Arial;color:#6b7c8b;width:100%;text-align:center">SciResearch-Bench-Lite · <span class="pageNumber"></span> / <span class="totalPages"></span></div>',
    });
    console.log(JSON.stringify({status: 'rendered', ...layout}));
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exit(1);});
