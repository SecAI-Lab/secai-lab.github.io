---
title: "Research"
layout: page
permalink: /research/
main_nav: true
sitemap: true
---

**Research Aims**

<img src="{{ site.url }}{{ site.baseurl }}/images/r1.png" style="max-width:none; width: auto; height: auto;">
In essence, our lab advances practical security by protecting software and data in 
real-world environments. We study both offensive and defensive 
dimensions of security by understanding attacks 
(e.g., code injection, code reuse), designing robust
defenses (e.g., attack surface reduction, moving target defense), and
investigating security-relevant artifacts (e.g., digital forensics).
As new technologies emerge, they introduce novel attack vectors, 
necessitating additional (and adaptive) layers of defense.

<img src="{{ site.url }}{{ site.baseurl }}/images/r2.png" style="max-width:none; width: auto; height: auto;">

To achieve our objectives, we investigate the essential processes involved in 
executable binaries to understand the underlying code semantics. These stages includes
1) code generation that transforms high-level source into machine code; 
2) obfuscation techniques that intentionally hinder analysis; 
3) static and dynamic analysis that reasons about structural and behavioral properties;
4) bug discovery that inspects program behaviors to uncover vulnerabilities;
5) patching that fixes security flaws directly at the binary level, and 
6) decompilation that reconstructs higher-level representations to support reversing.

As illustrated above, in the era of artificial intelligence (AI), one of our key research areas envisions
the unification of traditionally separate tasks into an AI-driven pipeline. 
Such a holistic approach forms the foundation of robust security analysis, enabling 
robust, scalable, and resilient security analysis of both benign and malicious software.

<img src="{{ site.url }}{{ site.baseurl }}/images/r3.png" style="max-width:none; width: auto; height: auto;">

Another direction lies in securing AI modelsi as the above illustration. We tackle the security challenges 
and defenses spanning the AI lifecycle, from data collection and training to deployment 
and inference. Our research addresses threats such as poisoning, backdoors, evasion, 
extraction, inversion, and membership inference, and develops holistic defenses 
including sanitization, adversarial training, unlearning, and watermarking
to build robust, trustworthy, and privacy-preserving AI systems.

<div class="mermaid">
gantt
  title Ongoing Projects with Fundings
  dateFormat  YYYY-MM-DD
  axisFormat  %m/%y
  section Fundings
  [12] Modular AI Watermarking : 2025-06-01, 36M
  [11] Binary Micro-patching: 2024-06-01, 33M
  [10] Securing Memory-Safety Languages: 2024-06-01, 48M
</div>

<script type="module">
  import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
  mermaid.initialize({ startOnLoad: true });
</script>

**Fundings (Past to Present)**

[12] _Research Laboratory for Modular AI Watermarking for Generative AI Compliance_,
Supported by NRF (National Research Foundation of Korea);
A joint project led by [Jonguk Hou](https://mmc.hallym.ac.kr/) at Hallym University.

[11] _Binary Micro-Security Patch Technology Applicable with Limited Reverse Engineering_
Supported by IITP (Institute of Information & Communications Technology Planning & Evaluation);
A joint project led by [Jooyong Yi](http://www.jooyongyi.com/) at Ulsan National Institute of Science and Technology (UNIST).

[10] _Development of Integrated Platform for Expanding and Safety Applying Memory-safe Languages_
Supported by IITP (Institute of Information & Communications Technology Planning & Evaluation);
A joint project led by [Yuseok Jeon](https://www.ysjeon.net/) at Korea University.

<hr>

[9] _Proofs and Responses against Evidence Tampering in the New Digital Environment_,
Supported by IITP (Institute of Information & Communications Technology Planning & Evaluation);
A joint project led by [Hyoungkee Choi](https://sites.google.com/g.skku.edu/meoseriful/)
at Sungkyunkwan University (SKKU).

[8] _AI Platform to Fully Adapt and Reflect Privacy-Policy Changes_,
Supported by IITP (Institute of Information & Communications Technology Planning & Evaluation);
A joint project led by [Simon Woo](https://dash-lab.github.io/About/)
at Sungkyunkwan University (SKKU).

[7] _A Generalizable and Continual Deep Learning Model for Inferring the Context of Binary Codes_,
Supported by NRF (National Research Foundation of Korea).

[6] _Code Unpacking Intermediate Representation Conversion_,
Supported by NSRI (National Security Research Institute).

[5] _A Metric to Measure the Quality of Decompiled Codes_,
Supported by NSRI (National Security Research Institute);
A joint project led by [Sungjae Hwang](https://softsec-lab.github.io/)
at Sungkyunkwan University (SKKU).

[4] _Efficient Fuzzing for Internal Communication Protocols with Firmware of Unmanned Vehicles_,
Supported by NSRI (National Security Research Institute);
A joint project led by [Daehee Jang](https://daehee87.github.io/)
at Sungshin Women's University.

[3] _Semantic-aware Executable Binary Code Representation and its Applications with BERT._,
Supported by NRF (National Research Foundation of Korea).

[2] _Autonomous Car Security as part of Advance Research and Development for Next-generation Security._,
Supported by IITP (Institute of Information & Communications Technology Planning & Evaluation);
A joint project led by
[Yuseok Jeon](https://ysjeon.net/) at Ulsan National Institute of Science and Technology (UNIST),
[Haehyun Cho](https://haehyun.github.io/) at Soongsil University, and
[Dokyung Song](https://cysec.yonsei.ac.kr/~dokyungs/) at Yonsei University.\*

[1] _Vulnerability Analysis on IoTivity Protocol Provisioning._,
Supported by NSRI (National Security Research Institute);
A joint project led by
[Hyongkee Choi](https://sites.google.com/g.skku.edu/meoseriful/) and
[Jaehoon Paul Jeong](http://iotlab.skku.edu/) at Sungkyunkwan University (SKKU).
