import syntaxHighlight from "@11ty/eleventy-plugin-syntaxhighlight";
import markdownIt from "markdown-it";
import markdownItAnchor from "markdown-it-anchor";
import { DateTime } from "luxon";
import * as yaml from "js-yaml";

export default function (eleventyConfig) {
  // Plugins
  eleventyConfig.addPlugin(syntaxHighlight);

  // Merge tags from data cascade
  eleventyConfig.setDataDeepMerge(true);

  // Current year, for the footer copyright line
  eleventyConfig.addGlobalData("buildYear", () => `${new Date().getFullYear()}`);

  // Read .yml/.yaml data files. Each post is <slug>/index.md, so its sibling
  // index.yml is picked up automatically as that template's data file.
  eleventyConfig.addDataExtension("yml,yaml", (contents) => yaml.load(contents));

  // Copy static files to the output folder
  eleventyConfig.addPassthroughCopy("src/assets");
  eleventyConfig.addPassthroughCopy("src/manifest.json");

  // Copy each post's co-located images/ folder next to its page,
  // e.g. src/posts/<slug>/images/* -> /posts/<slug>/images/*
  eleventyConfig.addPassthroughCopy("src/posts/**/images");

  // Excerpts
  eleventyConfig.setFrontMatterParsingOptions({
    excerpt: true,
    excerpt_alias: "post_excerpt",
    excerpt_separator: "<!-- excerpt -->",
  });

  // Estimated reading time (minutes)
  eleventyConfig.addFilter("readTime", (value) => {
    const textOnly = String(value).replace(/(<([^>]+)>)/gi, "");
    return Math.max(1, Math.floor(textOnly.length / 450));
  });

  eleventyConfig.addFilter("postDate", (dateObj) => {
    const dt =
      dateObj instanceof Date
        ? DateTime.fromJSDate(dateObj)
        : DateTime.fromISO(String(dateObj));
    return dt.toFormat("yyyy-MM-dd");
  });

  // Markdown with header anchors
  const md = markdownIt({ html: true, linkify: true });
  md.use(markdownItAnchor, {
    level: [1, 2],
    permalink: markdownItAnchor.permalink.headerLink({
      safariReaderFix: true,
      class: "header-anchor",
    }),
  });
  eleventyConfig.setLibrary("md", md);

  // {% asset_img 'name.jpg', 'alt' %} — resolves to the current post's
  // images/ folder; pass an optional third arg to override the base path.
  eleventyConfig.addShortcode("asset_img", function (filename, alt = "", path) {
    const base = path ?? `${this.page.url}images/`;
    return `<img class="my-4" src="${base}${filename}" alt="${alt}" />`;
  });

  // {% asset_video 'clip.mp4', 'cover.png' %} — embeds a local video from the
  // current post's images/ folder; optional second arg is a poster image,
  // optional third arg overrides the base path.
  eleventyConfig.addShortcode("asset_video", function (filename, poster = "", path) {
    const base = path ?? `${this.page.url}images/`;
    const posterAttr = poster ? ` poster="${base}${poster}"` : "";
    return `<video class="my-4" controls preload="metadata"${posterAttr} src="${base}${filename}"></video>`;
  });

  return {
    dir: {
      input: "src",
      output: "_site",
    },
    templateFormats: ["md", "njk", "html", "liquid"],
    markdownTemplateEngine: "njk",
    htmlTemplateEngine: "njk",
  };
}
