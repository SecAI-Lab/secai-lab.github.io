const { DateTime } = luxon;

const _now = DateTime.now().setZone('Asia/Seoul');
const _fromYear = _now.year - 2;
const _toYear = _now.year + 1;

const CONFIG = {
  displayZone: 'Asia/Seoul',
  includeFromYear: _fromYear,
  includeToYear: _toYear,
  sourceUrls: [
    { name: 'manual', kind: 'yaml', url: 'data/manual.yml', priority: 0 },
    ...Array.from({ length: _toYear - _fromYear + 1 }, (_, i) => _fromYear + i).flatMap(year =>
      ['system', 'software', 'security', 'ai'].map(cat => ({
        name: `${year}/${cat}`,
        kind: 'yaml',
        url: `data/conferences/${year}/${cat}.yml`,
        priority: 1
      }))
    )
  ]
};

const TARGETS = [
  { key: 'OSDI', category: 'system', aliases: ['OSDI'] },
  { key: 'SOSP', category: 'system', aliases: ['SOSP'] },
  { key: 'EuroSys', category: 'system', aliases: ['EuroSys'] },
  { key: 'ATC', category: 'system', aliases: ['ATC', 'USENIX ATC'] },
  { key: 'NSDI', category: 'system', aliases: ['NSDI'] },
  { key: 'DSN', category: 'system', aliases: ['DSN', 'Dependable Systems and Networks'] },

  { key: 'ICSE', category: 'software', aliases: ['ICSE'] },
  { key: 'FSE', category: 'software', aliases: ['FSE', 'ESEC/FSE', 'Foundations of Software Engineering'] },
  { key: 'ASE', category: 'software', aliases: ['ASE', 'Automated Software Engineering'] },
  { key: 'ISSTA', category: 'software', aliases: ['ISSTA'] },

  { key: 'IJCAI', category: 'ai', aliases: ['IJCAI', 'IJCAI-ECAI'] },
  { key: 'AAAI', category: 'ai', aliases: ['AAAI'] },
  { key: 'WWW', category: 'ai', aliases: ['WWW', 'The Web Conference', 'World Wide Web'] },

  { key: 'S&P', category: 'security', aliases: ['S&P', 'S&P (Oakland)', 'Oakland', 'IEEE Symposium on Security and Privacy'] },
  { key: 'CCS', category: 'security', aliases: ['CCS', 'Computer and Communications Security'] },
  { key: 'USENIX Security', category: 'security', aliases: ['USENIX Security', 'USENIX Security Symposium'] },
  { key: 'NDSS', category: 'security', aliases: ['NDSS', 'Network and Distributed System Security'] },
  { key: 'ACSAC', category: 'security', aliases: ['ACSAC', 'Annual Computer Security Applications Conference'] },
  { key: 'RAID', category: 'security', aliases: ['RAID', 'Research in Attacks, Intrusions and Defenses'] },
  { key: 'ASIACCS', category: 'security', aliases: ['ASIACCS', 'Asia CCS', 'AsiaCCS', 'ASIA CCS'] },
  { key: 'ESORICS', category: 'security', aliases: ['ESORICS', 'European Symposium on Research in Computer Security'] },
  { key: 'EuroS&P', category: 'security', aliases: ['Euro S&P', 'EuroS&P', 'EuroSP', 'European Symposium on Security and Privacy'] },
  { key: 'CODASPY', category: 'security', aliases: ['CODASPY', 'Data and Application Security and Privacy'] },
  { key: 'DIMVA', category: 'security', aliases: ['DIMVA', 'Detection of Intrusions and Malware'] },
  { key: 'SecureComm', category: 'security', aliases: ['SecureComm', 'Security and Privacy in Communication Networks'] },
  { key: 'SAC', category: 'security', aliases: ['SAC', 'Symposium on Applied Computing'] },
  { key: 'IFIP-Sec', category: 'security', aliases: ['IFIP SEC', 'IFIP-Sec', 'IFIP Sec'] },
  { key: 'ACNS', category: 'security', aliases: ['ACNS', 'Applied Cryptography and Network Security'] },

  { key: 'WOOT', category: 'security', workshop: true, aliases: ['WOOT', 'Workshop on Offensive Technologies', 'USENIX WOOT Conference on Offensive Technologies'] },
  { key: 'BAR', category: 'security', workshop: true, aliases: ['BAR', 'Workshop on Binary Analysis Research'] },
  { key: 'AISec', category: 'security', workshop: true, aliases: ['AISec', 'Workshop on Artificial Intelligence and Security'] },
  { key: 'CCS-LAMPS', category: 'security', workshop: true, aliases: ['CCS-LAMPS', 'Workshop on Large AI Systems and Models with Privacy and Safety Analysis'] },
  { key: 'EuroSec', category: 'system', workshop: true, aliases: ['EuroSec', 'European Workshop on Systems Security'] },
  { key: 'DFRWS EU', category: 'security', workshop: true, aliases: ['DFRWS EU', 'Digital Forensics Research Conference Europe'] },
  { key: 'DFRWS US', category: 'security', workshop: true, aliases: ['DFRWS US', 'Digital Forensics Research Conference'] },
  { key: 'DFRWS APAC', category: 'security', workshop: true, aliases: ['DFRWS APAC'] }
];

