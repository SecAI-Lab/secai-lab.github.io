---
title: "Lab Members"
layout: page
sitemap: false
permalink: /members/
main_nav: true
---

<h3> Leader </h3>

{% for member in site.data.team_members %}

<img src="{{ site.url }}{{ site.baseurl }}/images/members/{{ member.photo }}" class="img-responsive" style="float: left; width: 25%; padding: 3%; border-radius: 35px;" />

<h5>{{ member.name }}</h5>
<i>{{ member.info }}
<ul style="overflow: hidden">
  <li> {{ member.education1 }} </li>
  <li> {{ member.education2 }} </li>
  <li> {{ member.education3 }} </li>
  <li> {{ member.education4 }} </li>
</ul>
{% endfor %}    
<br>
  
<h4> Ph.D. Students </h4>
{% for member in site.data.phd_students %}
<img src="{{ site.url }}{{ site.baseurl }}/images/members/{{ member.photo }}" class="img-responsive members"/>
<h5 style="padding: 3%">{{ member.name }}</h5>
<em><strong>Email:</strong> {{ member.email }}</em>
<em><br><strong>Research interests:</strong> {{ member.research }}</em>
<ul style="overflow: hidden">  
</ul>
<br>
{% endfor %}

<h4> Master Students </h4>
{% for member in site.data.msb_students %}
<img src="{{ site.url }}{{ site.baseurl }}/images/members/{{ member.photo }}" class="img-responsive members" />
<h5 style="padding: 3%">{{ member.name }}</h5>
<em><strong>Email:</strong> {{ member.email }}</em>
<em><br><strong>Research interests:</strong> {{ member.research }}</em>
<ul style="overflow: hidden">  
</ul>
<br>
{% endfor %}
<br>

<h4> Undergraduate Students </h4>
{% for member in site.data.ug_students %}
<img src="{{ site.url }}{{ site.baseurl }}/images/members/{{ member.photo }}" class="img-responsive members"/>
<h5 style="padding: 3%">{{ member.name }}</h5>
<em><strong>Email:</strong> {{ member.email }}</em>
<em><br><strong>Research interests:</strong> {{ member.research }}</em>
<ul style="overflow: hidden">  
</ul>
<br>
{% endfor %}

<br>
<h4> Alumni </h4>
{% for alumni in site.data.alumni_members %}
<em>{{ alumni.name }}</em>
{% endfor %}
