// Preloaded via `node --import` to stub the global fetch that search.mjs calls,
// so search.test.mjs can exercise every Tavily runtime outcome deterministically
// and offline. Behaviour is selected by TAVILY_TEST_FETCH_MODE.
const mode = process.env.TAVILY_TEST_FETCH_MODE;

const resp = (init, body) => ({
  ok: init.ok,
  status: init.status,
  text: async () => body ?? "",
  json: async () => {
    if (init.badjson) throw new Error("Unexpected token < in JSON");
    return JSON.parse(body);
  },
});

globalThis.fetch = async () => {
  if (mode === "network") throw new Error("ECONNRESET (simulated)");
  if (mode === "httpError") return resp({ ok: false, status: 429 }, "rate limited");
  if (mode === "badjson") return resp({ ok: true, status: 200, badjson: true }, "<<not json>>");
  if (mode === "success") {
    return resp(
      { ok: true, status: 200 },
      JSON.stringify({
        answer: "ANS",
        results: [{ title: "T1", url: "http://u", content: "C", score: 0.9 }],
      }),
    );
  }
  throw new Error(`unknown TAVILY_TEST_FETCH_MODE: ${mode}`);
};
