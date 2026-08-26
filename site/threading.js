/* Progressive enhancement for archived Facebook reply hierarchy.
   Kept separate from app.js so the core static UI remains simple and testable. */
(function () {
  if (typeof commentEntities !== 'function' || typeof commentCard !== 'function' || typeof viewRecord !== 'function') return;

  function archivedCommentThread(postId, highlightedId) {
    const comments = commentEntities(postId);
    const byCommentId = new Map();
    comments.forEach(comment => {
      const id = String(comment.commentId || comment.replyCommentId || '');
      if (id) byCommentId.set(id, comment);
    });

    const children = new Map();
    const roots = [];
    comments.forEach(comment => {
      const parentId = String(comment.parentCommentId || '');
      const parent = parentId ? byCommentId.get(parentId) : null;
      if (parent && parent.id !== comment.id) {
        if (!children.has(parent.id)) children.set(parent.id, []);
        children.get(parent.id).push(comment);
      } else {
        roots.push(comment);
      }
    });

    const renderNode = (comment, depth, lineage) => {
      if (lineage.has(comment.id)) return '';
      const nextLineage = new Set(lineage);
      nextLineage.add(comment.id);
      const safeDepth = Math.min(depth, 4);
      const nested = (children.get(comment.id) || [])
        .map(child => renderNode(child, safeDepth + 1, nextLineage))
        .join('');
      return `<div class="comment-thread depth-${safeDepth}">${commentCard(comment, { highlight: comment.id === highlightedId })}${nested}</div>`;
    };

    return {
      comments,
      html: roots.map(comment => renderNode(comment, 0, new Set())).join('')
    };
  }

  viewRecord = function () {
    const id = params().get('entity');
    const entity = entityMap.get(id);
    if (!entity) return '<div class="empty">Archive record not found.</div>';
    const post = entity.itemType === 'post' ? entity : entityMap.get(entity.parentId);
    const thread = post ? archivedCommentThread(post.id, entity.id) : { comments: [], html: '' };
    const comments = thread.comments;
    return `<section class="view-section"><div class="view-heading"><div><p class="eyebrow">ARCHIVED DISCUSSION</p><h2>${esc(post?.author || entity.author || 'Archive record')}</h2></div>${routeLink(`?target=${encodeURIComponent(current.target.id)}&view=feed`, 'Back to feed')}</div>
      <div class="record-layout"><div>${post ? postCard(post, { highlight: entity.id === post.id }) : resultCard(entity)}
        ${post ? `<div class="discussion"><div class="section-heading"><div><p class="eyebrow">DISCUSSION</p><h3>${comments.length} archived comment${comments.length === 1 ? '' : 's'} / replies</h3></div></div>${thread.html || '<div class="empty">No comments were captured for this post.</div>'}</div>` : ''}
      </div><aside>${provenance(entity)}${versionsPanel(entity)}</aside></div>
    </section>`;
  };
})();
