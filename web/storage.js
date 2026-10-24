// The outbox has one record per review, separate from each tab's study snapshot.
// A stale tab can change its card position without erasing another tab's answer.
export function openStorage(name = 'enki-v1', blocked = () => {}) {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(name, 2);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains('kv')) db.createObjectStore('kv');
      if (!db.objectStoreNames.contains('outbox')) {
        const outbox = db.createObjectStore('outbox', { keyPath: 'id' });
        const old = request.transaction.objectStore('kv').get('state');
        old.onsuccess = () => { for (const event of old.result?.pending || []) outbox.put(event); };
      }
    };
    request.onblocked = blocked;
    request.onerror = () => reject(request.error);
    request.onsuccess = () => { const db = request.result; db.onversionchange = () => db.close(); resolve(db); };
  });
}
export function loadState(db) {
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(['kv', 'outbox']);
    const state = transaction.objectStore('kv').get('state');
    const outbox = transaction.objectStore('outbox').getAll();
    transaction.oncomplete = () => resolve(state.result ? { ...state.result, pending: outbox.result } : null);
    transaction.onerror = () => reject(transaction.error);
  });
}
export function pendingReviews(db) {
  return new Promise((resolve, reject) => {
    const request = db.transaction('outbox').objectStore('outbox').getAll();
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
export function saveState(db, next, changes = {}) {
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(['kv', 'outbox'], 'readwrite');
    const outbox = transaction.objectStore('outbox');
    if (changes.event) outbox.put(changes.event);
    for (const id of changes.ack || []) outbox.delete(id);
    transaction.objectStore('kv').put({ ...next, pending: [] }, 'state');
    const queue = outbox.getAll();
    queue.onsuccess = () => { next.pending = queue.result; };
    transaction.oncomplete = resolve;
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error);
  });
}
