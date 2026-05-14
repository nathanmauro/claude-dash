(() => {
  const filter = document.getElementById('filter');
  const PREV = window.DASH_CONFIG?.prevUrl;
  const NEXT = window.DASH_CONFIG?.nextUrl;

  // Click-to-copy session id
  document.querySelectorAll('.sid[data-sid]').forEach(el => {
    el.addEventListener('click', e => {
      e.preventDefault();
      e.stopPropagation();
      const sid = el.dataset.sid;
      if (navigator.clipboard) {
        navigator.clipboard.writeText(sid).then(() => {
          el.classList.add('copied');
          setTimeout(() => el.classList.remove('copied'), 1000);
        });
      }
    });
  });

  // Server-side + Client-side search
  if (filter) {
    let debounce;
    const searchResults = document.createElement('div');
    searchResults.className = 'search-results';
    filter.parentNode.after(searchResults);

    const apply = () => {
      const q = filter.value.trim();
      const ql = q.toLowerCase();

      // Client-side local filter
      document.querySelectorAll('.session').forEach(card => {
        const blob = card.dataset.search || '';
        card.style.display = (!ql || blob.includes(ql)) ? '' : 'none';
      });
      document.querySelectorAll('.project').forEach(p => {
        const any = [...p.querySelectorAll('.session')].some(c => c.style.display !== 'none');
        p.style.display = any ? '' : 'none';
      });

      // Global server-side search
      clearTimeout(debounce);
      if (q.length < 3) {
        searchResults.innerHTML = '';
        return;
      }
      debounce = setTimeout(async () => {
        const res = await fetch(`/search?q=${encodeURIComponent(q)}`);
        const data = await res.json();
        if (data.length === 0) {
          searchResults.innerHTML = '';
          return;
        }
        searchResults.innerHTML = `
          <div class="search-header">Global Search Results</div>
          ${data.map(r => `
            <a href="#sid-${r.session_id}" class="search-hit" onclick="document.getElementById('sid-${r.session_id}')?.querySelector('details')?.setAttribute('open', '')">
              <div class="hit-meta">${r.date} · ${r.cwd.split('/').pop()}</div>
              <div class="hit-title">${r.title}</div>
              <div class="hit-snippet">${r.snippet}</div>
            </a>
          `).join('')}
        `;
      }, 150);
    };
    filter.addEventListener('input', apply);
  }

  // Keyboard nav
  document.addEventListener('keydown', e => {
    if (e.target.matches('input, textarea')) {
      if (e.key === 'Escape' && e.target === filter) {
        filter.value = '';
        filter.dispatchEvent(new Event('input'));
        filter.blur();
      }
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 'ArrowLeft' && PREV) { location.href = PREV; }
    else if (e.key === 'ArrowRight' && NEXT) { location.href = NEXT; }
    else if (e.key === 't') { location.href = '/'; }
    else if (e.key === '/') {
      e.preventDefault();
      filter && filter.focus();
    }
  });
})();
