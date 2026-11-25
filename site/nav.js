/* The header strip: the box's name and its pages, from nav.json beside this file (schema tta-nav/1:
   {box: {name, href}, links: [{id, label, href | null, note}]}, every href relative to nav.json).

   One include per page, right after <body>:
     <script src="../nav.js" data-current="comparison" defer></script>
   data-current names the page's own link (drawn as the current page); data-theme="light" keeps the strip light on a
   page that has no dark mode (traj_compare's). No dependencies, light DOM, one <style>.

   WHY this small and this shape (lane DROP, 2026-11-24): lane NAV is designing the real tabs; this file and nav.json
   are meant to be replaced whole, and a page needs only its one include changed. A link whose page is not on the site
   yet is greyed text with its note, never a dead link. */
(() => {
  const me = document.currentScript;
  if (!me) return;
  const base = new URL('.', me.src);
  const current = me.dataset.current || '';
  const light = me.dataset.theme === 'light';
  const css = `
.tta-nav { display: flex; align-items: center; flex-wrap: wrap; gap: 2px 14px; padding: 7px 16px; box-sizing: border-box;
  border-bottom: 1px solid #e1e3e1; background: #ffffff; color: #1b1e23;
  font: 13px/1.35 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
.tta-nav a { color: inherit; text-decoration: none; }
.tta-nav .tta-box { font-weight: 650; margin-right: 6px; }
.tta-nav ol { display: flex; flex-wrap: wrap; gap: 2px 4px; margin: 0; padding: 0; list-style: none; }
.tta-nav li a, .tta-nav li span { display: inline-block; padding: 3px 8px; border-radius: 6px; }
.tta-nav li a:hover { background: #f0f1ef; }
.tta-nav li a[aria-current="page"] { background: #2c64d11f; color: #2c64d1; font-weight: 600; }
.tta-nav li .tta-off { color: #5e6570; border: 1px dashed #d0d4d8; cursor: help; }
.tta-nav a:focus-visible { outline: 2px solid #2c64d1; outline-offset: 1px; }
@media (prefers-color-scheme: dark) {
  .tta-nav:not(.tta-light) { border-color: #2a2f36; background: #181b20; color: #e6e8eb; }
  .tta-nav:not(.tta-light) li a:hover { background: #1f2329; }
  .tta-nav:not(.tta-light) li a[aria-current="page"] { background: #6c9cf026; color: #6c9cf0; }
  .tta-nav:not(.tta-light) li .tta-off { color: #a0a7b1; border-color: #2a2f36; }
}`;
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  function draw(nav) {
    const style = document.createElement('style');
    style.textContent = css;
    const bar = document.createElement('nav');
    bar.className = 'tta-nav' + (light ? ' tta-light' : '');
    bar.setAttribute('aria-label', 'Trajectory Tracking Agent pages');
    bar.dataset.ttaNav = '';
    const box = nav.box || { name: 'Trajectory Tracking Agent', href: 'index.html' };
    const items = (nav.links || []).map((link) => {
      if (!link.href) return `<li><span class="tta-off" title="${esc(link.note || 'not on the site yet')}">${esc(link.label)}</span></li>`;
      const here = link.id === current ? ' aria-current="page"' : '';
      return `<li><a href="${esc(new URL(link.href, base).href)}" data-nav="${esc(link.id)}"${here}>${esc(link.label)}</a></li>`;
    });
    bar.innerHTML = `<a class="tta-box" href="${esc(new URL(box.href, base).href)}">${esc(box.name)}</a><ol>${items.join('')}</ol>`;
    document.head.appendChild(style);
    document.body.insertBefore(bar, document.body.firstChild);
  }
  // WHY a fallback: from file:// a fetch is refused; the strip then still names the box and links the landing page
  fetch(new URL('nav.json', base)).then((r) => r.json()).then(draw, () => draw({}));
})();
