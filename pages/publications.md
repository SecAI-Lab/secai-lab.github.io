---
title: "Publications"
layout: page
sitemap: false
permalink: /publications/
main_nav: true
---


<!-- ## Publications -->


<input type="text" class="form-control" id="search-input" placeholder="Search...">
<br>
<div class="list-group mt-5" id="results-container">   
</div>


### Highlighted Projects

See [Full list](#full-list) ([Google Scholar](https://scholar.google.ch/citations?user=Jaws2sYAAAAJ))

{% assign number_printed = 0 %}
{% for publi in site.data.publist-conferences %}

{% assign even_odd = number_printed | modulo: 2 %}
{% if publi.highlight == 1 %}

{% if even_odd == 0 %}
<div class="row">
{% endif %}

<div class="container">
 <div class="well">
  <pubtit>{{ publi.title }}</pubtit>
  <img src="{{ site.url }}{{ site.baseurl }}/images/pubs/{{ publi.image }}" class="img-responsive" style="float: left; width: 40%; padding: 3%" /> 
  <p>{{ publi.description }}</p>
  <p><em>{{ publi.authors }}</em></p>
  <p><strong><a href="{{ publi.link.url }}">{{ publi.link.display }}</a></strong></p>
  <p class="text-danger"><strong> {{ publi.news1 }}</strong></p>
  <p> {{ publi.news2 }}</p>
 </div>
</div>

{% assign number_printed = number_printed | plus: 1 %}

{% if even_odd == 1 %}
</div>
{% endif %}

{% endif %}
{% endfor %}

{% assign even_odd = number_printed | modulo: 2 %}
{% if even_odd == 1 %}
</div>
{% endif %}

<p> &nbsp; </p>


<a name="full-list">
### Publications: International Conferences and Journals

{% for publi in site.data.publist-conferences %}

  {{ publi.title }} <br />
  <em>{{ publi.authors }} </em><br /> 
  <a href="{{ publi.link.url }}">{{ publi.link.display }}</a><br />
  <a href="{{ publi.link2.url }}">{{ publi.link2.display }}</a>

{% endfor %}

<br><br>
### Publications: Workshops and Domestic Conferences

{% for publi in site.data.publist-workshops %}

  {{ publi.title }} <br />
  <em>{{ publi.authors }} </em><br />
  <a href="{{ publi.link.url }}">{{ publi.link.display }}</a><br />
  <a href="{{ publi.link2.url }}">{{ publi.link2.display }}</a>

{% endfor %}