const CATEGORY_ORDER = ['system', 'software', 'security', 'ai'];

const NAME_HIGHLIGHT_CONFS = new Set(['S&P', 'CCS', 'USENIX Security', 'NDSS', 'ICSE', 'FSE']);

function groupBy(items, keyFn) {
  const m = new Map();
  for (const item of items) {
    const key = keyFn(item);
    if (!m.has(key)) m.set(key, []);
    m.get(key).push(item);
  }
  return m;
}

const CATEGORY_LABELS = { system: 'System', software: 'SE', security: 'Security', ai: 'AI / Web' };

function cleanName(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function matchTarget(record) {
  const title = cleanName(record.title || record.name || record.conference);
  const ht = title.toLowerCase();
  for (const target of TARGETS) {
    for (const alias of target.aliases) {
      const a = alias.toLowerCase();
      if (ht === a || ht.startsWith(`${a} `) || ht.includes(` ${a} `) || ht.endsWith(` ${a}`)) {
        return target;
      }
    }
  }
  return null;
}

function normalizeArray(value) {
  if (value === undefined || value === null || value === '') return [];
  return Array.isArray(value) ? value : [value];
}

function parseZoneDeadline(value, timezone) {
  if (!value || String(value).toUpperCase() === 'TBA') return null;
  const raw = String(value).trim();
  const iso = raw.replace(' ', 'T');
  const tz = String(timezone || 'UTC-12').trim();

  if (/^(AoE|UTC-12)$/i.test(tz)) {
    return DateTime.fromISO(`${iso}-12:00`, { setZone: true }).setZone(CONFIG.displayZone);
  }
  const utcOffset = tz.match(/^UTC([+-])(\d{1,2})(?::?(\d{2}))?$/i);
  if (utcOffset) {
    const sign = utcOffset[1];
    const hh = utcOffset[2].padStart(2, '0');
    const mm = (utcOffset[3] || '00').padStart(2, '0');
    return DateTime.fromISO(`${iso}${sign}${hh}:${mm}`, { setZone: true }).setZone(CONFIG.displayZone);
  }
  if (/^(PST|PDT)$/i.test(tz)) {
    const offset = tz.toUpperCase() === 'PST' ? '-08:00' : '-07:00';
    return DateTime.fromISO(`${iso}${offset}`, { setZone: true }).setZone(CONFIG.displayZone);
  }
  const parsed = DateTime.fromISO(iso, { zone: tz });
  if (parsed.isValid) return parsed.setZone(CONFIG.displayZone);
  return DateTime.fromISO(`${iso}-12:00`, { setZone: true }).setZone(CONFIG.displayZone);
}

function deriveAbstractFromComment(paperDeadline, comment) {
  if (!paperDeadline || !comment) return null;
  if (/abstract.*1 week before|1 week before.*abstract/i.test(comment)) {
    return paperDeadline.minus({ days: 7 });
  }
  return null;
}

function expandRecord(record, source) {
  const target = matchTarget(record);
  if (!target) return [];
  const year = Number(record.year);
  if (!year || year < CONFIG.includeFromYear || year > CONFIG.includeToYear) return [];

  const paperDeadlines = normalizeArray(record.deadline);
  const abstractDeadlines = normalizeArray(record.abstract_deadline);
  const rows = [];

  const maxLen = Math.max(paperDeadlines.length, abstractDeadlines.length, 1);
  for (let i = 0; i < maxLen; i++) {
    const paperRaw = paperDeadlines[i] || paperDeadlines[0] || null;
    const absRaw = abstractDeadlines[i] || null;
    const paper = parseZoneDeadline(paperRaw, record.timezone);
    let abstract = parseZoneDeadline(absRaw, record.timezone);
    if (!abstract) abstract = deriveAbstractFromComment(paper, record.comment || record.note);
    const effective = abstract || paper;
    rows.push({
      key: target.key,
      canonicalName: target.key,
      originalTitle: cleanName(record.title || record.name || record.conference || target.key),
      fullName: cleanName(record.full_name || record.description || ''),
      category: target.category,
      year,
      abstractRaw: absRaw || (abstract ? 'derived: paper - 7 days' : ''),
      paperRaw: paperRaw || '',
      abstractDt: abstract,
      paperDt: paper,
      effectiveDt: effective,
      timezone: record.timezone || 'UTC-12',
      place: cleanName(record.place || ''),
      date: cleanName(record.date || ''),
      start: record.start || '',
      end: record.end || '',
      link: record.link || '',
      note: cleanName(record.note || record.comment || ''),
      source: source.name,
      sourceUrl: source.url,
      priority: source.priority,
      id: cleanName(record.id || `${target.key.toLowerCase()}-${year}-${i}`),
      cycle: paperDeadlines.length > 1 ? `cycle ${i + 1}` : '',
      isWorkshop: Boolean(target.workshop),
      tier: String(record.tier || '')
    });
  }
  return rows;
}

async function fetchSource(source) {
  const res = await fetch(source.url, { cache: 'no-store' });
  if (res.status === 404) return [];
  if (!res.ok) throw new Error(`${source.name}: HTTP ${res.status}`);
  const text = await res.text();
  if (source.kind === 'json') return JSON.parse(text);
  const parsed = jsyaml.load(text);
  return Array.isArray(parsed) ? parsed : [];
}


function deadlineMillis(row) {
  const values = [row.abstractDt, row.paperDt, row.effectiveDt]
    .filter(dt => dt && dt.isValid)
    .map(dt => dt.toMillis());
  return values.length ? Math.min(...values) : null;
}

function cleanKey(value) {
  return cleanName(value).toLowerCase().replace(/[^a-z0-9가-힣]+/g, ' ').trim();
}

function deadlineDateKey(row) {
  const millis = deadlineMillis(row);
  if (millis === null) return 'tba';
  return DateTime.fromMillis(millis).setZone(CONFIG.displayZone).toISODate();
}

function uniqueBy(items, keyFn) {
  const seen = new Set();
  const out = [];
  for (const item of items) {
    const key = keyFn(item);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(item);
  }
  return out;
}

function extractCycle(row) {
  const text = `${row.originalTitle} ${row.fullName} ${row.id} ${row.cycle}`;
  const m = text.match(/\bcycle\s*(\d+)/i);
  if (m) return `cycle ${m[1]}`;
  if (/\b(first|1st)\s+cycle\b/i.test(text)) return 'cycle 1';
  if (/\b(second|2nd)\s+cycle\b/i.test(text)) return 'cycle 2';
  if (/\b(third|3rd)\s+cycle\b/i.test(text)) return 'cycle 3';
  return row.cycle || '';
}

function trackLabel(row) {
  const text = `${row.originalTitle} ${row.fullName} ${row.id}`.toLowerCase();

  // Keep security/system review cycles, but hide software-engineering subtracks by default.
  // The user's target list is conference-level, so ICSE-SEIP / ICSE-JF / NIER-like tracks
  // should not appear unless the UI toggle asks for detailed tracks.
  if (!['ICSE', 'FSE', 'ASE', 'ISSTA'].includes(row.canonicalName)) return '';

  const patterns = [
    [/\bseip\b/, 'SEIP'],
    [/\bjf\b|journal[- ]first|journal first/, 'Journal First'],
    [/\bnier\b|new ideas/, 'NIER'],
    [/\bsrc\b|student research/, 'SRC'],
    [/\bdemo(s)?\b|demonstration/, 'Demo'],
    [/doctoral|\bdoctoral symposium\b/, 'Doctoral Symposium'],
    [/artifact|artefact/, 'Artifact'],
    [/industry|practice/, 'Industry'],
    [/education|\bseet\b/, 'Education'],
    [/workshop|companion|tutorial|poster/, 'Companion']
  ];
  for (const [re, label] of patterns) {
    if (re.test(text)) return label;
  }
  return '';
}

function isDetailedTrack(row) {
  return Boolean(trackLabel(row));
}

function splitIntoDeadlineClusters(rows) {
  const ordered = [...rows].sort((a, b) => {
    const am = deadlineMillis(a);
    const bm = deadlineMillis(b);
    return (am ?? Infinity) - (bm ?? Infinity);
  });
  const clusters = [];
  for (const row of ordered) {
    const current = deadlineMillis(row);
    const lastCluster = clusters[clusters.length - 1];
    if (!lastCluster || current === null) {
      clusters.push([row]);
      continue;
    }
    const clusterTimes = lastCluster.map(deadlineMillis).filter(v => v !== null);
    const clusterMin = Math.min(...clusterTimes);
    const clusterMax = Math.max(...clusterTimes);
    const distanceDays = Math.min(
      Math.abs(current - clusterMin),
      Math.abs(current - clusterMax)
    ) / (24 * 60 * 60 * 1000);

    // Abstract and paper deadlines are often 7 days apart. Different review cycles are
    // usually much farther apart and should stay as separate rows.
    if (distanceDays <= 14) lastCluster.push(row);
    else clusters.push([row]);
  }
  return clusters;
}

function mergeRowCluster(cluster) {
  const sorted = [...cluster].sort((a, b) => a.priority - b.priority);
  const base = sorted[0];
  const sources = uniqueBy(sorted.map(row => ({ name: row.source, url: row.sourceUrl, priority: row.priority })), s => `${s.name}|${s.url}`)
    .sort((a, b) => a.priority - b.priority);

  const validAbstracts = sorted.map(row => row.abstractDt).filter(dt => dt && dt.isValid);
  const validPapers = sorted.map(row => row.paperDt).filter(dt => dt && dt.isValid);
  const allDates = [...validAbstracts, ...validPapers].sort((a, b) => a.toMillis() - b.toMillis());
  const uniquePapers = uniqueBy(validPapers.sort((a, b) => a.toMillis() - b.toMillis()), dt => dt.toISO());

  let abstractDt = validAbstracts.length ? validAbstracts.sort((a, b) => a.toMillis() - b.toMillis())[0] : null;
  let paperDt = validPapers.length ? validPapers.sort((a, b) => b.toMillis() - a.toMillis())[0] : null;

  // Some sources list the abstract deadline in `deadline` while another source lists the
  // actual paper deadline. If two same-venue deadlines are close, infer earlier=abstract,
  // later=paper. This removes duplicated FSE/ICSE-like rows while preserving cycles.
  if (!abstractDt && uniquePapers.length >= 2) {
    const earliest = uniquePapers[0];
    const latest = uniquePapers[uniquePapers.length - 1];
    const diffDays = latest.diff(earliest, 'days').days;
    if (diffDays > 0 && diffDays <= 14) {
      abstractDt = earliest;
      paperDt = latest;
    }
  }

  if (abstractDt && paperDt && abstractDt.toMillis() >= paperDt.toMillis()) {
    if (abstractDt.toMillis() === paperDt.toMillis()) abstractDt = null;
    else [abstractDt, paperDt] = [paperDt, abstractDt];
  }

  const firstNonEmpty = field => sorted.map(row => row[field]).find(value => cleanName(value)) || '';
  const cycle = extractCycle(base);
  const track = trackLabel(base);
  return {
    ...base,
    originalTitle: firstNonEmpty('originalTitle') || base.originalTitle,
    fullName: firstNonEmpty('fullName'),
    abstractDt,
    paperDt,
    effectiveDt: abstractDt || paperDt || (allDates[0] || null),
    place: firstNonEmpty('place'),
    date: firstNonEmpty('date'),
    start: firstNonEmpty('start'),
    end: firstNonEmpty('end'),
    link: firstNonEmpty('link'),
    note: firstNonEmpty('note'),
    source: sources[0]?.name || base.source,
    sourceUrl: sources[0]?.url || base.sourceUrl,
    sources,
    cycle,
    track,
    isTrack: Boolean(track),
    mergedCount: cluster.length
  };
}

function dedupe(rows) {
  const primaryGroups = groupBy(rows, row => {
    const cycle = extractCycle(row);
    const track = trackLabel(row);
    const conferenceKey = [row.canonicalName, row.year].join('|');
    if (cycle) return `${conferenceKey}|${cycle.toLowerCase()}`;
    if (track) return `${conferenceKey}|track:${track.toLowerCase()}`;
    return `${conferenceKey}|main`;
  });

  const merged = [];
  for (const groupRows of primaryGroups.values()) {
    const hasExplicitCycle = groupRows.some(row => extractCycle(row));
    const hasTrack = groupRows.some(row => trackLabel(row));
    const clusters = (hasExplicitCycle || hasTrack) ? [groupRows] : splitIntoDeadlineClusters(groupRows);
    for (const cluster of clusters) merged.push(mergeRowCluster(cluster));
  }
  return merged;
}

function daysLabelForDate(dt) {
  if (!dt || !dt.isValid) return { html: '<span class="past">TBA</span>', value: Infinity };
  const now = DateTime.now().setZone(CONFIG.displayZone).startOf('day');
  const target = dt.startOf('day');
  const days = Math.ceil(target.diff(now, 'days').days);
  if (days < 0) return { html: `<span class="past">D+${Math.abs(days)}</span>`, value: days };
  if (days === 0) return { html: '<strong class="urgent">D-Day</strong>', value: days };
  if (days <= 14) return { html: `<strong class="urgent">D-${days}</strong>`, value: days };
  if (days <= 60) return { html: `<strong class="soon">D-${days}</strong>`, value: days };
  return { html: `<strong>D-${days}</strong>`, value: days };
}

function daysLabel(row) {
  return daysLabelForDate(row.effectiveDt);
}

function fmt(dt) {
  if (!dt || !dt.isValid) return '-';
  return dt.toFormat('yyyy-LL-dd HH:mm') + ' KST';
}

function deadlineCellHtml(row) {
  const paperLine = `<div class="dl-paper-line">${fmt(row.paperDt)}</div>`;
  if (row.abstractDt && row.abstractDt.isValid) {
    return `<div>${fmt(row.abstractDt)}</div>${paperLine}`;
  }
  return paperLine;
}

function daysCellHtml(row) {
  const paperDays = daysLabelForDate(row.paperDt);
  const paperLine = `<div class="dl-paper-line">${paperDays.html}</div>`;
  if (row.abstractDt && row.abstractDt.isValid) {
    const abstractDays = daysLabelForDate(row.abstractDt);
    return `<div>${abstractDays.html}</div>${paperLine}`;
  }
  return paperLine;
}
function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}


