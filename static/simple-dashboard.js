(() => {
  'use strict';

  const allowedStatuses = new Set(['complete', 'incomplete', 'not_graded']);
  const autograderStatuses = new Set([
    'passed', 'failed', 'pending', 'error', 'not_submitted', 'not_configured', 'not_found'
  ]);
  const statusElement = document.querySelector('#status');
  const dashboard = document.querySelector('#dashboard');
  const endpoint = window.CHECKOFF_DATA_URL || 'checkoffs.json';

  function validatePayload(data) {
    if (!data || typeof data !== 'object') throw new Error('The checkoff data is not an object.');
    if (![3, 4, 5].includes(data.schema_version)) throw new Error('The checkoff data uses an unsupported schema.');
    if (!data.student || typeof data.student.netid !== 'string') throw new Error('Student information is missing.');
    if (typeof data.worksheet !== 'string' || !data.worksheet) throw new Error('Worksheet information is missing.');
    if (!Array.isArray(data.standards) || data.standards.length === 0) throw new Error('No standards were provided.');
    const updatedAt = new Date(data.updated_at);
    if (Number.isNaN(updatedAt.getTime())) throw new Error('The update time is invalid.');
    for (const standard of data.standards) {
      if (!standard || typeof standard.id !== 'string' ||
          typeof standard.name !== 'string' || !Array.isArray(standard.checkmarks)) {
        throw new Error('A standard is malformed.');
      }
      for (const checkmark of standard.checkmarks) {
        if (!checkmark || !['green', 'purple', 'shiny_purple'].includes(checkmark.kind) || !allowedStatuses.has(checkmark.status) ||
            typeof checkmark.label !== 'string' || !Array.isArray(checkmark.requirements) ||
            checkmark.requirements.length === 0) {
          throw new Error(`A checkmark in ${standard.id} is malformed.`);
        }
        if (checkmark.kind === 'green') {
          const manual = checkmark.requirements.find(item => item && item.id === 'manual');
          const autograder = checkmark.requirements.find(item => item && item.id === 'autograder');
          const manualOnly = checkmark.requirements.length === 1 && manual && !autograder;
          const manualAndAutograder = checkmark.requirements.length === 2 && manual && autograder &&
            autograderStatuses.has(autograder.status);
          if ((!manualOnly && !manualAndAutograder) || !allowedStatuses.has(manual.status) ||
              !Array.isArray(manual.details)) {
            throw new Error(`The requirements in ${checkmark.label} are malformed.`);
          }
        } else {
          const score = checkmark.requirements[0];
          if (checkmark.requirements.length !== 1 || !score || score.id !== 'exam_score' ||
              score.source !== 'gradescope_exam' || score.status !== checkmark.status) {
            throw new Error(`The exam result in ${checkmark.label} is malformed.`);
          }
        }
      }
    }
    return updatedAt;
  }

  function make(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function autograderLabel(status) {
    return {
      passed: 'Passed',
      failed: 'Not passed yet',
      pending: 'Running',
      error: 'Autograder error',
      not_submitted: 'No submission',
      not_configured: 'Not connected yet',
      not_found: 'Student record not found'
    }[status];
  }

  function renderCombinedRequirements(requirements, body) {
    const list = make('ul', 'source-requirements');
    for (const requirement of requirements) {
      const row = make('li', `source-requirement ${requirement.id} ${requirement.status}`);
      const label = make('span', 'source-requirement-name', requirement.label);
      const text = requirement.id === 'manual'
        ? (requirement.status === 'complete' ? 'Complete' : 'Incomplete')
        : requirement.id === 'exam_score'
          ? ({ complete: 'Checkmark earned', incomplete: 'Below checkmark threshold', not_graded: 'Not available yet' }[requirement.status])
          : autograderLabel(requirement.status);
      row.append(label, make('strong', 'source-requirement-status', text));
      if (requirement.id === 'manual' && requirement.details.length > 1) {
        const details = document.createElement('details');
        details.className = 'requirements';
        details.append(make('summary', '', `${requirement.details.length} sheet entries`));
        const detailList = make('ul', 'requirement-list');
        for (const detail of requirement.details) {
          const detailStatus = detail.status === 'complete' ? 'Complete' : 'Incomplete';
          detailList.append(make('li', detail.status, `${detail.label}: ${detailStatus}`));
        }
        details.append(detailList);
        row.append(details);
      }
      list.append(row);
    }
    body.append(list);
  }

  function allocateStandard(checkmarks) {
    const priority = { purple: 0, shiny_purple: 1, green: 2 };
    const earned = checkmarks.filter(item => item.status === 'complete');
    const linked = [...earned].sort((a, b) => priority[a.kind] - priority[b.kind]).slice(0, 2);
    const shiny = earned.filter(item => item.kind === 'shiny_purple' && !linked.includes(item));
    return { earned, linked, shiny };
  }

  function allocationLabel(checkmark, allocation) {
    if (allocation.linked.includes(checkmark)) return 'Counts in standard-linked box';
    if (allocation.shiny.includes(checkmark)) return 'Counts in shiny pool (overflow)';
    return 'Extra checkmark — does not count toward grade';
  }

  function checkmarkKindLabel(kind) {
    return { green: 'Green', purple: 'Purple', shiny_purple: 'Shiny purple' }[kind];
  }

  function renderCompactCheckmark(checkmark, label) {
    const color = checkmarkKindLabel(checkmark.kind);
    const mark = make(
      'span', `checkmark ${checkmark.kind}`,
      checkmark.kind === 'shiny_purple' ? '✦' : '✓'
    );
    const description = `${color}: ${checkmark.label}. ${label}`;
    mark.title = description;
    mark.setAttribute('role', 'img');
    mark.setAttribute('aria-label', description);
    return mark;
  }

  function renderLinkedBoxes(allocation, compact = false) {
    const boxes = make('div', 'linked-boxes');
    if (!compact) boxes.append(make('strong', '', 'Standard-linked boxes'));
    for (let index = 0; index < 2; index += 1) {
      const linked = allocation.linked[index];
      const box = linked
        ? renderCompactCheckmark(linked, 'Counts in standard-linked box')
        : make('span', 'checkmark empty-box', '–');
      if (!linked) box.setAttribute('aria-label', 'Empty standard-linked box');
      if (!compact) {
        box.className = `linked-box ${linked ? linked.kind : 'empty-box'}`;
        box.textContent = linked ? checkmarkKindLabel(linked.kind) : 'Empty';
      }
      boxes.append(box);
    }
    return boxes;
  }

  function renderOverview(data, allocations) {
    const overview = document.querySelector('#checkmark-overview');
    const headings = make('div', 'overview-row overview-heading');
    headings.append(
      make('strong', '', 'Standard'),
      make('strong', '', 'Linked boxes'),
      make('strong', '', 'All earned checkmarks')
    );
    overview.append(headings);
    const pool = make('div', 'shiny-pool');
    let shinyCount = 0;
    for (const [index, standard] of data.standards.entries()) {
      const allocation = allocations[index];
      const row = make('div', 'overview-row');
      const link = make('a', '', standard.id);
      link.href = `#standard-${standard.id}`;
      const marks = make('div', 'compact-marks');
      for (const item of allocation.earned) {
        marks.append(renderCompactCheckmark(item, allocationLabel(item, allocation)));
      }
      if (allocation.earned.length === 0) marks.append(make('span', 'note', 'None yet'));
      row.append(link, renderLinkedBoxes(allocation, true), marks);
      overview.append(row);
      for (const item of allocation.shiny) {
        pool.append(renderCompactCheckmark(item, `${standard.id}: Counts in shiny pool (overflow)`));
        shinyCount += 1;
      }
    }
    pool.prepend(make('strong', '', `Shiny pool (overflow): ${shinyCount}`));
    if (shinyCount === 0) pool.append(make('span', 'note', 'No overflow yet'));
    overview.append(pool);
  }

  function renderCheckmark(checkmark, allocation) {
    const item = make('li', `mapped-checkoff ${checkmark.kind} ${checkmark.status}`);
    const earnedSymbol = checkmark.kind === 'shiny_purple' ? '✦' : '✓';
    const mark = make(
      'span', `checkmark ${checkmark.kind}`,
      checkmark.status === 'complete' ? earnedSymbol : '–'
    );
    mark.setAttribute('aria-hidden', 'true');
    const body = make('div', 'checkoff-body');
    body.append(make('strong', 'checkoff-name', checkmark.label));
    body.append(make(
      'span',
      'checkoff-status',
      checkmark.status === 'complete'
        ? `${checkmarkKindLabel(checkmark.kind)} checkmark earned`
        : checkmark.status === 'not_graded' ? 'Score not available yet' : 'Checkmark not earned'
    ));
    if (checkmark.status === 'complete') {
      body.append(make('span', 'checkoff-allocation', allocationLabel(checkmark, allocation)));
    }

    renderCombinedRequirements(checkmark.requirements, body);
    item.append(mark, body);
    return item;
  }

  function render(data, updatedAt) {
    document.querySelector('.summary-strip span').textContent = 'Checkmarks earned';
    document.querySelector('#dashboard-description').textContent =
      'Your lab checkoffs, autograder results, and available Exam 1 checkmarks, mapped to course standards.';
    document.querySelector('#completion-note').textContent =
      'Lab green checkmarks require the listed Lab sources. Lab 4 Q1 has no autograded component. Exam 1 scores over 0.8 earn their mapped purple or shiny-purple checkmark. Unavailable exam scores do not earn a mark.';
    document.querySelector('#student-netid').textContent = data.student.netid;
    document.querySelector('#worksheet').textContent = data.worksheet;
    const time = document.querySelector('#updated-at');
    time.dateTime = data.updated_at;
    time.textContent = updatedAt.toLocaleString(undefined, { timeZoneName: 'short' });

    let earned = 0;
    let available = 0;
    const allocations = data.standards.map(standard => allocateStandard(standard.checkmarks));
    renderOverview(data, allocations);
    const standards = document.querySelector('#standards');
    for (const [standardIndex, standard] of data.standards.entries()) {
      const allocation = allocations[standardIndex];
      const article = make('article', 'standard');
      article.id = `standard-${standard.id}`;
      article.append(make('p', 'standard-id', standard.id));
      article.append(make('h3', '', standard.name));
      article.append(renderLinkedBoxes(allocation));
      const overflow = make('div', 'shiny-pool');
      overflow.append(make('strong', '', `Shiny overflow: ${allocation.shiny.length}`));
      for (const item of allocation.shiny) {
        overflow.append(renderCompactCheckmark(item, 'Counts in shiny pool (overflow)'));
      }
      article.append(overflow);
      const list = make('ul', 'mapped-checkoffs');
      if (standard.checkmarks.length === 0) {
        list.append(make('li', 'empty', 'No mapped checkoff opportunities are in the sheet yet.'));
      } else {
        for (const checkmark of standard.checkmarks) list.append(renderCheckmark(checkmark, allocation));
      }
      article.append(list);
      standards.append(article);
      earned += allocation.earned.length;
      available += standard.checkmarks.length;
    }
    document.querySelector('#earned-total').textContent = `${earned} of ${available}`;
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
      statusElement.textContent = `Unable to load checkoffs. ${error.message} Please refresh or contact course staff.`;
      statusElement.classList.add('error');
    });
})();
