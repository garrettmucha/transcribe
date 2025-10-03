import { chromium } from 'playwright';

export async function renderPdfFromHtml(html: string) {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage();
    await page.setContent(html, { waitUntil: 'networkidle' });
    const pdf = await page.pdf({
      format: 'A4',
      displayHeaderFooter: false,
      margin: { top: '0.75in', bottom: '0.75in', left: '0.65in', right: '0.65in' },
      printBackground: true
    });
    return pdf;
  } finally {
    await browser.close();
  }
}
