// bb-solution-detail: one solution's page (viewer/CONTRACT.md §16.3; ported from proposals-headliner/_detail). Pure: no DOM.
export default {
  tag: 'bb-solution-detail', name: 'Solution detail', version: 1, wave: 2,
  description: 'Everything the state knows about one solution: its verdict, objective and holdout, rank and the best so far at its step, its parent and children, its change, tags, proposer and commit, each gate\'s result, its costs and where it sits on each front, and (when the box saved one) its run explained by bb-evidence. Links to other solutions fire bb-open.',
  // `unscored` (lane ES): a registered solution with no ranking score yet gets its own page, never "no such solution"
  reads: ['iterations', 'ablations', 'costs', 'gates', 'playback', 'unscored'],
  settings: [
    { id: 'id', type: 'text', label: 'Solution id ("" = from the page URL: ?id=<id> or #solution=<id>)', default: '' },
  ],
  blocks: [],
  limit: 1,
  presets: [{ name: 'From the URL', settings: { id: '' } }],
  events: ['bb-open'],
  empty: 'No solution with that id in this state. A solution appears here once the box has its folder with a meta.json; open it as #solution=<id>.',
};
