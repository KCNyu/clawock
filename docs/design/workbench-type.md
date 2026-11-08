# Workbench type table

The Workbench is one surface at 320–1440px, in light and dark, in normal,
near-limit, alert, stale, disabled, empty, loading and failed states. Type is
therefore a closed vocabulary, not a per-rule choice: every text rule in
`examples/dsh/packages/clawock-dsh/src/styles.module.css` names a token from
this table, and state/theme rules may change colour or a weight token only —
never `font-size` or `line-height`.

The table is machine-read by `tests/workbench_typography.spec.js` and
`tests/decision_studio_plugin.spec.js` (the no-literal audit). `字号值` is the
resolved value of the size token; the test asserts it against the CSS root.

| 语义角色 | 字号 token | 字重 token | 行高 token | 字号值 | 用在哪 |
| --- | --- | --- | --- | --- | --- |
| 页面标题 | `--fs-3xl` | `--fw-medium` | `--lh-3xl` | 20px | `.wb-title` |
| 分组标题 | `--fs-lg` | `--fw-medium` | `--lh-xl` | 14px | `.wb-group`, `.wb-group-title` |
| 行标题 | `--fs-lg` | `--fw-medium` | `--lh-23` | 14px | `.wb-row-title`, `.wb-hist-title` |
| 行标题（强调） | `--fs-lg` | `--fw-semibold` | `--lh-23` | 14px | `.tq-d-name` |
| 主指标 | `--fs-3xl` | `--fw-semibold` | `--lh-2xl` | 20px | `.wb-ov-metric-value` |
| 次指标 | `--fs-md` | `--fw-medium` | `--lh-lg` | 13px | `.wb-ov-value`, `.wb-headline-value` |
| 提供方指标 | `--fs-md` | `--fw-bold` | `--lh-lg` | 13px | `.wb-prov-primary` |
| 说明/meta | `--fs-md` | `--fw-regular` | `--lh-21` | 13px | `.wb-row-sub`, `.wb-hist-meta`, `.wb-ov-note` |
| chip | `--fs-xs` | `--fw-regular` | `--lh-sm` | 11px | `.wb-ov-chip`, `.tq-tag` |
| 按钮 | `--fs-md` | `--fw-medium` | `--lh-lg` | 13px | `.wb-act`, `.tq-pill` |
| tab | `--fs-lg` | `--fw-regular` | `--lh-xl` | 14px | `.wb-tab`, `.wb-groupby-btn` |
| 空态标题 | `--fs-lg` | `--fw-regular` | `--lh-xl` | 14px | `.wb-empty-title` |
| 错误文本 | `--fs-sm` | `--fw-regular` | `--lh-md` | 12px | `.wb-notice`, `.wb-providers-error`, `.tq-stats-error-text` |
| 角标数字 | `--fs-badge` | `--fw-bold` | `--lh-xs` | 9px | `.wb-tab-alert`, `.wb-rail-alert` |
| 计数角标 | `--fs-micro` | `--fw-semibold` | `--lh-xs` | 10px | `.wb-tab-count` |
| 字段标签 | `--fs-xs` | `--fw-semibold` | `--lh-sm` | 11px | `.wb-needs-label`, `.wb-ov-sec-title` |
| 详情正文 | `--fs-md` | `--fw-regular` | `--lh-lg` | 13px | `.tq-d-v`, `.tq-d-k` |
| 长文本（Needs you） | `--fs-xl` | `--fw-regular` | `--lh-prose` | 15px | `.wb-needs` |
| 浮层标题 | `--fs-lg` | `--fw-semibold` | `--lh-lg` | 14px | `.wb-sheet-title` |

## Rules the table encodes

- **One role, one size.** A state selector such as `[data-wb-tone=alert]`,
  `[data-wb-provider-state=stale]`, `:disabled`, `.wb-providers-empty` or
  `body[data-ds-dark-theme]` may change `color`, `background`, `border-color`
  or a `--fw-*` token; it may not change `font-size` or `line-height`.
- **One weight ladder.** `400` regular, `500` medium, `600` semibold, `700`
  bold. The previous 550/650 steps collapsed into 500/600; nothing reads a
  numeric weight directly.
- **One line-height ladder.** Whole-pixel lines for one-line UI (`--lh-2xs` =
  12px … `--lh-2xl` = 24px) and ratios for prose (`--lh-prose` = 1.55).
- **One tracking ladder.** `--ls-tight` … `--ls-caps-wide`; no literal
  `letter-spacing`.
- **No raw declarations.** `tests/workbench_typography.spec.js` fails on
  `font-size:\s*[0-9]`, `line-height:\s*[0-9]`, `letter-spacing:\s*[0-9.-]` or
  `font-weight:\s*[0-9]` anywhere in the stylesheet or in `client.ts` inline
  styles. The only numeric `font-size` values allowed are the token
  definitions (`--fs-*`) — the test allow-lists exactly those lines.

## Host gap (why the package owns the ladder)

`dsh-client-ui-theme` publishes the font **family** (`--dsw-font-family`,
`--ds-font-family-code`) and a few composite shorthands
(`--dsw-font-xxs-12`, `--dsw-font-xs-13`, `--dsw-font-s-strong-14`,
`--dsw-font-xxs-strong-12`, `--dsw-font-markdown-code-block`) but no
size-only `--dsw-font-size-*` ladder. The existing `.pbc` rows keep using the
host shorthands where they fit (marked `宿主`); the Workbench roles above use
the package's `--fs-*` / `--lh-*` / `--fw-*` because the host has no equivalent
single-property token. This is a declared **宿主缺口**, not a second ladder:
no role may introduce another px step.

## Verification (same batch)

- `grep -nE "font-size:\s*[0-9]" src/styles.module.css src/client.ts` → only
  the `--fs-*` token lines, never a rule.
- `getComputedStyle` on `.wb-prov-name`, `.wb-prov-primary`, `.wb-prov-meta`,
  `.wb-tab-label` in normal / near-limit / alert / stale rows, light and dark:
  the computed `font-size`, `line-height` and `font-weight` are identical per
  role (values are printed by `tests/workbench_overlap.spec.js`).
- Light/dark screenshots at 320, 390 and 1280.
