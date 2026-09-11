/* Final feed-order override: publication evidence wins; observation time never
   masquerades as publication time. Truly undated posts sort after posts with
   usable chronology, preserving observation order only within the undated set. */
(function () {
  function parseMs(value) {
    if (!value) return 0;
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? 0 : d.getTime();
  }

  function publicationChronologyMs(entity) {
    for (const value of [
      entity?.publishedAt,
      entity?.publishedDate,
      entity?.timestampExact,
      entity?.publishedAtEstimated,
      entity?.publishedAtUpperBound
    ]) {
      const ms = parseMs(value);
      if (ms) return ms;
    }
    return null;
  }

  function observationMs(entity) {
    for (const value of [entity?.firstSeen, entity?.capturedAt, entity?.lastSeen]) {
      const ms = parseMs(value);
      if (ms) return ms;
    }
    return 0;
  }

  function newestFirst(a, b) {
    const left = publicationChronologyMs(a);
    const right = publicationChronologyMs(b);
    if (left !== null && right !== null && left !== right) return right - left;
    if (left !== null && right === null) return -1;
    if (left === null && right !== null) return 1;
    return observationMs(b) - observationMs(a);
  }

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

  if (typeof current !== 'undefined' && current) render();
})();
