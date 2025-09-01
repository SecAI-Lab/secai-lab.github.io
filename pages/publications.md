---
title: "Publications"
layout: page
sitemap: false
permalink: /publications/
main_nav: true
---

<!-- Font Awesome for icons -->
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
<!-- Bootstrap Icons -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">

<style>
.academic-header {
    border-bottom: 2px solid #2c3e50;
    padding-bottom: 2rem;
    margin-bottom: 3rem;
    text-align: center;
}

.academic-header h1 {
    font-size: 2.8rem;
    font-weight: 400;
    color: #2c3e50;
    margin-bottom: 0.5rem;
    letter-spacing: 1px;
}

.academic-header .subtitle {
    font-size: 1.1rem;
    color: #7f8c8d;
    font-style: italic;
    margin-bottom: 2rem;
}

.search-filter-section {
    background: #f8f9fa;
    border: 1px solid #e9ecef;
    padding: 2rem;
    margin: 0;
    border-radius: 4px;
}

.search-container {
    max-width: 600px;
    margin: 0 auto 1.5rem auto;
}

.search-input {
    width: 100%;
    padding: 0.8rem 1rem;
    border: 2px solid #bdc3c7;
    border-radius: 4px;
    font-size: 1rem;
    background: white;
}

.search-input:focus {
    outline: none;
    border-color: #3498db;
}

.filter-buttons {
    display: flex;
    justify-content: center;
    gap: 0.5rem;
    flex-wrap: wrap;
}

.filter-btn {
    padding: 0.6rem 1.2rem;
    border: 1px solid #bdc3c7;
    background: white;
    color: #2c3e50;
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.2s ease;
    font-size: 0.9rem;
}

.filter-btn:hover, .filter-btn.active {
    background: #2c3e50;
    color: white;
    border-color: #2c3e50;
}

.external-links {
    text-align: center;
    margin-top: 1.5rem;
}

.external-link {
    display: inline-block;
    padding: 0.7rem 1.5rem;
    background: #34495e;
    color: white;
    text-decoration: none;
    border-radius: 4px;
    margin: 0 0.5rem;
    font-size: 0.9rem;
    transition: background 0.2s ease;
}

.external-link:hover {
    background: #2c3e50;
    color: white;
    text-decoration: none;
}

.section-title {
    font-size: 1.8rem;
    font-weight: 400;
    color: #2c3e50;
    margin: 3rem 0 0.5rem 0;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid #bdc3c7;
}

.highlighted-section {
    margin: 3rem 0;
}

.featured-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 2rem;
    margin: 2rem 0;
}

.featured-publication {
    background: white;
    border: 1px solid #e1e8ed;
    padding: 1.5rem;
    padding-bottom: 4rem;
    border-radius: 4px;
    height: 500px;
    position: relative;
    transition: height 0.3s ease;
}

.featured-publication.expanded {
    height: auto;
    min-height: 500px;
    padding-bottom: 4rem;
}

.publication-header {
    display: flex;
    flex-direction: column;
    margin-bottom: 1rem;
}

.publication-image {
    width: 100%;
    height: 150px;
    object-fit: cover;
    border: 1px solid #ddd;
    border-radius: 4px;
    margin-bottom: 1rem;
}

.publication-content {
    width: 100%;
}

.publication-title {
    font-size: 1.15rem;
    font-weight: 500;
    color: #2c3e50;
    margin-top: 0.6rem;
    margin-bottom: 0.6rem;
    line-height: 1.4;
}

.publication-authors {
    color: #34495e;
    margin-bottom: 0.4rem;
    font-style: italic;
    font-size: 0.9rem;
}

.publication-venue {
    color: #3498db;
    font-weight: 500;
    margin-bottom: 0.8rem;
    font-size: 0.9rem;
}

.abstract-container {
    flex: 1;
    overflow: hidden;
    margin-bottom: 1rem;
    display: flex;
    flex-direction: column;
}

.publication-description {
    color: #555;
    line-height: 1.5;
    font-size: 0.9rem;
    text-align: justify;
    margin-bottom: 0;
}

.description-preview {
    cursor: pointer;
    position: relative;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    overflow: hidden;
}

.description-preview::after {
    content: "...";
    position: absolute;
    bottom: 0;
    right: 0;
    background: white;
    padding-left: 0.5rem;
}

.description-full {
    cursor: pointer;
    display: block;
    overflow: visible;
}

.description-full::after {
    display: none;
}

.expand-toggle {
    color: #3498db;
    font-size: 0.8rem;
    cursor: pointer;
    margin-top: 0.5rem;
    font-weight: 500;
}

