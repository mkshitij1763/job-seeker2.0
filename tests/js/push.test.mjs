import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { cardState } = require("../../src/jobseeker/web/static/push.js");
const base = { hasPush: true, standalone: true, permission: "default", subscribed: false, configured: true };

test("server without VAPID keys", () => assert.equal(cardState({ ...base, configured: false }), "unconfigured"));
test("Safari tab must install first", () => assert.equal(cardState({ ...base, standalone: false }), "install"));
test("no PushManager means install", () => assert.equal(cardState({ ...base, hasPush: false }), "install"));
test("standalone default asks", () => assert.equal(cardState(base), "ask"));
test("granted and subscribed is on", () =>
  assert.equal(cardState({ ...base, permission: "granted", subscribed: true }), "on"));
test("granted but not subscribed asks again", () =>
  assert.equal(cardState({ ...base, permission: "granted", subscribed: false }), "ask"));
test("denied is blocked", () => assert.equal(cardState({ ...base, permission: "denied" }), "blocked"));
