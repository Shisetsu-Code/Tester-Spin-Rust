// Observe only the official client's demo lifecycle. No UI traversal or wagers.
(() => {
  if (window.__testerNgmInstalled) return;
  window.__testerNgmInstalled = true;
  const seen = new WeakSet();
  let budget;
  function snapshot(value, depth = 0) {
    if (!depth) budget = 10000;
    if (--budget < 0 || depth > 40) return '[CAPTURE_LIMIT]';
    if (value == null || ['number', 'boolean'].includes(typeof value)) return value;
    if (typeof value === 'string') return value.length <= 30000 ? value : '[CAPTURE_LIMIT]';
    if (typeof value !== 'object') return undefined;
    if (seen.has(value)) return '[CYCLE]';
    seen.add(value);
    try {
      if (Array.isArray(value)) return value.length <= 1000 ? value.map(x => snapshot(x, depth + 1)) : '[CAPTURE_LIMIT]';
      const keys = Object.keys(value);
      if (keys.length > 128) return '[CAPTURE_LIMIT]';
      const result = {};
      for (const key of keys) {
        const descriptor = Object.getOwnPropertyDescriptor(value, key);
        if (descriptor && 'value' in descriptor && typeof descriptor.value !== 'function')
          result[key] = snapshot(descriptor.value, depth + 1);
      }
      return result;
    } finally { seen.delete(value); }
  }
  window.__testerNgmEmit = (type, data) => {
    try { console.debug('__TESTER_NGM__' + JSON.stringify({type, data: snapshot(data), frame: location.origin + location.pathname})); }
    catch (_) { /* Missing evidence is rejected by the Python ledger. */ }
  };
  const parse = value => { try { return typeof value === 'string' ? JSON.parse(value) : value; } catch (_) { return null; } };
  const permitted = new Set(['GameRoundStartNotification', 'GameRoundEndNotification', 'NextGameRoundAllowed',
    'IGameBusyRequest', 'ISetGameBalanceRequest', 'GameBetUpdateNotification',
    'GameLoadingEndNotification', 'GamePopupNotification', 'ISetActiveSceneRequest']);
  function observe(messenger) {
    if (!messenger || typeof messenger !== 'object') return messenger;
    const functions = new WeakMap();
    return new Proxy(messenger, {get(target, key, receiver) {
      const original = Reflect.get(target, key, receiver);
      if (key !== 'request' || typeof original !== 'function') return original;
      if (functions.has(original)) return functions.get(original);
      const wrapped = function(message, callback, ...rest) {
        const parsed = parse(message);
        if (parsed && permitted.has(parsed.classifier)) window.__testerNgmEmit('message', parsed);
        let replacement = callback;
        if (callback && typeof callback.done === 'function' && parsed &&
            ['IUserDataRequest', 'IGetRegulationsRequest'].includes(parsed.classifier)) {
          replacement = Object.create(callback);
          replacement.done = function(...args) {
            const response = parse(args[0]);
            if (response) window.__testerNgmEmit('configuration', {
              classifier: response.classifier, mode: response.mode,
              keyboardFilter: response.keyboardFilter
            });
            return Reflect.apply(callback.done, callback, args);
          };
        }
        return Reflect.apply(original, target, [message, replacement, ...rest]);
      };
      functions.set(original, wrapped);
      return wrapped;
    }});
  }
  try {
    let messenger = observe(window.MESSENGER);
    Object.defineProperty(window, 'MESSENGER', {configurable: true, enumerable: true,
      get() { return messenger; }, set(value) { messenger = observe(value); }});
  } catch (_) { window.__testerNgmEmit('hook.error', {}); }
})();
