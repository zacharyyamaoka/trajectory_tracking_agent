// bb-site-nav: the site's one bar (CONTRACT §18). The brand row names the box (a link to its landing page) and the
// dashboards (the box's viewer, then each drop-in: Trajectory coverage, comparison, Model × Dataset on
// trajectory_tracking_agent), in one of two looks, nav.json `layout`: "switcher", the default (lane NAV's 07, Zach's ruling
// 2026-11-24 ~21:30: "its still the top row tabs but instead of having them spread out its the drop down"), "Box name /
// Black box ▾" opening every dashboard under its group's heading; or "two-rows" (lane NAV's 01), the dashboards spread out
// as tabs. The row below holds the open dashboard's own tabs, folding into More ▾ (the open tab never folds). Top right:
// Needs you (where the state is loaded), GitHub, the settings gear (Appearance, CONTRACT §17.4). It reads the site's
// nav.json (bb-site-nav/1) and, on the viewer's own page, the state for the tabs' counts and the box's own tabs. Pure: no
// DOM.
export default {
  tag: 'bb-site-nav', name: 'Site bar', version: 1, wave: 3,
  description: "The box's site bar on every page: the box's name (to its landing page) then the open dashboard with ▾ in the top row, its menu listing every dashboard under its group's heading (nav.json \"layout\": \"switcher\", the default; \"two-rows\" spreads the dashboards out as tabs instead), the open dashboard's own tabs below with counts, folding into More ▾ as the width shrinks (the open tab never folds); Needs you, a GitHub button and the settings gear top right. Drawn from one site/nav.json (bb-site-nav/1).",
  // the same slices bb-nav reads for its counts and the box's own tabs (+ about for the repo when nav.json names none)
  reads: ['spec', 'feedback', 'iterations', 'ablations', 'unscored', 'agents', 'activity', 'audits', 'reports', 'analysis', 'needs', 'ideas',
    'references', 'notes', 'tabs'],
  settings: [
    { id: 'src', type: 'text', label: 'nav.json', default: 'nav.json', info: "the site's bar file, relative to the page (a page deeper in the site climbs to it with ../)" },
    { id: 'current', type: 'text', label: 'Dashboard', default: '', info: "the open dashboard's id; empty = the one whose page this URL is" },
    { id: 'page', type: 'text', label: 'Tab or page', default: '', info: "the open tab (the viewer's) or page (a drop-in's); empty = from the URL" },
    { id: 'here', type: 'text', label: 'Where in the page', default: '', info: 'a crumb after the tabs for a page below them (a run report: "Run · workspace-dev-001")' },
    { id: 'href', type: 'text', label: 'Tab link pattern', default: '', info: "{page} is replaced; the viewer's own page sets #{page} so a tab is one hash change; empty = the dashboard's href + #{page}" },
    { id: 'theme', type: 'select', label: 'Theme', default: 'auto', info: 'light: this page has no dark mode (it stays light; a pick is remembered for the other pages)',
      options: [{ value: 'auto', label: 'Follow the reader (Light / Dark / System)' }, { value: 'light', label: 'This page is light only' }] },
    { id: 'counts', type: 'checkbox', label: 'Show counts', default: true },
    { id: 'needs_pill', type: 'checkbox', label: 'Needs-you pill', default: true, info: 'drawn only where the state is loaded (the box\'s own dashboard)' },
  ],
  limit: 1,
  presets: [{ name: 'Site bar' }],
  empty: 'The bar always draws the box\'s name; it says so when its nav.json cannot be read.',
};