.expand-toggle:hover {
    color: #2980b9;
}

.publication-links {
    display: flex;
    gap: 0.8rem;
    flex-wrap: wrap;
    position: absolute;
    bottom: 1.5rem;
    left: 1.5rem;
    right: 1.5rem;
}

.publication-link {
    padding: 0.3rem 0.6rem;
    background: #f8f9fa;
    color: #495057;
    text-decoration: none;
    border-radius: 3px;
    font-size: 0.8rem;
    border: 1px solid #dee2e6;
    transition: all 0.2s ease;
}

.publication-link:hover {
    background: #f8f9fa;
    color: black;
    border-color: #dee2e6;
    text-decoration: none;
}


.award-badge {
    display: inline-block;
    background: #2c3e50;
    color: white;
    padding: 0.25rem 0.5rem;
    border-radius: 3px;
    font-size: 0.75rem;
    font-weight: 500;
    margin-left: 0.5rem;
    vertical-align: middle;
}

.featured-publication .award-badge {
    display: block;
    margin: 0.3rem 0 0 0;
    width: fit-content;
}

.year-section {
    margin: 2.5rem 0;
}


.publication-entry {
    padding: 1rem 0;
    border-bottom: 1px solid #f0f0f0;
    margin: 0;
}

.publication-entry:last-child {
    border-bottom: none;
}

.entry-title {
    font-size: 1.05rem;
    font-weight: 600;
    color: #2c3e50;
    margin-bottom: 0.4rem;
    line-height: 1.4;
}

.entry-authors {
    color: #34495e;
    margin-bottom: 0.3rem;
    font-style: italic;
    font-size: 0.95rem;
}

.entry-venue {
    color: #3498db;
    font-weight: 500;
    margin-bottom: 0.6rem;
    font-size: 0.95rem;
}

.entry-links {
    display: flex;
    gap: 0.8rem;
    flex-wrap: wrap;
}

.entry-link {
    padding: 0.25rem 0.5rem;
    background: #f8f9fa;
    color: #495057;
    text-decoration: none;
    border-radius: 3px;
    font-size: 0.8rem;
    border: 1px solid #dee2e6;
    transition: all 0.2s ease;
}

.entry-link:hover {
    background: #f8f9fa;
    color: black;
    text-decoration: none;
}

/* GitHub button styling */
.github-link {
    padding: 0.3rem 0.6rem;
    background: #f8f9fa;
    color: #495057;
    text-decoration: none;
    border-radius: 3px;
    font-size: 0.8rem;
    border: 1px solid #dee2e6;
    transition: all 0.2s ease;
}


/* Slides button styling */
.slides-link {
    padding: 0.3rem 0.6rem;
    background: #f8f9fa;
    color: #495057;
    text-decoration: none;
    border-radius: 3px;
    font-size: 0.8rem;
    border: 1px solid #dee2e6;
    transition: all 0.2s ease;
}

/* Icon spacing */
.github-link i, .slides-link i {
    margin-right: 0.3rem;
}


@media (max-width: 768px) {
    .academic-header h1 {
        font-size: 2.2rem;
    }
    
    .featured-grid {
        grid-template-columns: 1fr;
        gap: 1.5rem;
    }
    
    .filter-buttons {
        flex-direction: column;
        align-items: center;
    }
    
    .filter-btn {
        width: 200px;
    }
    
    /* Fix mobile layout for featured publications */
    .featured-publication {
        height: auto !important;
        min-height: 400px;
        padding-bottom: 3rem;
    }
    
    .featured-publication.expanded {
        min-height: 400px;
    }
    
    .abstract-container {
        height: auto !important;
        margin-bottom: 1.5rem;
    }
    
    .publication-links {
        position: relative !important;
        bottom: auto !important;
        left: auto !important;
        right: auto !important;
        margin-top: 1rem;
    }
}
</style>
<div class="search-filter-section">
    <div class="search-container">
        <input type="text" class="search-input" id="search-input" placeholder="Search publications by title, authors, or venue...">
    </div>
    
    <div class="filter-buttons">
        <button class="filter-btn active" data-filter="all">All Publications</button>
        <button class="filter-btn" data-filter="conferences">Conferences & Journals</button>
        <button class="filter-btn" data-filter="workshops">Workshops & Domestic</button>
    </div>
    
</div>

