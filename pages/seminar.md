---
title: "Paper Reading"
layout: page
permalink: /seminar/
main_nav: true
# pagination: 
#   enabled: true
---


<ul class="post-list">
  {% for post in site.data.readings %}
    <li>
      <span><h4>{{ post.title }}</h4> ({{ post.conference}}, {{post.pub_year}})</span>
      <section class="post-meta">
      <div class="post-data">{{ post.date | date: "%B %-d, %Y" }}</div>
      <ul>        
        <li class="post-data">Presented by {{ post.presenter }}</li>
        <li class="post-data"><a href="{{post.code_link}}" target="_blank" style="color: black"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-github" viewBox="0 0 16 16">
         <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8"/></svg></a> | 
         <a href="{{post.ppt_link}}" style="color: orange" target="_blank"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-file-earmark-ppt" viewBox="0 0 16 16">
            <path d="M7 5.5a1 1 0 0 0-1 1V13a.5.5 0 0 0 1 0v-2h1.188a2.75 2.75 0 0 0 0-5.5zM8.188 10H7V6.5h1.188a1.75 1.75 0 1 1 0 3.5"/>
            <path d="M14 4.5V14a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V2a2 2 0 0 1 2-2h5.5zm-3 0A1.5 1.5 0 0 1 9.5 3V1H4a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V4.5z"/></svg></a>
         </li>
      </ul>        
      </section>
    </li>
    {% if forloop.last == false %}
      <hr>
    {% endif %}
  {% endfor %}
</ul>


<!-- <div aria-label="Page navigation" >
  <ul class="pagination" style="margin-left: 43%;">
    {% if paginator.previous_page %}
      <li class="page-item">
        <a class="page-link" href="{{ paginator.previous_page_path }}" aria-label="Previous">
          <span aria-hidden="true">&laquo;</span>
        </a>
      </li>
    {% else %}
      <li class="page-item disabled">
        <span class="page-link" aria-hidden="true">&laquo;</span>
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
          <span aria-hidden="true">&raquo;</span>
        </a>
      </li>
    {% else %}
      <li class="page-item disabled">
        <span class="page-link" aria-hidden="true">&raquo;</span>
      </li>
    {% endif %}
  </ul>
</div> -->
