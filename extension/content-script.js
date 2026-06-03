/**
 * Calm Capture — content-script.js
 *
 * Extracts the main readable content from the current page using a self-contained
 * heuristic extractor (no external CDN required). Works on authenticated / paywalled
 * pages because it reads the live DOM the browser has already rendered.
 *
 * Messages accepted:
 *   { action: 'extract' }
 *
 * Response payload:
 *   { success: true, title, content_markdown, byline, excerpt, source_url, word_count }
 *   { success: false, error: string }
 */

(function () {
  'use strict';

  /* ─────────────────────────────────────────────────────────────────────────
   * 1. MINIMAL READABILITY-STYLE EXTRACTOR
   * ───────────────────────────────────────────────────────────────────────── */

  /**
   * Score a candidate element for "article-ness".
   * Returns a numeric score — higher is better.
   */
  function scoreElement(el) {
    if (!el) return -Infinity;
    const tag = el.tagName.toLowerCase();

    // Hard positive containers
    const positiveContainerTags = new Set(['article', 'main', 'section']);
    // Hard negative containers
    const negativeContainerTags = new Set([
      'nav', 'header', 'footer', 'aside', 'form', 'menu',
      'menubar', 'dialog', 'select', 'option',
    ]);
    // Inline / void tags we never want as root
    const inlineTags = new Set([
      'a', 'abbr', 'acronym', 'b', 'bdo', 'big', 'br', 'button', 'cite',
      'code', 'dfn', 'em', 'i', 'img', 'input', 'kbd', 'label', 'map',
      'object', 'output', 'q', 's', 'samp', 'select', 'small', 'span',
      'strong', 'sub', 'sup', 'textarea', 'time', 'tt', 'u', 'var',
    ]);

    if (inlineTags.has(tag)) return -Infinity;

    let score = 0;

    if (positiveContainerTags.has(tag)) score += 30;
    if (negativeContainerTags.has(tag)) score -= 50;
    if (tag === 'div') score += 5;
    if (tag === 'p') score += 3;

    // class / id heuristics
    const identity = ((el.className || '') + ' ' + (el.id || '')).toLowerCase();
    const positivePattern = /article|content|post|story|entry|text|body|main|prose|reader|blog/;
    const negativePattern = /comment|sidebar|nav|menu|footer|header|widget|ad|promo|related|share|social|cookie|banner|popup|modal/;

    if (positivePattern.test(identity)) score += 25;
    if (negativePattern.test(identity)) score -= 30;

    // Text density
    const text = el.innerText || '';
    const words = text.trim().split(/\s+/).filter(Boolean).length;
    const links = el.querySelectorAll('a');
    const linkText = Array.from(links).reduce((acc, a) => acc + (a.innerText || '').length, 0);
    const totalText = text.length || 1;
    const linkDensity = linkText / totalText;

    score += Math.min(words / 20, 20);        // up to +20 for word count
    score -= linkDensity * 30;                // penalise nav-heavy blocks

    // Paragraph count bonus
    const pCount = el.querySelectorAll('p').length;
    score += Math.min(pCount * 3, 30);

    return score;
  }

  /**
   * Walk candidates from most-specific containers and pick the best scoring one.
   */
  function findBestContentElement(doc) {
    // Priority 1: semantic landmarks
    const semanticCandidates = [
      doc.querySelector('article'),
      doc.querySelector('main'),
      doc.querySelector('[role="main"]'),
      doc.querySelector('[role="article"]'),
    ].filter(Boolean);

    if (semanticCandidates.length > 0) {
      // Among semantic candidates pick by score
      return semanticCandidates.reduce((best, el) =>
        scoreElement(el) >= scoreElement(best) ? el : best
      );
    }

    // Priority 2: heuristic scan of div / section elements
    const candidates = Array.from(
      doc.querySelectorAll('div, section, td')
    );

    let bestEl = doc.body;
    let bestScore = -Infinity;

    for (const el of candidates) {
      // Skip tiny elements
      const text = (el.innerText || '').trim();
      if (text.length < 200) continue;

      const s = scoreElement(el);
      if (s > bestScore) {
        bestScore = s;
        bestEl = el;
      }
    }

    return bestEl;
  }

  /* ─────────────────────────────────────────────────────────────────────────
   * 2. HTML → MARKDOWN CONVERTER
   * ───────────────────────────────────────────────────────────────────────── */

  /**
   * Convert a DOM node tree into a Markdown string.
   * Handles: h1-h6, p, br, strong/b, em/i, code, pre, a, ul/ol/li, blockquote,
   *           img (alt text), hr, and strips everything else to plain text.
   */
  function nodeToMarkdown(node, ctx) {
    ctx = ctx || { listDepth: 0, orderedStack: [] };

    if (node.nodeType === Node.TEXT_NODE) {
      // Preserve meaningful whitespace but collapse runs
      const text = node.textContent.replace(/[\r\n]+/g, ' ').replace(/\s{2,}/g, ' ');
      return text;
    }

    if (node.nodeType !== Node.ELEMENT_NODE) return '';

    const tag = node.tagName.toLowerCase();

    // Elements to completely skip
    const skip = new Set([
      'script', 'style', 'noscript', 'iframe', 'svg', 'canvas', 'video',
      'audio', 'template', 'figure', // figure captions handled via figcaption below
    ]);
    if (skip.has(tag)) return '';

    const childMd = () =>
      Array.from(node.childNodes)
        .map(child => nodeToMarkdown(child, ctx))
        .join('');

    switch (tag) {
      case 'h1': return `\n\n# ${childMd().trim()}\n\n`;
      case 'h2': return `\n\n## ${childMd().trim()}\n\n`;
      case 'h3': return `\n\n### ${childMd().trim()}\n\n`;
      case 'h4': return `\n\n#### ${childMd().trim()}\n\n`;
      case 'h5': return `\n\n##### ${childMd().trim()}\n\n`;
      case 'h6': return `\n\n###### ${childMd().trim()}\n\n`;

      case 'p': {
        const inner = childMd().trim();
        if (!inner) return '';
        return `\n\n${inner}\n\n`;
      }

      case 'br': return '  \n';

      case 'strong':
      case 'b': {
        const inner = childMd().trim();
        return inner ? `**${inner}**` : '';
      }

      case 'em':
      case 'i': {
        const inner = childMd().trim();
        return inner ? `*${inner}*` : '';
      }

      case 'del':
      case 's': {
        const inner = childMd().trim();
        return inner ? `~~${inner}~~` : '';
      }

      case 'code': {
        // Inline code — if parent is pre, skip (pre handles it)
        if (node.parentElement && node.parentElement.tagName.toLowerCase() === 'pre') {
          return node.textContent;
        }
        return `\`${node.textContent}\``;
      }

      case 'pre': {
        // Try to detect language from class
        const codeEl = node.querySelector('code');
        let lang = '';
        if (codeEl) {
          const cls = codeEl.className || '';
          const langMatch = cls.match(/language-(\S+)/);
          if (langMatch) lang = langMatch[1];
        }
        const text = (codeEl ? codeEl.textContent : node.textContent).trim();
        return `\n\n\`\`\`${lang}\n${text}\n\`\`\`\n\n`;
      }

      case 'a': {
        const href = node.getAttribute('href') || '';
        const inner = childMd().trim();
        if (!inner) return href ? `<${href}>` : '';
        if (!href || href.startsWith('javascript:')) return inner;
        // Make relative URLs absolute
        let absHref = href;
        try {
          absHref = new URL(href, window.location.href).href;
        } catch (_) { /* keep original */ }
        return `[${inner}](${absHref})`;
      }

      case 'img': {
        const alt = node.getAttribute('alt') || '';
        const src = node.getAttribute('src') || '';
        if (!src) return alt;
        let absSrc = src;
        try { absSrc = new URL(src, window.location.href).href; } catch (_) { /* ignore */ }
        return `![${alt}](${absSrc})`;
      }

      case 'figcaption': {
        const inner = childMd().trim();
        return inner ? `\n*${inner}*\n` : '';
      }

      case 'figure': {
        return `\n\n${childMd().trim()}\n\n`;
      }

      case 'ul': {
        ctx.listDepth += 1;
        const items = Array.from(node.children)
          .map(li => {
            if (li.tagName.toLowerCase() !== 'li') return '';
            const indent = '  '.repeat(ctx.listDepth - 1);
            const content = nodeToMarkdown(li, ctx).trim();
            return `${indent}- ${content}`;
          })
          .filter(Boolean)
          .join('\n');
        ctx.listDepth -= 1;
        return `\n\n${items}\n\n`;
      }

      case 'ol': {
        ctx.listDepth += 1;
        let counter = 1;
        const items = Array.from(node.children)
          .map(li => {
            if (li.tagName.toLowerCase() !== 'li') return '';
            const indent = '  '.repeat(ctx.listDepth - 1);
            const content = nodeToMarkdown(li, ctx).trim();
            return `${indent}${counter++}. ${content}`;
          })
          .filter(Boolean)
          .join('\n');
        ctx.listDepth -= 1;
        return `\n\n${items}\n\n`;
      }

      case 'li': {
        // li is handled by parent ul/ol; if called directly just return children
        return childMd();
      }

      case 'blockquote': {
        const inner = childMd().trim();
        const lines = inner.split('\n').map(l => `> ${l}`).join('\n');
        return `\n\n${lines}\n\n`;
      }

      case 'hr': return '\n\n---\n\n';

      case 'table': {
        return convertTable(node);
      }

      case 'thead':
      case 'tbody':
      case 'tfoot':
      case 'tr':
      case 'th':
      case 'td':
        // Handled by convertTable — skip if encountered standalone
        return childMd();

      case 'div':
      case 'section':
      case 'article':
      case 'main':
      case 'aside':
      case 'header':
      case 'footer':
      case 'nav':
      case 'span':
      case 'details':
      case 'summary':
      default:
        return childMd();
    }
  }

  /**
   * Convert an HTML table into a GFM markdown table.
   */
  function convertTable(tableEl) {
    const rows = Array.from(tableEl.querySelectorAll('tr'));
    if (rows.length === 0) return '';

    const parseRow = (row) =>
      Array.from(row.querySelectorAll('th, td')).map(cell => {
        const text = (cell.innerText || '').replace(/\n/g, ' ').replace(/\|/g, '\\|').trim();
        return text;
      });

    const allRows = rows.map(parseRow).filter(r => r.length > 0);
    if (allRows.length === 0) return '';

    const colCount = Math.max(...allRows.map(r => r.length));
    const pad = (row) => {
      while (row.length < colCount) row.push('');
      return row;
    };

    const headerRow = pad(allRows[0]);
    const separator = headerRow.map(() => '---');
    const bodyRows = allRows.slice(1).map(pad);

    const rowToMd = (r) => `| ${r.join(' | ')} |`;

    return [
      '',
      rowToMd(headerRow),
      rowToMd(separator),
      ...bodyRows.map(rowToMd),
      '',
    ].join('\n');
  }

  /**
   * Post-process markdown: collapse excessive blank lines, trim.
   */
  function cleanMarkdown(md) {
    return md
      .replace(/\n{4,}/g, '\n\n\n')   // max 3 consecutive newlines
      .replace(/[ \t]+$/gm, '')        // trailing spaces per line
      .trim();
  }

  /* ─────────────────────────────────────────────────────────────────────────
   * 3. METADATA EXTRACTION
   * ───────────────────────────────────────────────────────────────────────── */

  function extractMetadata(doc) {
    const meta = (name) => {
      const el =
        doc.querySelector(`meta[name="${name}"]`) ||
        doc.querySelector(`meta[property="${name}"]`) ||
        doc.querySelector(`meta[property="og:${name}"]`) ||
        doc.querySelector(`meta[name="twitter:${name}"]`);
      return el ? (el.getAttribute('content') || '').trim() : '';
    };

    const title =
      meta('title') ||
      doc.querySelector('h1')?.innerText?.trim() ||
      doc.title?.trim() ||
      '';

    const byline =
      meta('author') ||
      meta('article:author') ||
      doc.querySelector('[rel="author"]')?.innerText?.trim() ||
      doc.querySelector('.author')?.innerText?.trim() ||
      doc.querySelector('[class*="byline"]')?.innerText?.trim() ||
      '';

    const excerpt =
      meta('description') ||
      meta('og:description') ||
      '';

    return { title, byline, excerpt };
  }

  /* ─────────────────────────────────────────────────────────────────────────
   * 4. MAIN EXTRACTION FUNCTION
   * ───────────────────────────────────────────────────────────────────────── */

  function extractPageContent() {
    try {
      const doc = window.document;

      // Work on a clone so we don't mutate the live page
      const clone = doc.cloneNode(true);

      // Remove noise nodes from clone
      const noiseSelectors = [
        'script', 'style', 'noscript', 'iframe',
        'nav', 'header', 'footer',
        '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
        '[aria-hidden="true"]',
        '.cookie-banner', '.cookie-notice', '.gdpr',
        '.advertisement', '.ad', '[class*="sidebar"]',
        '[class*="related"]', '[class*="recommend"]',
        '[class*="social"]', '[class*="share"]',
        '[class*="comment"]', '[id*="comment"]',
        '[class*="newsletter"]', '[class*="subscribe"]',
        '[class*="popup"]', '[class*="modal"]',
        '[class*="overlay"]',
      ];

      // We must query the clone, but clone doesn't have the browser layout
      // so use doc for scoring and clone for serialisation
      const bestEl = findBestContentElement(doc);

      // Find the equivalent node in the clone by XPath
      function getXPath(el, root) {
        const parts = [];
        let current = el;
        while (current && current !== root && current.nodeType === Node.ELEMENT_NODE) {
          let index = 1;
          let sib = current.previousElementSibling;
          while (sib) {
            if (sib.tagName === current.tagName) index++;
            sib = sib.previousElementSibling;
          }
          parts.unshift(`${current.tagName.toLowerCase()}[${index}]`);
          current = current.parentElement;
        }
        return '/' + parts.join('/');
      }

      // Remove noise from the best element's clone counterpart (operate on doc directly for text)
      // Since we cannot easily mirror XPath in a detached clone, we directly work on the live doc element
      // but avoid mutating it — instead we do a targeted clone of just the content node.
      const contentClone = bestEl.cloneNode(true);

      // Strip noise from content clone
      const noiseEls = contentClone.querySelectorAll(noiseSelectors.join(','));
      noiseEls.forEach(el => el.remove());

      // Convert to markdown
      const rawMarkdown = nodeToMarkdown(contentClone, { listDepth: 0 });
      const content_markdown = cleanMarkdown(rawMarkdown);

      // Metadata (from live doc)
      const { title, byline, excerpt } = extractMetadata(doc);

      // Word count from plain text
      const plainText = (contentClone.innerText || contentClone.textContent || '').trim();
      const word_count = plainText.split(/\s+/).filter(Boolean).length;

      return {
        success: true,
        title: title || doc.title || '',
        content_markdown,
        byline,
        excerpt,
        source_url: window.location.href,
        word_count,
      };
    } catch (err) {
      return {
        success: false,
        error: err.message || String(err),
      };
    }
  }

  /* ─────────────────────────────────────────────────────────────────────────
   * 5. MESSAGE LISTENER
   * ───────────────────────────────────────────────────────────────────────── */

  chrome.runtime.onMessage.addListener(function (message, _sender, sendResponse) {
    if (!message || message.action !== 'extract') return false;

    // Run extraction asynchronously to not block the message channel
    Promise.resolve().then(() => {
      const result = extractPageContent();
      sendResponse(result);
    });

    return true; // keep message channel open for async response
  });

})();
