import { stateQueue, makeId, refreshedState, maintainStudy } from './state.js';
import { openStorage, loadState, pendingReviews, saveState } from './storage.js';
const $ = id => document.getElementById(id);
let state = { cards: [], index: 0, side: 'front', pending: [], device_id: 'browser-' + makeId() };
let busy = false, db, imageURL, fetching;
const opened = openStorage('enki-v1', () => { $('notice').textContent = 'Reload or close older Enki tabs to finish the update.'; }).then(value => { db = value; });
const commit = stateQueue(() => state, async (next, metadata) => { await opened; await saveState(db, next, metadata); }, next => { state = next; });
const tell = message => { $('notice').textContent = message; };
async function api(path, options = {}) {
  let response;
  try { response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers } }); }
  catch { throw Error('Offline. Your answers are saved here.'); }
  if (response.status === 401) { $('login').hidden = false; throw Error('Enter the device key to connect.'); }
  if (!response.ok) {
    let body = {};
    try { body = await response.json(); } catch {}
    const error = Error(typeof body.detail === 'string' ? body.detail : 'Could not connect. Your answers are saved here.');
    throw error;
  }
  return response.status === 204 ? null : response.json();
}
async function acknowledge(accepted) {
  const ids = new Set(accepted.map(event => event.id));
  await commit(current => ({ ...current, pending: current.pending.filter(event => !ids.has(event.id)) }), { ack: [...ids] });
}
async function sync() {
  await opened;
  const sent = (await pendingReviews(db)).slice(0, 200);
  if (!sent.length) return;
  const result = await api('/api/reviews', { method: 'POST', body: JSON.stringify({ events: sent }) });
  await acknowledge([...result.accepted, ...(result.rejected || [])]);
}
async function imageBlob(path) {
  let response;
  try { response = await fetch(path); } catch { throw Error('Could not download the next card. Try again when connected.'); }
  if (!response.ok) throw Error('Could not download the next card. Try again when connected.');
  return response.blob();
}
function batch(refresh = false) {
  if (fetching) return fetching;
  fetching = (async () => {
    const viewed = state.cards[state.index]?.id;
    const query = new URLSearchParams({ count: '4' });
    if (refresh) for (const card of state.cards.slice(state.index)) query.append('keep', card.id);
    await sync();
    const bundle = await api('/api/study?' + query);
    const cards = await Promise.all(bundle.cards.map(async card => ({ ...card, images: {
      front: await imageBlob(card.front.png), back: await imageBlob(card.back.png)
    } })));
    const idle = bundle.idle ? await imageBlob(bundle.idle.png) : null;
    await commit(current => refreshedState(current, { cards, idle, saved_at: Date.now(), valid_until: bundle.context.valid_until_epoch }, refresh, viewed));
    draw();
    await status(false);
  })().finally(() => { fetching = null; });
  return fetching;
}
function draw() {
  const card = state.cards[state.index], frame = card?.[state.side], blob = card?.images[state.side] || state.idle;
  if (imageURL) URL.revokeObjectURL(imageURL);
  if (blob) {
    imageURL = URL.createObjectURL(blob);
    $('screen').src = imageURL;
    $('screen').alt = card ? (state.side === 'front' ? 'Japanese card. Reveal to check your reading.' : 'Reading and meaning. Grade what you remembered.') : 'Nothing due right now.';
  }
  $('targets').replaceChildren();
  for (const hit of frame?.hits || []) {
    const button = document.createElement('button');
    button.textContent = hit.action === 'little' ? 'knew a little' : hit.action;
    button.setAttribute('aria-label', hit.action === 'reveal' ? 'Reveal card' : button.textContent);
    Object.assign(button.style, { left: hit.x / 6 + '%', top: hit.y / 6 + '%', width: hit.w / 6 + '%', height: hit.h / 6 + '%' });
    button.onclick = () => act(hit);
    $('targets').append(button);
  }
  $('queue').textContent = state.pending.length ? `${state.pending.length} answer(s) saved here, waiting to sync.` : 'All answers synced.';
  tell(card ? '' : 'Nothing due. New cards will arrive when they are ready.');
  if (state.saved_at && (Date.now() - state.saved_at > 7200000 || Date.now() / 1000 >= state.valid_until)) tell('Cached cards. Weather and calendar may be out of date.');
  $('retry').hidden = !!card;
}
async function act(hit) {
  if (busy) return;
  busy = true;
  try {
    if (hit.action === 'reveal') {
      await commit(current => ({ ...current, side: 'back' }));
      draw();
    } else {
      const event = { id: makeId(), card_id: state.cards[state.index].id, rating: hit.rating, device_id: state.device_id, reviewed_at: new Date().toISOString() };
      await commit(current => ({ ...current, pending: [...current.pending, event], index: current.index + 1, side: 'front' }), { event });
      if (state.index >= state.cards.length) {
        tell('Getting your next card…');
        try { await batch(); } catch (error) { draw(); tell(error.message); $('retry').hidden = false; }
      } else {
        draw();
        sync().then(() => status(false)).catch(error => tell(error.message));
      }
    }
  } catch { tell('Could not save your answer. Please try again.'); }
  finally { busy = false; }
}
async function status(hydrate = true) {
  const result = await api('/api/status');
  $('stats').textContent = `${result.stats.cards.toLocaleString()} cards · ${result.stats.reviews} reviews`;
  if (hydrate) {
    $('stage').value = result.settings.start_stage;
    $('daily').value = result.settings.new_per_day;
    $('advance').checked = result.settings.auto_advance;
    $('exclude').value = result.settings.calendar_exclude.join('\n');
  }
  $('calendar-state').textContent = result.context.errors?.calendar ? 'Calendar could not refresh. Check the feed address.' : result.settings.calendar_configured ? 'Calendar connected.' : 'No calendar connected.';
  $('recovery').textContent = result.stats.recovery ? `${result.stats.recovery} answer(s) preserved for recovery.` : '';
  $('recovery-download').hidden = !result.stats.recovery;
  if (result.device) {
    const d=result.device, live=d.wifi_seen_at && Date.now()/1000-d.wifi_seen_at<50;
    const ready=Number.isInteger(d.wifi_remaining)?` ${d.wifi_remaining} cards ready on the Inkplate.`:'';
    const downloading=d.wifi_fetching?' Downloading more.':d.wifi_error?' Retrying download.':'';
    const pending=d.wifi_pending>0?` ${d.wifi_pending} answers waiting to sync.`:'';
    $('device-state').textContent=live?'Wi-Fi connected.'+ready+downloading+pending:d.message+(d.connected&&d.wifi?` Wi-Fi connected (${d.ip}).`:'');
  }
  $('queue').textContent = state.pending.length ? `${state.pending.length} answer(s) waiting to sync.` : 'All answers synced.';
}
async function task(fn) { try { await fn(); } catch (error) { tell(error.message); } }
$('retry').onclick = () => task(() => batch());
$('unlock').onclick = () => task(async () => {
  await api('/api/login', { method: 'POST', body: JSON.stringify({ token: $('key').value }) });
  $('key').value = ''; $('login').hidden = true;
  await batch(); await status();
});
$('save-learning').onclick = () => task(async () => {
  await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ start_stage: Number($('stage').value), new_per_day: Number($('daily').value), auto_advance: $('advance').checked }) });
  await batch(true); await status(); tell('Learning settings saved.');
});
$('save-calendar').onclick = () => task(async () => {
  const settings = { calendar_exclude: $('exclude').value.split('\n').map(value => value.trim()).filter(Boolean) };
  if ($('calendar').value) settings.calendar_url = $('calendar').value;
  await api('/api/settings', { method: 'PATCH', body: JSON.stringify(settings) });
  $('calendar').value = '';
  await api('/api/context/refresh', { method: 'POST' }); await status();
  if (state.cards[state.index]) await batch(true);
  tell('Calendar saved.');
});
$('clear-calendar').onclick = () => task(async () => {
  await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ calendar_url: '' }) });
  await status(); tell('Calendar disconnected.');
});
$('connect-usb').onclick = () => task(async () => { const result = await api('/api/device/connect', { method: 'POST' }); $('device-state').textContent = result.message; });
$('disconnect-usb').onclick = () => task(async () => { await api('/api/device/disconnect', { method: 'POST' }); $('device-state').textContent = 'USB disconnected. The port is free for flashing.'; });
$('wifi-form').onsubmit = event => {
  event.preventDefault(); task(async () => {
    await api('/api/device/configure', { method: 'POST', body: JSON.stringify({ ssid: $('ssid').value, password: $('wifi-password').value }) });
    $('wifi-password').value = ''; $('device-state').textContent = 'Wi-Fi settings sent over USB. Waiting for the Inkplate to connect.';
  });
};
window.addEventListener('online', () => task(async () => { await sync(); await status(false); }));
if ('serviceWorker' in navigator && isSecureContext) navigator.serviceWorker.register('/sw.js').catch(() => {});
try {
  await opened;
  const saved = await loadState(db);
  if (saved) state = saved;
  if (state.cards[state.index]) { draw(); await sync(); if (state.side === 'front') await batch(true); await status(); }
  else { await batch(); await status(); }
} catch (error) { draw(); tell(error.message); $('retry').hidden = false; }
setInterval(() => { if (!busy && !fetching) task(() => maintainStudy(() => state, sync, batch, () => status(false))); }, 60000);
setInterval(() => { if ([...document.querySelectorAll('details')].some(element => element.open && element.contains($('device-state')))) task(() => status(false)); }, 5000);
