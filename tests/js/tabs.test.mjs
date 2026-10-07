import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { resolveTab } = require("../../src/jobseeker/web/static/tabs.js");

test("requested tab wins when it exists", () => assert.equal(resolveTab(["people", "draft", "job"], "draft", "people"), "draft"));
test("unknown request falls back", () => assert.equal(resolveTab(["people", "draft", "job"], "nope", "job"), "job"));
test("missing fallback picks the first", () => assert.equal(resolveTab(["a", "b"], null, "zzz"), "a"));
test("no tabs gives empty", () => assert.equal(resolveTab([], "a", "b"), ""));
