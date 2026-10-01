import assert from "node:assert/strict";
import test from "node:test";

import { duration, phaseWidths } from "../static/format.mjs";

test("duration formats milliseconds and seconds", () => {
  assert.equal(duration(350), "350 ms");
  assert.equal(duration(1250), "1.25 s");
});

test("phase widths preserve four visible phases", () => {
  const widths = phaseWidths({
    authenticationMs: 10,
    requestToHeadersMs: 20,
    headersToFirstTokenMs: 30,
    generationMs: 40,
  });
  assert.deepEqual(widths, ["10.00%", "20.00%", "30.00%", "40.00%"]);
});
