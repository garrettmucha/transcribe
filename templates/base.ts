import type { ResumeData } from '@/types';

interface TemplateOptions {
  accent: string;
  headingCase?: 'uppercase' | 'title';
  bodyFont?: string;
  borderStyle?: string;
}

export function renderResume(data: ResumeData, options: TemplateOptions) {
  const roles = data.roles
    .map((role) => {
      const bullets = role.bullets
        .map((bullet) => `<li>${escapeHtml(bullet)}</li>`)
        .join('');
      return `
        <section class="role">
          <header>
            <div>
              <h3>${escapeHtml(role.title)}</h3>
              <p class="meta">${escapeHtml(role.company)} · ${escapeHtml(role.startDate)} – ${escapeHtml(role.endDate)}</p>
            </div>
          </header>
          <ul>${bullets}</ul>
        </section>
      `;
    })
    .join('');

  const skills = data.skills.map((skill) => `<span class="chip">${escapeHtml(skill)}</span>`).join('');

  return `<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>
      :root {
        color-scheme: light;
      }
      * {
        box-sizing: border-box;
      }
      body {
        font-family: ${options.bodyFont ?? '"Inter", Arial, sans-serif'};
        margin: 0;
        padding: 56px 64px;
        color: #0f172a;
        background: #ffffff;
      }
      h1, h2, h3 {
        margin: 0;
        color: #111827;
      }
      h2 {
        margin-bottom: 12px;
        ${options.headingCase === 'uppercase' ? 'text-transform: uppercase; letter-spacing: 2px;' : ''}
      }
      p {
        margin: 0;
      }
      .summary {
        font-size: 14px;
        line-height: 1.6;
      }
      .divider {
        height: 1px;
        background: ${options.borderStyle ?? '#e2e8f0'};
        margin: 24px 0;
      }
      .role {
        margin-bottom: 24px;
        page-break-inside: avoid;
      }
      .role header {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        margin-bottom: 8px;
      }
      .role h3 {
        font-size: 15px;
        font-weight: 600;
      }
      .meta {
        font-size: 12px;
        color: #475569;
      }
      ul {
        margin: 0;
        padding-left: 20px;
      }
      li {
        margin-bottom: 8px;
        font-size: 13px;
        line-height: 1.5;
      }
      li::marker {
        color: ${options.accent};
      }
      .chip {
        display: inline-block;
        border: 1px solid ${options.accent};
        color: ${options.accent};
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 11px;
        margin: 0 8px 8px 0;
      }
    </style>
  </head>
  <body>
    <header>
      <h1 style="font-size:28px; font-weight:700;">${escapeHtml(data.summary.split('.')[0] ?? '')}</h1>
      <p class="summary">${escapeHtml(data.summary)}</p>
    </header>
    <div class="divider"></div>
    <section>
      <h2>Experience</h2>
      ${roles}
    </section>
    <div class="divider"></div>
    <section>
      <h2>Core Skills</h2>
      <div>${skills}</div>
    </section>
  </body>
</html>`;
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
