// Serialize every read-modify-save operation, including network acknowledgements.
export function stateQueue(read, save, publish) {
  let chain = Promise.resolve();
  return (change, metadata) => {
    const result = chain.then(async () => {
      const next = change(read());
      await save(next, metadata);
      publish(next);
      return next;
    });
    chain = result.catch(() => {});
    return result;
  };
}
export function makeId() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
}

export function refreshedState(current, patch, refresh, viewed) {
  if (refresh && current.cards[current.index]?.id !== viewed) return current;
  const sameCard = patch.cards[0]?.id === viewed;
  return { ...current, ...patch, index: 0, side: refresh && sameCard ? current.side : 'front' };
}
export async function maintainStudy(getState, sync, refresh, status, now = Date.now) {
  await sync();
  const state = getState();
  if (!state.cards[state.index]) await refresh(false);
  else if (state.side === 'front' && (now() - state.saved_at >= 600000 || now()/1000 >= state.valid_until)) await refresh(true);
  await status();
}
