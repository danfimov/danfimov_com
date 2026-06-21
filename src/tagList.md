---
layout: default
pagination:
  data: collections
  size: 1
  alias: tag
permalink: /tags/{{ tag }}/
eleventyComputed:
  title: "#{{ tag }}"
  subtitle: "Posts tagged with this topic"
---

{% for post in collections[tag] %}
<article class="py-6 border-b border-line dark:border-line-dark">
  <div class="flex items-baseline justify-between gap-4">
    <h3 class="text-xl sm:text-2xl font-semibold tracking-tight leading-snug">
      <a href="{{ post.url }}" class="hover:text-accent dark:hover:text-accent-dark transition-colors">{{ post.data.title }}</a>
    </h3>
    <time class="shrink-0 font-mono text-sm text-muted dark:text-muted-dark whitespace-nowrap">{{ post.date | postDate }}</time>
  </div>
  <p class="mt-2 text-muted dark:text-muted-dark leading-relaxed">
    {{ post.data.desc or post.data.post_excerpt }}
    <a href="{{ post.url }}" class="font-medium text-accent hover:underline dark:text-accent-dark">Read&nbsp;&rarr;</a>
  </p>
</article>
{% endfor %}
