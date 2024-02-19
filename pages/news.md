---
title: "News"
layout: page
sitemap: false
permalink: /news/
main_nav: true
---

{% for article in site.data.news %}
<p>{{ article.date }} <br>
<em>{{ article.headline }}</em></p>
{% endfor %}