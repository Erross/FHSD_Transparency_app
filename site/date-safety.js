/* Date-safety and deterministic feed-order hardening.

   Facebook often exposes labels such as "August 25" without a year. Browser
   Date parsing is not safe for those strings: Chromium can interpret a
   yearless label as a date in 2001. This layer never asks the browser to guess.

   Only explicit year-bearing ISO values are parsed. Raw yearless Facebook
   labels remain raw labels. Target-specific earliest plausible dates can also
   reject impossible publication years without rewriting the raw evidence.
*/
(function () {
  const ISO_DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
  const ISO_WITH_YEAR = /^\d{4}-\d{2}-\d{2}T/;
  const FACEBOOK_EARLIEST_YEAR = 2004;

  function strictDate(value) {
    const text = String(value || '').trim();
    if (!text) return null;
    if (!ISO_DATE_ONLY.test(text) && !ISO_WITH_YEAR.test(text)) return null;

    const year = Number(text.slice(0, 4));
    const maxYear = new Date().getFullYear() + 1;
    if (!Number.isInteger(year) || year < FACEBOOK_EARLIEST_YEAR || year > maxYear) return null;

    let parsed;
    if (ISO_DATE_ONLY.test(text)) {
      const [y, m, d] = text.split('-').map(Number);
      parsed = new Date(y, m - 1, d);
      if (parsed.getFullYear() !== y || parsed.getMonth() !== m - 1 || parsed.getDate() !== d) return null;
    } else {
      parsed = new Date(text);
      if (Number.isNaN(parsed.getTime())) return null;
    }
    return parsed;
  }

  function targetMinimumDate() {
    const raw = String(current?.target?.earliestPublicationDate || '').trim();
    return strictDate(raw);
  }

  function safePublicationDate(value) {
    const parsed = strictDate(value);
    if (!parsed) return null;
    const minimum = targetMinimumDate();
    if (minimum && parsed < minimum) return null;
    return parsed;
  }

  function rawPublicationValue(entity) {
    return entity?.publishedAt || entity?.publishedDate || entity?.timestampExact || entity?.timestampText || '';
  }

  function formatStrict(value, parsed) {
    const text = String(value || '').trim();
    if (ISO_DATE_ONLY.test(text)) {
      return parsed.toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' });
    }
    return parsed.toLocaleString([], { year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  }

  function publicationLabel(entity) {
    const raw = String(rawPublicationValue(entity) || '').trim();
    if (!raw) return 'publication date unavailable';

    const parsed = safePublicationDate(raw);
    if (parsed) return formatStrict(raw, parsed);

    // If the crawler supplied an explicit year that fails plausibility checks,
    // do not surface it as a publication date. Preserve the raw value in the
    // provenance panel instead.
    if (/^\d{4}-/.test(raw)) return 'publication date unavailable · invalid captured date';

    // Yearless/relative Facebook labels remain exactly what Facebook exposed.
    // Crucially, they are never passed to new Date().
    return `${raw} · year not captured`;
  }

  function sortablePublication(entity) {
    for (const value of [entity?.publishedAt, entity?.publishedDate, entity?.timestampExact]) {
      const parsed = safePublicationDate(value);
      if (parsed) return parsed.getTime();
    }
    return null;
  }

  function observationOrder(entity) {
    for (const value of [entity?.lastSeen, entity?.firstSeen, entity?.capturedAt]) {
      const parsed = strictDate(value);
      if (parsed) return parsed.getTime();
    }
    return 0;
  }

  function newestFirst(a, b) {
    const left = sortablePublication(a);
    const right = sortablePublication(b);
    if (left !== null && right !== null && left !== right) return right - left;
    if (left !== null && right === null) return -1;
    if (left === null && right !== null) return 1;

    // Both are undated. The generated entity list preserves crawler/feed order
    // for equal observation times; returning 0 preserves that stable order.
    const leftObserved = observationOrder(a);
    const rightObserved = observationOrder(b);
    return leftObserved === rightObserved ? 0 : rightObserved - leftObserved;
  }

  function oldestFirst(a, b) {
    const left = sortablePublication(a);
    const right = sortablePublication(b);
    if (left !== null && right !== null && left !== right) return left - right;
    if (left !== null && right === null) return -1;
    if (left === null && right !== null) return 1;
    const leftObserved = observationOrder(a);
    const rightObserved = observationOrder(b);
    return leftObserved === rightObserved ? 0 : leftObserved - rightObserved;
  }

  // Replace generic browser parsing with strict ISO-only parsing globally.
  dateValue = function (value) {
    return strictDate(value);
  };

  time = function (value) {
    const text = String(value || '').trim();
    if (!text) return 'time unavailable';
    const parsed = strictDate(text);
    return parsed ? formatStrict(text, parsed) : text;
  };

  contentTime = function (entity) {
    return rawPublicationValue(entity);
  };

  authorBlock = function (entity) {
    const name = entity.authorDisplayName || entity.author || 'Unknown author';
    const key = entity.authorKey || `name:${String(name).toLowerCase()}`;
    return `<div class="author-row"><div class="avatar" aria-hidden="true">${esc(initials(name))}</div><div><a class="author-name" href="${esc(authorUrl(key))}">${esc(name)}</a><div class="post-time">${esc(publicationLabel(entity))}</div></div></div>`;
  };

  commentCard = function (comment, options = {}) {
    const source = comment.permalink;
    const key = comment.authorKey || `name:${String(comment.author || '').toLowerCase()}`;
    return `<article class="comment-card ${options.highlight ? 'highlighted-comment' : ''}" id="comment-${esc(comment.id)}"><div class="avatar small">${esc(initials(comment.authorDisplayName || comment.author))}</div><div class="comment-main"><div class="comment-bubble"><a class="author-name" href="${esc(authorUrl(key))}">${esc(comment.authorDisplayName || comment.author || 'Unknown author')}</a><div>${esc(comment.text || '')}</div></div><div class="comment-meta">${esc(publicationLabel(comment))} · ${esc(statusLabel(comment.status))} ${source ? `· ${externalLink(source, 'source ↗')}` : ''}</div></div></article>`;
  };

  commentEntities = function (postId) {
    return current.entities
      .filter(entity => entity.itemType !== 'post' && entity.parentId === postId)
      .sort(oldestFirst);
  };

  feedPosts = function (queryText = '') {
    const query = queryText.trim().toLowerCase();
    return current.entities
      .filter(entity => entity.itemType === 'post')
      .filter(post => {
        if (!query) return true;
        const comments = commentEntities(post.id);
        return `${post.author} ${post.text} ${post.attachmentSummary || ''}`.toLowerCase().includes(query)
          || comments.some(comment => `${comment.author} ${comment.text}`.toLowerCase().includes(query));
      })
      .sort(newestFirst);
  };

  viewFeed = function () {
    const query = currentQuery();
    const posts = feedPosts(query);
    const shown = posts.slice(0, renderedFeedLimit);
    return `<section class="view-section feed-layout"><div class="feed-column"><div class="view-heading"><div><p class="eyebrow">ACCOUNT HISTORY</p><h2>${esc(current.target.displayName)} feed</h2><p>Posts are shown newest → oldest when a reliable publication date exists. Undated captures retain crawler/feed order and are never assigned an invented publication year.</p></div><p>${posts.length} matching post${posts.length === 1 ? '' : 's'}</p></div>${shown.map(post => postCard(post)).join('') || '<div class="empty">No matching posts.</div>'}${shown.length < posts.length ? `<button class="load-more" data-action="more-feed">Show more posts (${posts.length - shown.length} remaining)</button>` : ''}</div><aside class="feed-sidebar panel"><p class="eyebrow">ARCHIVE FLAGS</p><h3>How cards are marked</h3><p><span class="status-badge edited">observed versions</span> The archive saw substantive text versions after filtering Facebook UI noise.</p><p><span class="status-badge missing_once">not observed once</span> Absent from a later comparable crawl.</p><p><span class="status-badge confirmed_unavailable">confirmed unavailable</span> Separately reviewed or directly checked.</p><p><span class="status-badge incomplete">capture incomplete</span> The crawler retained truncated text; this is not treated as an authored edit.</p></aside></section>`;
  };

  personDetail = function (key) {
    const author = deriveAuthors().find(row => row.key === key);
    if (!author) return '<div class="empty">Author not found in this target.</div>';
    const entities = (author.entityIds || []).map(id => entityMap.get(id)).filter(Boolean).sort(newestFirst);
    const comments = entities.filter(entity => entity.itemType !== 'post');
    const posts = entities.filter(entity => entity.itemType === 'post');
    return `<section class="view-section"><div class="person-hero panel"><div class="avatar large">${esc(initials(author.displayName))}</div><div><p class="eyebrow">OBSERVED PUBLIC AUTHOR</p><h2>${esc(author.displayName)}</h2><p>${comments.length} captured comment/repl${comments.length === 1 ? 'y' : 'ies'} · ${posts.length} captured post${posts.length === 1 ? '' : 's'} in ${esc(current.target.displayName)} material.</p>${externalLink(author.profileUrl, 'Public Facebook profile ↗')}</div></div><div class="section-heading"><div><p class="eyebrow">PUBLIC COMMENTARY</p><h2>Captured comments and replies</h2></div></div>${comments.length ? comments.map(comment => { const parent = entityMap.get(comment.parentId); return `<div class="person-result">${commentCard(comment)}<div class="context-row">${parent ? `On: ${routeLink(entityUrl(parent.id), truncate(parent.text, 120))}` : 'Parent post not recovered'} ${comment.permalink ? externalLink(comment.permalink, 'Jump to Facebook comment ↗') : ''}</div></div>`; }).join('') : '<div class="empty">No comments or replies captured for this author.</div>'}${posts.length ? `<div class="section-heading"><div><p class="eyebrow">AUTHORED POSTS</p><h2>Captured posts</h2></div></div>${posts.map(post => postCard(post)).join('')}` : ''}</section>`;
  };

  archiveResults = function () {
    const query = currentQuery().trim().toLowerCase();
    let rows = current.entities;
    if (query) rows = rows.filter(entity => `${entity.author} ${entity.authorDisplayName || ''} ${entity.text} ${entity.attachmentSummary || ''} ${entity.id}`.toLowerCase().includes(query));
    return rows.slice().sort(newestFirst);
  };

  provenance = function (entity) {
    return `<div class="panel provenance"><p class="eyebrow">ARCHIVE RECORD</p><dl><dt>Archive ID</dt><dd>${esc(entity.id)}</dd><dt>Type</dt><dd>${esc(entity.itemType)}</dd><dt>First observed</dt><dd>${esc(time(entity.firstSeen))}</dd><dt>Last observed</dt><dd>${esc(time(entity.lastSeen))}</dd><dt>Publication date</dt><dd>${esc(publicationLabel(entity))}</dd><dt>Raw Facebook label</dt><dd>${esc(entity.timestampText || entity.timestampExact || 'unavailable')}</dd><dt>Identity confidence</dt><dd>${esc(entity.identityConfidence || entity.identityQuality || 'unknown')}</dd><dt>Capture completeness</dt><dd>${entity.bodyComplete === false || entity.contentCompleteness === 'truncated' ? 'incomplete / truncated' : 'complete as observed'}</dd><dt>Current archive status</dt><dd>${esc(statusLabel(entity.status))}</dd></dl>${externalLink(entity.permalink || entity.parentPostPermalink, 'Open current Facebook source ↗')}</div>`;
  };

  // Re-render if app.js completed its first asynchronous load before this
  // enhancement script ran. Otherwise the overridden functions will be used
  // naturally when the target data finishes loading.
  if (typeof current !== 'undefined' && current) render();
})();
