async page => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("http://127.0.0.1:8027");
  await page.locator("#status").filter({hasText: "Lokální statický preview"}).waitFor();
  if (!await page.locator("#run").isDisabled()) throw new Error("Local preview attempted a live call");
  for (const width of [1440, 820, 375, 320]) {
    await page.setViewportSize({width, height: 1000});
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) {
      throw new Error("Horizontal page overflow at " + width);
    }
  }
  // Only test routes are mocked; the application has no fake-live mode.
  await page.route("**/api/config", route => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({live: true, prompt: "TEST FIXTURE", offers_csv: "TEST CSV", csrf: "test-csrf"}),
  }));
  const events = [
    {type: "accepted", agent: "test-agent", agent_version: "1", conversation_id: "test-conversation"},
    {type: "tool", id: "fc-skill", name: "skill", status: "started"},
    {type: "tool", id: "fc-skill", name: "skill", status: "completed"},
    {type: "tool", id: "ws-1", name: "web_search_call", status: "started"},
    {type: "tool", id: "ws-1", name: "web_search", status: "in_progress"},
    {type: "tool", id: "ws-1", name: "web_search", status: "searching"},
    {type: "tool", id: "ws-1", name: "web_search", status: "completed"},
    {type: "tool", id: "ws-1", name: "web_search_call", status: "completed"},
    {type: "tool", id: "lsh-1", name: "shell_call", status: "started"},
    {type: "tool", id: "lsh-1", name: "shell_call", status: "completed"},
    {type: "result", text: "**Doporučení:** <img src=x onerror=alert(1)> `celkem`\n\n| Nabídka | Stav |\n| --- | --- |\n| A | **splňuje** |", verified: true, response_id: "test-response",
     warnings: [], files: [{filename: "budget.json", url: "/api/files/test-fixture"}],
     citations: [{title: "Test citation", url: "https://example.com/advice"}],
     budget: {offers: [
       {id: "A", name: "Atelier A", base_czk: "19200", total_czk: "21120", eligible: true, reasons: []},
       {id: "B", name: "Forum B", base_czk: "24400", total_czk: "26840", eligible: false, reasons: ["budget"]},
     ]}},
  ];
  await page.route("**/api/run", async route => {
    const request = route.request();
    if (request.headers()["x-csrf-token"] !== "test-csrf" || request.postData() !== "{}") {
      throw new Error("Wrong fixed prompt/CSRF request");
    }
    await route.fulfill({contentType: "application/x-ndjson", body: events.map(event => JSON.stringify(event)).join("\n") + "\n"});
  });
  await page.reload();
  await page.locator("#run:not([disabled])").waitFor();
  await page.locator("#run").click();
  await page.getByText("Dokončeno a ověřeno.", {exact: true}).waitFor();
  if (await page.locator("#result img").count()) throw new Error("Untrusted HTML was executed");
  if (await page.locator("#result strong").count() < 2) throw new Error("Markdown bold was not rendered");
  if (await page.locator("#result table").count() !== 1) throw new Error("Markdown table was not rendered");
  if (await page.locator("#trace li.trace-item").count() !== 3) throw new Error("Tool lifecycle events were not grouped by call id");
  if (await page.locator("#trace li.trace-item[data-state='completed']").count() !== 3) throw new Error("Completed state not updated");
  if (!await page.getByText("přes limit", {exact: true}).count()) throw new Error("Missing rejection reason");
  await page.getByRole("link", {name: "Stáhnout budget.json"}).waitFor();
  await page.route("**/api/run", route => route.fulfill({
    status: 429, contentType: "application/json", body: '{"detail":"Test rate limit"}',
  }));
  await page.locator("#run").click();
  await page.getByText("Test rate limit", {exact: true}).waitFor();
  if (await page.locator("#run").isDisabled()) throw new Error("Error state did not recover");
  if (errors.length) throw new Error(errors.join("\n"));
  await page.unroute("**/api/config");
  await page.unroute("**/api/run");
  await page.setViewportSize({width: 1440, height: 1000});
  await page.reload();
  await page.screenshot({path: "workshop-preview-final.png"});
  return {staticPreview: true, mockWorkflow: true, rateLimitRecovery: true, xssSafe: true, errors};
}
