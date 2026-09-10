// Reported-vs-visible comment presentation.
// "Reported" is Facebook's headline count. "Visible" is what the latest
// settled crawl could actually see. A gap is not labelled a deletion because
// moderation, hiding, privacy, ranking, or other Facebook visibility rules can
// also explain it.
(() => {
  const originalPostCard = window.postCard || postCard;

  function visibilityMetric(post, archivedCount) {
    const map = (window.current || current)?.commentVisibility || {};
    const row = map?.[post?.id];
    if (!row) {
      return `<span>💬 Reported — · Visible —</span><span>${archivedCount} archived</span>`;
    }
    const reported = Number(row.reported || 0);
    const visible = Number(row.visible || 0);
    const gap = Math.max(0, Number(row.gap || reported - visible));
    const note = gap > 0
      ? `Facebook reports ${reported} comment${reported === 1 ? '' : 's'}; ${visible} ${visible === 1 ? 'is' : 'are'} currently visible to the crawl. The ${gap}-comment gap may reflect deletion, hiding, moderation, privacy, or other visibility limits; no cause is inferred.`
      : `Facebook reports ${reported} comment${reported === 1 ? '' : 's'} and ${visible} ${visible === 1 ? 'is' : 'are'} visible to the crawl.`;
    return `<span title="${esc(note)}">💬 Reported ${reported} · Visible ${visible}</span><span>${archivedCount} archived</span>`;
  }

  function patchedPostCard(post, options = {}) {
    const archivedCount = discussionCount(post);
    const html = originalPostCard(post, options);
    const metric = visibilityMetric(post, archivedCount);
    return html.replace(
      /<div class="engagement-row">[\s\S]*?<\/div><div class="card-actions">/,
      `<div class="engagement-row">${metric}</div><div class="card-actions">`
    );
  }

  window.postCard = patchedPostCard;
  postCard = patchedPostCard;
})();
