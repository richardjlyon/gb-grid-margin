// site/share.js — prefilled social share intents + button markup for the cards.
const SITE = 'https://gridmargin.co.uk';

export function intents(card) {
  const text = encodeURIComponent(`${card.figure} — ${card.label}`);
  // The content hash on the shared URL is the cache-bust: social platforms key their
  // unfurl cache off the posted URL, so a re-rendered card (new hash) forces a fresh card.
  const bust = card.version ? `?v=${card.version}` : '';
  const url = encodeURIComponent(`${SITE}/s/${card.slug}${bust}`);
  return [
    { name: 'X', href: `https://twitter.com/intent/tweet?text=${text}&url=${url}` },
    { name: 'LinkedIn', href: `https://www.linkedin.com/sharing/share-offsite/?url=${url}` },
    { name: 'Bluesky', href: `https://bsky.app/intent/compose?text=${text}%20${url}` },
    { name: 'Facebook', href: `https://www.facebook.com/sharer/sharer.php?u=${url}` },
  ];
}

export function shareButtons(card) {
  return `<div class="share-row">${intents(card)
    .map((i) => `<a class="share-btn" href="${i.href}" target="_blank" rel="noopener">${i.name}</a>`)
    .join('')}</div>`;
}

export function actionButtons(card) {
  return `<div class="action-row">
    <a class="action-btn" href="${card.png}" download="grid-margin-${card.slug}.png">Download</a>
    <button class="action-btn" type="button" data-copy="${card.png}">Copy image</button>
  </div>`;
}

export function wireCopyButtons(root) {
  root.querySelectorAll('button[data-copy]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      try {
        const blob = await (await fetch(btn.dataset.copy, { cache: 'no-store' })).blob();
        await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
        btn.textContent = 'Copied ✓';
        setTimeout(() => { btn.textContent = 'Copy image'; }, 2000);
      } catch { btn.textContent = 'Copy failed'; }
    });
  });
}
