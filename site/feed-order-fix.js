/* Final feed-order override: use publication evidence when available, otherwise first observation. */
(function () {
  function parseMs(value) {
    if (!value) return 0;
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? 0 : d.getTime();
  }

  function feedChronologyMs(entity) {
    for (const value of [
      entity?.publishedAt,
      entity?.publishedDate,
      entity?.timestampExact,
      entity?.publishedAtEstimated,
      entity?.publishedAtUpperBound,
      entity?.firstSeen,
      entity?.capturedAt,
      entity?.lastSeen
    ]) {
      const ms = parseMs(value);
      if (ms) return ms;
    }
    return 0;
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
      .sort((a, b) => feedChronologyMs(b) - feedChronologyMs(a));
  };

  if (typeof current !== 'undefined' && current) render();
})();
