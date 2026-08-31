const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

function loadAppContext() {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) {
      elements.set(id, {
        id,
        value: '',
        innerHTML: '',
        addEventListener() {}
      });
    }
    return elements.get(id);
  };
  const context = {
    console,
    URLSearchParams,
    location: { search: '', pathname: '/' },
    history: { pushState() {}, replaceState() {} },
    fetch: () => new Promise(() => {}),
    document: {
      getElementById: element,
      addEventListener() {},
      querySelectorAll: () => [],
      querySelector: () => null
    }
  };
  context.window = {
    addEventListener() {}
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('site/app.js', 'utf8'), context, { filename: 'site/app.js' });
  return context;
}

const app = loadAppContext();
const populatedFallback = vm.runInContext(
  `initialTargetId([
    {id:'empty',summary:{entities:0,posts:0,comments:0,snapshots:0}},
    {id:'school-watchlist',summary:{entities:2704,posts:410,comments:2294,snapshots:5}}
  ], null)`,
  app
);
assert.strictEqual(populatedFallback, 'school-watchlist', 'initial load must prefer the first populated target');
assert.strictEqual(
  vm.runInContext(
    `initialTargetId([
      {id:'empty',summary:{entities:0}},
      {id:'school-watchlist',summary:{entities:2704}}
    ], 'empty')`,
    app
  ),
  'empty',
  'an explicit valid target URL must remain authoritative'
);

const comments = [
  { id: 'c1', commentId: '1', parentCommentId: '', text: 'Root one' },
  { id: 'r1', commentId: '11', parentCommentId: '1', text: 'Reply one' },
  { id: 'r2', commentId: '12', parentCommentId: '1', text: 'Reply two' },
  { id: 'r3', commentId: '13', parentCommentId: '1', text: 'Reply three' },
  { id: 'c2', commentId: '2', parentCommentId: '', text: 'Root two' },
  { id: 'c3', commentId: '3', parentCommentId: '', text: 'Root three' },
  { id: 'c4', commentId: '4', parentCommentId: '', text: 'Root four' }
];
let clickHandler;
const card = { replaceWith() {} };
const threading = {
  console,
  current: { target: { id: 'school-watchlist' } },
  entityMap: new Map([['post', { id: 'post', itemType: 'post' }]]),
  commentEntities: () => comments,
  commentCard: comment => `<article data-comment="${comment.id}">${comment.text}</article>`,
  viewRecord: () => '',
  params: () => new URLSearchParams(),
  esc: value => String(value ?? ''),
  routeLink: () => '',
  provenance: () => '',
  versionsPanel: () => '',
  resultCard: () => '',
  postCard: () => '<article class="post-card"></article>',
  render() {},
  renderView() {},
  document: {
    addEventListener(type, handler) {
      if (type === 'click') clickHandler = handler;
    },
    createElement() {
      return { innerHTML: '', content: { firstElementChild: {} } };
    },
    getElementById: () => null
  }
};
threading.window = threading;
vm.createContext(threading);
vm.runInContext(fs.readFileSync('site/threading.js', 'utf8'), threading, { filename: 'site/threading.js' });

assert.strictEqual(threading.ArchiveThreading.expansionBatch(1397), 250, 'very large threads expand in useful batches');
assert.strictEqual(threading.ArchiveThreading.expansionBatch(700), 100);
assert.strictEqual(threading.ArchiveThreading.expansionBatch(200), 50);
assert.strictEqual(threading.ArchiveThreading.expansionBatch(20), 20, 'the final small batch is revealed at once');

assert(threading.archiveInlineDiscussionControls({ id: 'post' }, comments.length).includes('View all 7 comments'));
assert.strictEqual(threading.archiveInlineDiscussionPanel({ id: 'post' }), '', 'discussion starts collapsed');

function click(dataset) {
  const action = {
    dataset,
    closest(selector) {
      if (selector === '.post-card') return card;
      if (selector.includes('[data-action=')) return action;
      return null;
    }
  };
  clickHandler({ target: action, preventDefault() {} });
}

click({ action: 'toggle-inline-comments', postId: 'post' });
let panel = threading.archiveInlineDiscussionPanel({ id: 'post' });
assert(panel.includes('Showing 5 of 7'), 'initial expansion shows three roots and two replies');
assert(panel.includes('View 1 more reply'), 'replies remain progressively expandable');
assert(panel.includes('View 1 more comment'), 'additional top-level comments remain progressively expandable');
assert(panel.indexOf('Root one') < panel.indexOf('Reply one'), 'replies render beneath their parent');

click({ action: 'more-inline-replies', postId: 'post', commentId: 'c1' });
panel = threading.archiveInlineDiscussionPanel({ id: 'post' });
assert(panel.includes('Showing 6 of 7'), 'reply expansion adds the next reply batch in situ');
assert(!panel.includes('View 1 more reply'));

click({ action: 'more-inline-comments', postId: 'post' });
panel = threading.archiveInlineDiscussionPanel({ id: 'post' });
assert(panel.includes('Showing 7 of 7'), 'comment expansion eventually reveals the full archived discussion');
assert(!panel.includes('more comment'));

click({ action: 'toggle-inline-comments', postId: 'post' });
assert.strictEqual(threading.archiveInlineDiscussionPanel({ id: 'post' }), '', 'expanded discussions can be collapsed');

console.log('feed interaction tests passed');
