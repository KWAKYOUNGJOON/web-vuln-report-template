      (function () {
        var BRACE_TOKEN_RE = /\{\{[^}]+\}\}/;
        var PAGE_TOKEN_RE = /\{\{\s*page:([^}]+)\s*\}\}/;
        var BRACKET_RE = /\[[^\]]+\]/;
        var SAMPLE_LIMIT = 6;

        function normalizeText(value) {
          return (value || '').replace(/\s+/g, ' ').trim();
        }

        function getTokenKey(element) {
          var field = element.getAttribute('data-field') || '';
          if (field.indexOf('page.') === 0) {
            return field.slice(5);
          }
          var parent = element.closest('[data-toc-key]');
          return parent ? parent.getAttribute('data-toc-key') : '';
        }

        function buildLabel(element, text) {
          var key = element.getAttribute('data-field') || element.getAttribute('data-page-token') || element.getAttribute('data-toc-key');
          if (key) {
            return key + ' -> ' + text;
          }
          return text;
        }

        var seen = new Set();
        var targets = Array.prototype.slice.call(document.querySelectorAll('.placeholder, .requires-input, .token-text, .toc-page, .auto-field[data-field]'));
        var unresolved = [];
        var retainedPlaceholderClass = 0;
        var pageTokenCount = 0;
        var criticalCount = 0;

        targets.forEach(function (element) {
          if (seen.has(element)) {
            return;
          }
          seen.add(element);

          var text = normalizeText(element.textContent);
          var pageTokenKey = '';

          element.classList.remove('has-placeholder-class', 'is-unresolved', 'is-page-token');

          if (element.classList.contains('toc-page')) {
            pageTokenKey = getTokenKey(element);
            if (pageTokenKey) {
              element.dataset.pageToken = pageTokenKey;
              element.classList.add('page-token');
              if (!text || PAGE_TOKEN_RE.test(text)) {
                element.textContent = '{{page:' + pageTokenKey + '}}';
                text = normalizeText(element.textContent);
              }
            }
          }

          if (element.classList.contains('placeholder')) {
            element.classList.add('has-placeholder-class');
            retainedPlaceholderClass += 1;
          }

          var hasBraceToken = BRACE_TOKEN_RE.test(text);
          var hasBracketToken = BRACKET_RE.test(text);
          var isPageToken = PAGE_TOKEN_RE.test(text) || (element.classList.contains('toc-page') && text.indexOf('{{page:') === 0);
          var isUnresolved = isPageToken || hasBraceToken || (hasBracketToken && (element.classList.contains('placeholder') || element.classList.contains('requires-input') || element.classList.contains('token-text')));

          if (isUnresolved) {
            element.classList.add('is-unresolved');
            if (isPageToken) {
              element.classList.add('is-page-token');
              pageTokenCount += 1;
            }
            if (element.classList.contains('requires-input')) {
              criticalCount += 1;
            }
            unresolved.push(buildLabel(element, text));
          }
        });

        var summary = document.getElementById('submission-audit-summary');
        var list = document.getElementById('submission-audit-list');

        if (!summary || !list) {
          return;
        }

        if (!unresolved.length) {
          summary.innerHTML = '<span class="submission-audit-empty">미치환 placeholder와 페이지 토큰이 탐지되지 않았습니다.</span>';
          list.innerHTML = '';
          return;
        }

        summary.innerHTML =
          '<strong>미치환 항목 ' + unresolved.length + '건</strong> / 중요 입력 ' + criticalCount + '건 / 페이지 토큰 ' + pageTokenCount + '건 / placeholder class ' + retainedPlaceholderClass + '건';

        list.innerHTML = unresolved.slice(0, SAMPLE_LIMIT).map(function (item) {
          return '<li>' + item.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</li>';
        }).join('');

        if (unresolved.length > SAMPLE_LIMIT) {
          list.insertAdjacentHTML('beforeend', '<li>외 ' + (unresolved.length - SAMPLE_LIMIT) + '건 추가</li>');
        }

      })();
