---
title: "Lab Members"
layout: page
sitemap: false
permalink: /members/
main_nav: true
---

<style>
.members-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20px;
  margin-top: 20px;
  margin-bottom: 24px;
}

/* Mobile responsive */
@media (max-width: 768px) {
  .members-grid {
    grid-template-columns: 1fr;
    gap: 16px;
  }
}

.member-card {
  border-radius: 16px;
  padding: 20px;
  display: flex;
  gap: 20px;
  align-items: flex-start;
  transition: all 0.2s ease;
}

/* Mobile card layout */
@media (max-width: 640px) {
  .member-card {
    gap: 12px;
    padding: 16px;
  }
}

.member-card img {
  width: auto;
  height: 195px;
  object-fit: cover;
  border-radius: 12px;
  flex-shrink: 0;
}

/* Mobile image sizing */
@media (max-width: 640px) {
  .member-card img {
    width: 80px;
    height: 120px;
  }
}

.member-info {
  flex: 1;
}

.member-info h5 {
  margin-top: 48px;
  margin-bottom: 24px;
  font-weight: 600;
  line-height: 1.3;
}

/* Mobile text spacing */
@media (max-width: 640px) {
  .member-info h5 {
    margin-top: 0;
    margin-bottom: 12px;
    font-size: 16px;
  }
  
  .member-info em {
    font-size: 14px;
    margin-bottom: 3px;
  }
}

.member-info em {
  font-style: normal;
}

/* Leaders section mobile styles */
.leader-container {
  display: flex;
  gap: 20px;
  align-items: flex-start;
  margin-bottom: 32px;
}

.leader-container img.img-responsive {
  width: auto !important;
  height: 195px !important;
  object-fit: cover;
  border-radius: 12px;
  flex-shrink: 0;
}

@media (max-width: 640px) {
  .leader-container {
    gap: 12px;
  }
  
  .leader-container img.img-responsive {
    width: 80px !important;
    height: 120px !important;
  }
  
  .leader-info h5 {
    margin-top: 0;
    margin-bottom: 12px;
    font-size: 16px;
  }
  
  .leader-info em {
    font-size: 14px !important;
    margin-bottom: 3px !important;
  }
  
  .leader-info ul {
    margin-top: 8px !important;
    font-size: 14px !important;
  }
  
  .leader-info li {
    margin-bottom: 2px !important;
  }
}

</style>
<h3> Leader </h3>

{% for member in site.data.team_members %}

<div class="leader-container">
  <img src="{{ site.url }}{{ site.baseurl }}/images/members/{{ member.photo }}" class="img-responsive" />
  
  <div class="leader-info" style="flex: 1;">
    <h5 style="margin-top: 40px; margin-bottom: 16px; font-weight: 600; line-height: 1.3;">{{ member.name }}</h5>
    <em style="font-style: normal; line-height: 1.5; display: block; margin-bottom: 0px;">{{ member.info }}</em>
    <ul style="overflow: hidden; margin-top: 8px; padding-left: 20px; line-height: 1.5;">
      <li style="margin-bottom: 4px;">{{ member.education1 }}</li>
      <li style="margin-bottom: 4px;">{{ member.education2 }}</li>
      <li style="margin-bottom: 4px;">{{ member.education3 }}</li>
      <li style="margin-bottom: 4px;">{{ member.education4 }}</li>
    </ul>
  </div>
</div>
{% endfor %}
  
<h4> Ph.D. Students </h4>

<div class="members-grid">
{% for member in site.data.phd_students %}
  <div class="member-card">
    <img src="{{ site.url }}{{ site.baseurl }}/images/members/{{ member.photo }}" class="img-responsive"/>
    
    <div class="member-info">
      <h5>
        {{ member.name }}
        {% if member.github %}
          <a href="{{ member.github }}" target="_blank" style="margin-left: 5px; color: black;">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor"
                 class="bi bi-github" viewBox="0 0 16 16"
                 style="vertical-align: text-bottom;">
                        <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38
                0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13
                -.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21
                1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95
                0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12
                0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27
                c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12
                .51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95
                .29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2
                0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8"/>
            </svg>
          </a>
        {% endif %}
        {% if member.blog %}
      <a href="{{ member.blog }}" target="_blank" style="margin-left: 5px; color: black">
