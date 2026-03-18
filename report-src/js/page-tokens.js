        function getTokenKey(element) {
          var field = element.getAttribute('data-field') || '';
          if (field.indexOf('page.') === 0) {
            return field.slice(5);
          }
          var parent = element.closest('[data-toc-key]');
          return parent ? parent.getAttribute('data-toc-key') : '';
        }
