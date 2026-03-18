      (function () {
        var BRACE_TOKEN_RE = /\{\{[^}]+\}\}/;
        var PAGE_TOKEN_RE = /\{\{\s*page:([^}]+)\s*\}\}/;
        var BRACKET_RE = /\[[^\]]+\]/;
        var SAMPLE_LIMIT = 6;

        function normalizeText(value) {
          return (value || '').replace(/\s+/g, ' ').trim();
        }
