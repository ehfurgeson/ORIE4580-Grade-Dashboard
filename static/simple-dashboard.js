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
    if (![2, 3, 4].includes(data.schema_version)) throw new Error('The checkoff data uses an unsupported schema.');
    if (!data.student || typeof data.student.netid !== 'string') throw new Error('Student information is missing.');
    if (typeof data.worksheet !== 'string' || !data.worksheet) throw new Error('Worksheet information is missing.');
    if (!Array.isArray(data.standards) || data.standards.length === 0) throw new Error('No standards were provided.');
    const updatedAt = new Date(data.updated_at);
    if (Number.isNaN(updatedAt.getTime())) throw new Error('The update time is invalid.');
    for (const standard of data.standards) {
      if (!standard || typeof standard.key !== 'string' || typeof standard.id !== 'string' ||
          typeof standard.name !== 'string' || !Array.isArray(standard.checkmarks)) {
        throw new Error('A standard is malformed.');
      }
      for (const checkmark of standard.checkmarks) {
        if (!checkmark || !['green', 'purple', 'shiny_purple'].includes(checkmark.kind) || !allowedStatuses.has(checkmark.status) ||
            typeof checkmark.label !== 'string' || !Array.isArray(checkmark.requirements) ||
            checkmark.requirements.length === 0) {
          throw new Error(`A checkmark in ${standard.id} is malformed.`);
        }
        if (data.schema_version >= 3 && checkmark.kind === 'green') {
          const manual = checkmark.requirements.find(item => item && item.id === 'manual');
          const autograder = checkmark.requirements.find(item => item && item.id === 'autograder');
          if (checkmark.requirements.length !== 2 || !manual || !autograder ||
              !allowedStatuses.has(manual.status) || !autograderStatuses.has(autograder.status) ||
              !Array.isArray(manual.details)) {
            throw new Error(`The requirements in ${checkmark.label} are malformed.`);
          }
        } else if (data.schema_version === 4) {
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

  function renderManualOnlyRequirements(requirements, body) {
    if (requirements.length <= 1) return;
    const details = document.createElement('details');
    details.className = 'requirements';
    details.append(make('summary', '', `${requirements.length} recorded requirements`));
    const list = make('ul', 'requirement-list');
    for (const requirement of requirements) {
      const label = requirement.status === 'complete' ? 'Complete' : 'Incomplete';
      list.append(make('li', requirement.status, `${requirement.label}: ${label}`));
    }
    details.append(list);
    body.append(details);
  }

  function renderCheckmark(checkmark) {
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
        ? `${checkmark.kind === 'green' ? 'Green' : checkmark.kind === 'purple' ? 'Purple' : 'Shiny purple'} checkmark earned`
        : checkmark.status === 'not_graded' ? 'Score not available yet' : 'Checkmark not earned'
    ));

    if (checkmark.requirements.some(item => item && item.source)) {
      renderCombinedRequirements(checkmark.requirements, body);
    } else {
      renderManualOnlyRequirements(checkmark.requirements, body);
    }
    item.append(mark, body);
    return item;
  }

  function render(data, updatedAt) {
    if (data.schema_version >= 3) {
      document.querySelector('#dashboard-description').textContent =
        data.schema_version === 4
          ? 'Your lab checkoffs, autograder results, and available Exam 1 checkmarks, mapped to course standards.'
          : 'Your manual lab checkoffs and Gradescope autograder results, mapped to the standards they demonstrate.';
      document.querySelector('#completion-note').textContent =
        data.schema_version === 4
          ? 'Lab green checkmarks require both Lab sources. Exam 1 scores over 0.8 earn their mapped purple or shiny-purple checkmark. Unavailable exam scores do not earn a mark.'
          : 'A lab green checkmark is earned only when both its manual checkoff and Gradescope autograder requirement are complete. Each standard has two linked boxes; future purple and shiny purple marks take priority under the syllabus rules.';
    }
    document.querySelector('#student-netid').textContent = data.student.netid;
    document.querySelector('#worksheet').textContent = data.worksheet;
    const time = document.querySelector('#updated-at');
    time.dateTime = data.updated_at;
    time.textContent = updatedAt.toLocaleString(undefined, { timeZoneName: 'short' });

    let earned = 0;
    let available = 0;
    const standards = document.querySelector('#standards');
    for (const standard of data.standards) {
      const article = make('article', 'standard');
      article.append(make('p', 'standard-id', standard.id));
      article.append(make('h3', '', standard.name));
      const linkedBoxes = make('div', 'linked-boxes');
      linkedBoxes.append(make('strong', '', 'Standard-linked boxes'));
      const priority = { purple: 0, shiny_purple: 1, green: 2 };
      const completed = standard.checkmarks
        .map((item, index) => ({ item, index }))
        .filter(entry => entry.item.status === 'complete')
        .sort((a, b) => priority[a.item.kind] - priority[b.item.kind] || a.index - b.index)
        .slice(0, 2)
        .map(entry => entry.item);
      for (let index = 0; index < 2; index += 1) {
        const linked = completed[index];
        const label = linked
          ? linked.kind === 'shiny_purple' ? 'Shiny purple' : linked.kind[0].toUpperCase() + linked.kind.slice(1)
          : 'Empty';
        linkedBoxes.append(make(
          'span',
          `linked-box ${linked ? linked.kind : 'empty-box'}`,
          label
        ));
      }
      article.append(linkedBoxes);
      const list = make('ul', 'mapped-checkoffs');
      if (standard.checkmarks.length === 0) {
        list.append(make('li', 'empty', 'No mapped checkoff opportunities are in the sheet yet.'));
      } else {
        for (const checkmark of standard.checkmarks) list.append(renderCheckmark(checkmark));
      }
      article.append(list);
      standards.append(article);
      earned += standard.checkmarks.filter(item => item.status === 'complete').length;
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