<div id="publications-content">
    <div class="highlighted-section" id="highlighted-section">
        <h2 class="section-title">Featured Publications</h2>
        
        <div class="featured-grid">
            {% for publi in site.data.publist-conferences %}
            {% if publi.highlight == 1 %}
            <div class="featured-publication" data-type="highlighted conferences" data-year="{{ publi.link.display | slice: -4, 4 }}">
                <div class="publication-header">
                    {% if publi.image %}
                    <img src="{{ site.url }}{{ site.baseurl }}/images/pubs/{{ publi.image }}" class="publication-image" alt="{{ publi.title }}">
                    {% endif %}
                    <div class="publication-content">
                        <h3 class="publication-title">{{ publi.title }}</h3>
                        <p class="publication-authors">{{ publi.authors }}</p>
                        <p class="publication-venue">{{ publi.link.display }}{% if publi.link2.display contains "Award" %}<span class="award-badge">{{ publi.link2.display }}</span>{% endif %}</p>
                    </div>
                </div>
                
                {% if publi.description %}
                <div class="abstract-container">
                    <div class="publication-description description-preview" onclick="toggleDescription(this)">
                        {{ publi.description }}
                    </div>
                </div>
                {% endif %}
                
                <div class="publication-links">
                    {% if publi.link.url and publi.link.url != "To appear" %}
                    <a href="{{ publi.link.url }}" class="publication-link" target="_blank"> Paper</a>
                    {% endif %}
                    {% if publi.github %}
                    <a href="{{ publi.github }}" class="publication-link github-link" target="_blank">
                        Code
                    </a>
                    {% endif %}
                    {% if publi.slides %}
                    <a href="{{ publi.slides }}" class="publication-link slides-link" target="_blank">
                         Slides
                    </a>
                    {% endif %}
                </div>
            </div>
            {% endif %}
            {% endfor %}
        </div>
    </div>

    <div class="year-section" id="conferences-section">
        <h2 class="section-title">International Conferences and Journals</h2>

        {% for publi in site.data.publist-conferences %}
        <div class="publication-entry" data-type="conferences">
            <h4 class="entry-title">{{ publi.title }}</h4>
            <p class="entry-authors">{{ publi.authors }}</p>
            <p class="entry-venue">{{ publi.link.display }}{% if publi.link2.display contains "Award" %}<span class="award-badge">{{ publi.link2.display }}</span>{% endif %}</p>

            <div class="entry-links">
                {% if publi.link.url and publi.link.url != "To appear" %}
                <a href="{{ publi.link.url }}" class="entry-link" target="_blank">
                 Paper</a>
                {% endif %}
                {% if publi.github %}
                <a href="{{ publi.github }}" class="entry-link github-link" target="_blank">
                     Code
                </a>
                {% endif %}
                {% if publi.slides %}
                <a href="{{ publi.slides }}" class="entry-link slides-link" target="_blank">
                    Slides
                </a>
                {% endif %}
            </div>
        </div>
        {% endfor %}
    </div>

    <div class="year-section" id="workshops-section">
        <h2 class="section-title">Workshops and Domestic Conferences</h2>

        {% for publi in site.data.publist-workshops %}
        <div class="publication-entry" data-type="workshops">
            <h4 class="entry-title">{{ publi.title }}</h4>
            <p class="entry-authors">{{ publi.authors }}</p>
            <p class="entry-venue">{{ publi.link.display }}{% if publi.link2.display contains "Award" %}<span class="award-badge">{{ publi.link2.display }}</span>{% endif %}</p>

            <div class="entry-links">
                {% if publi.link.url %}
                <a href="{{ publi.link.url }}" class="entry-link" target="_blank"> Paper</a>
                {% endif %}
                {% if publi.github %}
                <a href="{{ publi.github }}" class="entry-link github-link" target="_blank">
                     Code
                </a>
                {% endif %}
                {% if publi.slides %}
                <a href="{{ publi.slides }}" class="entry-link slides-link" target="_blank">
                     Slides
                </a>
                {% endif %}
            </div>
        </div>
        {% endfor %}
    </div>

</div>

