(() => {
  'use strict';

  const allowedStatuses = new Set(['complete', 'incomplete']);
  const statusElement = document.querySelector('#status');
  const dashboard = document.querySelector('#dashboard');
  const endpoint = window.CHECKOFF_DATA_URL || 'checkoffs.json';

  function validatePayload(data) {
    if (!data || typeof data !== 'object') throw new Error('The checkoff data is not an object.');
    if (!data.student || typeof data.student.netid !== 'string') throw new Error('Student information is missing.');
    if (typeof data.worksheet !== 'string' || !data.worksheet) throw new Error('Worksheet information is missing.');
    if (!Array.isArray(data.items) || data.items.length === 0) throw new Error('No checkoffs were provided.');
    const updatedAt = new Date(data.updated_at);
    if (Number.isNaN(updatedAt.getTime())) throw new Error('The update time is invalid.');
    for (const item of data.items) {
      if (!item || typeof item.name !== 'string' || !allowedStatuses.has(item.status)) {
        throw new Error('A checkoff entry is malformed.');
      }
    }
    return updatedAt;
  }

  function render(data, updatedAt) {
    document.querySelector('#student-netid').textContent = data.student.netid;
    document.querySelector('#worksheet').textContent = data.worksheet;
    const time = document.querySelector('#updated-at');
    time.dateTime = data.updated_at;
    time.textContent = updatedAt.toLocaleString(undefined, { timeZoneName: 'short' });

    const list = document.querySelector('#checkoffs');
    for (const item of data.items) {
      const row = document.createElement('li');
      row.className = `simple-checkoff ${item.status}`;
      const name = document.createElement('span');
      name.className = 'checkoff-name';
      name.textContent = item.name;
      const result = document.createElement('span');
      result.className = 'checkoff-status';
      result.textContent = item.status === 'complete' ? 'Complete' : 'Incomplete';
      row.append(name, result);
      list.append(row);
    }
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
