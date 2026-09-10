/* Infer a conservative post chronology from crawler/archive evidence.
   Loaded after date-safety.js so exact publication timestamps remain preferred. */
(function () {
  const ISO_DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
  const ISO_WITH_YEAR = /^\d{4}-\d{2}-\d{2}T/;

  function strictIso(value) {
    const text = String(value || '').trim();
    if (!text || (!ISO_DATE_ONLY.test(text) && !ISO_WITH_YEAR.test(text))) return null;
    const parsed = new Date(text);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  function formatIso(value, parsed) {
    return ISO_DATE_ONLY.test(String(value || '').trim())
      ? parsed.toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' })
      : parsed.toLocaleString([], { year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  }

  function exactPublication(entity) {
    for (const value of [entity?.publishedAt, entity?.publishedDate, entity?.timestampExact]) {
      const parsed = strictIso(value);
      if (parsed) return { value, parsed };
    }
    return null;
  }

  function estimatedPublication(entity) {
    const value = String(entity?.publishedAtEstimated || '').trim();
    const parsed = strictIso(value);
    return value && parsed ? { value, parsed } : null;
  }

  function inferredPublication(entity) {
    const value = String(entity?.publishedAtUpperBound || '').trim();
    const parsed = strictIso(value);
    return value && parsed ? { value, parsed } : null;
  }

  function publicationSortMs(entity) {
    const exact = exactPublication(entity);
    if (exact) return exact.parsed.getTime();
    const estimated = estimatedPublication(entity);
    if (estimated) return estimated.parsed.getTime();
    const inferred = inferredPublication(entity);
    return inferred ? inferred.parsed.getTime() : null;
  }

  function publicationLabel(entity) {
    const exact = exactPublication(entity);
    if (exact) return formatIso(exact.value, exact.parsed);

    const estimated = estimatedPublication(entity);
    if (estimated) {
      const raw = String(entity?.publicationEvidenceLabel || '').trim();
      const suffix = raw ? ` · Facebook showed “${raw}”` : ' · derived from Facebook relative time';
      return `about ${formatIso(estimated.value, estimated.parsed)}${suffix}`;
    }

    const inferred = inferredPublication(entity);
    if (inferred) {
      const source = String(entity?.publishedAtUpperBoundSource || '').trim();
      const note = source === 'earliest-observed-comment' || source === 'earliest-archived-comment'
        ? 'inferred from earliest archived comment'
        : 'inferred from archive evidence';
      return `posted by ${formatIso(inferred.value, inferred.parsed)} · ${note}`;
    }

    const raw = String(entity?.timestampText || '').trim();
    return raw ? `${raw} · exact date not captured` : 'publication date unavailable';
  }

  function observationMs(entity) {
    for (const value of [entity?.lastSeen, entity?.firstSeen, entity?.capturedAt]) {
      const parsed = strictIso(value);
      if (parsed) return parsed.getTime();
    }
    return 0;
  }

  function newestFirst(a, b) {
    const left = publicationSortMs(a), right = publicationSortMs(b);
    if (left !== null && right !== null && left !== right) return right - left;
    if (left !== null && right === null) return -1;
    if (left === null && right !== null) return 1;
    return observationMs(b) - observationMs(a);
  }

  function oldestFirst(a, b) {
    const left = publicationSortMs(a), right = publicationSortMs(b);
    if (left !== null && right !== null && left !== right) return left - right;
    if (left !== null && right === null) return -1;
    if (left === null && right !== null) return 1;
    return observationMs(a) - observationMs(b);
  }

  contentTime = function (entity) {
    const exact = exactPublication(entity);
    if (exact) return exact.value;
    const estimated = estimatedPublication(entity);
    if (estimated) return estimated.value;
    const inferred = inferredPublication(entity);
    if (inferred) return inferred.value;
    return entity?.timestampText || entity?.firstSeen || entity?.lastSeen || '';
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

  archiveResults = function () {
    const query = currentQuery().trim().toLowerCase();
    let rows = current.entities;
    if (query) rows = rows.filter(entity => `${entity.author} ${entity.authorDisplayName || ''} ${entity.text} ${entity.attachmentSummary || ''} ${entity.id}`.toLowerCase().includes(query));
    return rows.slice().sort(newestFirst);
  };

  provenance = function (entity) {
    const bounds = entity.publishedAtLowerBound || entity.publishedAtUpperBound
      ? `<dt>Publication evidence</dt><dd>${esc(publicationLabel(entity))}</dd>`
      : '';
    return `<div class="panel provenance"><p class="eyebrow">ARCHIVE RECORD</p><dl><dt>Archive ID</dt><dd>${esc(entity.id)}</dd><dt>Type</dt><dd>${esc(entity.itemType)}</dd><dt>First observed</dt><dd>${esc(time(entity.firstSeen))}</dd><dt>Last observed</dt><dd>${esc(time(entity.lastSeen))}</dd><dt>Publication date</dt><dd>${esc(publicationLabel(entity))}</dd>${bounds}<dt>Raw Facebook label</dt><dd>${esc(entity.publicationEvidenceLabel || entity.timestampText || entity.timestampExact || 'unavailable')}</dd><dt>Identity confidence</dt><dd>${esc(entity.identityConfidence || entity.identityQuality || 'unknown')}</dd><dt>Capture completeness</dt><dd>${entity.bodyComplete === false || entity.contentCompleteness === 'truncated' ? 'incomplete / truncated' : 'complete as observed'}</dd><dt>Current archive status</dt><dd>${esc(statusLabel(entity.status))}</dd></dl>${externalLink(entity.permalink || entity.parentPostPermalink, 'Open current Facebook source ↗')}</div>`;
  };

  if (typeof current !== 'undefined' && current) render();
})();
