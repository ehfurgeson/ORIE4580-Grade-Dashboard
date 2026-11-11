/* Shared Exam 3 renderer and dashboard adapter. Student files stay in their protected directory. */
(() => {
  'use strict';
  const make = (tag, text) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const labels = {met: 'Correct', not_met: 'Incorrect', blank: 'Blank', not_checked: 'Not checked'};
  const summaryOrder = {
    '7.1': ['locations-histogram', 'locations-cdf', 'counts-histogram', 'counts-cdf'],
    '7.2': ['poisson-0.5-histogram', 'poisson-0.5-cdf', 'poisson-3-histogram', 'poisson-3-cdf'],
  };
  function summaryPlots(part) {
    const plots = part.plots || [];
    const order = summaryOrder[part.label];
    return order ? order.map(id => plots.find(plot => plot.id === id)).filter(Boolean) :
      plots.filter(plot => ['cdf', 'histogram'].includes(plot.kind));
  }
  function plotFigure(plot, zoomable = true) {
    const histogram = plot.kind === 'histogram';
    const discrete = plot.discrete === true;
    const title = (plot.title || 'Sample distribution').replace(/\s*·\s*(CDF|Histogram)$/i, '');
    const figure = make('figure');
    figure.append(make('figcaption', `${title} · ${histogram ? 'Histogram' : 'CDF'}`));
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    const draw = (tag, attributes, text) => {
      const node = document.createElementNS(ns, tag);
      for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
      if (text !== undefined) node.textContent = text;
      svg.append(node); return node;
    };
    svg.setAttribute('viewBox', '0 0 600 360');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', `${title}: ${histogram ? 'histogram' : 'cumulative distribution'}, sampled versus expected`);
    svg.setAttribute('font-family', 'system-ui, sans-serif');
    svg.setAttribute('font-size', '13');
    const expected = plot.expected || [];
    const observed = histogram ? plot.density.map((v, i) => [plot.edges[i], v]) : plot.observed;
    const points = [...observed, ...expected];
    if (!points.length || points.some(p => p.length !== 2 || !p.every(Number.isFinite))) throw new Error('Invalid plot data.');
    const low = histogram ? plot.edges[0] : (plot.domain?.[0] ?? Math.min(...points.map(p => p[0])));
    const high = histogram ? plot.edges.at(-1) : (plot.domain?.[1] ?? Math.max(...points.map(p => p[0])));
    const top = histogram ? Math.max(1e-10, ...points.map(p => p[1])) * 1.12 : 1;
    const left = 72, right = 578, bottom = 276, upper = 34;
    const x = v => left + (v - low) / (high - low || 1) * (right - left);
    const y = v => bottom - v / top * (bottom - upper);
    const fmt = v => Number(v.toPrecision(3)).toString();
    draw('rect', {width: 600, height: 360, fill: '#fff'});
    for (let i = 0; i <= 4; i++) {
      const value = top * i / 4;
      draw('path', {d: `M${left},${y(value)}H${right}`, stroke: '#e4e9ef'});
      draw('text', {x: left - 10, y: y(value) + 4, 'text-anchor': 'end', fill: '#354456'}, fmt(value));
    }
    const ticks = [...new Set(Array.from({length: 5}, (_, i) => {
      const value = low + (high - low) * i / 4;
      return discrete ? Math.round(value) : value;
    }))].filter(v => v >= low && v <= high);
    for (const value of ticks) {
      draw('path', {d: `M${x(value)},${bottom}v5`, stroke: '#354456'});
      draw('text', {x: x(value), y: bottom + 22, 'text-anchor': 'middle', fill: '#354456'}, fmt(value));
    }
    draw('path', {d: `M${left},${upper}V${bottom}H${right}`, fill: 'none', stroke: '#354456'});
    draw('text', {x: left, y: 19, fill: '#354456'}, histogram ? (discrete ? 'Probability per integer bin' : 'Probability density') : 'Cumulative probability · P(X ≤ x)');
    draw('text', {x: (left + right) / 2, y: 318, 'text-anchor': 'middle', fill: '#354456'}, plot.x_label || 'Sample value');
    const path = (values, steps) => values.map(([a, b], i) => i ?
      (steps ? `H${x(a)} V${y(b)}` : `L${x(a)},${y(b)}`) : `M${x(a)},${y(b)}`).join(' ');
    if (histogram) {
      plot.density.forEach((height, i) => draw('rect', {
        x: x(plot.edges[i]), y: y(height), width: x(plot.edges[i + 1]) - x(plot.edges[i]),
        height: bottom - y(height), fill: '#2666b5', 'fill-opacity': '.6', stroke: '#fff', 'stroke-width': '.5'}));
    }
    let reference = path(expected, discrete);
    if (histogram && discrete && expected.length === plot.density.length) {
      reference = expected.map(([, height], i) => `${i ? 'V' + y(height) : 'M' + x(plot.edges[0]) + ',' + y(height)}H${x(plot.edges[i + 1])}`).join(' ');
    }
    draw('path', {d: reference, fill: 'none', stroke: '#d07822', 'stroke-width': 2.5, 'stroke-dasharray': histogram ? 'none' : '7 4'});
    if (!histogram) draw('path', {d: path(observed, true), fill: 'none', stroke: '#2666b5', 'stroke-width': 2});
    draw('path', {d: 'M150,343H180', stroke: '#2666b5', 'stroke-width': histogram ? 10 : 2, 'stroke-opacity': histogram ? .6 : 1});
    draw('text', {x: 188, y: 347, fill: '#354456'}, 'Sampled');
    draw('path', {d: 'M320,343H350', stroke: '#d07822', 'stroke-width': 2.5, 'stroke-dasharray': histogram ? 'none' : '7 4'});
    draw('text', {x: 358, y: 347, fill: '#354456'}, plot.expected_label || 'Expected');
    if (zoomable) {
      const button = styled('button', 'plot-button'); button.type = 'button';
      button.setAttribute('aria-label', `Enlarge ${title}`);
      button.append(svg); button.addEventListener('click', () => showZoom(plotFigure(plot, false)));
      figure.append(button);
    } else figure.append(svg);
    if (Number.isInteger(plot.sample_count)) figure.append(make('p', `${plot.sample_count.toLocaleString()} samples` +
      (plot.outside_count ? ` · ${plot.outside_count.toLocaleString()} outside the plotted range` : '')));
    return figure;
  }
  function styled(tag, className, text) {
    const node = make(tag, text); node.className = className; return node;
  }
  function earnedKind(question) {
    if (question.normal_credit !== 'met') return null;
    return question.credit_kind === 'shiny_purple' || question.id === 'q9' || question.shiny_credit === 'met' ? 'shiny_purple' : 'purple';
  }
  function mark(question, large = false) {
    const kind = earnedKind(question);
    const node = styled('span', kind ? `checkmark ${kind} earned` : 'checkmark empty-box', kind === 'shiny_purple' ? '✦' : kind ? '✓' : '–');
    node.setAttribute('role', 'img');
    node.setAttribute('aria-label', kind === 'shiny_purple' ? 'Shiny purple checkmark earned' : kind ? 'Purple checkmark earned' : labels[question.normal_credit]);
    return node;
  }
  function pdfButton(url, label, page = null) {
    const link = styled('a', 'review-button', label);
    link.href = page ? `${url}#page=${page}` : url;
    link.target = '_blank'; link.rel = 'noopener'; return link;
  }
  function showZoom(content, pdfLink = null) {
    const dialog = styled('dialog', 'scan-dialog');
    const close = styled('button', 'review-button', 'Close'); close.type = 'button';
    close.autofocus = true;
    close.addEventListener('click', () => dialog.close());
    const tools = styled('div', 'scan-tools');
    if (pdfLink) tools.append(pdfLink);
    tools.append(close); dialog.append(tools, content); document.body.append(dialog);
    dialog.addEventListener('close', () => dialog.remove());
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
    dialog.showModal();
  }
  function scanFigure(image, pdfUrl) {
    const figure = styled('figure', 'scan');
    // Student JSON never gets to request a remote URL or inject SVG/HTML.
    if (!/^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(image.src || '')) {
      figure.append(styled('p', 'review-message', 'Scan image unavailable.')); return figure;
    }
    const img = make('img'); img.src = image.src; img.alt = `Original scanned answer ${image.label}`; img.loading = 'lazy';
    const button = styled('button', 'scan-button'); button.type = 'button';
    button.setAttribute('aria-label', `Enlarge scanned answer ${image.label}`);
    button.append(img);
    button.addEventListener('click', () => {
      const full = make('img'); full.src = image.src; full.alt = img.alt;
      const link = pdfUrl && Number.isInteger(image.page) && image.page > 0 ? pdfButton(pdfUrl, 'Open PDF', image.page) : null;
      showZoom(full, link);
    });
    figure.append(button); return figure;
  }
  function answerPair(text, images, label, pdfUrl, outcome) {
    const pair = styled('div', `answer-pair ${label ? 'math-pair' : 'code-pair'}`);
    const parsed = styled('div', 'answer-column');
    if (label && label !== 'Answer') {
      const partLabel = styled('div', 'answer-label');
      partLabel.append(styled('span', 'answer-number', label));
      if (Object.hasOwn(labels, outcome)) partLabel.append(styled('span', `outcome ${outcome}`, labels[outcome]));
      parsed.append(partLabel);
    }
    parsed.append(styled('pre', 'answer-text', text));
    const scans = styled('div', 'answer-column');
    if (!images.length) scans.append(styled('p', 'review-message', 'No scan included in this export.'));
    images.forEach(image => scans.append(scanFigure(image, pdfUrl)));
    pair.append(parsed, scans); return pair;
  }

  function render(data, root = document.querySelector('#review'), prefix = '', pdfUrl = null) {
    if (data.schema_version !== 1 || data.exam !== 3 || !Array.isArray(data.questions)) throw new Error('Expected an Exam 3 student export (version 1).');
    const fragment = document.createDocumentFragment();
    const nav = styled('nav', 'exam-nav'); nav.setAttribute('aria-label', 'Exam questions');
    const questions = [...data.questions].sort((a, b) => Number(a.id.slice(1)) - Number(b.id.slice(1)));
    for (const question of questions) {
      if (!/^q[1-9]$/.test(question.id)) throw new Error('Invalid question identifier.');
      const link = make('a'); link.href = `#${prefix}${question.id}`;
      link.addEventListener('click', () => openQuestion(root, question.id, prefix));
      link.append(make('span', question.id.toUpperCase()), mark(question)); nav.append(link);
    }
    fragment.append(nav);
    if (pdfUrl) { const tools = styled('div', 'review-tools'); tools.append(pdfButton(pdfUrl, 'Open exam PDF')); fragment.append(tools); }
    for (const question of questions) {
      const section = styled('details', 'exam-question'); section.id = prefix + question.id;
      section.open = false;
      const body = styled('div', 'question-body');
      const heading = styled('summary', 'question-heading'), award = styled('div', 'question-award');
      award.append(styled('span', 'standard-id', question.standard || 'Exam 3'), mark(question, true));
      const title = styled('div', 'question-title');
      const line = styled('div', 'question-title-line'); line.append(make('h2', `${question.id.toUpperCase()} · ${question.title}`));
      const badges = styled('div', 'question-statuses');
      badges.append(styled('span', `outcome ${question.normal_credit}`, `${question.shiny_credit != null ? 'Main part: ' : ''}${labels[question.normal_credit] || 'Not checked'}`));
      if (question.shiny_credit != null) badges.append(styled('span', `outcome ${question.shiny_credit}`, `Shiny part: ${labels[question.shiny_credit] || 'Not checked'}`));
      const toggle = styled('span', 'question-toggle');
      toggle.append(styled('span', 'when-closed', '▸ Show details'), styled('span', 'when-open', '▾ Hide details'));
      line.append(badges); title.append(line, toggle); heading.append(award, title); section.append(heading);
      const images = question.images || [], used = new Set(), mathLabels = new Set();
      for (const answer of question.answers) {
        let fields = null;
        if (answer.format === 'json') {
          try { const value = JSON.parse(answer.text); fields = value.answers || value; } catch { /* Keep exact text if it isn't JSON. */ }
        }
        if (fields && typeof fields === 'object' && !Array.isArray(fields)) {
          for (const [label, value] of Object.entries(fields)) {
            mathLabels.add(label);
            const matches = images.filter(image => image.label === label); matches.forEach(image => used.add(image));
            body.append(answerPair(value === null ? '' : typeof value === 'string' ? value : JSON.stringify(value, null, 2), matches, label, pdfUrl, question.parts.find(part => part.label === label)?.outcome));
          }
        } else {
          images.forEach(image => used.add(image));
          body.append(answerPair(answer.text, images, answer.format === 'json' ? 'Answer' : null, pdfUrl));
        }
      }
      for (const image of images.filter(image => !used.has(image))) body.append(scanFigure(image, pdfUrl));
      const summaries = styled('div', question.id === 'q7' ? 'process-summary' : '');
      for (const part of question.parts) {
        const selectedPlots = summaryPlots(part);
        const oldSummary = summaryOrder[part.label] && part.plots?.some(plot => !plot.id);
        const hasOutcome = Object.hasOwn(labels, part.outcome);
        if (!selectedPlots.length && !part.message && !oldSummary && (!hasOutcome || mathLabels.has(part.label))) continue;
        const evidence = styled('div', 'review-evidence');
        const partHeading = styled('div', 'part-heading');
        partHeading.append(styled('h3', 'evidence-heading', `Q${part.label}${question.answers.some(answer => answer.format === 'pseudocode') ? ' · Code output' : ''}`));
        if (hasOutcome) partHeading.append(styled('span', `outcome ${part.outcome}`, labels[part.outcome]));
        evidence.append(partHeading);
        const plots = styled('div', 'plot-grid'); selectedPlots.forEach(plot => plots.append(plotFigure(plot)));
        evidence.append(plots);
        if (oldSummary) evidence.append(styled('p', 'review-message', 'Plot summary needs a fresh export from the updated Examiner.'));
        if (part.message) evidence.append(styled('p', 'review-message', part.message));
        summaries.append(evidence);
      }
      body.append(summaries);
      section.append(body);
      fragment.append(section);
    }
    root.replaceChildren(fragment);
  }
  function openQuestion(root, id, prefix = '') {
    if (!root) return;
    const outer = root.closest('details'); if (outer) outer.open = true;
    const question = root.querySelector(`#${prefix}${id}`); if (question) question.open = true;
  }
  const standards = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S6', 'S7', 'S7'];
  function validate(data) {
    if (!data || data.schema_version !== 1 || data.exam !== 3 || !Array.isArray(data.questions)) throw new Error('Expected an Exam 3 student export (version 1).');
    const seen = new Set();
    for (const question of data.questions) {
      if (!/^q[1-9]$/.test(question.id) || seen.has(question.id) || typeof question.title !== 'string' ||
          !Object.hasOwn(labels, question.normal_credit) || (question.shiny_credit != null && !Object.hasOwn(labels, question.shiny_credit)) ||
          !Array.isArray(question.answers) || !Array.isArray(question.parts) ||
          (question.credit_kind != null && !['purple', 'shiny_purple'].includes(question.credit_kind)) ||
          question.answers.some(answer => typeof answer.text !== 'string') ||
          (question.standard != null && question.standard !== standards[Number(question.id.slice(1)) - 1])) throw new Error('Invalid Exam 3 question.');
      seen.add(question.id);
    }
    return data;
  }
  async function load(url = 'exam3.json') {
    const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}});
    // The publication switch denies these files with 403 while Exam 3 is hidden.
    if (response.status === 403 || response.status === 404) return null;
    if (!response.ok) throw new Error('Exam 3 unavailable.');
    return validate(await response.json());
  }
  function merge(record, exam) {
    if (!exam) return record;
    validate(exam);
    const questions = new Map(exam.questions.map(question => [question.id, question]));
    return {...record, standards: record.standards.map(standard => {
      const marks = standard.checkmarks.filter(mark => !/^exam3-q/.test(mark.id || ''));
      standards.forEach((standardId, index) => {
        if (standardId !== standard.id) return;
        const id = `q${index + 1}`, question = questions.get(id);
        const outcome = question?.normal_credit || 'not_checked';
        const status = outcome === 'met' ? 'complete' : outcome === 'not_checked' ? 'not_graded' : 'incomplete';
        const kind = question ? (earnedKind(question) || question.credit_kind || (id === 'q9' ? 'shiny_purple' : 'purple')) : id === 'q9' ? 'shiny_purple' : 'purple';
        marks.push({id: `exam3-${id}`, label: `Exam 3 · Question ${index + 1}`, kind, status,
          requirements: [{id: 'exam_score', source: 'examiner', label: 'Exam 3', status, outcome}]});
      });
      return {...standard, checkmarks: marks};
    })};
  }
  window.Exam3Review = {render, load, merge, validate, openQuestion};
  const page = document.querySelector('#exam3-page');
  if (page) {
    Promise.all([load(page.dataset?.source || 'exam3.json'), fetch(page.dataset?.checkoffs || 'checkoffs.json', {credentials: 'same-origin', cache: 'no-store'})
      .then(response => { if (!response.ok) throw new Error('Unable to load student details.'); return response.json(); })])
      .then(([exam, checkoffs]) => {
        const status = document.querySelector('#status');
        document.querySelector('#student-netid').textContent = checkoffs.student.netid;
        const time = document.querySelector('#updated-at');
        const timestamp = exam?.exported_at || checkoffs.updated_at;
        time.dateTime = timestamp; time.textContent = new Date(timestamp).toLocaleString(undefined, {timeZoneName: 'short'});
        if (!exam) { status.textContent = 'Exam 3 is not available yet.'; return; }
        const root = document.querySelector('#review');
        render(exam, root, '', page.dataset?.pdf || 'exam3.pdf'); status.textContent = '';
        if (/^#q[1-9]$/.test(location.hash)) {
          openQuestion(root, location.hash.slice(1));
          root.querySelector(location.hash)?.scrollIntoView();
        }
      }).catch(() => { document.querySelector('#status').textContent = 'Unable to load Exam 3. Please refresh.'; });
    return;
  }
  const fileInput = document.querySelector('#file');
  if (!fileInput) return;
  let selection = 0;
  fileInput.addEventListener('change', async event => {
    const revision = ++selection;
    const status = document.querySelector('#status');
    document.querySelector('#review').replaceChildren();
    try {
      const file = event.target.files[0]; if (!file) return;
      const text = await file.text();
      if (revision !== selection) return;
      render(validate(JSON.parse(text))); status.textContent = '';
    } catch (error) { if (revision === selection) status.textContent = error.message; }
  });
})();
