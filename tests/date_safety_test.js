const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

// Minimal globals normally supplied by app.js. date-safety.js progressively
// replaces the relevant functions without needing a DOM for these tests.
global.current = {
  target: { id: 'school-watchlist', earliestPublicationDate: '2024-01-01' },
  entities: []
};
global.dateValue = () => null;
global.time = value => String(value || '');
global.contentTime = () => '';
global.authorBlock = () => '';
global.commentCard = () => '';
global.commentEntities = () => [];
global.feedPosts = () => [];
global.viewFeed = () => '';
global.personDetail = () => '';
global.archiveResults = () => [];
global.provenance = () => '';
global.deriveAuthors = () => [];
global.render = () => {};
global.esc = value => String(value ?? '');
global.initials = name => String(name || '?').slice(0, 1);
global.authorUrl = key => `?author=${key}`;
global.statusLabel = value => String(value || '');
global.externalLink = () => '';
global.currentQuery = () => '';
global.postCard = () => '';
global.truncate = value => String(value || '');
global.routeLink = () => '';
global.entityUrl = id => `?entity=${id}`;
global.entityMap = new Map();
global.renderedFeedLimit = 40;

const code = fs.readFileSync('site/date-safety.js', 'utf8');
vm.runInThisContext(code, { filename: 'site/date-safety.js' });

// Chromium/JavaScript may otherwise invent year 2001 for a yearless date.
assert.strictEqual(dateValue('August 25'), null, 'yearless Facebook label must not be browser-parsed');
assert.strictEqual(dateValue('2001-08-25'), null, 'pre-Facebook date must be rejected');

const valid = dateValue('2026-08-25');
assert(valid instanceof Date, 'valid ISO date should parse');
assert.strictEqual(valid.getFullYear(), 2026);
assert.strictEqual(valid.getMonth(), 7);
assert.strictEqual(valid.getDate(), 25);
assert(!authorBlock({ author: 'School Watchlist', timestampText: 'August 25' }).includes('2001'), 'rendered yearless label must never display 2001');
assert(authorBlock({ author: 'School Watchlist', publishedDate: '2023-12-31' }).includes('invalid captured date'), 'target-specific pre-archive publication date must be rejected at the publication layer');

current.entities = [
  { id: 'post:2024', itemType: 'post', publishedDate: '2024-06-01', author: 'School Watchlist', text: '2024' },
  { id: 'post:unknown', itemType: 'post', author: 'School Watchlist', text: 'unknown', firstSeen: '2026-08-25T14:17:42Z' },
  { id: 'post:2026', itemType: 'post', publishedDate: '2026-08-25', author: 'School Watchlist', text: '2026' },
  { id: 'post:2025', itemType: 'post', publishedDate: '2025-08-25', author: 'School Watchlist', text: '2025' }
];

assert.deepStrictEqual(
  feedPosts('').map(post => post.id),
  ['post:2026', 'post:2025', 'post:2024', 'post:unknown'],
  'feed must sort reliable publication dates newest to oldest and place undated records afterward'
);

console.log('date safety tests passed');
