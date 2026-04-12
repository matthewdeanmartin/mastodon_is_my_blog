const storms = require("./storms.json");

const monthFormatter = new Intl.DateTimeFormat("en-US", {
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});

function authorPath(acct) {
  return `/authors/${String(acct).toLowerCase()}/`;
}

function authorMonthPath(acct, year, month) {
  return `${authorPath(acct)}${year}/${month}/`;
}

function monthLabel(year, month) {
  return monthFormatter.format(new Date(`${year}-${month}-01T00:00:00Z`));
}

const monthBucketsByAuthor = new Map();
const stormsByAuthor = new Map();

for (const storm of storms.storms || []) {
  const acct = storm.author && storm.author.acct;
  if (!acct) {
    continue;
  }

  const monthKey = String(storm.created_at || "").slice(0, 7);
  if (!monthKey) {
    continue;
  }

  const [year, month] = monthKey.split("-");
  const authorKey = acct;

  if (!monthBucketsByAuthor.has(authorKey)) {
    monthBucketsByAuthor.set(authorKey, new Map());
  }
  if (!stormsByAuthor.has(authorKey)) {
    stormsByAuthor.set(authorKey, []);
  }

  stormsByAuthor.get(authorKey).push(storm);

  const authorMonths = monthBucketsByAuthor.get(authorKey);
  if (!authorMonths.has(monthKey)) {
    authorMonths.set(monthKey, {
      key: monthKey,
      year,
      month,
      label: monthLabel(year, month),
      count: 0,
      path: authorMonthPath(acct, year, month),
      storms: [],
    });
  }

  const monthEntry = authorMonths.get(monthKey);
  monthEntry.storms.push(storm);
  monthEntry.count += 1;
}

const authors = (storms.authors || []).map((author) => {
  const authorRecord = {
    ...author,
    path: authorPath(author.acct),
  };
  const months = Array.from(monthBucketsByAuthor.get(author.acct)?.values() || []).sort(
    (left, right) => right.key.localeCompare(left.key)
  );

  return {
    author: authorRecord,
    months,
    recentStorms: (stormsByAuthor.get(author.acct) || []).slice(0, 12),
  };
});

module.exports = {
  authors,
  authorMonths: authors.flatMap((authorArchive) =>
    authorArchive.months.map((month) => ({
      author: authorArchive.author,
      month,
      storms: month.storms,
    }))
  ),
};
