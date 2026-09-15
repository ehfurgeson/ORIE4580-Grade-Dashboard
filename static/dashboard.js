(() => {
  'use strict';

  const statusElement = document.querySelector('#status');
  const dashboard = document.querySelector('#dashboard');
  const endpoint = window.GRADE_DATA_URL || 'students/me/grades.json';
  const allowedStatuses = new Set(['complete', 'incomplete', 'not_graded', 'excused']);
  const escapeHtml = value => String(value ?? '').replace(
    /[&<>"']/g,
    character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]
  );
  const statusLabels = {
    complete: 'Earned',
    incomplete: 'Not earned',
    not_graded: 'Not graded',
    excused: 'Excused (not counted)'
  };

  function validatePayload(data) {
    if (!data || typeof data !== 'object') throw new Error('The grade data is not an object.');
    if (!data.student || typeof data.student.name !== 'string') throw new Error('Student information is missing.');
    if (typeof data.course !== 'string') throw new Error('Course information is missing.');
    if (!Array.isArray(data.standards) || data.standards.length === 0) throw new Error('No standards were provided.');
    const updatedAt = new Date(data.updated_at);
    if (Number.isNaN(updatedAt.getTime())) throw new Error('The update time is invalid.');
    for (const standard of data.standards) {
      if (!standard || typeof standard.id !== 'string' || typeof standard.name !== 'string' || !Array.isArray(standard.opportunities)) {
        throw new Error('A standard is malformed.');
      }
      for (const opportunity of standard.opportunities) {
        if (!opportunity || !['green', 'purple', 'shiny_purple'].includes(opportunity.kind) || !allowedStatuses.has(opportunity.status)) {
          throw new Error(`An opportunity in ${standard.id} is malformed.`);
        }
      }
    }
    return updatedAt;
  }

  function allocateStandard(opportunities) {
    const priority = { purple: 0, shiny_purple: 1, green: 2 };
    const earned = opportunities.filter(item => item.status === 'complete');
    const linked = new Set(
      earned.map((item, index) => ({ item, index }))
        .sort((a, b) => priority[a.item.kind] - priority[b.item.kind] || a.index - b.index)
        .slice(0, 2)
        .map(entry => entry.item)
    );
    const shiny = new Set(earned.filter(item => item.kind === 'shiny_purple' && !linked.has(item)));
    return { linked, shiny, missing: 2 - linked.size };
  }

  function summarize(standards) {
    let green = 0;
    let purple = 0;
    let shiny = 0;
    let purpleStandards = 0;
    let missing = 0;
    for (const standard of standards) {
      const allocation = allocateStandard(standard.opportunities);
      const linked = [...allocation.linked];
      const standardPurple = linked.filter(item => ['purple', 'shiny_purple'].includes(item.kind)).length;
      green += linked.filter(item => item.kind === 'green').length;
      purple += standardPurple + allocation.shiny.size;
      shiny += standard.opportunities.filter(item => item.kind === 'shiny_purple' && item.status === 'complete').length;
      purpleStandards += standardPurple > 0 ? 1 : 0;
      missing += allocation.missing;
    }
    return { n: standards.length, green, purple, shiny, purpleStandards, missing };
  }

  function estimateGrade(summary) {
    const { n, purple, shiny, purpleStandards, missing } = summary;
    const rules = [
      ['A+', n, Math.floor(2 * n), n - 1, 1],
      ['A', n - 1, Math.floor(1.5 * n), 1, 1],
      ['A−', n - 1, n, 0, 2],
      ['B+', Math.floor(0.75 * n), n, 0, 2],
      ['B', Math.floor(0.75 * n), Math.floor(0.75 * n), 0, 2],
      ['B−', Math.floor(0.75 * n), Math.floor(0.75 * n), 0, 4],
      ['C+', Math.floor(0.5 * n), Math.floor(0.75 * n), 0, 4],
      ['C', Math.floor(0.5 * n), Math.floor(0.5 * n), 0, 4]
    ];
    return rules.find(([, standardsNeeded, purpleNeeded, shinyNeeded, maxMissing]) =>
      purpleStandards >= standardsNeeded && purple >= purpleNeeded && shiny >= shinyNeeded && missing <= maxMissing
    )?.[0] ?? 'No listed threshold currently met';
  }

  function render(data, updatedAt) {
    document.querySelector('#student-name').textContent = data.student.name;
    document.querySelector('#course-name').textContent = data.course;
    const time = document.querySelector('#updated-at');
    time.dateTime = data.updated_at;
    time.textContent = updatedAt.toLocaleString(undefined, { timeZoneName: 'short' });

    const summary = summarize(data.standards);
    document.querySelector('#green-total').textContent = summary.green;
    document.querySelector('#purple-total').textContent = summary.purple;
    document.querySelector('#shiny-total').textContent = summary.shiny;
    document.querySelector('#purple-standards').textContent = `${summary.purpleStandards} of ${summary.n}`;
    document.querySelector('#missing-total').textContent = summary.missing;
    document.querySelector('#grade-estimate').textContent = estimateGrade(summary);

    document.querySelector('#standards').innerHTML = data.standards.map(standard => {
      const allocation = allocateStandard(standard.opportunities);
      const linkedItems = [...allocation.linked];
      const linkedBoxes = [0, 1].map(index => {
        const item = linkedItems[index];
        if (!item) return '<span class="linked-box empty-box">Empty</span>';
        const label = item.kind === 'shiny_purple' ? 'Shiny purple' : item.kind[0].toUpperCase() + item.kind.slice(1);
        return `<span class="linked-box ${item.kind}" title="${escapeHtml(item.label)}">${label}</span>`;
      }).join('');
      const opportunities = standard.opportunities.length
        ? standard.opportunities.map(item => {
          const earned = item.status === 'complete';
          const source = item.source === 'exam_like' ? 'exam-like' : item.source;
          let displayedStatus = statusLabels[item.status];
          if (earned && allocation.linked.has(item)) displayedStatus = 'Counts in standard box';
          else if (earned && allocation.shiny.has(item)) displayedStatus = 'Counts in shiny box';
          else if (earned) displayedStatus = 'Extra—not counted';
          const mark = earned ? (item.kind === 'shiny_purple' ? '✦' : '✓') : '–';
          return `<li class="opportunity ${item.kind} ${item.status}">
            <span class="checkmark ${item.kind} ${earned ? 'earned' : 'unearned'}" aria-hidden="true">${mark}</span>
            <span class="opportunity-name">${escapeHtml(item.label)}</span>
            <span class="opportunity-source">${escapeHtml(source)}</span>
            <span class="opportunity-status">${displayedStatus}</span>
          </li>`;
        }).join('')
        : '<li class="empty">No opportunities recorded yet.</li>';
      return `<article class="standard">
        <p class="category">${escapeHtml(standard.category)}</p>
        <h3>${escapeHtml(standard.id)}: ${escapeHtml(standard.name)}</h3>
        <div class="linked-boxes"><strong>Standard-linked boxes:</strong>${linkedBoxes}</div>
        <ul class="opportunities">${opportunities}</ul>
      </article>`;
    }).join('');

    statusElement.textContent = 'Grades loaded.';
    statusElement.hidden = true;
    dashboard.hidden = false;
  }

  fetch(endpoint, { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } })
    .then(response => {
      if (!response.ok) throw new Error(`Request failed (${response.status}).`);
      return response.json();
    })
    .then(data => render(data, validatePayload(data)))
    .catch(error => {
      statusElement.textContent = `Unable to load grades. ${error.message} Please refresh or contact course staff.`;
      statusElement.classList.add('error');
    });
})();
