---
title: "Gallery"
layout: page
sitemap: false
permalink: /gallery/
main_nav: true
---

<div class="gallery-container">
  {% for group in site.data.gallery %}
    <div class="gallery-box">
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

<!-- Lightbox 추가 -->
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/lightbox2/2.11.3/css/lightbox.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/lightbox2/2.11.3/js/lightbox.min.js"></script>
