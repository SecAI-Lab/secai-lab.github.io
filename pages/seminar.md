---
title: "Reading Seminar"
layout: page
permalink: /seminar/
main_nav: true
# pagination:
#   enabled: true
---

<style>
.toggle-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    background: none;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.2s ease;
    color: #000000;
    padding: 0;
}

.toggle-button:hover {
    background: rgba(255, 255, 255, 0.1);
    color: #000000ff;
}

.toggle-icon {
    font-size: 12px;
    transition: transform 0.3s ease;
    transform-origin: center;
}

.toggle-button.active .toggle-icon {
    transform: rotate(90deg);
}

.dotted-box {
    display: none;
    margin-top: 10px;
    padding: 15px;
    border: 1px dashed #ccc;
    background: #f9f9f9;
}

.dotted-box.active {
    display: block;
}

.year-tabs {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
    border-bottom: 1px solid #e0e0e0;
    margin-bottom: 25px;
}

.year-tab {
    background: none;
    border: none;
    border-bottom: 3px solid transparent;
    border-radius: 0;
    outline: none;
    margin-bottom: -1px;
    padding: 0.6rem 0.9rem;
    color: #95a5a6;
    font-family: "Roboto Slab";
    font-weight: 600;
    font-size: 1.2rem;
    cursor: pointer;
    transition: all 0.2s ease;
}

.year-tab:focus {
    background: none;
    outline: none;
}

.year-tab:hover {
    color: #111;
    background: #f0f0f0;
    font-weight: 700;
}

.year-tab.active {
    color: #111;
    border-bottom-color: #111;
}

.year-section {
    display: none;
}

.year-section.active {
    display: block;
}

.post-list {
    display: grid;
    grid-template-columns: 1fr 1fr;
    column-gap: 40px;
    align-items: start;
}

.post-column .post-meta:not(:last-child) {
    margin-bottom: 20px;
}

@media (max-width: 768px) {
    .post-list {
        grid-template-columns: 1fr;
    }

    .post-column:first-child .post-meta:last-child {
        margin-bottom: 20px;
    }
}
</style>

{% assign all_years = '' | split: ',' %}
{% for post in site.data.readings %}
  {% assign post_year = post.date | date: '%Y' %}
  {% unless all_years contains post_year %}
    {% assign all_years = all_years | push: post_year %}
  {% endunless %}
{% endfor %}
{% assign years = all_years | uniq | sort | reverse %}

<div class="year-tabs">
  {% for year in years %}
    <button class="year-tab{% if forloop.first %} active{% endif %}" data-year="{{ year }}" onclick="selectYear('{{ year }}')">{{ year }}</button>
  {% endfor %}
</div>

<div class="year-sections">
  {% for year in years %}
    {% assign year_posts = '' | split: ',' %}
    {% for post in site.data.readings %}
      {% assign post_year = post.date | date: '%Y' %}
      {% if post_year == year %}
        {% assign year_posts = year_posts | push: post %}
      {% endif %}
    {% endfor %}
    {% assign year_posts = year_posts | sort: 'date' | reverse %}
    {% assign half = year_posts.size | plus: 1 | divided_by: 2 %}
    <div class="year-section{% if forloop.first %} active{% endif %}" data-year="{{ year }}">
      <div class="post-list">
        <div class="post-column">
          {% for post in year_posts %}
            {% if forloop.index0 < half %}
              {% include seminar_post.html post=post %}
            {% endif %}
          {% endfor %}
        </div>
        <div class="post-column">
          {% for post in year_posts %}
            {% if forloop.index0 >= half %}
              {% include seminar_post.html post=post %}
            {% endif %}
          {% endfor %}
        </div>
      </div>
    </div>
  {% endfor %}
</div>

<script>
function toggleDiscussion(button) {
    const discussionBox = button.parentElement.querySelector('.dotted-box');
    const isActive = discussionBox.classList.contains('active');
    
    if (isActive) {
        discussionBox.classList.remove('active');
        button.classList.remove('active');
    } else {
        discussionBox.classList.add('active');
        button.classList.add('active');
    }
}

function selectYear(year) {
    document.querySelectorAll('.year-tab').forEach(function(tab) {
        tab.classList.toggle('active', tab.dataset.year === year);
    });
    document.querySelectorAll('.year-section').forEach(function(section) {
        section.classList.toggle('active', section.dataset.year === year);
    });
}

// Ensure all triangles start in the correct position
document.addEventListener('DOMContentLoaded', function() {
    const toggleButtons = document.querySelectorAll('.toggle-button');
    toggleButtons.forEach(button => {
        button.classList.remove('active');
    });
});
</script>
