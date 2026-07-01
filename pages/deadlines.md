---
title: "Conference Deadlines"
layout: page
sitemap: true
permalink: /deadlines/
main_nav: true
hide_title: true
---

<div class="deadline-page">
  <header class="hero">
    <div>
      <p class="eyebrow">system / software / security / ai</p>
      <h1>Conference Deadline Tracker</h1>
    </div>
    <div class="clock">
      <span id="todayLabel">-</span>
      <strong>Asia/Seoul</strong>
    </div>
  </header>

  <section class="controls" aria-label="filters">
    <div class="controls-row">
      <label>Search <input id="searchInput" type="search" placeholder="S&P, CCS, USENIX..." /></label>
      <label>Year <select id="yearFilter"><option value="all">All</option></select></label>
      <label>Category <select id="categoryFilter"><option value="all">All</option></select></label>
    </div>
    <div class="controls-row">
      <label><input id="futureOnly" type="checkbox" checked /> Upcoming only</label>
      <label><input id="includeWorkshops" type="checkbox" /> Include workshops</label>
    </div>
  </section>

  <section class="status" id="statusBox">Loading data...</section>

  <main id="deadlineRoot" class="deadline-root"></main>

  <template id="rowTemplate">
    <tr>
      <td class="conf"></td>
      <td class="category"></td>
      <td class="deadline"></td>
      <td class="days"></td>
      <td class="place"></td>
      <td class="date"></td>
    </tr>
  </template>

  <footer>
    <p>Disclaimer: Please verify all dates and submission details through the conference's official CFP prior to final submission, as the deadline tracker data may contain errors.</p>
  </footer>
</div>

<link rel="stylesheet" href="{{ site.baseurl }}/deadlines/assets/style.css">
<script src="https://cdn.jsdelivr.net/npm/luxon@3.5.0/build/global/luxon.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/js-yaml@4.1.0/dist/js-yaml.min.js"></script>
<script src="{{ site.baseurl }}/deadlines/assets/deadline-tracker.js"></script>
