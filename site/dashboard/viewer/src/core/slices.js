/* The state.json slices a component may read (viewer/CONTRACT.md §3), and the one function that hands a component only
   the slices its schema declares. Pure (no DOM). WHY by construction: "the blackbox viz is not related to the solution,
   only to the metrics out" (Zach, 2026-11-24); a component cannot reach a slice it did not declare, because it never
   receives it. */

export const HEADER = ['schema', 'box', 'ref', 'read_at', 'ref_date', 'about', 'objective'];
export const SLICES = ['kpis', 'iterations', 'ablations', 'unscored', 'spec', 'needs', 'gates', 'ideas', 'costs', 'feedback', 'audits',
  'agents', 'activity', 'reports', 'report_files', 'references', 'playback', 'source', 'ablation_study', 'spec_history', 'analysis', 'notes', 'tabs'];
/** Row slices bb-data-page can show (arrays, or arrays nested one level down). */
export const ROW_SLICES = ['iterations', 'ablations', 'unscored', 'needs', 'gates', 'ideas', 'feedback', 'audits', 'report_files',
  'references', 'kpis', 'agents.proposers', 'activity.recent', 'costs', 'spec.requirements', 'ablation_study.variants', 'ablation_study.rows',
  'analysis', 'notes.rows'];
// CONTRACT §16.2: the Ablation tab after Iterations (Zach treats the ablation study as its own tab).
// CONTRACT §17 (Zach, 2026-11-24): Reports is Analysis; References and Notes are tabs; a box's own tabs follow these.
export const PAGES = ['overview', 'spec', 'feedback', 'iterations', 'ablation', 'agents', 'activity', 'audits', 'analysis', 'ideas',
  'references', 'notes'];
export const PAGE_LABELS = { overview: 'Overview', spec: 'Spec', feedback: 'Feedback', iterations: 'Iterations', ablation: 'Ablation',
  agents: 'Agents', activity: 'Activity', audits: 'Audits', analysis: 'Analysis', ideas: 'Ideas', references: 'References', notes: 'Notes' };
/** Old page ids a page.json may still name (CONTRACT §17): `reports` is the Analysis tab. */
export const PAGE_ALIASES = { reports: 'analysis' };
/** A page id as the tabs know it (an alias read as its tab). */
export const pageId = (id) => PAGE_ALIASES[id] || id;
/** Page ids a box's own tab may not take: the built-in tabs, their aliases, and the site's own pages. */
export const RESERVED_PAGES = [...PAGES, ...Object.keys(PAGE_ALIASES), 'solution', 'tab'];

const freeze = (o) => {
  if (o && typeof o === 'object' && !Object.isFrozen(o)) {
    Object.freeze(o);
    for (const v of Object.values(o)) freeze(v);
  }
  return o;
};
const clone = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)));

export function get(state, path) {
  return path.split('.').reduce((o, k) => (o && typeof o === 'object' ? o[k] : undefined), state);
}

/** The header + the declared slices, deep-copied and frozen. `reads` may hold dot paths ("agents.proposers"). */
export function pick(state, reads = []) {
  const out = {};
  if (!state || typeof state !== 'object') return freeze(out);
  for (const k of HEADER) if (state[k] !== undefined) out[k] = clone(state[k]);
  for (const path of reads) {
    if (path === '*') continue; // reserved for bb-page / custom-html, which narrow it themselves
    const v = get(state, path);
    if (v === undefined) continue;
    const parts = path.split('.');
    let at = out;
    for (const p of parts.slice(0, -1)) at = at[p] = at[p] && typeof at[p] === 'object' ? at[p] : {};
    at[parts[parts.length - 1]] = clone(v);
  }
  return freeze(out);
}

/** The keys a picked object may hold for these reads (the runtime check in the story runner uses it). */
export function allowedKeys(reads = []) {
  return new Set([...HEADER, ...reads.filter((r) => r !== '*').map((r) => r.split('.')[0])]);
}

/** The split the box ranks its solutions on, as its objective names it (CONTRACT §3.1 + lane ES): "dev" for a box whose
    ledger rows say so, null for one whose rows name none (robot_sdk_agent) or a population graded at once
    (robot_controllers). A state folded before the field existed has no key: "dev", what every box then was. */
export const splitOf = (objective) => (objective && Object.prototype.hasOwnProperty.call(objective, 'split') ? objective.split ?? null : 'dev');

/** How many active shall requirements name a test yet (their note's `tests:` patterns), out of how many: {tested, of},
    or null when the spec slice lists no requirements. What the Spec counts can say with no test run folded (lane ES:
    a private box's tab read "Spec null/41"). */
export function specTested(spec) {
  const reqs = spec && Array.isArray(spec.requirements) ? spec.requirements : null;
  if (!reqs) return null;
  const shalls = reqs.filter((r) => r && r.kind === 'objective' && r.verb === 'shall');
  return { tested: shalls.filter((r) => Array.isArray(r.patterns) && r.patterns.length > 0).length, of: shalls.length };
}
