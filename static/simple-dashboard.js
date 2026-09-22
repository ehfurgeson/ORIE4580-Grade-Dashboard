(() => {
  'use strict';

  const allowedStatuses = new Set(['complete', 'incomplete']);
  const statusElement = document.querySelector('#status');
  const dashboard = document.querySelector('#dashboard');
  const endpoint = window.CHECKOFF_DATA_URL || 'checkoffs.json';

  function validatePayload(data) {
    if (!data || typeof data !== 'object') throw new Error('The checkoff data is not an object.');
    if (data.schema_version !== 2) throw new Error('The checkoff data uses an unsupported schema.');
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
        if (!checkmark || checkmark.kind !== 'green' || !allowedStatuses.has(checkmark.status) ||
            typeof checkmark.label !== 'string' || !Array.isArray(checkmark.requirements) ||
            checkmark.requirements.length === 0) {
          throw new Error(`A checkmark in ${standard.id} is malformed.`);
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

  function renderCheckmark(checkmark) {
    const item = make('li', `mapped-checkoff ${checkmark.status}`);
    const mark = make('span', 'checkmark green', checkmark.status === 'complete' ? '✓' : '–');
    mark.setAttribute('aria-hidden', 'true');
    const body = make('div', 'checkoff-body');
    body.append(make('strong', 'checkoff-name', checkmark.label));
    body.append(make(
      'span',
      'checkoff-status',
      checkmark.status === 'complete' ? 'Green checkmark earned' : 'Not yet earned'
    ));

    if (checkmark.requirements.length > 1) {
      const details = document.createElement('details');
      details.className = 'requirements';
      details.append(make('summary', '', `${checkmark.requirements.length} recorded requirements`));
      const list = make('ul', 'requirement-list');
      for (const requirement of checkmark.requirements) {
        const label = requirement.status === 'complete' ? 'Complete' : 'Incomplete';
        list.append(make('li', requirement.status, `${requirement.label}: ${label}`));
      }
      details.append(list);
      body.append(details);
    }
    item.append(mark, body);
    return item;
  }

  function render(data, updatedAt) {
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
      const completed = standard.checkmarks.filter(item => item.status === 'complete').slice(0, 2);
      for (let index = 0; index < 2; index += 1) {
        linkedBoxes.append(make(
          'span',
          `linked-box ${completed[index] ? 'green' : 'empty-box'}`,
          completed[index] ? 'Green' : 'Empty'
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
