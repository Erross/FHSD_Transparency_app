/* Compact comment-state badges with on-demand audit detail.
   Loaded after activity-ui.js so it replaces the large repeated state strips
   while preserving the archive's underlying status/event model. */
(function () {
  const MISSING = new Set(['missing_once', 'missing_recheck', 'confirmed_unavailable']);
  const priorCommentCard = window.commentCard || commentCard;

  function parseMs(value) {
    if (!value) return 0;
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? 0 : d.getTime();
  }

  function latestObservationMs() {
    const snapshots = Array.isArray(current?.snapshots) ? current.snapshots : [];
    const values = snapshots.map(s => parseMs(s.observedAt || s.exportedAt)).filter(Boolean);
    return values.length ? Math.max(...values) : Date.now();
  }

  function isNew24h(comment) {
    const first = parseMs(comment?.firstSeen);
    if (!first) return false;
    const anchor = latestObservationMs();
    return first >= anchor - 24 * 60 * 60 * 1000 && first <= anchor + 60000;
  }

  function commentEvents(comment) {
    return (current?.events || [])
      .filter(event => event.entityId === comment.id)
      .slice()
      .sort((a, b) => parseMs(a.observedAt) - parseMs(b.observedAt));
  }

  function stateFor(comment) {
    if (MISSING.has(comment.status)) return { key: 'missing', label: 'NO LONGER PRESENT' };
    if (comment.status === 'reappeared') return { key: 'reappeared', label: 'REAPPEARED' };
    if ((comment.versions || []).length > 1) return { key: 'edited', label: 'EDITED' };
    if (isNew24h(comment)) return { key: 'new', label: 'NEW' };
    return null;
  }

  function eventTime(value) {
    if (!value) return 'time unavailable';
    try { return time(value); } catch (_) { return String(value); }
  }

  function timelineRow(kind, when, label, note = '') {
    return `<li class="status-timeline-row ${esc(kind)}"><span class="timeline-dot" aria-hidden="true"></span><div><strong>${esc(label)}</strong><span>${esc(eventTime(when))}</span>${note ? `<small>${esc(note)}</small>` : ''}</div></li>`;
  }

  function absenceEvents(comment) {
    const events = commentEvents(comment);
    const explicit = events.filter(event => event.type === 'not_present_observation');
    if (explicit.length) return explicit;
    return events.filter(event => ['missing_once', 'missing_recheck', 'confirmed_unavailable'].includes(event.type));
  }

  function visibilityTimeline(comment) {
    const rows = [];
    rows.push(timelineRow('observed', comment.firstSeen, 'First observed'));
    absenceEvents(comment).forEach(event => {
      const note = event.coverageMode ? `Qualifying ${String(event.coverageMode).replaceAll('_', ' ')} crawl` : 'Qualifying comparable crawl';
      rows.push(timelineRow('missing', event.observedAt, 'No longer present in this check', note));
    });
    commentEvents(comment).filter(event => event.type === 'reappeared').forEach(event => {
      rows.push(timelineRow('reappeared', event.observedAt, 'Reappeared'));
    });
    return `<ol class="status-timeline">${rows.join('')}</ol>`;
  }

  function tokenize(text) {
    return String(text || '').trim().split(/\s+/).filter(Boolean);
  }

  function inlineDiff(before, after) {
    const a = tokenize(before), b = tokenize(after);
    if (!a.length && !b.length) return '<span class="diff-unchanged">No text retained for this version.</span>';
    if (a.length > 260 || b.length > 260) {
      return `<div class="diff-fallback"><div><span>Before</span>${esc(before || '—')}</div><div><span>After</span>${esc(after || '—')}</div></div>`;
    }
    const dp = Array.from({ length: a.length + 1 }, () => new Uint16Array(b.length + 1));
    for (let i = a.length - 1; i >= 0; i -= 1) {
      for (let j = b.length - 1; j >= 0; j -= 1) {
        dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
    const parts = [];
    let i = 0, j = 0;
    while (i < a.length || j < b.length) {
      if (i < a.length && j < b.length && a[i] === b[j]) {
        parts.push(esc(a[i])); i += 1; j += 1;
      } else if (j < b.length && (i >= a.length || dp[i][j + 1] >= dp[i + 1][j])) {
        parts.push(`<ins>${esc(b[j])}</ins>`); j += 1;
      } else {
        parts.push(`<del>${esc(a[i])}</del>`); i += 1;
      }
    }
    return parts.join(' ');
  }

  function editHistory(comment) {
    const versions = Array.isArray(comment.versions) ? comment.versions : [];
    if (versions.length < 2) return '<p class="status-detail-note">No separate substantive text version is retained.</p>';
    return `<div class="edit-history">${versions.slice(1).map((version, index) => {
      const previous = versions[index];
      const when = version.firstSeen || version.lastSeen || '';
      return `<section class="edit-change"><div class="edit-change-heading"><strong>Edit ${index + 1}</strong><span>${esc(eventTime(when))}</span></div><div class="inline-diff">${inlineDiff(previous?.text || '', version?.text || '')}</div></section>`;
    }).join('')}</div><div class="diff-legend"><span><del>removed</del></span><span><ins>added</ins></span></div>`;
  }

  function detailFor(comment, state) {
    if (state.key === 'new') {
      return `<div class="status-detail-copy"><strong>First observed ${esc(eventTime(comment.firstSeen))}</strong><span>This comment was first captured within the last 24 hours.</span></div>`;
    }
    if (state.key === 'edited') {
      return `<div class="status-detail-copy"><strong>Archived edit history</strong><span>Highlighted text shows substantive differences between captured versions.</span></div>${editHistory(comment)}`;
    }
    if (state.key === 'reappeared') {
      return `<div class="status-detail-copy"><strong>Visibility history</strong><span>The archive shows when this comment was first seen, each recorded qualifying check where it was no longer present, and when it reappeared.</span></div>${visibilityTimeline(comment)}`;
    }
    return `<div class="status-detail-copy"><strong>Visibility history</strong><span>This comment was previously captured but is no longer present in the latest qualifying crawl. The archive records visibility only and does not infer the cause.</span></div>${visibilityTimeline(comment)}`;
  }

  function removeOldStateStrip(html) {
    return html.replace(/<div class="comment-state-strip [^"]+">[\s\S]*?<\/div>/g, '');
  }

  commentCard = function (comment, options = {}) {
    let html = removeOldStateStrip(priorCommentCard(comment, options));
    const state = stateFor(comment);
    if (!state) return html;
    const id = `status-detail-${encodeURIComponent(String(comment.id || '')).replaceAll('%', '_')}`;
    const badge = `<button class="comment-status-badge status-${esc(state.key)}" type="button" data-action="toggle-comment-status" aria-expanded="false" aria-controls="${esc(id)}"><span class="status-badge-icon" aria-hidden="true"></span>${esc(state.label)}</button>`;
    const detail = `<div class="comment-status-details status-${esc(state.key)}" id="${esc(id)}" hidden>${detailFor(comment, state)}</div>`;
    html = html.replace('</article>', `${badge}${detail}</article>`);
    return html;
  };
  window.commentCard = commentCard;

  function relabel(root = document) {
    const replacements = [
      [/newly not observed/gi, match => match[0] === 'N' ? 'Newly no longer present' : 'newly no longer present'],
      [/currently not observed/gi, match => match[0] === 'C' ? 'Currently no longer present' : 'currently no longer present'],
      [/not observed/gi, match => match[0] === 'N' ? 'No longer present' : 'no longer present']
    ];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(node => {
      if (node.parentElement?.closest('script,style')) return;
      let value = node.nodeValue || '';
      replacements.forEach(([pattern, replacement]) => { value = value.replace(pattern, replacement); });
      if (value !== node.nodeValue) node.nodeValue = value;
    });
  }

  document.addEventListener('click', event => {
    const badge = event.target.closest('[data-action="toggle-comment-status"]');
    if (!badge) return;
    event.preventDefault();
    const detailId = badge.getAttribute('aria-controls');
    const detail = detailId ? document.getElementById(detailId) : null;
    if (!detail) return;
    const opening = detail.hidden;
    detail.hidden = !opening;
    badge.setAttribute('aria-expanded', opening ? 'true' : 'false');
  });

  let queued = false;
  const observer = new MutationObserver(() => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; relabel(document.body); });
  });
  observer.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  relabel(document.body);

  if (typeof current !== 'undefined' && current) render();
})();
