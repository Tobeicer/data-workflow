/**
 * detail_extract.js — 1688 商品详情页提取脚本（单一事实源）
 *
 * 用法：
 *   1. Playwright: 将本文件内容作为 page.evaluate 的函数体执行；
 *   2. Codex 控制真实 Chrome: 将本文件内容作为 tab.evaluate 的函数体执行。
 *
 * 设计原则（对应 2026-08-12 数据链路精准确认结论）：
 *   - 只提取页面真实文本，不做 AI 推断、不补值、不计算（价格区间由 SKU 明细聚合，
 *     页面区间原文只作证据保留在 priceRangeText）；
 *   - 多选择器容错：主路径抓不到时走备选选择器，并记录实际使用的路径（layoutKey）；
 *   - 活动文案（"【平台活动下价格】活动前价格…"）视为非价格内容，标记 tooltip 并排除；
 *   - 价格与库存合并在同一节点时原样保留并标记 stock_merged，由 Python 侧拆分；
 *   - 每个模块记录 found/missing/fallback，供布局差异（排版变体）统计与链路适配。
 */
function extractDetailPage() {
  const clean = (s) =>
    s == null ? '' : String(s).replace(/\s+/g, ' ').trim();
  const pickText = (selectors) => {
    for (const selector of selectors) {
      const node = document.querySelector(selector);
      const text = clean(node && (node.innerText || node.textContent));
      if (text) return text;
    }
    return '';
  };
  const imgSrc = (img) =>
    img
      ? (img.currentSrc ||
          img.getAttribute('data-src') ||
          img.getAttribute('data-lazyload') ||
          img.src ||
          img.getAttribute('src') ||
          '')
      : '';
  const isRealImage = (url) =>
    /^https?:\/\//i.test(url) &&
    /(cbu\d*\.alicdn\.com|img\.alicdn\.com\/imgextra\/)/i.test(url) &&
    !/tps-|\.svg(\?|$)|gg_dtc|_sum\.(jpg|png|webp)(\?|$)|amos\.alicdn\.com|img\.taobao\.com|NewGualianyingxiao|online\.aw/i.test(url);
  const uniqueUrls = (list) => Array.from(new Set(list.filter(Boolean)));
  const notes = [];

  // ---------- 标题 ----------
  const title =
    pickText([
      '[data-module="od_title"] h1',
      '[data-module="title"] h1',
      '.module-od-title h1',
      '#mod-detail-title h1',
      'h1',
    ]) ||
    clean((document.title || '').replace(/[-_]\s*阿里巴巴.*$/, ''));

  // ---------- 供应商/店铺名 ----------
  const supplierName = pickText([
    '[data-module="od_shop"] [class*="name"]',
    '[class*="company"] [class*="name"]',
    '[class*="supplier"] [class*="name"]',
    '[class*="shop"] [class*="name"]',
  ]);

  // ---------- 价格（排除活动文案） ----------
  const TOOLTIP_MARKERS = ['活动前价格', '平台活动', '前述价格未计算'];
  const isTooltip = (t) => TOOLTIP_MARKERS.some((m) => t.includes(m));
  const PRICE_SELECTORS = [
    '[data-module="od_main_price"] .price-text',
    '.module-od-main-price .price-text',
    '[data-module="od_price"] .price-text',
    '[data-module="od_consign"] .price-text',
    '.module-od-price .price-text',
    '.module-od-consign .item-price',
    '.price-text',
  ];
  let priceText = '';
  let priceNode = '';
  for (const selector of PRICE_SELECTORS) {
    const node = document.querySelector(selector);
    if (!node) continue;
    const text = clean(node.innerText || node.textContent);
    if (!text) continue;
    if (isTooltip(text) || text.length > 60) {
      notes.push('price:' + selector + ':tooltip_or_long');
      continue;
    }
    priceText = text;
    priceNode = selector;
    break;
  }
  // 兜底：主路径只剩 tooltip 时，在价格模块内找第一个含数字的短文本节点
  if (!priceText) {
    const candidates = Array.from(
      document.querySelectorAll(
        '[data-module="od_main_price"] span, [data-module="od_price"] span, [data-module="od_consign"] span, .module-od-main-price span, .module-od-price span, .module-od-consign span'
      )
    )
      .map((n) => clean(n.innerText || n.textContent))
      .filter((t) => t && /[0-9]/.test(t) && !isTooltip(t) && t.length <= 40);
    if (candidates.length) {
      priceText = candidates[0];
      priceNode = 'fallback:price_spans';
      notes.push('price:fallback_spans');
    }
  }
  if (priceText && /库存/.test(priceText)) notes.push('price:stock_merged');
  if (priceText && /活动前价格/.test(priceText)) notes.push('price:activity_tooltip');

  // 价格区间原文（页面若有 "¥2.04-2.20" 形式节点则保留作证据，不直接作为交付值）
  const priceRangeText = pickText([
    '[data-module="od_main_price"] [class*="range"]',
    '[data-module="od_price"] [class*="range"]',
    '.module-od-price [class*="range"]',
    '[data-module="od_consign"] [class*="range"]',
  ]);

  // ---------- 文本扫描兜底（布局无关：起订量/单位/库存/发货承诺） ----------
  const RE_MOQ = /(起订|最少起订|MOQ|订购量|起批)/i;
  const RE_UNIT = /^(个|台|件|套|条|只|米|平方米|㎡|pcs|PCS|包|箱|张|对|双)$/;
  const RE_STOCK = /库存\s*\d+/;
  const RE_DELIVERY = /\d+\s*小时发货|次日发货|48小时/;
  let moqText = pickText([
    '[data-module="od_main_price"] [class*="moq"]',
    '[data-module="od_consign"] [class*="moq"]',
    '[data-module="od_price"] [class*="moq"]',
    '[data-module="od_consign"] [class*="moq"]',
    '[class*="moq"]',
    '[class*="MOQ"]',
  ]);
  let unitText = pickText([
    '[data-module="od_main_price"] [class*="unit"]',
    '[data-module="od_consign"] [class*="unit"]',
    '[data-module="od_price"] [class*="unit"]',
  ]);
  let stockText = pickText([
    '[data-module="od_main_price"] [class*="stock"]',
    '[data-module="od_price"] [class*="stock"]',
    '[data-module="od_consign"] [class*="stock"]',
    '[class*="stock"]',
  ]);
  // 校验：库存文本必须含“库存”或为纯数字，否则视为误抓（如价格节点）
  if (stockText && !/库存/.test(stockText) && !/^[0-9]+$/.test(stockText)) {
    stockText = '';
    notes.push('stock:invalid_text_discarded');
  }
  let deliveryText = pickText([
    '[data-module="od_shipping_services"]',
    '[class*="delivery"] [class*="text"]',
    '[class*="delivery"]',
  ]);
  // 发货承诺只取承诺句式（去掉地址/运费噪音）
  const dlMatch = String(deliveryText).match(/承诺?\s*(\d+小时发货|次日发货|当天发货|48小时内发货)/);
  if (dlMatch) {
    deliveryText = dlMatch[0].replace(/^承诺/, '');
  } else {
    deliveryText = '';
  }
  const scanFallbacks = () => {
    const all = Array.from(document.querySelectorAll('span, div, li, dd, td, p'));
    const priceModule = document.querySelector('[data-module="od_main_price"], [data-module="od_price"], [data-module="od_consign"], .module-od-price, .module-od-main-price');
    const inPriceModule = (node) =>
      priceModule ? priceModule.contains(node) : true;
    const moqCand = [];
    const unitCand = [];
    const stockCand = [];
    const deliveryCand = [];
    for (const node of all) {
      const text = clean(node.innerText || node.textContent);
      if (!text || text.length > 60) continue;
      if (RE_MOQ.test(text) && text.length <= 20) moqCand.push({ text, in: inPriceModule(node) });
      else if (RE_UNIT.test(text)) unitCand.push({ text, in: inPriceModule(node) });
      if (RE_STOCK.test(text) && text.length <= 20) stockCand.push({ text, in: inPriceModule(node) });
      if (RE_DELIVERY.test(text) && text.length <= 20) deliveryCand.push({ text, in: inPriceModule(node) });
    }
    const pick = (list) => {
      const inside = list.find((x) => x.in);
      return (inside || list[0] || {}).text || '';
    };
    if (!moqText) moqText = pick(moqCand);
    if (!unitText) unitText = pick(unitCand);
    if (!stockText) stockText = pick(stockCand);
    if (!deliveryText) deliveryText = pick(deliveryCand);
    if (moqCand.length && !moqText) notes.push('moq:ambiguous');
  };
  if (!moqText || !unitText || !stockText || !deliveryText) {
    scanFallbacks();
    notes.push('textscan:used');
  }

  // ---------- 商品属性（多路径：表格行 / 商品属性区块 / dt-dd） ----------
  const attrs = {};
  let attrPath = 'none';
  const setAttrs = (rows) => {
    for (const row of rows) {
      if (!Array.isArray(row) || row.length < 2) continue;
      for (let i = 0; i + 1 < row.length; i += 2) {
        const key = clean(row[i]).replace(/[:：]$/, '');
        const val = clean(row[i + 1]);
        if (key && val && key.length <= 20 && key !== '商品属性' && !(key in attrs)) {
          attrs[key] = val;
        }
      }
    }
  };
  const tableRows = Array.from(
    document.querySelectorAll(
      '[data-module="od_product_attributes"] tr, #productAttributes tr, .module-od-product-attributes tr'
    )
  ).map((tr) =>
    Array.from(tr.querySelectorAll('th, td')).map((c) => clean(c.innerText || c.textContent))
  );
  if (tableRows.length) {
    setAttrs(tableRows);
    attrPath = 'rows';
  }
  if (Object.keys(attrs).length < 3) {
    const attrSection = Array.from(document.querySelectorAll('*')).find(
      (node) => clean(node.innerText) === '商品属性'
    );
    if (attrSection) {
      let parent = attrSection.parentElement;
      for (let depth = 0; depth < 6 && parent; depth++, parent = parent.parentElement) {
        const text = clean(parent.innerText);
        if (text.includes('商品属性') && text.length > 20) {
          const lines = text.split(/[\n\r]/).map(clean).filter(Boolean);
          const rows = [];
          for (let i = 0; i + 1 < lines.length; i += 2) rows.push([lines[i], lines[i + 1]]);
          setAttrs(rows);
          if (Object.keys(attrs).length >= 3) {
            attrPath = 'section';
            break;
          }
        }
      }
    }
  }
  if (Object.keys(attrs).length < 3) {
    const dtRows = Array.from(document.querySelectorAll('dl, [class*="attribute"] dl, [class*="param"] dl')).map(
      (dl) =>
        Array.from(dl.querySelectorAll('dt, dd')).map((c) =>
          clean(c.innerText || c.textContent)
        )
    );
    setAttrs(dtRows);
    if (Object.keys(attrs).length >= 3) attrPath = 'dl';
  }
  const attrCount = Object.keys(attrs).length;
  if (attrCount === 0) notes.push('attrs:missing');

  // ---------- SKU 明细（多路径） ----------
  const skuRows = [];
  let skuPath = 'none';
  // 拆分“价格+库存”span 拼接单元格（2026 gyp-pro-table 变体）：
  // <div class="gyp-pro-table-price"><span>¥2300</span><span>9983</span></div> -> price=¥2300, stock=9983
  // <span>¥12</span><span>.677675</span> -> price=¥12.677675
  const splitPriceStock = (text, node) => {
    const spans = node
      ? Array.from(node.querySelectorAll('span')).map((s) => clean(s.innerText || s.textContent)).filter(Boolean)
      : [];
    if (spans.length >= 2) {
      let price = '';
      let stock = '';
      let seenPrice = false;
      for (const sp of spans) {
        if (!seenPrice && /[¥￥]/.test(sp)) { price = sp; seenPrice = true; continue; }
        if (seenPrice && sp.startsWith('.')) { price += sp; continue; }
        if (seenPrice) { stock = sp; break; }
      }
      if (price && seenPrice && stock && !/[¥￥]/.test(stock) && !stock.startsWith('.')) {
        return { price, stock };
      }
    }
    return { price: text, stock: '' };
  };
  const pushSku = (label, priceSrc, stockSrc, imageUrl) => {
    const name = clean(label);
    if (!name || skuRows.some((x) => x.label === name)) return;
    skuRows.push({ label: name, priceText: clean(priceSrc), stockText: clean(stockSrc), imageUrl: clean(imageUrl || '') });
  };
  // 路径 1：expand-view-list（价格/库存明细模块）
  const expandItems = Array.from(document.querySelectorAll('.expand-view-list .expand-view-item'));
  if (expandItems.length) {
    skuPath = 'expand';
    for (const node of expandItems) {
      const label = clean((node.querySelector('.item-label') || {}).innerText || '');
      const stockNodes = Array.from(node.querySelectorAll('.item-price-stock'));
      let priceSrc = '';
      let stockSrc = '';
      for (const sn of stockNodes) {
        const raw = clean(sn.innerText || sn.textContent);
        if (!raw) continue;
        const split = splitPriceStock(raw, sn);
        if (!priceSrc && /[¥￥]/.test(split.price)) priceSrc = split.price;
        if (!stockSrc && split.stock) stockSrc = split.stock;
        if (!priceSrc && /[¥￥]/.test(raw)) priceSrc = raw;
        if (!stockSrc && RE_STOCK.test(raw)) stockSrc = raw;
      }
      const img = node.querySelector('img');
      const imageUrl = img ? (img.currentSrc || img.src || img.getAttribute('src') || '') : '';
      pushSku(label, priceSrc, stockSrc, imageUrl);
    }
  }
  // 路径 2：通用 sku item（类名含 sku 的列表项）
  if (!skuRows.length) {
    const generic = Array.from(
      document.querySelectorAll('[class*="sku"] [class*="item"], .sku-item, .offer-sku-item')
    );
    if (generic.length) {
      skuPath = 'generic';
      for (const node of generic.slice(0, 200)) {
        const label = clean(
          (node.querySelector('[class*="name"], [class*="label"], dt') || {}).innerText || node.innerText
        );
        const texts = Array.from(node.querySelectorAll('[class*="price"], [class*="stock"], dd, td'))
          .map((n) => clean(n.innerText || n.textContent))
          .filter(Boolean);
        let priceSrc = texts.find((t) => /[¥￥]\s*\d+(\.\d+)?/.test(t) && !isTooltip(t)) || '';
        let stockSrc = texts.find((t) => RE_STOCK.test(t)) || '';
        // span 拼接单元格拆分（价格+库存）
        if (priceSrc) {
          const priceNodes = Array.from(node.querySelectorAll('[class*="price"], [class*="stock"], td'));
          const split = priceNodes.map((pn) => splitPriceStock(clean(pn.innerText || pn.textContent), pn))
            .find((x) => /[¥￥]/.test(x.price) && x.stock);
          if (split) { priceSrc = split.price; stockSrc = split.stock; }
        }
        if (!priceSrc && !stockSrc) continue;
        const img = node.querySelector('img');
        const imageUrl = img ? (img.currentSrc || img.src || '') : '';
        pushSku(label, priceSrc, stockSrc, imageUrl);
      }
    }
  }
  // 路径 3：表格（规格名 + 价格/库存列）
  if (!skuRows.length) {
    const skuTables = Array.from(
      document.querySelectorAll('table:not([data-module]) tr, [class*="sku"] table tr')
    );
    const rows = skuTables
      .map((tr) => {
        const cells = Array.from(tr.querySelectorAll('th, td'));
        return {
          texts: cells.map((c) => clean(c.innerText || c.textContent)),
          nodes: cells,
        };
      })
      .filter((r) => r.texts.length >= 2 && r.texts.some((c) => /[¥￥]\s*\d+(\.\d+)?/.test(c)));
    if (rows.length) {
      skuPath = 'table';
      for (const r of rows) {
        const name = r.texts[0];
        let priceSrc = '';
        let stockSrc = '';
        for (let ci = 0; ci < r.nodes.length; ci++) {
          const cellText = r.texts[ci];
          const node = r.nodes[ci];
          if (!/[¥￥]/.test(cellText) && !RE_STOCK.test(cellText) && !/^\d+$/.test(cellText)) continue;
          const split = splitPriceStock(cellText, node);
          if (/[¥￥]/.test(split.price) && !isTooltip(split.price)) priceSrc = split.price;
          if (split.stock) stockSrc = split.stock;
          else if (RE_STOCK.test(cellText)) stockSrc = cellText;
          else if (/^\d+$/.test(cellText) && !priceSrc) stockSrc = cellText;
        }
        pushSku(name, priceSrc, stockSrc, '');
      }
    }
  }
  if (!skuRows.length) notes.push('sku:missing');

  // SKU 维度标题（如 "颜色分类"、"规格"；颜色×规格多维度时收集全部标题）
  // 2026-08-14 适配：当前布局为 od_sku_selection 内无 class 的 H3（父级 feature-item-label），
  // 旧 [class*="title"] 选择器已失效，新选择器置前，旧选择器保留兜底。
  const pickSkuDimensions = () => {
    const selectors = [
      '[data-module="od_sku_selection"] .feature-item-label',
      '[data-module="od_sku_selection"] h3',
      '[data-module="od_sku_selection"] [class*="title"]',
      '[data-module="od_sku"] [class*="title"]',
      '[class*="sku"] [class*="title"]',
    ];
    for (const selector of selectors) {
      const values = [];
      for (const node of Array.from(document.querySelectorAll(selector))) {
        const text = clean(node && (node.innerText || node.textContent));
        if (
          text &&
          text.length <= 12 &&
          !/[¥￥]|库存|\d/.test(text) &&
          !values.includes(text)
        ) {
          values.push(text);
        }
      }
      if (values.length) return values;
    }
    return [];
  };
  const skuDimensions = skuRows.length ? pickSkuDimensions() : [];
  const skuDimension = skuDimensions.join(',');

  // ---------- 包装参数表 ----------
  const packRows = Array.from(
    document.querySelectorAll(
      '[data-module="od_product_pack_info"] table tr, [data-module="od_package"] table tr, .module-od-package table tr, [class*="package"] table tr'
    )
  )
    .slice(0, 50)
    .map((tr) =>
      Array.from(tr.querySelectorAll('th, td')).map((c) => clean(c.innerText || c.textContent))
    );

  // ---------- 图库（主图 + 轮播图，过滤 SVG 占位图标） ----------
  const galleryModule = document.querySelector(
    '[data-module="od_picture_gallery"], [data-module="od_gallery"], .module-od-picture-gallery'
  );
  const galleryScope = galleryModule || document;
  const galleryImgs = Array.from(galleryScope.querySelectorAll('img')).filter(
    (img) => {
      const cls = (img.className || '') + '';
      const url = imgSrc(img);
      return (
        /preview-img/.test(cls) ||
        (/ant-image-img/.test(cls) && isRealImage(url))
      );
    }
  );
  const galleryImages = uniqueUrls(galleryImgs.map(imgSrc).filter(isRealImage));
  const mainImgNode =
    galleryImgs.find(
      (img) =>
        img.classList.contains('preview-img') && img.classList.contains('active-preview-img')
    ) ||
    galleryImgs.find((img) => img.classList.contains('preview-img')) ||
    galleryImgs.find((img) => isRealImage(imgSrc(img)));
  const mainImageUrl = mainImgNode ? imgSrc(mainImgNode) : galleryImages[0] || '';
  const imageUrls = galleryImages.length ? galleryImages : mainImageUrl ? [mainImageUrl] : [];

  // ---------- 详情图片（v-detail-8 shadow DOM 异步加载，过滤 SVG） ----------
  const detailHosts = Array.from(
    document.querySelectorAll(
      '[class*="html-description"], v-detail-8, [data-module="od_product_description"], [data-module="od_detail"], .module-od-product-description, .module-od-detail'
    )
  ).filter((el) => {
    const tag = (el.tagName || '').toLowerCase();
    const marker = [
      (el.className || ''),
      (el.getAttribute && el.getAttribute('data-module')) || '',
    ]
      .join(' ')
      .toLowerCase();
    return (
      /^v-detail-/.test(tag) ||
      /html-description|module-od-product-description|module-od-detail|od_product_description|od_detail/.test(
        marker
      )
    );
  });
  let detailImages = [];
  const collectImages = (root) =>
    uniqueUrls(
      Array.from((root || document).querySelectorAll('img'))
        .map(imgSrc)
        .filter(isRealImage)
    );
  for (const host of detailHosts) {
    detailImages = collectImages(host.shadowRoot || host);
    if (detailImages.length) break;
  }
  if (!detailImages.length) {
    detailImages = collectImages(
      document.querySelector(
        '[data-module="od_product_description"], [data-module="od_detail"], .module-od-product-description, .module-od-detail'
      )
    );
  }

  // ---------- 商品视频（页面 / shadow DOM / 图库，不重复） ----------
  const videoCandidates = [];
  const collectVideos = (root) => {
    for (const v of (root || document).querySelectorAll('video, source')) {
      const u = clean(
        v.currentSrc ||
          v.src ||
          v.getAttribute('src') ||
          v.getAttribute('data-src') ||
          ''
      );
      if (u && /^https?:\/\//i.test(u)) videoCandidates.push(u);
    }
  };
  collectVideos(document);
  for (const host of detailHosts) {
    if (host.shadowRoot) collectVideos(host.shadowRoot);
  }
  if (galleryModule) collectVideos(galleryModule);
  const videoUrl = uniqueUrls(videoCandidates)[0] || '';

  // ---------- 关联商品 ----------
  const related = Array.from(document.querySelectorAll('a[href*="/offer/"], a[href*="offerId="]'))
    .slice(0, 80)
    .map((a) => ({ text: clean(a.innerText || a.textContent), href: a.href || '' }))
    .filter((x) => x.href && x.text && x.text.length > 4);

  // ---------- memberId（取页面中最后一个 b2b memberId，见失败链路 F6） ----------
  const htmlMatches = (document.documentElement.outerHTML.match(/"memberId"\s*:\s*"([^"]+)"/g) || []).map(
    (m) => (m.match(/"memberId"\s*:\s*"([^"]+)"/) || [])[1] || ''
  );
  const memberIds = htmlMatches.filter((x) => x.startsWith('b2b-'));
  const memberId = memberIds.length ? memberIds[memberIds.length - 1] : '';

  // ---------- 布局签名（排版变体统计用） ----------
  const modules = {
    title: title ? 'found' : 'missing',
    price: priceText ? (priceNode.startsWith('fallback') ? 'fallback' : 'found') : 'missing',
    attrs: attrPath,
    sku: skuPath,
    moq: moqText ? 'found' : 'missing',
    unit: unitText ? 'found' : 'missing',
    stock: stockText ? 'found' : 'missing',
    delivery: deliveryText ? 'found' : 'missing',
    package: packRows.length ? 'found' : 'missing',
  };
  const layoutKey = [
    't:' + modules.title,
    'p:' + modules.price,
    'a:' + modules.attrs,
    's:' + modules.sku,
    'm:' + modules.moq,
    'u:' + modules.unit,
    'k:' + modules.stock,
  ].join('|');

  return {
    title,
    supplierName,
    priceText,
    priceNode,
    priceRangeText,
    moqText,
    unitText,
    stockText,
    deliveryText,
    attrs,
    skuRows,
    skuDimensions,
    skuDimension,
    packRows,
    mainImageUrl,
    imageUrls,
    detailImages,
    videoUrl,
    related,
    memberId,
    modules,
    layoutKey,
    notes,
    extractedAt: new Date().toISOString(),
  };
};

// 兼容 CommonJS/浏览器两种加载方式
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { extractDetailPage };
}
