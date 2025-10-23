---
title: "News"
layout: page
permalink: /news/
main_nav: true
sitemap: true
---

{% for article in site.data.news %}

<p>{{ article.date }} <br>
<em>{{ article.headline }}</em></p>
{% endfor %}
