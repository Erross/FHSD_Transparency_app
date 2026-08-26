/* Evidence-aware classification for first-observed entities.
   The core engine emits `new` when the archive first sees an entity. This layer
   separates that from publication-time evidence for the public dashboard. */
(function () {
  if (typeof classification !== 'function' || typeof viewChanges !== 'function') return;

  function calendarDate(value) {
    if (!value) return '';
    const parsed = dateValue(value);
    if (!parsed) return String(value).slice(0, 10);
    const year = parsed.getFullYear();
    const month = String(parsed.getMonth() + 1).padStart(2, '0');
    const day = String(parsed.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  classification = function (event) {
    if (event.type !== 'new') return event.type;
    const entity = eventEntity(event);
    const previousAt = dateValue(current.latestDelta?.previousObservedAt);
    const latestAt = dateValue(current.latestDelta?.observedAt);
    const publishedAt = dateValue(entity.publishedAt);

    // This is the strongest statement: an actual publication timestamp falls
    // after the previous snapshot and no later than the current observation.
    if (publishedAt && previousAt && (!latestAt || publishedAt <= latestAt) && publishedAt > previousAt) {
      return 'newly_published';
    }

    const publishedDate = String(entity.publishedDate || '').slice(0, 10);
    const previousDate = calendarDate(current.latestDelta?.previousObservedAt);
    const latestDate = calendarDate(current.latestDelta?.observedAt);
    if (publishedDate && previousDate) {
      if (publishedDate < previousDate) return 'historical_discovery';
      if (publishedDate === previousDate || (latestDate && publishedDate <= latestDate)) return 'publication_window_date_only';
    }
    return 'first_observed_undated';
  };

  eventName = function (type) {
    return ({
      newly_published: 'newly published',
      publication_window_date_only: 'publication date in comparison window',
      historical_discovery: 'historical item newly recovered',
      first_observed_undated: 'first observed · publication date unknown',
      edited: 'edited',
      missing_once: 'not observed',
      missing_recheck: 'missing on recheck',
      reappeared: 'reappeared',
      confirmed_unavailable: 'confirmed unavailable',
      directly_confirmed_visible: 'confirmed visible',
      bulk_missing: 'bulk missing signal',
      bulk_missing_thread: 'thread missing signal'
    })[type] || String(type || '').replaceAll('_', ' ');
  };

  viewChanges = function () {
    const delta = current.latestDelta || {};
    const events = latestEvents();
    const meaningful = events.filter(event => !['bulk_missing', 'bulk_missing_thread'].includes(event.type));
    const firstObserved = meaningful.filter(event => event.type === 'new');
    const classified = firstObserved.map(event => classification(event));
    const confirmedPublished = classified.filter(value => value === 'newly_published').length;
    const dateOnly = classified.filter(value => value === 'publication_window_date_only').length;
    const historical = classified.filter(value => value === 'historical_discovery').length;
    const undated = classified.filter(value => value === 'first_observed_undated').length;
    const edited = meaningful.filter(event => event.type === 'edited').length;
    const missing = meaningful.filter(event => ['missing_once', 'missing_recheck'].includes(event.type)).length;
    const unavailable = meaningful.filter(event => event.type === 'confirmed_unavailable').length;
    const reappeared = meaningful.filter(event => event.type === 'reappeared').length;
    const completeness = delta.complete ? 'complete comparison snapshot' : 'partial observation — negative inference disabled';

    return `<section class="view-section">
      <div class="view-heading"><div><p class="eyebrow">LATEST DELTA</p><h2>What changed?</h2>
      <p>Observed ${esc(time(delta.observedAt))}${delta.previousObservedAt ? ` compared with ${esc(time(delta.previousObservedAt))}` : ''}. ${esc(completeness)}.</p></div></div>

      <div class="delta-grid delta-grid-primary">
        <div class="delta-stat positive"><strong>${confirmedPublished}</strong><span>confirmed newly published</span></div>
        <div class="delta-stat date-only"><strong>${dateOnly}</strong><span>publication date in window · exact time unavailable</span></div>
        <div class="delta-stat historical"><strong>${historical}</strong><span>older items newly recovered</span></div>
        <div class="delta-stat neutral"><strong>${undated}</strong><span>undated first observations</span></div>
        <div class="delta-stat edited"><strong>${edited}</strong><span>observed text edits</span></div>
      </div>
      <div class="delta-grid delta-grid-secondary">
        <div class="delta-stat warning"><strong>${missing}</strong><span>missing / recheck candidates</span></div>
        <div class="delta-stat danger"><strong>${unavailable}</strong><span>confirmed unavailable</span></div>
        <div class="delta-stat positive"><strong>${reappeared}</strong><span>reappeared</span></div>
      </div>

      <div class="explanation panel"><strong>Publication confidence matters.</strong> “Confirmed newly published” requires a usable Facebook publication timestamp after the previous snapshot. A day-only date is shown separately. Material with an older date is explicitly classified as historical discovery, so a better crawler cannot inflate the daily-news count.</div>

      <div class="section-heading"><div><p class="eyebrow">OBSERVED EVENTS</p><h2>Latest comparison</h2></div><p>${meaningful.length} record-level event${meaningful.length === 1 ? '' : 's'}</p></div>
      <div>${meaningful.length ? meaningful.map(eventCard).join('') : '<div class="empty">No record-level changes were detected in the latest comparison.</div>'}</div>
    </section>`;
  };
})();