<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-bootstrap" viewBox="0 0 16 16" style="vertical-align: text-bottom;">
  <path d="M5.062 12h3.475c1.804 0 2.888-.908 2.888-2.396 0-1.102-.761-1.916-1.904-2.034v-.1c.832-.14 1.482-.93 1.482-1.816 0-1.3-.955-2.11-2.542-2.11H5.062zm1.313-4.875V4.658h1.78c.973 0 1.542.457 1.542 1.237 0 .802-.604 1.23-1.764 1.23zm0 3.762V8.162h1.822c1.236 0 1.887.463 1.887 1.348 0 .896-.627 1.377-1.811 1.377z"/>
  <path d="M0 4a4 4 0 0 1 4-4h8a4 4 0 0 1 4 4v8a4 4 0 0 1-4 4H4a4 4 0 0 1-4-4zm4-3a3 3 0 0 0-3 3v8a3 3 0 0 0 3 3h8a3 3 0 0 0 3-3V4a3 3 0 0 0-3-3z"/>
</svg>
      </a>
        {% endif %}
      </h5>

      <em><strong>Email:</strong> {{ member.email }}</em>
      <em><br><strong>Research interests:</strong> {{ member.research }}</em>
      <em><br><strong>Joined:</strong> {{ member.joined }}</em>
    </div>

  </div>
{% endfor %}
</div>
<h4> M.S./Ph.D. Students </h4>
<div class="members-grid">
{% for member in site.data.phd_ms_students %}
  <div class="member-card">
    <img src="{{ site.url }}{{ site.baseurl }}/images/members/{{ member.photo }}" class="img-responsive"/>
    
    <div class="member-info">
      <h5>
        {{ member.name }}
        {% if member.github %}
          <a href="{{ member.github }}" target="_blank" style="margin-left: 5px; color: black;">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor"
                 class="bi bi-github" viewBox="0 0 16 16"
                 style="vertical-align: text-bottom;">
                        <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38
                0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13
                -.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21
                1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95
                0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12
                0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27
                c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12
                .51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95
                .29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2
                0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8"/>
            </svg>
          </a>
        {% endif %}
        {% if member.blog %}
      <a href="{{ member.blog }}" target="_blank" style="margin-left: 5px; color: black">
<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-bootstrap" viewBox="0 0 16 16" style="vertical-align: text-bottom;">
  <path d="M5.062 12h3.475c1.804 0 2.888-.908 2.888-2.396 0-1.102-.761-1.916-1.904-2.034v-.1c.832-.14 1.482-.93 1.482-1.816 0-1.3-.955-2.11-2.542-2.11H5.062zm1.313-4.875V4.658h1.78c.973 0 1.542.457 1.542 1.237 0 .802-.604 1.23-1.764 1.23zm0 3.762V8.162h1.822c1.236 0 1.887.463 1.887 1.348 0 .896-.627 1.377-1.811 1.377z"/>
  <path d="M0 4a4 4 0 0 1 4-4h8a4 4 0 0 1 4 4v8a4 4 0 0 1-4 4H4a4 4 0 0 1-4-4zm4-3a3 3 0 0 0-3 3v8a3 3 0 0 0 3 3h8a3 3 0 0 0 3-3V4a3 3 0 0 0-3-3z"/>
</svg>
      </a>
        {% endif %}
      </h5>

      <em><strong>Email:</strong> {{ member.email }}</em>
      <em><br><strong>Research interests:</strong> {{ member.research }}</em>
      <em><br><strong>Joined:</strong> {{ member.joined }}</em>
    </div>

  </div>
{% endfor %}
</div>
<h4> Master Students </h4>
<div class="members-grid">
{% for member in site.data.msb_students %}
  <div class="member-card">
    <img src="{{ site.url }}{{ site.baseurl }}/images/members/{{ member.photo }}" class="img-responsive"/>
    
    <div class="member-info">
      <h5>
        {{ member.name }}
        {% if member.github %}
          <a href="{{ member.github }}" target="_blank" style="margin-left: 5px; color: black;">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor"
                 class="bi bi-github" viewBox="0 0 16 16"
                 style="vertical-align: text-bottom;">
                        <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38
                0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13
                -.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21
                1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95
                0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12
                0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27
                c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12
                .51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95
                .29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2
                0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8"/>
            </svg>
          </a>
        {% endif %}
        {% if member.blog %}
      <a href="{{ member.blog }}" target="_blank" style="margin-left: 5px; color: black">
