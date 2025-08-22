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

.year-columns {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 40px;
    margin-top: 20px;
}

.year-section {
    break-inside: avoid;
}

.year-section:not(:first-child) {
    margin-top: 40px;
}

.year-header {
    font-weight: bold;
    font-size: 1.4em;
    margin-bottom: 15px;
    padding-bottom: 5px;
    border-bottom: 2px solid #333;
    font-family: "Roboto Slab";
}

@media (max-width: 768px) {
    .year-columns {
        display: block;
    }
    
    .column-1, .column-2 {
        display: none;
    }
    
    .mobile-years {
        display: block;
    }
}

@media (min-width: 769px) {
    .mobile-years {
        display: none;
    }
}
</style>

<div class="year-columns">
  {% assign all_years = '' | split: ',' %}
  {% for post in site.data.readings %}
    {% assign post_year = post.date | date: '%Y' %}
    {% unless all_years contains post_year %}
      {% assign all_years = all_years | push: post_year %}
    {% endunless %}
  {% endfor %}
  {% assign years = all_years | uniq | sort | reverse %}
  
  <div class="column-1">
    {% for year in years %}
      {% assign index = forloop.index0 %}
      {% assign is_even = index | modulo: 2 %}
      {% if is_even == 0 %}
        {% assign year_posts = '' | split: ',' %}
        {% for post in site.data.readings %}
          {% assign post_year = post.date | date: '%Y' %}
          {% if post_year == year %}
            {% assign year_posts = year_posts | push: post %}
          {% endif %}
        {% endfor %}
        {% assign year_posts = year_posts | sort: 'date' | reverse %}
        <div class="year-section">
          <div class="year-header">{{ year }}</div>
          <div class="post-list">
            {% for post in year_posts %}
              <section class="post-meta">
                <div class="post-data">{{ post.date | date: "%B %-d, %Y" }}, presented by {{ post.presenter }}  
                  <a href="{{post.code_link}}" target="_blank" style="color: black"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-github" viewBox="0 0 16 16">
                 <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8"/></svg>
                  </a> | 
                  <a href="{{post.ppt_link}}" style="color: orange" target="_blank"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-file-earmark-ppt" viewBox="0 0 16 16">
                    <path d="M7 5.5a1 1 0 0 0-1 1V13a.5.5 0 0 0 1 0v-2h1.188a2.75 2.75 0 0 0 0-5.5zM8.188 10H7V6.5h1.188a1.75 1.75 0 1 1 0 3.5"/>
                    <path d="M14 4.5V14a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V2a2 2 0 0 1 2-2h5.5zm-3 0A1.5 1.5 0 0 1 9.5 3V1H4a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V4.5z"/>
                  </svg>
                  </a>
                </div>
                <span class="toggle-button" onclick="toggleDiscussion(this)">
                  <span class="toggle-icon">▶</span>
                </span>
                <span><a href="{{ post.link }}" target="_blank"> {{ post.title }} </a> ({{ post.conference }}, {{ post.pub_year }})</span>
                <div class="dotted-box">{{ post.discussion }}</div>
              </section>
              {% unless forloop.last %}<br>{% endunless %}
            {% endfor %}
          </div>
        </div>
      {% endif %}
    {% endfor %}
  </div>
  
  <div class="column-2">
    {% for year in years %}
      {% assign index = forloop.index0 %}
      {% assign is_odd = index | modulo: 2 %}
      {% if is_odd == 1 %}
        {% assign year_posts = '' | split: ',' %}
        {% for post in site.data.readings %}
          {% assign post_year = post.date | date: '%Y' %}
          {% if post_year == year %}
            {% assign year_posts = year_posts | push: post %}
          {% endif %}
        {% endfor %}
        {% assign year_posts = year_posts | sort: 'date' | reverse %}
        <div class="year-section">
          <div class="year-header">{{ year }}</div>
          <div class="post-list">
            {% for post in year_posts %}
              <section class="post-meta">
                <div class="post-data">{{ post.date | date: "%B %-d, %Y" }}, presented by {{ post.presenter }}  
                  <a href="{{post.code_link}}" target="_blank" style="color: black"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-github" viewBox="0 0 16 16">
                 <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8"/></svg>
                  </a> | 
                  <a href="{{post.ppt_link}}" style="color: orange" target="_blank"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-file-earmark-ppt" viewBox="0 0 16 16">
                    <path d="M7 5.5a1 1 0 0 0-1 1V13a.5.5 0 0 0 1 0v-2h1.188a2.75 2.75 0 0 0 0-5.5zM8.188 10H7V6.5h1.188a1.75 1.75 0 1 1 0 3.5"/>
                    <path d="M14 4.5V14a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V2a2 2 0 0 1 2-2h5.5zm-3 0A1.5 1.5 0 0 1 9.5 3V1H4a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V4.5z"/>
                  </svg>
                  </a>
                </div>
                <span class="toggle-button" onclick="toggleDiscussion(this)">
                  <span class="toggle-icon">▶</span>
                </span>
                <span><a href="{{ post.link }}" target="_blank"> {{ post.title }} </a> ({{ post.conference }}, {{ post.pub_year }})</span>
                <div class="dotted-box">{{ post.discussion }}</div>
              </section>
              {% unless forloop.last %}<br>{% endunless %}
            {% endfor %}
          </div>
        </div>
      {% endif %}
    {% endfor %}
  </div>
  
  <div class="mobile-years">
    {% for year in years %}
      {% assign year_posts = '' | split: ',' %}
      {% for post in site.data.readings %}
        {% assign post_year = post.date | date: '%Y' %}
        {% if post_year == year %}
          {% assign year_posts = year_posts | push: post %}
        {% endif %}
      {% endfor %}
      {% assign year_posts = year_posts | sort: 'date' | reverse %}
      <div class="year-section">
        <div class="year-header">{{ year }}</div>
        <div class="post-list">
          {% for post in year_posts %}
            <section class="post-meta">
              <div class="post-data">{{ post.date | date: "%B %-d, %Y" }}, presented by {{ post.presenter }}  
                <a href="{{post.code_link}}" target="_blank" style="color: black"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-github" viewBox="0 0 16 16">
               <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8"/></svg>
                </a> | 
                <a href="{{post.ppt_link}}" style="color: orange" target="_blank"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-file-earmark-ppt" viewBox="0 0 16 16">
                  <path d="M7 5.5a1 1 0 0 0-1 1V13a.5.5 0 0 0 1 0v-2h1.188a2.75 2.75 0 0 0 0-5.5zM8.188 10H7V6.5h1.188a1.75 1.75 0 1 1 0 3.5"/>
                  <path d="M14 4.5V14a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V2a2 2 0 0 1 2-2h5.5zm-3 0A1.5 1.5 0 0 1 9.5 3V1H4a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V4.5z"/>
                </svg>
                </a>
              </div>
              <span class="toggle-button" onclick="toggleDiscussion(this)">
                <span class="toggle-icon">▶</span>
              </span>
              <span><a href="{{ post.link }}" target="_blank"> {{ post.title }} </a> ({{ post.conference }}, {{ post.pub_year }})</span>
              <div class="dotted-box">{{ post.discussion }}</div>
            </section>
            {% unless forloop.last %}<br>{% endunless %}
          {% endfor %}
        </div>
      </div>
    {% endfor %}
  </div>
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

