---
title: "Gallery"
layout: page
sitemap: false
permalink: /gallery/
main_nav: true
---

<div class="gallery-container">
  {% for group in site.data.gallery %}
    <div class="gallery-box" data-index="{{ forloop.index0 }}">
      <!-- 제목 -->
      <div style="margin-bottom: 2px;">{{ group.title }}</div>

      <!-- 날짜 -->
      {% if group.images[0].date %}
        <div style="margin-bottom: 8px;">
          <small style="color: gray;">{{ group.images[0].date }}</small>
        </div>
      {% endif %}

<!-- 대표 이미지 썸네일 -->
<div class="thumbnail">
  <a href="{{ site.url }}{{ site.baseurl }}/images/gallery/{{ group.images[0].filename }}"
     data-lightbox="group{{ forloop.index }}"
     data-title="{{ group.title }}<br><small>{{ group.images[0].date }}</small>">
    <img src="{{ site.url }}{{ site.baseurl }}/images/gallery/{{ group.images[0].filename }}" alt="{{ group.title }}">
  </a>
</div>

<!-- 숨겨진 이미지들 -->
<div class="hidden-images">
  {% for image in group.images offset:1 %}
    <a href="{{ site.url }}{{ site.baseurl }}/images/gallery/{{ image.filename }}"
       data-lightbox="group{{ forloop.parentloop.index }}"
       data-title="{{ group.title }}<br><small>{{ image.date }}</small>">
      <img src="{{ site.url }}{{ site.baseurl }}/images/gallery/{{ image.filename }}" alt="">
    </a>
  {% endfor %}
</div>

    </div>

{% endfor %}

</div>

<!-- Pagination Controls -->
<div class="pagination-controls">
  <button id="firstBtn" onclick="goToFirstPage()"><<</button>
  <button id="prevBtn" onclick="changePage(-1)"><</button>
  <div id="pageNumbers"></div>
  <button id="nextBtn" onclick="changePage(1)">></button>
  <button id="lastBtn" onclick="goToLastPage()">>></button>
</div>

<!-- Lightbox 추가 -->
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/lightbox2/2.11.3/css/lightbox.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/lightbox2/2.11.3/js/lightbox.min.js"></script>

<style>
.pagination-controls {
  text-align: center;
  margin: 20px 0;
  padding: 10px;
}

.pagination-controls {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin: 30px 0;
}

.pagination-controls button {
  -webkit-font-smoothing: antialiased;
  background-color: #fff;
  border-radius: 3px;
  border: 1px solid #ddd;
  color: #333;
  cursor: pointer;
  display: inline-block;
  font-family: "Open Sans", "Helvetica Neue", "Helvetica", "Roboto", "Arial", sans-serif;
  font-size: 16px;
  font-weight: 600;
  line-height: 1;
  padding: 0.75em 1em;
  text-decoration: none;
  user-select: none;
  vertical-align: middle;
  white-space: nowrap;
  min-width: 44px;
  transition: all 0.2s ease;
}

.pagination-controls button:hover,
.pagination-controls button:focus {
  background-color: #f8f8f8;
  color: #333;
  border-color: #bbb;
}

.pagination-controls button:disabled {
  cursor: not-allowed;
  background-color: #fff;
  color: #333;
  border-color: #ddd;
}

.pagination-controls button:disabled:hover {
  background-color: #fff;
  color: #333;
  border-color: #ddd;
}

.pagination-controls button.active {
  background-color: #27ae60;
  box-shadow: inset 0 2px 4px rgba(0,0,0,0.1);
}

.pagination-controls button.active:hover {
  background-color: #1e8449;
}

#pageNumbers {
  display: flex;
  align-items: center;
  gap: 0;
  margin: 0 15px;
}


.pagination-controls #pageNumbers button {
  background-color: transparent;
  color: #333;
  border: none;
  border-radius: 0;
  padding: 0.4em 0.8em;
  font-size: 14px;
  font-weight: 400;
  min-width: 32px;
  margin: 0;
  text-decoration: none;
  border-bottom: 2px solid transparent;
  transition: all 0.2s ease;
  outline: none;
}

.pagination-controls #pageNumbers button:hover {
  background-color: #f8f8f8;
  color: #333;
}

.pagination-controls #pageNumbers button:focus {
  outline: none;
  background-color: #f8f8f8;
}

.pagination-controls #pageNumbers button.active {
  background-color: transparent;
  color: #333;
  border-bottom: 2px solid #2c3e50;
  font-weight: 600;
}

.pagination-controls #pageNumbers button.active:hover {
  background-color: #f8f8f8;
  color: #333;
}

.pagination-controls button#prevBtn,
.pagination-controls button#nextBtn {
  padding: 0.6em 0.7em;
  font-weight: 600;
  font-size: 14px;
  outline: none;
}

.pagination-controls button#firstBtn,
.pagination-controls button#lastBtn {
  padding: 0.6em 0.5em;
  font-weight: 600;
  font-size: 14px;
  outline: none;
}

