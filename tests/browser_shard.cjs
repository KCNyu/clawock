"use strict";
const { createHash } = require("node:crypto");

// Select whole browser cases: each owns its page/context and its cleanup.
// Every named case, including newly added ones, belongs to exactly one shard.
function browserShard(env = process.env) {
  const indexText = env.CI_BROWSER_SHARD_INDEX;
  const totalText = env.CI_BROWSER_SHARD_TOTAL;
  if (indexText === undefined && totalText === undefined) return () => true;
  const index = Number(indexText), total = Number(totalText);
  if (indexText === "" || totalText === "" || !Number.isInteger(index) ||
      !Number.isInteger(total) || total < 1 || index < 0 || index >= total) {
    throw new Error("CI_BROWSER_SHARD_INDEX must be in [0, CI_BROWSER_SHARD_TOTAL)");
  }
  return name => createHash("sha256").update(name).digest().readUInt32BE(0) % total === index;
}
module.exports = { browserShard };