// Ensure all triangles start in the correct position
document.addEventListener('DOMContentLoaded', function() {
    const toggleButtons = document.querySelectorAll('.toggle-button');
    toggleButtons.forEach(button => {
        button.classList.remove('active');
    });
});
</script>

<!-- <div aria-label="Page navigation" >
  <ul class="pagination" style="margin-left: 43%;">
    {% if paginator.previous_page %}
      <li class="page-item">
        <a class="page-link" href="{{ paginator.previous_page_path }}" aria-label="Previous">
          <span aria-hidden="true">«</span>
        </a>
      </li>
    {% else %}
      <li class="page-item disabled">
        <span class="page-link" aria-hidden="true">«</span>
      </li>
    {% endif %}
    {% for page in (1..paginator.total_pages) %}
    {% if page == paginator.page %}
      <li class="page-item active" aria-current="page">
        <span class="page-link">{{ page }}</span>
      </li>
    {% else %}
      <li class="page-item">
        <a class="page-link" href="{{ page.url }}">{{ page }}</a>
      </li>
    {% endif %}
  {% endfor %}
    {% if paginator.next_page %}
      <li class="page-item">
        <a class="page-link" href="{{ paginator.next_page_path }}" aria-label="Next">
          <span aria-hidden="true">»</span>
        </a>
      </li>
    {% else %}
      <li class="page-item disabled">
        <span class="page-link" aria-hidden="true">»</span>
      </li>
    {% endif %}
  </ul>
</div> -->
