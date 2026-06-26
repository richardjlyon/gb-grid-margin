// site/share.js — prefilled social share intents + button markup for the cards.
const SITE = 'https://gridgauge.co.uk';

export function intents(card) {
  const text = encodeURIComponent(`${card.figure} — ${card.label}`);
  const url = encodeURIComponent(`${SITE}/s/${card.slug}`);
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