function buildFilters(rows) {
  const yearFilter = document.getElementById('yearFilter');
  const categoryFilter = document.getElementById('categoryFilter');
  const years = [...new Set(rows.map(r => r.year))].sort((a, b) => a - b);
  for (const year of years) {
    const opt = document.createElement('option');
    opt.value = String(year);
    opt.textContent = String(year);
    yearFilter.appendChild(opt);
  }
  for (const cat of CATEGORY_ORDER) {
    if (!rows.some(r => r.category === cat)) continue;
    const opt = document.createElement('option');
    opt.value = cat;
    opt.textContent = CATEGORY_LABELS[cat] || cat;
    categoryFilter.appendChild(opt);
  }
}

function render(rows) {
  const root = document.getElementById('deadlineRoot');
  const q = document.getElementById('searchInput').value.trim().toLowerCase();
  const yearValue = document.getElementById('yearFilter').value;
  const catValue = document.getElementById('categoryFilter').value;
  const futureOnly = document.getElementById('futureOnly').checked;
  const includeWorkshops = document.getElementById('includeWorkshops').checked;

  let filtered = rows.filter(row => {
    const days = daysLabel(row).value;
    const paperDaysValue = row.paperDt && row.paperDt.isValid
      ? daysLabelForDate(row.paperDt).value
      : days;
    const text = `${row.canonicalName} ${row.originalTitle} ${row.fullName} ${row.place}`.toLowerCase();
    return (!q || text.includes(q)) &&
      (yearValue === 'all' || String(row.year) === yearValue) &&
      (catValue === 'all' || row.category === catValue) &&
      (!futureOnly || paperDaysValue >= 0) &&
      !row.isTrack &&
      (includeWorkshops || !row.isWorkshop);
  });

  filtered.sort((a, b) =>
    a.year - b.year ||
    daysLabel(a).value - daysLabel(b).value ||
    CATEGORY_ORDER.indexOf(a.category) - CATEGORY_ORDER.indexOf(b.category) ||
    a.canonicalName.localeCompare(b.canonicalName)
  );

  root.innerHTML = '';
  if (!filtered.length) {
    root.innerHTML = '<p class="status">No deadlines match the current filters.</p>';
    return;
  }

  const byYear = groupBy(filtered, r => r.year);
  for (const [year, yearRowsRaw] of byYear) {
    const yearRows = yearRowsRaw.sort((a, b) =>
      daysLabel(a).value - daysLabel(b).value ||
      CATEGORY_ORDER.indexOf(a.category) - CATEGORY_ORDER.indexOf(b.category) ||
      a.canonicalName.localeCompare(b.canonicalName)
    );
    const yearSection = document.createElement('section');
    yearSection.className = 'year-block';
    yearSection.innerHTML = `<h2 class="year-title">${year}</h2>`;

    const block = document.createElement('section');
    block.className = 'category-block';
    block.innerHTML = `
      <div class="category-title"><h3>Sorted by nearest deadline</h3><span>${yearRows.length} deadlines</span></div>
      <table>
        <colgroup>
          <col class="col-conf"><col class="col-category"><col class="col-deadline"><col class="col-days"><col class="col-place"><col class="col-date">
        </colgroup>
        <thead><tr>
          <th>Conference</th><th>Category</th><th>Deadline</th><th>D-day</th><th>Place</th><th>Conference date</th>
        </tr></thead>
        <tbody></tbody>
      </table>`;
    const tbody = block.querySelector('tbody');
    for (const row of yearRows) {
      const tr = document.getElementById('rowTemplate').content.firstElementChild.cloneNode(true);
      const subtitleParts = [];
      if (row.originalTitle && row.originalTitle.toLowerCase() !== row.canonicalName.toLowerCase()) subtitleParts.push(escapeHtml(row.originalTitle));
      if (row.cycle) subtitleParts.push(escapeHtml(row.cycle));
      if (row.track) subtitleParts.push(escapeHtml(row.track));
      const subtitleHtml = subtitleParts.length ? `<small>${subtitleParts.join(' · ')}</small>` : '';
      const nameClass = NAME_HIGHLIGHT_CONFS.has(row.canonicalName) ? 'conf-name-highlight' : 'conf-name-default';
      const nameHtml = `<span class="${nameClass}">${escapeHtml(row.canonicalName)}</span>`;
      tr.querySelector('.conf').innerHTML = `<strong>${row.link ? `<a href="${escapeHtml(row.link)}" target="_blank" rel="noreferrer">${nameHtml}</a>` : nameHtml}</strong>${row.isWorkshop ? ' <span class="badge-workshop">Workshop</span>' : ''}${subtitleHtml}`;
      tr.querySelector('.category').innerHTML = `<span class="badge">${CATEGORY_LABELS[row.category] || row.category}</span>`;
      tr.querySelector('.deadline').innerHTML = deadlineCellHtml(row);
      tr.querySelector('.days').innerHTML = daysCellHtml(row);
      tr.querySelector('.place').textContent = row.place || '-';
      tr.querySelector('.date').textContent = row.date || '-';
      tbody.appendChild(tr);
    }
    yearSection.appendChild(block);
    root.appendChild(yearSection);
  }
}

async function main() {
  document.getElementById('todayLabel').textContent = DateTime.now().setZone(CONFIG.displayZone).toFormat('yyyy-LL-dd HH:mm');
  const status = document.getElementById('statusBox');
  const results = await Promise.allSettled(CONFIG.sourceUrls.map(async source => ({ source, records: await fetchSource(source) })));
  const failures = results.filter(r => r.status === 'rejected').map(r => r.reason.message);
  const loaded = results.filter(r => r.status === 'fulfilled').flatMap(r => r.value.records.flatMap(rec => expandRecord(rec, r.value.source)));
  const rows = dedupe(loaded);
  buildFilters(rows);
  status.textContent = failures.length ? `Failed sources: ${failures.join(', ')}` : '';

  for (const id of ['searchInput', 'yearFilter', 'categoryFilter', 'futureOnly', 'includeWorkshops']) {
    document.getElementById(id).addEventListener('input', () => render(rows));
  }
  render(rows);
}

main().catch(error => {
  document.getElementById('statusBox').textContent = `Load failed: ${error.message}`;
});
