# Custom (tree-shaken) ECharts bundle

`site/assets/js/echarts.min.js` is **not** the stock ECharts dist. It is a tree-shaken
build that registers only the chart types and components this dashboard uses, so it
is ~620KB instead of ~1MB (gzip ~202KB vs ~334KB) and parses ~40% faster on mobile.
It exposes the exact same global surface the app relies on — `window.echarts.init(...)`
and `window.echarts.color.modifyAlpha(...)` — so no calling code changes.

Verified pixel-identical to the full dist across all 6 tabs × dark/light (0.000%
pixel diff, identical canvas dimensions, no new console warnings) and through the
full GIF/social-card capture pipeline (`shoot_dashboard.js`).

## When to rebuild

- Bumping the ECharts version.
- Adding a chart that needs a component/series type not in the list below — otherwise
  ECharts logs `Component/Series ... is used but not imported` and that series silently
  drops. Grep `site/assets/js/dashboard.charts.js` for `type: "<series>"` and any new
  `echarts.*` component usage, then add the matching import + `use()` entry.

## Reproduce

Pin the same upstream version the app was verified against (currently **5.6.0**).

```sh
mkdir echarts-build && cd echarts-build
npm init -y
npm install echarts@5.6.0 esbuild

cat > entry.js <<'JS'
import * as echarts from 'echarts/core';
import { LineChart, BarChart, ScatterChart, PieChart } from 'echarts/charts';
import {
  GridComponent, TooltipComponent, AxisPointerComponent,
  LegendComponent, LegendScrollComponent,
  DataZoomComponent, DataZoomInsideComponent, DataZoomSliderComponent,
  MarkLineComponent, MarkAreaComponent, MarkPointComponent,
  GraphicComponent, TitleComponent, DatasetComponent, TransformComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  LineChart, BarChart, ScatterChart, PieChart,
  GridComponent, TooltipComponent, AxisPointerComponent,
  LegendComponent, LegendScrollComponent,
  DataZoomComponent, DataZoomInsideComponent, DataZoomSliderComponent,
  MarkLineComponent, MarkAreaComponent, MarkPointComponent,
  GraphicComponent, TitleComponent, DatasetComponent, TransformComponent,
  CanvasRenderer,
]);

if (typeof window !== 'undefined') { window.echarts = echarts; }
JS

./node_modules/.bin/esbuild entry.js --bundle --minify --format=iife \
  --target=es2017 --legal-comments=none --outfile=echarts.min.js

cp echarts.min.js ../site/assets/js/echarts.min.js
```

## Re-verify after a rebuild

Serve the site and, in headless Chromium, drive all 6 tabs in both color schemes
against the OLD (full dist) and NEW bundle; assert: no new console warnings, identical
`canvas.width×height` per tab, and ~0% pixel diff between the two screenshot sets. Then
run `site/tools/shoot_dashboard.js` with `CAPTURE_GIF=1` and confirm 6 frames/tab and
the win-rate chart + social card render.

Keep the previous `site/assets/js/echarts.min.js` recoverable via git history as a one-commit
rollback if a rebuild regresses.
