const path = require("node:path");

module.exports = function (eleventyConfig) {
  eleventyConfig.setDataDeepMerge(true);
  eleventyConfig.addPassthroughCopy({ "src/assets/generated": "assets/generated" });
  eleventyConfig.addPassthroughCopy({ "src/assets/js": "assets/js" });
  eleventyConfig.addCollection("navigation", (collectionApi) =>
    collectionApi
      .getAll()
      .filter((item) => item.data && item.data.nav)
      .sort(
        (left, right) => (left.data.nav.order || 0) - (right.data.nav.order || 0)
      )
  );

  eleventyConfig.addFilter("formatDate", (value) => {
    const date = new Date(value);
    return date.toLocaleDateString("en-US", {
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  });

  eleventyConfig.addFilter("decodeHtml", (value = "") =>
    String(value)
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&amp;/g, "&")
  );

  eleventyConfig.addFilter("stormsByAuthor", (storms, acct) =>
    (storms || []).filter((storm) => storm.author && storm.author.acct === acct)
  );

  eleventyConfig.addFilter("relativeUrl", (targetUrl, pageUrl = "/") => {
    const normalizedTarget = (targetUrl || "/").replace(/\\/g, "/");
    const normalizedPage = (pageUrl || "/").replace(/\\/g, "/");
    const targetPath = normalizedTarget.startsWith("/")
      ? normalizedTarget.slice(1)
      : normalizedTarget;
    const pagePath = normalizedPage.startsWith("/")
      ? normalizedPage.slice(1)
      : normalizedPage;
    const fromDir = pagePath.endsWith("/")
      ? pagePath.replace(/\/$/, "")
      : path.posix.dirname(pagePath);

    let relativePath = path.posix.relative(fromDir, targetPath);
    if (!relativePath) {
      relativePath = ".";
    }
    if (normalizedTarget.endsWith("/") && !relativePath.endsWith("/")) {
      relativePath = `${relativePath}/`;
    }
    return relativePath;
  });

  return {
    templateFormats: ["md", "njk"],
    markdownTemplateEngine: "njk",
    htmlTemplateEngine: "njk",
    dataTemplateEngine: "njk",
    dir: {
      input: "src",
      includes: "_includes",
      layouts: "_layouts",
      data: "_data",
      output: "../docs",
    },
  };
};
