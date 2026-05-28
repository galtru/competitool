/**
 * Probe script injected at document_start.
 * Captures Prebid events, IMA state, identity globals, and video events.
 * All observations accumulate in window.__probe_log.
 */
(function () {
  if (window.__probe_installed) return;
  window.__probe_installed = true;
  window.__probe_log = [];

  function log(type, data) {
    window.__probe_log.push({ type: type, ts: Date.now(), data: data });
  }

  // --- Prebid hooks ---
  var _pbjsQueue = [];
  Object.defineProperty(window, 'pbjs', {
    configurable: true,
    get: function () { return window._pbjs_real; },
    set: function (instance) {
      window._pbjs_real = instance;
      log('pbjs_loaded', { version: instance.version });

      // Drain queued calls
      _pbjsQueue.forEach(function (fn) { try { fn(); } catch (e) {} });
      _pbjsQueue = [];

      // Hook events
      var EVENTS = [
        'auctionInit', 'auctionEnd', 'bidRequested', 'bidResponse',
        'bidWon', 'bidTimeout', 'noBid', 'setTargeting'
      ];
      EVENTS.forEach(function (evt) {
        instance.onEvent(evt, function (data) {
          log('pbjs_event_' + evt, data);
        });
      });

      // Snapshot config after a short delay (config is set async)
      setTimeout(function () {
        try { log('pbjs_config', instance.getConfig()); } catch (e) {}
        try { log('pbjs_bid_responses', instance.getBidResponses()); } catch (e) {}
      }, 3000);
    }
  });

  // Intercept que.push before pbjs loads
  window.pbjs = window.pbjs || {};
  window.pbjs.que = window.pbjs.que || [];
  var _origPush = window.pbjs.que.push.bind(window.pbjs.que);
  window.pbjs.que.push = function (fn) {
    log('pbjs_que_push', { fn: fn.toString().slice(0, 200) });
    _pbjsQueue.push(fn);
    return _origPush(fn);
  };

  // --- IMA hooks ---
  function hookIMA() {
    if (!window.google || !window.google.ima) return false;
    log('ima_loaded', {});
    var _origAdsRequest = window.google.ima.AdsRequest;
    if (_origAdsRequest) {
      window.google.ima.AdsRequest = function () {
        var req = new _origAdsRequest();
        log('ima_ads_request_created', {});
        return req;
      };
    }
    return true;
  }

  // --- Identity globals polling ---
  var IDENTITY_GLOBALS = [
    '__uid2', 'ID5', '__id5_consent', 'LiveRampATSEmail',
    'idl_env', 'pubcid', '__tcfapi', '__gpp'
  ];
  var _identityPolls = 0;
  var _identityTimer = setInterval(function () {
    _identityPolls++;
    var found = {};
    IDENTITY_GLOBALS.forEach(function (key) {
      if (window[key] !== undefined) {
        try {
          var val = window[key];
          if (typeof val === 'object' && val !== null) {
            found[key] = JSON.stringify(val).slice(0, 500);
          } else {
            found[key] = String(val).slice(0, 200);
          }
        } catch (e) {
          found[key] = '[unserializable]';
        }
      }
    });
    if (Object.keys(found).length > 0) {
      log('identity_globals', found);
    }
    if (!hookIMA()) {
      // keep trying
    }
    if (_identityPolls >= 60) { // 30 seconds at 500ms
      clearInterval(_identityTimer);
    }
  }, 500);

  // --- Video element events ---
  function attachVideoListeners(video) {
    var id = video.__probe_id || (video.__probe_id = 'v' + Math.random().toString(36).slice(2));
    ['play', 'pause', 'ended', 'error', 'waiting', 'playing', 'timeupdate'].forEach(function (evt) {
      video.addEventListener(evt, function () {
        if (evt === 'timeupdate' && video.currentTime % 5 > 0.5) return; // throttle
        log('video_event_' + evt, {
          id: id,
          currentTime: video.currentTime,
          duration: video.duration,
          readyState: video.readyState
        });
      });
    });
    log('video_detected', { id: id, src: video.src || video.currentSrc });
  }

  // Observe DOM for video elements
  var _seenVideos = new WeakSet();
  var _videoObserver = new MutationObserver(function (mutations) {
    mutations.forEach(function (m) {
      m.addedNodes.forEach(function (node) {
        if (node.tagName === 'VIDEO' && !_seenVideos.has(node)) {
          _seenVideos.add(node);
          attachVideoListeners(node);
        }
        if (node.querySelectorAll) {
          node.querySelectorAll('video').forEach(function (v) {
            if (!_seenVideos.has(v)) {
              _seenVideos.add(v);
              attachVideoListeners(v);
            }
          });
        }
      });
    });
  });
  _videoObserver.observe(document.documentElement, { childList: true, subtree: true });

  // Catch existing videos
  document.querySelectorAll('video').forEach(function (v) {
    if (!_seenVideos.has(v)) {
      _seenVideos.add(v);
      attachVideoListeners(v);
    }
  });

  log('probe_installed', { url: location.href });
})();