.pagination-controls button#prevBtn:focus,
.pagination-controls button#nextBtn:focus,
.pagination-controls button#firstBtn:focus,
.pagination-controls button#lastBtn:focus {
  outline: none;
  background-color: #f8f8f8;
}

.page-separator {
  color: #999;
  margin: 0 8px;
  font-weight: 300;
  user-select: none;
}

.pagination-ellipsis {
  background-color: transparent;
  color: #666;
  border: none;
  border-radius: 0;
  padding: 0.4em 0.8em;
  font-size: 14px;
  font-weight: 400;
  min-width: 32px;
  margin: 0;
  cursor: pointer;
  outline: none;
  transition: all 0.2s ease;
}

.pagination-ellipsis:hover {
  background-color: #f8f8f8;
  color: #333;
}

.gallery-box {
  display: none;
}

.gallery-box.visible {
  display: block;
}
</style>

<script>
let currentPage = 1;
const itemsPerPage = 9;
let totalItems = 0;
let totalPages = 0;

document.addEventListener('DOMContentLoaded', function() {
  const galleryBoxes = document.querySelectorAll('.gallery-box');
  totalItems = galleryBoxes.length;
  totalPages = Math.ceil(totalItems / itemsPerPage);

  createPageNumbers();
  showPage(1);
});

function createPageNumbers() {
  const pageNumbersContainer = document.getElementById('pageNumbers');
  pageNumbersContainer.innerHTML = '';

  if (totalPages <= 5) {
    // Show all pages if 5 or fewer
    for (let i = 1; i <= totalPages; i++) {
      addPageButton(i, pageNumbersContainer);
      if (i < totalPages) addSeparator(pageNumbersContainer);
    }
  } else {
    // Range-based pagination for more than 5 pages
    createRangePagination(pageNumbersContainer);
  }
}

function createRangePagination(container) {
  const pagesPerRange = 5;
  const currentRange = Math.ceil(currentPage / pagesPerRange);
  const totalRanges = Math.ceil(totalPages / pagesPerRange);

  const rangeStart = (currentRange - 1) * pagesPerRange + 1;
  const rangeEnd = Math.min(rangeStart + pagesPerRange - 1, totalPages);

  // Show current range of pages
  for (let i = rangeStart; i <= rangeEnd; i++) {
    addPageButton(i, container);
    if (i < rangeEnd) addSeparator(container);
  }

  // Add ellipsis if there are more pages after current range
  if (currentRange < totalRanges) {
    addSeparator(container);
    addEllipsis(container, 'next');
  }
}

function addPageButton(pageNum, container) {
  const pageBtn = document.createElement('button');
  pageBtn.textContent = pageNum;
  pageBtn.onclick = () => showPage(pageNum);
  pageBtn.id = `page-${pageNum}`;
  container.appendChild(pageBtn);
}

function addSeparator(container) {
  const separator = document.createElement('span');
  separator.className = 'page-separator';
  separator.textContent = '|';
  container.appendChild(separator);
}

function addEllipsis(container, direction) {
  const ellipsis = document.createElement('button');
  ellipsis.className = 'pagination-ellipsis';
  ellipsis.textContent = '...';
  ellipsis.onclick = () => handleEllipsisClick(direction);
  container.appendChild(ellipsis);
}

function handleEllipsisClick(direction) {
  const pagesPerRange = 5;
  const currentRange = Math.ceil(currentPage / pagesPerRange);
  let targetPage;

  if (direction === 'next') {
    // Move to first page of next range
    const nextRange = currentRange + 1;
    targetPage = (nextRange - 1) * pagesPerRange + 1;
    targetPage = Math.min(targetPage, totalPages);
  }

  showPage(targetPage);
}

function showPage(page) {
  const galleryBoxes = document.querySelectorAll('.gallery-box');
  const startIndex = (page - 1) * itemsPerPage;
  const endIndex = startIndex + itemsPerPage;

  // Hide all gallery boxes
  galleryBoxes.forEach(box => {
    box.classList.remove('visible');
  });

  // Show gallery boxes for current page
  for (let i = startIndex; i < endIndex && i < totalItems; i++) {
    galleryBoxes[i].classList.add('visible');
  }

  // Update current page
  currentPage = page;

  // Regenerate pagination buttons to show correct range
  createPageNumbers();

  // Update active state for current page
  const currentPageBtn = document.getElementById(`page-${page}`);
  if (currentPageBtn) {
    currentPageBtn.classList.add('active');
  }

  // Update button states
  document.getElementById('firstBtn').disabled = (page === 1);
  document.getElementById('prevBtn').disabled = (page === 1);
  document.getElementById('nextBtn').disabled = (page === totalPages);
  document.getElementById('lastBtn').disabled = (page === totalPages);

  // Scroll to top of page
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function changePage(direction) {
  const newPage = currentPage + direction;
  if (newPage >= 1 && newPage <= totalPages) {
    showPage(newPage);
  }
}

function goToFirstPage() {
  showPage(1);
}

function goToLastPage() {
  showPage(totalPages);
}
</script>