<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-bootstrap" viewBox="0 0 16 16" style="vertical-align: text-bottom;">
  <path d="M5.062 12h3.475c1.804 0 2.888-.908 2.888-2.396 0-1.102-.761-1.916-1.904-2.034v-.1c.832-.14 1.482-.93 1.482-1.816 0-1.3-.955-2.11-2.542-2.11H5.062zm1.313-4.875V4.658h1.78c.973 0 1.542.457 1.542 1.237 0 .802-.604 1.23-1.764 1.23zm0 3.762V8.162h1.822c1.236 0 1.887.463 1.887 1.348 0 .896-.627 1.377-1.811 1.377z"/>
  <path d="M0 4a4 4 0 0 1 4-4h8a4 4 0 0 1 4 4v8a4 4 0 0 1-4 4H4a4 4 0 0 1-4-4zm4-3a3 3 0 0 0-3 3v8a3 3 0 0 0 3 3h8a3 3 0 0 0 3-3V4a3 3 0 0 0-3-3z"/>
</svg>
      </a>
        {% endif %}
      </h5>

      <em><strong>Email:</strong> {{ member.email }}</em>
      <em><br><strong>Research interests:</strong> {{ member.research }}</em>
      <em><br><strong>Joined:</strong> {{ member.joined }}</em>
    </div>

  </div>
{% endfor %}
</div>

<h4> Undergraduate Students </h4>
<div class="members-grid">
{% for member in site.data.ug_students %}
  <div class="member-card">
    <img src="{{ site.url }}{{ site.baseurl }}/images/members/{{ member.photo }}" class="img-responsive"/>
    
    <div class="member-info">
      <h5>
        {{ member.name }}
        {% if member.github %}
          <a href="{{ member.github }}" target="_blank" style="margin-left: 5px; color: black;">
            <svg xmlns="http://www.w3.org/2000/svg"
                 width="16" height="16" fill="currentColor"
                 class="bi bi-github" viewBox="0 0 16 16"
                 style="vertical-align: text-bottom;">
              <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38
                0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13
                -.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21
                1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95
                0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12
                0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27
                c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12
                .51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95
                .29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2
                0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8"/>
            </svg>
          </a>
        {% endif %}
        {% if member.blog %}
      <a href="{{ member.blog }}" target="_blank" style="margin-left: 5px; color: black">
<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-bootstrap" viewBox="0 0 16 16" style="vertical-align: text-bottom;">
  <path d="M5.062 12h3.475c1.804 0 2.888-.908 2.888-2.396 0-1.102-.761-1.916-1.904-2.034v-.1c.832-.14 1.482-.93 1.482-1.816 0-1.3-.955-2.11-2.542-2.11H5.062zm1.313-4.875V4.658h1.78c.973 0 1.542.457 1.542 1.237 0 .802-.604 1.23-1.764 1.23zm0 3.762V8.162h1.822c1.236 0 1.887.463 1.887 1.348 0 .896-.627 1.377-1.811 1.377z"/>
  <path d="M0 4a4 4 0 0 1 4-4h8a4 4 0 0 1 4 4v8a4 4 0 0 1-4 4H4a4 4 0 0 1-4-4zm4-3a3 3 0 0 0-3 3v8a3 3 0 0 0 3 3h8a3 3 0 0 0 3-3V4a3 3 0 0 0-3-3z"/>
</svg>
      </a>
        {% endif %}
      </h5>

      <em><strong>Email:</strong> {{ member.email }}</em>
      <em><br><strong>Research interests:</strong> {{ member.research }}</em>
      <em><br><strong>Joined:</strong> {{ member.joined }}</em>
    </div>

  </div>
{% endfor %}
</div>

<br>
<h4> Alumni </h4>
{% for alumni in site.data.alumni_members %}
<em>{{ alumni.name }}</em>
{% endfor %}