<script>
document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('search-input');
    const filterButtons = document.querySelectorAll('.filter-btn');
    const publications = document.querySelectorAll('.featured-publication, .publication-entry');
    const sections = document.querySelectorAll('.highlighted-section, .year-section');
    
    let currentFilter = 'all';
    
    // Filter functionality
    filterButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            filterButtons.forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            currentFilter = this.dataset.filter;
            filterPublications();
        });
    });
    
    // Search functionality
    searchInput.addEventListener('input', function() {
        filterPublications();
    });
    
    function filterPublications() {
        const searchTerm = searchInput.value.toLowerCase();
        let visibleCount = 0;
        
        // Show/hide sections based on filter
        sections.forEach(section => {
            const sectionId = section.id;
            let shouldShow = false;
            
            if (currentFilter === 'all') {
                shouldShow = true;
            } else if (currentFilter === 'conferences' && sectionId === 'conferences-section') {
                shouldShow = true;
            } else if (currentFilter === 'workshops' && sectionId === 'workshops-section') {
                shouldShow = true;
            }
            
            section.style.display = shouldShow ? 'block' : 'none';
        });
        
        publications.forEach(pub => {
            const title = pub.querySelector('.publication-title, .entry-title').textContent.toLowerCase();
            const authors = pub.querySelector('.publication-authors, .entry-authors').textContent.toLowerCase();
            const venue = pub.querySelector('.publication-venue, .entry-venue').textContent.toLowerCase();
            const pubType = pub.dataset.type;
            
            const matchesSearch = title.includes(searchTerm) || 
                                authors.includes(searchTerm) || 
                                venue.includes(searchTerm);
            
            // Filter based on current selection
            let matchesFilter = false;
            
            if (currentFilter === 'all') {
                matchesFilter = true;
            } else if (currentFilter === 'conferences') {
                matchesFilter = pubType.includes('conferences');
            } else if (currentFilter === 'workshops') {
                matchesFilter = pubType.includes('workshops');
            }
            
            if (matchesSearch && matchesFilter) {
                pub.style.display = 'block';
                visibleCount++;
            } else {
                pub.style.display = 'none';
            }
        });
        
        // Show no results message if needed
        if (visibleCount === 0 && searchTerm) {
            showNoResults();
        } else {
            hideNoResults();
        }
    }
    
    function showNoResults() {
        let noResultsMsg = document.getElementById('no-results');
        if (!noResultsMsg) {
            noResultsMsg = document.createElement('div');
            noResultsMsg.id = 'no-results';
            noResultsMsg.innerHTML = `
                <div style="text-align: center; padding: 3rem; color: #7f8c8d; font-family: 'Georgia', serif;">
                    <h3>No publications found</h3>
                    <p>Please adjust your search terms or filter selection</p>
                </div>
            `;
            document.getElementById('publications-content').appendChild(noResultsMsg);
        }
        noResultsMsg.style.display = 'block';
    }
    
    function hideNoResults() {
        const noResultsMsg = document.getElementById('no-results');
        if (noResultsMsg) {
            noResultsMsg.style.display = 'none';
        }
    }
    
    // Smooth scrolling for internal links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });
    
    // Initialize page
    filterPublications();
});

// Function to toggle description expansion
function toggleDescription(element) {
    const container = element.closest('.featured-publication');
    const abstractContainer = element.closest('.abstract-container');
    
    if (element.classList.contains('description-preview')) {
        element.classList.remove('description-preview');
        element.classList.add('description-full');
        container.classList.add('expanded');
        // Remove height constraint when expanding
        if (abstractContainer) {
            abstractContainer.style.height = 'auto';
        }
    } else {
        element.classList.remove('description-full');
        element.classList.add('description-preview');
        container.classList.remove('expanded');
        // Recalculate line clamp and restore height when collapsing
        calculateLineClamp(element);
    }
}

// Function to calculate optimal line clamp for each abstract
function calculateLineClamp(desc) {
    const abstractContainer = desc.closest('.abstract-container');
    if (!abstractContainer) return;
    
    const container = desc.closest('.featured-publication');
    const containerHeight = 500; // Fixed height
    const headerHeight = container.querySelector('.publication-header').offsetHeight;
    const reservedBottomSpace = 64; // 4rem bottom padding for button area
    const topPadding = 24; // 1.5rem top padding
    const containerMargin = 16; // 1rem margin for abstract container
    
    const availableSpace = containerHeight - headerHeight - reservedBottomSpace - topPadding - containerMargin;
    
    // Set the container height to the available space
    abstractContainer.style.height = availableSpace + 'px';
    
    const lineHeight = parseFloat(window.getComputedStyle(desc).lineHeight);
    const maxLines = Math.floor(availableSpace / lineHeight);
    
    desc.style.webkitLineClamp = Math.max(3, maxLines); // Minimum 3 lines
}

document.addEventListener('DOMContentLoaded', function() {
    // Calculate line clamp for all preview descriptions
    const descriptions = document.querySelectorAll('.featured-publication .description-preview');
    descriptions.forEach(desc => {
        calculateLineClamp(desc);
    });
});
</script>
