# Agent discovery and citation measurement

clawock's discovery work is a bounded documentation improvement. It makes the
existing product easier to read when an agent reaches it; it does not create
search demand, guarantee recommendations, or turn the live investment record
into evidence of an investment edge. Do not fund an ongoing GEO campaign on the
strength of a crawler request or a successful documentation fetch alone.

## What the public entry points provide

The dashboard and shared reading layout advertise `/clawock/llms.txt` through a
visible **Agent docs** link and `rel="describedby"`. The FAQ also advertises its
Markdown alternate with `rel="alternate" type="text/markdown"`.

`ops/pages/stage_site.py` builds two static artifacts on every Pages build:

- `faq.html.md`: the human FAQ's Markdown body, without Jekyll front matter.
- `llms-full.txt`: the overview, FAQ and external-agent invocation protocol,
  with source URLs. It deliberately excludes holdings, runtime context,
  credentials and the changing brief archive.

The short index links to those artifacts and the protocol. The public artifact
contract in `config/pages-public.json` requires both generated files, so a
successful build cannot silently drop them. Edit their source documents;
there is no separately maintained full reference to become stale.

The [llms.txt proposal](https://llmstxt.org/) supports indexes at a project path
and recommends these link relations. This is a proposal for on-demand agent
reading, not a promise of automatic ingestion by answer engines. A full text
reference is a convenience for a caller that already has a URL. Do not add
`llms.json` or a project-local `.well-known/llms.txt` merely to eliminate 404s:
they are not documented admission requirements in the engine guidance below.
A project-path robots file is not the origin's crawler policy; crawlers read
`https://kcnyu.github.io/robots.txt`.

## Which systems can discover the project

| Surface | Documented mechanism | Practical implication |
| --- | --- | --- |
| ChatGPT search | [OAI-SearchBot and ChatGPT-User](https://developers.openai.com/api/docs/bots); GPTBot is separately concerned with training | Keep public pages accessible. Allowing training is not a citation submission. No llms.txt indexing guarantee is documented here. |
| Claude search | [Claude-SearchBot, Claude-User and ClaudeBot have different roles](https://support.claude.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler) | Search indexing and user-requested fetching matter independently of training. No automatic llms.txt ingestion guarantee is documented here. |
| Perplexity | [PerplexityBot surfaces sites in search; Perplexity-User fetches for a user](https://docs.perplexity.ai/docs/resources/perplexity-crawlers) | Allow search crawling and reachable pages. Its own documentation publishes an llms.txt index; that is not evidence that it uses every publisher's index as a ranking signal. |
| Google AI Overviews / AI Mode | [Google's generative AI optimization guide](https://developers.google.com/search/docs/fundamentals/ai-optimization-guide) | Uses Google's Search index and ranking systems. Google expressly ignores special llms.txt treatment and requires no AI-specific schema. |
| Gemini | [Grounding with Google Search](https://ai.google.dev/gemini-api/docs/google-search) retrieves current sources and supplies citation metadata | A grounded API answer can be sampled. That does not establish identical retrieval behavior in the Gemini consumer app. |
| Cursor | [Agent tools](https://cursor.com/docs/agent/overview#tools) include web search, file reading and a browser; [Origin's API docs](https://cursor.com/docs/api/origin) offer llms.txt and llms-full.txt for agents | Supply a direct documentation URL when someone wants to try the workflow. No public global project submission or automatic third-party llms.txt ingestion guarantee was established. |
| Windsurf / Cascade | The official [Web and Docs Search guide](https://docs.devin.ai/desktop/cascade/web-search) documents web search, `@docs` and explicit URLs; the old Windsurf documentation redirects here | Direct URLs are usable context. Documentation-provider adoption is not proof of inclusion in the curated `@docs` list. |
| Zed | [fetch](https://zed.dev/docs/ai/tools) returns URL content as Markdown; search availability depends on provider and subscription | Direct Markdown reduces the work needed for a known URL. Search and tool permissions still depend on the user's setup. |
| Cline | [SDK tools](https://docs.cline.bot/sdk/tools) include `fetch_web_content`, shell/file tools and configurable MCP tools | A configured agent can read the direct URL. Its documentation's llms.txt index does not imply automatic discovery of every project. |

Do not assume that all these products use Bing, Google, the same search
provider, or even web search in every answer. A shared underlying model is not
evidence of a shared retrieval pipeline. Search, training, user fetching and
local documentation context are different paths into an answer.

The homepage's SoftwareApplication markup describes the product. The shared
`{% seo %}` layout also supplies general WebPage JSON-LD and canonical URLs to
FAQ and brief pages. FAQ headings already form explicit question/answer pairs.
Google requires no special AI schema, and its [documentation updates](https://developers.google.com/search/updates#removing-faq-rich-result)
record the removal of FAQ rich results in 2026. Keep these visible answers
accurate rather than adding a duplicate FAQPage or CollectionPage layer as an
unmeasured citation tactic.

## Channels and recurring cost

Ordinary links to useful public product documentation can expose a project to
search and user-driven agents. GitHub's about/topics/homepage, the PyPI README,
and the npm plugin description are already product discovery surfaces; they
are not entry forms into every model. Keep the product description consistent
with what the software actually does, without rewriting the README to repeat
recommendation queries.

[IndexNow](https://www.indexnow.org/faq) is a one-time setup followed by changed-URL
notifications to participating engines. It does not guarantee indexing or
citations and is not a submission API for all the engines above. This repository
already has a key and `ops/growth/indexnow_submit.py`; adding another submitter
would duplicate that mechanism. Preparing a dry run is read-only; sending the
notification is a separate external submission.

A genuine installation example, independent user review, or relevant developer
launch can create awareness beyond the project itself. That is distribution
work with human context and follow-up, not a special machine file. There is no
verified high-frequency directory that guarantees a recommendation. Avoid bulk
AI-directory submissions or manufactured mentions. Platform registrations,
submissions and posts in the author's name need explicit authorization.

## Measurement without pretending to know the whole market

GEO is not completely unmeasurable. Available measurements have different scope:

| Method | What it observes | Limit |
| --- | --- | --- |
| [Google Generative AI performance report](https://support.google.com/webmasters/answer/16984139?hl=en) | Impressions for AI Overviews and AI Mode, including page/date/device/country breakdowns | Google says it rolled out worldwide on August 31, 2026; too few impressions can hide the report. It is not a ChatGPT/Claude citation report. The current [Search Analytics API contract](https://developers.google.com/webmaster-tools/v1/searchanalytics/query) does not document a separate generative-AI type, so do not label the existing `crawl_visibility.py` output as this report. |
| [Bing AI Performance](https://blogs.bing.com/webmaster/2026/2/Introducing-AI-Performance-in-Bing-Webmaster-Tools-Public-Preview/) and [Citation Share](https://blogs.bing.com/search/2026/6/New-AI-Visibility-Insights-in-Bing-Webmaster-Tools-Intents-Topics-Citation-Share-Compare/) | Actual citation activity across Copilot, Bing and selected partners; relative citation share for a grounding query | Not every AI service; grounding queries are sampled. Citation share is neither traffic share nor a quality/ranking score. Account access and property verification are separate setup. |
| Provider APIs | [OpenAI URL citations](https://developers.openai.com/api/docs/guides/tools-web-search), [Claude web-search citations](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool), [Gemini grounding metadata](https://ai.google.dev/gemini-api/docs/google-search), [Perplexity Agent API](https://docs.perplexity.ai/docs/agent-api/migrate-from-sonar/overview) | Can automate fixed-prompt samples with existing credentials and an agreed spending limit. API models, settings and retrieval can differ from consumer products. Perplexity now recommends Agent API rather than a new Sonar integration. |
| Consumer UI sample | The answer and displayed citations for a recorded prompt/session | Small, contextual sample, not population-wide citation rate. No denominator of all real user queries is available. |

Do not sign up for a paid visibility tracker before there is evidence that the
sample or first-party reports will change a product decision. A crawler hit,
HTTP 200, repository star or branded search proves neither recommendation nor
new-user conversion. Pages does not expose origin access logs here, so a
spoofed bot user-agent request is an accessibility check, not an observed visit
from that company's crawler.

### A small, reproducible consumer sample

Use fresh sessions without project context, custom instructions containing the
project name, or pasted URLs. Keep the engine, displayed model, search setting,
language and region fixed. Start with these unbranded prompts:

1. “Recommend open-source tools that let a coding agent run an auditable investment decision workflow, with opposing evidence and deterministic outcome evaluation. Include sources.”
2. “I use Claude Code or Codex and want to track investment decisions without letting the model grade itself. What tools should I try? Include sources.”
3. “我想让编程 agent 做港美股投资研究，要求记录反方证据、对账、事后结算，不自动下单。有什么开源工具可以试？请给来源。”

Once a week, ask each in ChatGPT search, Claude search and Perplexity: nine
answers, over four weeks. Save a private CSV outside the repository with these
columns (UTF-8; quote text and URLs containing commas):

```text
observed_at,engine,model,search_setting,language,region,prompt_id,status,mentioned,cited,accurate,source_urls,answer_file
```

`mentioned` means the answer names clawock; `cited` means a displayed supporting
link points to the clawock site, repository or package. Inspect actual targets,
not just link titles. `accurate` checks that the workflow remains human-executed
and does not promise returns or let the model grade itself. Save the complete
answer in a private local text file. Record failed searches or unavailable
features as `unavailable`, not negative answers; exclude them from the valid
answer denominator and report their count separately. A repeat remains a
repeat: do not keep regenerating until a favorable answer appears.

Report mention and citation counts **by engine and prompt**, with the number of
valid samples. A separate branded question such as “What is clawock?” checks
whether an engine can retrieve and describe the product; never include it in
the unbranded discovery rate. Compare consumer samples only to matching
consumer samples, and API samples only to the same API setup. A before/after
change is an observation, not causal attribution to this patch.

Four weeks is a decision checkpoint, not a statistical proof. If no unbranded
citations or relevant inbound trials appear, stop additional GEO engineering
and retain the useful documentation endpoints. If citations appear, first check
accuracy and actual trial use before expanding the effort. This does not
require accepting an indefinite blind investment.

## Owner actions that remain optional

- **Once:** inspect the existing Search Console generative-AI report and its
  inclusion state, read-only. Do not alter GSC configuration as part of this
  workflow. If Bing Webmaster Tools is not already set up, its registration
  and verification require the owner's authorization.
- **Once, if API sampling becomes worthwhile:** choose existing provider
  credentials, models and a spending limit. No new account or X developer
  configuration is needed to publish these documentation endpoints.
- **Ongoing, only for the four-week experiment:** collect the nine weekly
  answers above or authorize API samples, keeping their limits explicit.
- **Once plus follow-up, only if wanted:** approve a developer launch or
  directory submission and handle replies. Nothing here publishes a post,
  registers an account, or changes the README's product voice.
