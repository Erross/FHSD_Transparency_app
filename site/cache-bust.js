/* Prevent browsers from serving stale generated archive JSON after a Pages deploy.
   The token is intentionally per page load: static JS/CSS can still be cached normally,
   while generated data files are always requested from the current deployment. */
(function () {
  const nativeFetch = window.fetch.bind(window);
  const refreshToken = Date.now().toString(36);

  function isArchiveDataUrl(url) {
    return url.origin === window.location.origin
      && /\/data\/(?:catalog\.json|people\.json|targets\/[^/?#]+\.json)$/.test(url.pathname);
  }

  window.fetch = function (input, init) {
    try {
      const raw = input instanceof Request ? input.url : String(input);
      const url = new URL(raw, window.location.href);
      if (isArchiveDataUrl(url)) {
        url.searchParams.set('_archive', refreshToken);
        const options = { ...(init || {}), cache: 'no-store' };
        if (input instanceof Request) {
          return nativeFetch(new Request(url.toString(), input), options);
        }
        return nativeFetch(url.toString(), options);
      }
    } catch (error) {
      console.warn('Archive cache-bust fallback:', error);
    }
    return nativeFetch(input, init);
  };
})();
