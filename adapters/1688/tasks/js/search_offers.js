/** 1688 搜索页商品链接提取（CommonJS，供引擎 evaluate 模块包装调用）。 */
function collectOfferLinks() {
  const seen = new Set();
  const out = [];
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.href || '';
    let match = href.match(/offer\/(\d+)\.html/);
    if (!match) match = href.match(/offerId=(\d+)/);
    if (!match || seen.has(match[1])) continue;
    if (!/detail\.(m\.)?1688\.com/.test(href)) continue;
    const img = a.querySelector('img');
    const text = (
      a.innerText || a.textContent || a.getAttribute('title') ||
      (img && (img.alt || img.title)) || ''
    ).replace(/\s+/g, ' ').trim();
    seen.add(match[1]);
    out.push({
      offer_id: match[1],
      url: 'https://detail.1688.com/offer/' + match[1] + '.html',
      title: text.slice(0, 120),
    });
  }
  return out;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { collectOfferLinks };
}
