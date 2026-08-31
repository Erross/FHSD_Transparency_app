/* Progressive, in-feed rendering for archived Facebook discussions.
   The full record route remains available for provenance and version history. */
(function () {
  if (typeof commentEntities !== 'function' || typeof commentCard !== 'function' || typeof viewRecord !== 'function') return;

  const INITIAL_ROOTS = 3;
  const ROOT_BATCH = 5;
  const INITIAL_REPLIES = 2;
  const REPLY_BATCH = 3;
  const inlineState = new Map();

  function stateKey(postId) {
    return `${current?.target?.id || ''}::${postId}`;
  }

  function stateFor(postId) {
    const key = stateKey(postId);
    if (!inlineState.has(key)) {
      inlineState.set(key, {
        expanded: false,
        visibleRoots: INITIAL_ROOTS,
        replyLimits: new Map()
      });
    }
    return inlineState.get(key);
  }

  function domToken(value) {
    return encodeURIComponent(String(value || '')).replaceAll('%', '_');
  }

  function buildThread(postId) {
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

    // Malformed source relationships can contain cycles. Treat one member as
    // a root so every archived observation remains reachable without looping.
    const reachable = new Set();
    const markReachable = (comment, lineage = new Set()) => {
      if (!comment || lineage.has(comment.id) || reachable.has(comment.id)) return;
      reachable.add(comment.id);
      const next = new Set(lineage);
      next.add(comment.id);
      (children.get(comment.id) || []).forEach(child => markReachable(child, next));
    };
    roots.forEach(root => markReachable(root));
    comments.forEach(comment => {
      if (!reachable.has(comment.id)) {
        roots.push(comment);
        markReachable(comment);
      }
    });

    return { comments, roots, children };
  }

  function renderThread(model, options = {}) {
    const progressive = options.progressive === true;
    const state = options.state || {
      visibleRoots: model.roots.length,
      replyLimits: new Map()
    };
    const rootLimit = progressive ? state.visibleRoots : model.roots.length;
    const emitted = new Set();
    let visibleCount = 0;

    const renderNode = (comment, depth, lineage) => {
      if (!comment || lineage.has(comment.id) || emitted.has(comment.id)) return '';
      emitted.add(comment.id);
      visibleCount += 1;

      const nextLineage = new Set(lineage);
      nextLineage.add(comment.id);
      const safeDepth = Math.min(depth, 4);
      const replies = model.children.get(comment.id) || [];
      const configuredLimit = state.replyLimits.get(comment.id);
      const replyLimit = progressive
        ? Math.min(configuredLimit ?? INITIAL_REPLIES, replies.length)
        : replies.length;
      const nested = replies
        .slice(0, replyLimit)
        .map(reply => renderNode(reply, safeDepth + 1, nextLineage))
        .join('');
      const hiddenReplies = replies.length - replyLimit;
      const moreReplies = progressive && hiddenReplies > 0
        ? `<button class="inline-replies-more depth-${Math.min(safeDepth + 1, 4)}" type="button" data-action="more-inline-replies" data-post-id="${esc(options.postId)}" data-comment-id="${esc(comment.id)}">View ${Math.min(REPLY_BATCH, hiddenReplies)} more repl${Math.min(REPLY_BATCH, hiddenReplies) === 1 ? 'y' : 'ies'} <span>(${hiddenReplies} remaining)</span></button>`
        : '';

      return `<div class="comment-thread depth-${safeDepth}">${commentCard(comment, { highlight: comment.id === options.highlightedId })}${nested}${moreReplies}</div>`;
    };

    const html = model.roots
      .slice(0, rootLimit)
      .map(comment => renderNode(comment, 0, new Set()))
      .join('');
    return {
      html,
      visibleCount,
      hiddenRoots: Math.max(0, model.roots.length - rootLimit)
    };
  }

  function inlineDiscussionControls(post, count) {
    if (!count) return '';
    const state = stateFor(post.id);
    const panelId = `inline-thread-${domToken(post.id)}`;
    return `<button class="inline-comment-toggle" type="button" data-action="toggle-inline-comments" data-post-id="${esc(post.id)}" aria-expanded="${state.expanded ? 'true' : 'false'}" aria-controls="${esc(panelId)}">${state.expanded ? 'Hide comments' : `View all ${count} comment${count === 1 ? '' : 's'}`}</button>`;
  }

  function inlineDiscussionPanel(post) {
    const state = stateFor(post.id);
    if (!state.expanded) return '';

    const model = buildThread(post.id);
    const rendered = renderThread(model, {
      progressive: true,
      state,
      postId: post.id
    });
    const total = model.comments.length;
    const moreRoots = rendered.hiddenRoots > 0
      ? `<button class="inline-comments-more" type="button" data-action="more-inline-comments" data-post-id="${esc(post.id)}">View ${Math.min(ROOT_BATCH, rendered.hiddenRoots)} more comment${Math.min(ROOT_BATCH, rendered.hiddenRoots) === 1 ? '' : 's'}</button>`
      : '';

    return `<section class="inline-discussion" id="inline-thread-${esc(domToken(post.id))}" aria-label="Archived comments">
      <div class="inline-discussion-heading"><strong>Archived discussion</strong><span>Showing ${rendered.visibleCount} of ${total} captured comment${total === 1 ? '' : 's'}</span></div>
      <div class="inline-comment-list">${rendered.html || '<div class="empty compact">No comments were captured for this post.</div>'}</div>
      ${moreRoots ? `<div class="inline-discussion-actions">${moreRoots}</div>` : ''}
    </section>`;
  }

  function archivedCommentThread(postId, highlightedId) {
    const model = buildThread(postId);
    const rendered = renderThread(model, {
      progressive: false,
      highlightedId,
      postId
    });
    return { comments: model.comments, html: rendered.html };
  }

  function replacePostCard(trigger, postId, focusAction) {
    const post = entityMap.get(postId);
    const card = trigger.closest('.post-card');
    if (!post || !card) {
      renderView();
      return;
    }
    const template = document.createElement('template');
    template.innerHTML = postCard(post).trim();
    card.replaceWith(template.content.firstElementChild);
    const freshCard = document.getElementById(`card-${postId}`);
    const focusTarget = freshCard?.querySelector(`[data-action="${focusAction}"]`)
      || freshCard?.querySelector('[data-action="toggle-inline-comments"]');
    focusTarget?.focus({ preventScroll: true });
  }

  window.archiveInlineDiscussionControls = inlineDiscussionControls;
  window.archiveInlineDiscussionPanel = inlineDiscussionPanel;
  window.ArchiveThreading = { buildThread, renderThread };

  document.addEventListener('click', event => {
    const action = event.target.closest(
      '[data-action="toggle-inline-comments"], [data-action="more-inline-comments"], [data-action="more-inline-replies"]'
    );
    if (!action) return;
    event.preventDefault();

    const postId = action.dataset.postId;
    const state = stateFor(postId);
    let focusAction = 'toggle-inline-comments';
    if (action.dataset.action === 'toggle-inline-comments') {
      state.expanded = !state.expanded;
    } else if (action.dataset.action === 'more-inline-comments') {
      state.expanded = true;
      state.visibleRoots += ROOT_BATCH;
      focusAction = 'more-inline-comments';
    } else {
      state.expanded = true;
      const parentId = action.dataset.commentId;
      const currentLimit = state.replyLimits.get(parentId) ?? INITIAL_REPLIES;
      state.replyLimits.set(parentId, currentLimit + REPLY_BATCH);
      focusAction = 'more-inline-replies';
    }
    replacePostCard(action, postId, focusAction);
  });

  viewRecord = function () {
    const id = params().get('entity');
    const entity = entityMap.get(id);
    if (!entity) return '<div class="empty">Archive record not found.</div>';
    const post = entity.itemType === 'post' ? entity : entityMap.get(entity.parentId);
    const thread = post ? archivedCommentThread(post.id, entity.id) : { comments: [], html: '' };
    const comments = thread.comments;
    return `<section class="view-section"><div class="view-heading"><div><p class="eyebrow">ARCHIVED DISCUSSION</p><h2>${esc(post?.author || entity.author || 'Archive record')}</h2></div>${routeLink(`?target=${encodeURIComponent(current.target.id)}&view=feed`, 'Back to feed')}</div>
      <div class="record-layout"><div>${post ? postCard(post, { highlight: entity.id === post.id, inlineDiscussion: false }) : resultCard(entity)}
        ${post ? `<div class="discussion"><div class="section-heading"><div><p class="eyebrow">DISCUSSION</p><h3>${comments.length} archived comment${comments.length === 1 ? '' : 's'} / replies</h3></div></div>${thread.html || '<div class="empty">No comments were captured for this post.</div>'}</div>` : ''}
      </div><aside>${provenance(entity)}${versionsPanel(entity)}</aside></div>
    </section>`;
  };

  // The app may finish a cached fetch before this enhancement executes.
  if (typeof current !== 'undefined' && current) render();
})();
