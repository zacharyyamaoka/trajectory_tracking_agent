/* <bb-stages src="../stages/stages.json" current="deployments"></bb-stages>: the stage bar across the top of a page.

   The list is ONE file, stages.json (schema bb-stages/1: {stages: [{id, label, href, status: live | not-yet, note,
   reason}]}, every href relative to that file), so every page shows the same bar and a page ships by flipping one
   status. A host that already holds the list sets `el.stages = {doc, base}` (base: the URL its hrefs are relative to)
   instead of `src`; the black-box viewer can host the same list that way. No dependencies, light DOM, one <style>.

   WHY a stage list, left to right (Zach, 2026-11-24): the pages run left to right across the top, landing, then the
   dashboard, then models x datasets, then the datasets' coverage. WHY a not-yet stage is greyed text with its
   reason and never a link: a stage whose page is not built must not be a dead link. */

const STYLE_ID = 'bb-stages-style';
const CSS = `
bb-stages { display: block; min-height: 46px; }
bb-stages .bbs { border-bottom: 1px solid var(--line, #e1e3e1); background: var(--surface, #ffffff); }
bb-stages ol { display: flex; align-items: center; margin: 0; padding: 6px 12px; list-style: none; overflow-x: auto;
  scrollbar-width: thin; gap: 0; }
bb-stages li { flex: 0 0 auto; display: flex; align-items: center; }
bb-stages li + li::before { content: "\\203A"; color: var(--muted, #5e6570); margin: 0 4px; font-size: 16px; }
bb-stages .bbs-stage { display: flex; align-items: center; gap: 7px; padding: 5px 10px; border-radius: 8px;
  font: 500 13px/1.25 var(--sans, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif); white-space: nowrap;
  text-decoration: none; color: var(--ink, #1b1e23); border: 1px solid transparent; }
bb-stages a.bbs-stage:hover { background: var(--surface-2, #f0f1ef); }
bb-stages a.bbs-stage:focus-visible, bb-stages .bbs-off:focus-visible { outline: 2px solid var(--accent, #2c64d1); outline-offset: 1px; }
bb-stages a.bbs-stage[aria-current="page"] { background: var(--accent-soft, #2c64d11f); color: var(--accent, #2c64d1);
  font-weight: 650; }
bb-stages .bbs-n { display: inline-grid; place-items: center; width: 18px; height: 18px; border-radius: 50%;
  border: 1px solid currentColor; font: 600 11px/1 var(--mono, ui-monospace, Menlo, Consolas, monospace); }
bb-stages .bbs-off { color: var(--muted, #5e6570); border: 1px dashed var(--line, #d0d4d8); cursor: help; }
bb-stages .bbs-off .bbs-label { opacity: 0.85; }
bb-stages .bbs-note { font-size: 11.5px; font-style: italic; }
bb-stages .bbs-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
@media (prefers-color-scheme: dark) {
  bb-stages .bbs { border-color: var(--line, #2a2f36); background: var(--surface, #181b20); }
  bb-stages .bbs-stage { color: var(--ink, #e6e8eb); }
  bb-stages a.bbs-stage:hover { background: var(--surface-2, #1f2329); }
  bb-stages a.bbs-stage[aria-current="page"] { background: var(--accent-soft, #6c9cf026); color: var(--accent, #6c9cf0); }
  bb-stages .bbs-off { color: var(--muted, #a0a7b1); border-color: var(--line, #2a2f36); }
}
`;

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** The bar's markup for one list: `doc` (bb-stages/1), `base` (the URL its hrefs are relative to), `current` (a stage id). */
export function renderStages(doc, base, current) {
  const stages = (doc && Array.isArray(doc.stages)) ? doc.stages : [];
  const items = stages.map((stage, i) => {
    const n = `<span class="bbs-n" aria-hidden="true">${i + 1}</span>`;
    const label = `<span class="bbs-label">${esc(stage.label)}</span>`;
    if (stage.status === 'live' && stage.href) {
      const href = new URL(stage.href, base).href;
      const here = stage.id === current ? ' aria-current="page"' : '';
      return `<li data-stage="${esc(stage.id)}" data-status="live"><a class="bbs-stage" href="${esc(href)}"${here}>${n}${label}</a></li>`;
    }
    const note = stage.note ? `<span class="bbs-note">${esc(stage.note)}</span>` : '';
    const reason = stage.reason ? `<span class="bbs-sr">: ${esc(stage.reason)}</span>` : '';
    return `<li data-stage="${esc(stage.id)}" data-status="not-yet"><span class="bbs-stage bbs-off" role="link" aria-disabled="true" tabindex="0" title="${esc(stage.reason || stage.note || 'not built yet')}">${n}${label}${note}${reason}</span></li>`;
  });
  return `<nav class="bbs" aria-label="Stages"><ol>${items.join('')}</ol></nav>`;
}

// WHY guarded: renderStages is importable where there is no DOM (tests/test_coverage_pages.py runs it in node)
const Base = typeof HTMLElement === 'undefined' ? class {} : HTMLElement;

class BbStages extends Base {
  static get observedAttributes() { return ['src', 'current']; }

  connectedCallback() {
    if (!document.getElementById(STYLE_ID)) {
      const style = document.createElement('style');
      style.id = STYLE_ID;
      style.textContent = CSS;
      document.head.appendChild(style);
    }
    if (this._held) this._draw(); else this._load();
  }

  attributeChangedCallback(name) {
    if (!this.isConnected) return;
    if (name === 'src') this._load(); else this._draw();
  }

  /** A host's own copy of the list: {doc, base}. */
  set stages(value) {
    this._held = value;
    if (this.isConnected) this._draw();
  }

  get stages() { return this._held || null; }

  async _load() {
    const src = this.getAttribute('src');
    if (!src) return;
    const url = new URL(src, document.baseURI).href;
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      this._held = { doc: await response.json(), base: url };
      this._draw();
    } catch (error) {
      this.dataset.error = `${url}: ${error.message}`;
      console.warn('bb-stages: could not read the stage list', url, error);
    }
  }

  _draw() {
    if (!this._held) return;
    this.innerHTML = renderStages(this._held.doc, this._held.base, this.getAttribute('current'));
    this.dataset.ready = '';
    // keep the current stage in view on a narrow screen, by scrolling the bar itself (never the page)
    const list = this.querySelector('ol');
    const here = this.querySelector('[aria-current="page"]');
    if (list && here && list.scrollWidth > list.clientWidth) {
      const left = here.getBoundingClientRect().left - list.getBoundingClientRect().left + list.scrollLeft;
      list.scrollLeft = Math.max(0, left - (list.clientWidth - here.offsetWidth) / 2);
    }
    this.dispatchEvent(new CustomEvent('bb-stages-ready', { bubbles: true }));
  }
}

if (typeof customElements !== 'undefined' && !customElements.get('bb-stages')) customElements.define('bb-stages', BbStages);
