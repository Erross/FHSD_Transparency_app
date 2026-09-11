/* Activity-first presentation layer for the transparency archive.
   This module deliberately does not rewrite archive state. It turns preserved
   events, entity statuses, and reported/visible thread metadata into obvious
   operational signals while keeping observation separate from causation. */
(function () {
  const MISSING = new Set(['missing_once', 'missing_recheck', 'confirmed_unavailable']);
  const originalPostCard = window.postCard || postCard;
  const originalCommentCard = window.commentCard || commentCard;
  const originalInlinePanel = window.archiveInlineDiscussionPanel;
  const chronologyFeedPosts = window.feedPosts || feedPosts;

  function parseMs(value) {
    if (!value) return 0;
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? 0 : d.getTime();
  }

  function anchorMs() {
    const snapshots = Array.isArray(current?.snapshots) ? current.snapshots : [];
    const values = snapshots.map(s => parseMs(s.observedAt || s.exportedAt)).filter(Boolean);
    return values.length ? Math.max(...values) : Date.now();
  }

  function rangeHours() {
    const raw = Number(params().get('period') || 24);
    return [24, 168, 720].includes(raw) ? raw : 24;
  }

  function rangeLabel(hours = rangeHours()) {
    return hours === 24 ? '24 hours' : hours === 168 ? '7 days' : '30 days';
  }

  function rangeStartMs(hours = rangeHours()) {
    return anchorMs() - hours * 60 * 60 * 1000;
  }

  function inRange(value, hours = rangeHours()) {
    const ms = parseMs(value);
    return Boolean(ms && ms >= rangeStartMs(hours) && ms <= anchorMs() + 60000);
  }

  function recentEvents(hours = rangeHours()) {
    return (current?.events || []).filter(event => inRange(event.observedAt, hours));
  }

  function entityForEvent(event) {
    return entityMap.get(event.entityId) || {};
  }

  function postForEvent(event) {
    const entity = entityForEvent(event);
    if (entity.itemType === 'post') return entity.id;
    return entity.parentId || event.parentId || '';
  }

  function isCommentEvent(event) {
    const entity = entityForEvent(event);
    return (event.itemType || entity.itemType) !== 'post';
  }

  function currentMissingComments(postId) {
    return current.entities.filter(entity =>
      entity.itemType !== 'post' && entity.parentId === postId && MISSING.has(entity.status)
    );
  }

  function visibility(postId) {
    const row = (current?.commentVisibility || {})[postId];
    if (!row) return null;
    const reported = Number(row.reported || 0);
    const visible = Number(row.visible || 0);
    return {
      reported,
      visible,
      gap: Math.max(0, Number(row.gap ?? reported - visible))
    };
  }

  function postActivity(post, hours = rangeHours()) {
    const events = recentEvents(hours).filter(event => postForEvent(event) === post.id);
    const newComments = events.filter(event => event.type === 'new' && isCommentEvent(event)).length;
    const missingComments = events.filter(event => ['missing_once', 'missing_recheck', 'confirmed_unavailable'].includes(event.type) && isCommentEvent(event)).length;
    const reappeared = events.filter(event => event.type === 'reappeared').length;
    const edits = events.filter(event => event.type === 'edited').length;
    const latestActivity = Math.max(
      0,
      ...events.map(event => parseMs(event.observedAt)),
      parseMs(post.lastSeen),
      parseMs(post.firstSeen)
    );
    return { events, newComments, missingComments, reappeared, edits, latestActivity };
  }

  function stats(hours = rangeHours()) {
    const events = recentEvents(hours);
    const newPosts = events.filter(event => event.type === 'new' && !isCommentEvent(event)).length;
    const newComments = events.filter(event => event.type === 'new' && isCommentEvent(event)).length;
    const missingComments = events.filter(event => ['missing_once', 'missing_recheck', 'confirmed_unavailable'].includes(event.type) && isCommentEvent(event)).length;
    const reappeared = events.filter(event => event.type === 'reappeared').length;
    const edited = events.filter(event => event.type === 'edited').length;
    const rows = Object.values(current?.commentVisibility || {}).map(row => {
      const reported = Number(row?.reported || 0), visible = Number(row?.visible || 0);
      return Math.max(0, Number(row?.gap ?? reported - visible));
    });
    return {
      newPosts,
      newComments,
      missingComments,
      reappeared,
      edited,
      gapThreads: rows.filter(gap => gap > 0).length,
      gapTotal: rows.reduce((sum, gap) => sum + gap, 0)
    };
  }

  function metricButton(value, label, filter, tone = '') {
    const selected = params().get('feedFilter') === filter ? ' selected' : '';
    return `<button class="activity-stat ${esc(tone)}${selected}" type="button" data-feed-filter="${esc(filter)}"><strong>${esc(value)}</strong><span>${esc(label)}</span></button>`;
  }

  function periodControls() {
    const selected = rangeHours();
    return `<div class="period-control" aria-label="Activity period">
      ${[[24, '24 hours'], [168, '7 days'], [720, '30 days']].map(([hours, label]) =>
        `<button type="button" data-period="${hours}" class="${selected === hours ? 'active' : ''}">${label}</button>`
      ).join('')}
    </div>`;
  }

  function coverageSummary() {
    const s = current.summary || {};
    return `<details class="coverage-summary"><summary>Archive coverage</summary><div class="coverage-grid">
      <span><strong>${Number(s.posts || 0)}</strong> posts preserved</span>
      <span><strong>${Number(s.comments || 0)}</strong> comments / replies preserved</span>
      <span><strong>${Number(s.snapshots || 0)}</strong> snapshots</span>
      <span><strong>${Number(s.editedEntities || 0)}</strong> with text versions</span>
      <span><strong>${Number(s.missing || 0)}</strong> currently not observed</span>
      <span><strong>${Number(s.confirmedUnavailable || 0)}</strong> confirmed unavailable</span>
    </div></details>`;
  }

  metrics = function () {
    const s = stats();
    const label = rangeLabel();
    el('metrics').className = 'metrics activity-metrics';
    el('metrics').innerHTML = `
      <div class="activity-dashboard-heading"><div><p class="eyebrow">RECENT ACTIVITY</p><h2>What is happening now?</h2><p>Measured against the latest archived observation. Click a card to filter the account feed.</p></div>${periodControls()}</div>
      <div class="activity-stat-grid">
        ${metricButton(s.newPosts, `new posts · ${label}`, 'new', 'positive')}
        ${metricButton(s.newComments, `new comments / replies · ${label}`, 'new-comments', 'positive')}
        ${metricButton(s.missingComments, `newly not observed · ${label}`, 'missing', 'warning')}
        ${metricButton(s.gapThreads, 'threads with visibility gaps', 'gaps', 'warning')}
        ${metricButton(s.gapTotal, 'reported − visible gap total', 'gaps', 'danger')}
        ${metricButton(s.edited, `text edits · ${label}`, 'edited', 'edited')}
      </div>${coverageSummary()}`;
  };

  function discussionSummary(post) {
    const archived = discussionCount(post);
    const vis = visibility(post.id);
    const activity = postActivity(post);
    const knownMissing = currentMissingComments(post.id).length;
    const main = vis
      ? `<span><strong>${vis.reported}</strong> Facebook reported</span><span><strong>${vis.visible}</strong> visible in latest crawl</span><span><strong>${archived}</strong> preserved historically</span>`
      : `<span><strong>—</strong> Facebook reported</span><span><strong>—</strong> visible in latest crawl</span><span><strong>${archived}</strong> preserved historically</span>`;
    const signals = [];
    if (vis?.gap > 0) signals.push(`<span class="thread-signal gap">⚠ ${vis.gap} visibility gap</span>`);
    if (knownMissing > 0) signals.push(`<span class="thread-signal missing">● ${knownMissing} previously observed ${knownMissing === 1 ? 'comment is' : 'comments are'} currently not observed</span>`);
    if (activity.newComments > 0) signals.push(`<span class="thread-signal new">+${activity.newComments} new in ${rangeLabel()}</span>`);
    if (activity.missingComments > 0) signals.push(`<span class="thread-signal missing">${activity.missingComments} newly not observed in ${rangeLabel()}</span>`);
    if (activity.edits > 0) signals.push(`<span class="thread-signal edited">${activity.edits} edit${activity.edits === 1 ? '' : 's'} in ${rangeLabel()}</span>`);
    return `<div class="thread-health"><div class="thread-health-title">Discussion</div><div class="thread-health-numbers">${main}</div>${signals.length ? `<div class="thread-signals">${signals.join('')}</div>` : ''}</div>`;
  }

  postCard = function (post, options = {}) {
    const html = originalPostCard(post, options);
    const summary = discussionSummary(post);
    return html.replace(/<div class="engagement-row">[\s\S]*?<\/div><div class="card-actions">/, `${summary}<div class="card-actions">`);
  };
  window.postCard = postCard;

  function commentActivityClass(comment) {
    const classes = [];
    if (MISSING.has(comment.status)) classes.push('activity-missing');
    if (comment.status === 'reappeared') classes.push('activity-reappeared');
    if ((comment.versions || []).length > 1) classes.push('activity-edited');
    if (inRange(comment.firstSeen)) classes.push('activity-new');
    return classes.join(' ');
  }

  function commentStatusStrip(comment) {
    if (MISSING.has(comment.status)) {
      const direct = comment.status === 'confirmed_unavailable' ? 'Confirmed unavailable' : 'Not observed in latest covered crawl';
      return `<div class="comment-state-strip missing"><strong>${direct}</strong><span>Last observed ${esc(time(comment.lastSeen))}. The archive records non-observation; it does not infer why the comment is unavailable.</span></div>`;
    }
    if (comment.status === 'reappeared') {
      return `<div class="comment-state-strip reappeared"><strong>Reappeared</strong><span>Previously not observed, then seen again in a later crawl.</span></div>`;
    }
    if (inRange(comment.firstSeen)) return `<div class="comment-state-strip new"><strong>Newly observed</strong><span>First captured within the last ${esc(rangeLabel())}.</span></div>`;
    if ((comment.versions || []).length > 1) return `<div class="comment-state-strip edited"><strong>Edited text observed</strong><span>${comment.versions.length} substantive archived versions.</span></div>`;
    return '';
  }

  commentCard = function (comment, options = {}) {
    let html = originalCommentCard(comment, options);
    const cls = commentActivityClass(comment);
    if (cls) html = html.replace('class="comment-card ', `class="comment-card ${cls} `);
    const strip = commentStatusStrip(comment);
    if (strip) html = html.replace('</article>', `${strip}</article>`);
    return html;
  };
  window.commentCard = commentCard;

  function threadFilterBar(post) {
    const comments = commentEntities(post.id);
    const newCount = comments.filter(c => inRange(c.firstSeen)).length;
    const missingCount = comments.filter(c => MISSING.has(c.status)).length;
    const editedCount = comments.filter(c => (c.versions || []).length > 1).length;
    const reappearedCount = comments.filter(c => c.status === 'reappeared').length;
    return `<div class="thread-filter-bar" data-post-id="${esc(post.id)}">
      <span>Show:</span>
      <button type="button" data-thread-filter="all" class="active">All <b>${comments.length}</b></button>
      <button type="button" data-thread-filter="new">New <b>${newCount}</b></button>
      <button type="button" data-thread-filter="missing">Not observed <b>${missingCount}</b></button>
      <button type="button" data-thread-filter="edited">Edited <b>${editedCount}</b></button>
      <button type="button" data-thread-filter="reappeared">Reappeared <b>${reappearedCount}</b></button>
    </div>`;
  }

  if (typeof originalInlinePanel === 'function') {
    window.archiveInlineDiscussionPanel = function (post) {
      const html = originalInlinePanel(post);
      if (!html) return html;
      return html.replace('<div class="inline-comment-list">', `${threadFilterBar(post)}<div class="inline-comment-list">`);
    };
  }

  function matchesThreadFilter(card, filter) {
    if (filter === 'all') return true;
    return card.classList.contains(`activity-${filter}`);
  }

  function applyThreadFilter(panel, filter) {
    const threads = [...panel.querySelectorAll('.comment-thread')];
    threads.forEach(thread => { thread.hidden = filter !== 'all'; });
    if (filter === 'all') return;
    [...panel.querySelectorAll('.comment-card')].filter(card => matchesThreadFilter(card, filter)).forEach(card => {
      let node = card.closest('.comment-thread');
      while (node && panel.contains(node)) {
        node.hidden = false;
        node = node.parentElement?.closest('.comment-thread');
      }
    });
  }

  function feedFilterValue() {
    return params().get('feedFilter') || 'all';
  }

  function postMatchesFilter(post, filter) {
    if (!filter || filter === 'all') return true;
    const activity = postActivity(post);
    if (filter === 'new') return inRange(post.firstSeen) || activity.newComments > 0;
    if (filter === 'new-comments') return activity.newComments > 0;
    if (filter === 'missing') return MISSING.has(post.status) || currentMissingComments(post.id).length > 0 || activity.missingComments > 0;
    if (filter === 'gaps') return (visibility(post.id)?.gap || 0) > 0;
    if (filter === 'edited') return (post.versions || []).length > 1 || activity.edits > 0;
    return true;
  }

  function feedSortValue() {
    return params().get('feedSort') || 'publication';
  }

  function sortedPosts(queryText = '') {
    let rows = chronologyFeedPosts(queryText).filter(post => postMatchesFilter(post, feedFilterValue()));
    const sort = feedSortValue();
    if (sort === 'activity') rows = rows.slice().sort((a, b) => postActivity(b).latestActivity - postActivity(a).latestActivity);
    if (sort === 'discussion') rows = rows.slice().sort((a, b) => discussionCount(b) - discussionCount(a));
    if (sort === 'gap') rows = rows.slice().sort((a, b) => (visibility(b.id)?.gap || 0) - (visibility(a.id)?.gap || 0));
    return rows;
  }

  feedPosts = sortedPosts;
  window.feedPosts = sortedPosts;

  function feedControls() {
    const filter = feedFilterValue(), sort = feedSortValue();
    const filters = [
      ['all', 'All'], ['new-comments', 'New activity'], ['missing', 'Not observed'], ['gaps', 'Visibility gaps'], ['edited', 'Edited']
    ];
    return `<div class="feed-controls panel"><div class="feed-filter-group"><span>Show</span>${filters.map(([value, label]) => `<button type="button" data-feed-filter="${value}" class="${filter === value ? 'active' : ''}">${label}</button>`).join('')}</div><label>Sort by<select data-feed-sort><option value="publication" ${sort === 'publication' ? 'selected' : ''}>Latest posts</option><option value="activity" ${sort === 'activity' ? 'selected' : ''}>Latest activity</option><option value="discussion" ${sort === 'discussion' ? 'selected' : ''}>Most discussion</option><option value="gap" ${sort === 'gap' ? 'selected' : ''}>Largest visibility gap</option></select></label></div>`;
  }

  viewFeed = function () {
    const q = currentQuery(), posts = sortedPosts(q), shown = posts.slice(0, renderedFeedLimit);
    const latest = current.snapshots?.[0]?.observedAt || current.latestDelta?.observedAt || '';
    return `<section class="view-section feed-layout"><div class="feed-column"><div class="view-heading"><div><p class="eyebrow">ACCOUNT HISTORY</p><h2>${esc(current.target.displayName)} feed</h2><p>Publication chronology is the default. Activity and discrepancy filters expose what changed without replacing the historical state.</p></div><div class="feed-heading-meta"><strong>Latest crawl</strong><span>${esc(time(latest))}</span><span>${posts.length} matching post${posts.length === 1 ? '' : 's'}</span></div></div>${feedControls()}${shown.map(post => postCard(post)).join('') || '<div class="empty">No posts match this filter.</div>'}${shown.length < posts.length ? `<button class="load-more" data-action="more-feed">Show more posts (${posts.length - shown.length} remaining)</button>` : ''}</div><aside class="feed-sidebar panel"><p class="eyebrow">HOW TO READ THE DATA</p><h3>Three different comment counts</h3><p><strong>Facebook reported</strong> is the headline count Facebook displayed.</p><p><strong>Visible</strong> is what the latest crawl could retrieve.</p><p><strong>Preserved historically</strong> is what this archive has observed across all snapshots.</p><p><strong>Visibility gap</strong> means reported minus visible. It may reflect deletion, hiding, moderation, privacy, ranking, or other limits; the archive does not infer a cause.</p><hr><p><span class="status-badge missing_once">not observed</span> is only applied inside proven crawl coverage. Comments are re-evaluated only when their parent thread was actually revisited.</p></aside></section>`;
  };
  window.viewFeed = viewFeed;

  viewChanges = function () {
    const hours = rangeHours(), events = recentEvents(hours).filter(event => !['bulk_missing', 'bulk_missing_thread'].includes(event.type));
    const s = stats(hours);
    const latest = current.snapshots?.[0] || {};
    const scope = latest.missingDetectionApplied
      ? `Negative observations were evaluated only inside proven coverage (${latest.coverageStart || 'window start'} through ${latest.coverageEnd || 'window end'}), and comments only on revisited threads.`
      : 'This observation did not establish comparable negative coverage, so absence alone was not used to mark records missing.';
    return `<section class="view-section"><div class="view-heading"><div><p class="eyebrow">ACTIVITY TIMELINE</p><h2>What changed?</h2><p>${esc(scope)}</p></div>${periodControls()}</div><div class="delta-grid activity-delta"><div class="delta-stat positive"><strong>${s.newPosts}</strong><span>new posts</span></div><div class="delta-stat positive"><strong>${s.newComments}</strong><span>new comments / replies</span></div><div class="delta-stat warning"><strong>${s.missingComments}</strong><span>newly not observed</span></div><div class="delta-stat edited"><strong>${s.edited}</strong><span>text edits</span></div><div class="delta-stat neutral"><strong>${s.reappeared}</strong><span>reappeared</span></div></div><div class="section-heading"><div><p class="eyebrow">LAST ${esc(rangeLabel(hours).toUpperCase())}</p><h2>Observed activity</h2></div><p>${events.length} record-level event${events.length === 1 ? '' : 's'}</p></div><div>${events.length ? events.slice().sort((a,b) => parseMs(b.observedAt) - parseMs(a.observedAt)).map(eventCard).join('') : '<div class="empty">No record-level changes were observed in this period.</div>'}</div></section>`;
  };
  window.viewChanges = viewChanges;

  document.addEventListener('click', event => {
    const period = event.target.closest('[data-period]');
    if (period) {
      event.preventDefault();
      setParams({ period: period.dataset.period }, false);
      return;
    }
    const feedFilter = event.target.closest('[data-feed-filter]');
    if (feedFilter) {
      event.preventDefault();
      const value = feedFilter.dataset.feedFilter;
      setParams({ view: 'feed', feedFilter: value === 'all' ? null : value }, false);
      return;
    }
    const threadFilter = event.target.closest('[data-thread-filter]');
    if (threadFilter) {
      event.preventDefault();
      const bar = threadFilter.closest('.thread-filter-bar');
      const panel = threadFilter.closest('.inline-discussion');
      if (!bar || !panel) return;
      bar.querySelectorAll('[data-thread-filter]').forEach(button => button.classList.toggle('active', button === threadFilter));
      applyThreadFilter(panel, threadFilter.dataset.threadFilter || 'all');
    }
  });

  document.addEventListener('change', event => {
    const select = event.target.closest('[data-feed-sort]');
    if (!select) return;
    setParams({ view: 'feed', feedSort: select.value === 'publication' ? null : select.value }, false);
  });

  if (typeof current !== 'undefined' && current) render();
})();
