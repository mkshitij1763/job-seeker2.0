import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { decide, release, parseOutcome, withoutFlash } = require("../../src/jobseeker/web/static/swipe.js");
const at = (x, y, t = 0) => ({ x, y, t });

test("small moves are undecided", () => assert.equal(decide(at(100, 100), at(105, 104)).mode, "none"));
test("vertical move is a scroll", () => assert.equal(decide(at(100, 100), at(108, 140)).mode, "scroll"));
test("diagonal drift is a scroll", () => assert.equal(decide(at(100, 100), at(120, 115)).mode, "scroll"));
test("horizontal move locks to swipe after 10px", () => assert.equal(decide(at(100, 100), at(115, 103)).mode, "swipe"));
test("edge start is ignored", () => assert.equal(decide(at(10, 100), at(140, 100)).mode, "none"));
test("far left release skips", () => assert.equal(release(at(300, 100, 0), at(160, 100, 600), 360), "skip"));
test("far right release snoozes", () => assert.equal(release(at(60, 100, 0), at(200, 100, 600), 360), "snooze"));
test("short slow release snaps back", () => assert.equal(release(at(200, 100, 0), at(150, 100, 600), 360), null));
test("fast flick commits", () => assert.equal(release(at(200, 100, 0), at(140, 100, 80), 360), "skip"));
test("tiny fast jitter does not commit", () => assert.equal(release(at(200, 100, 0), at(180, 100, 10), 360), null));
test("parseOutcome success reads msg", () =>
  assert.deepEqual(parseOutcome("http://h/?msg=Marked%20skipped", true, 200), { ok: true, message: "Marked skipped" }));
test("parseOutcome reports err from redirect", () =>
  assert.deepEqual(parseOutcome("http://h/applications/3?err=Can%27t%20move", true, 200), { ok: false, message: "Can't move" }));
test("parseOutcome reports HTTP failures", () =>
  assert.deepEqual(parseOutcome("http://h/applications/3/snooze", false, 500), { ok: false, message: "Request failed (HTTP 500)" }));
test("withoutFlash drops msg/err but keeps filters", () =>
  assert.equal(withoutFlash("https://h/?band=all&msg=Marked%20skipped&city=Pune"), "/?band=all&city=Pune"));
test("withoutFlash on a clean URL is just the path", () =>
  assert.equal(withoutFlash("https://h/?err=x"), "/"));
