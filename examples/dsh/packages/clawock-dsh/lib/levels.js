// src/levels.ts
/**
* Colour tier for one used-percent reading against the REMAINING-watermark
* threshold (lowPct). kcn 的配色口径:已使用低 = 正常绿(--ok),逼近额度
* 上限先黄(--warn)再红(--bad)。档位从既有 lowPct 派生,不新增配置:
* warn at 100−2·lowPct, red inside 100−lowPct(默认 20 → 60% 黄 / 80% 红)。
* 档位只决定颜色,绝不增删信息(kcn 反馈 #908:变红不许吃掉任何字段)。
*/
function _usedLevel(percent, threshold) {
	if (percent === null) return "ok";
	if (percent >= 100 - threshold) return "low";
	if (percent >= 100 - 2 * threshold) return "mid";
	return "ok";
}
export { _usedLevel };
