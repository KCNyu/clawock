const PROMOTION_SECTION_HEADING_RE = /^## Promoted From Short-Term Memory \(([^)]+)\)\s*$/;
/**
* Default budget for MEMORY.md content on disk, in characters. Chosen to
* stay safely below the bootstrap injection cap (~12KB per file at the
* time of writing) so promoted memory keeps reaching new sessions instead
* of being silently dropped by bootstrap truncation.
*/
const DEFAULT_MEMORY_FILE_MAX_CHARS = 1e4;
/**
* Reserve for writer-side overhead that the helper does not see directly:
* the `# Long-Term Memory\n\n` header re-emitted when compaction empties
* out (20 chars) and `withTrailingNewline`'s trailing `\n` (1 char). See
* the actual write expression in `applyShortTermPromotions`. Subtracting
* this from `budgetChars` keeps the on-disk file inside the caller's
* stated budget instead of exceeding it by up to ~21 chars in edge cases.
*/
const WRITE_OVERHEAD_RESERVE = 21;
function parseMemoryBlocks(content) {
	if (content.length === 0) return [];
	const lines = content.split(/\r?\n/);
	const blocks = [];
	let currentLines = [];
	let currentKind = "preserved";
	let currentDate;
	const flush = () => {
		if (currentLines.length === 0) return;
		const text = currentLines.join("\n");
		if (currentKind === "promotion" && currentDate) blocks.push({
			kind: "promotion",
			date: currentDate,
			text
		});
		else blocks.push({
			kind: "preserved",
			text
		});
		currentLines = [];
		currentKind = "preserved";
		currentDate = void 0;
	};
	for (const line of lines) if (line.startsWith("## ")) {
		flush();
		const match = PROMOTION_SECTION_HEADING_RE.exec(line);
		if (match) {
			currentKind = "promotion";
			currentDate = match[1];
		} else currentKind = "preserved";
		currentLines = [line];
	} else currentLines.push(line);
	flush();
	return blocks;
}
function joinBlocks(blocks) {
	return blocks.map((block) => block.text).join("\n");
}
/**
* Drop oldest auto-promotion sections from `existingMemory` until
* `existingMemory + newSection` fits within `budgetChars`. Returns the
* (possibly trimmed) existing memory and the dates of dropped sections.
*
* Guarantees:
* - Non-promotion content (user-authored markdown, the file header, any
*   `##` heading not matching the promotion pattern) is preserved.
* - Promotion sections are dropped in ascending date order (oldest first).
* - If `existingMemory + newSection` already fits the budget, the existing
*   memory is returned unchanged.
* - If the budget cannot be satisfied even by dropping every promotion
*   section, the function drops them all and returns; the caller writes
*   the new section anyway. This is the "log and continue" failure mode —
*   refusing the new write would silently swallow the freshest material.
*/
function compactMemoryForBudget(params) {
	const { existingMemory, newSection, budgetChars } = params;
	if (budgetChars <= 0) return {
		compacted: existingMemory,
		droppedDates: []
	};
	const effectiveBudget = Math.max(0, budgetChars - WRITE_OVERHEAD_RESERVE);
	if (existingMemory.length + newSection.length <= effectiveBudget) return {
		compacted: existingMemory,
		droppedDates: []
	};
	const blocks = parseMemoryBlocks(existingMemory);
	const promotionEntries = blocks.map((block, index) => block.kind === "promotion" ? {
		index,
		date: block.date,
		length: block.text.length
	} : null).filter((entry) => entry !== null).toSorted((a, b) => a.date.localeCompare(b.date));
	if (promotionEntries.length === 0) return {
		compacted: existingMemory,
		droppedDates: []
	};
	const droppedIndices = /* @__PURE__ */ new Set();
	const droppedDates = [];
	let projectedExistingSize = existingMemory.length;
	const blockSeparatorCost = blocks.length > 1 ? 1 : 0;
	for (const entry of promotionEntries) {
		if (projectedExistingSize + newSection.length <= effectiveBudget) break;
		droppedIndices.add(entry.index);
		droppedDates.push(entry.date);
		projectedExistingSize = Math.max(0, projectedExistingSize - entry.length - blockSeparatorCost);
	}
	if (droppedIndices.size === 0) return {
		compacted: existingMemory,
		droppedDates: []
	};
	return {
		compacted: joinBlocks(blocks.filter((_, index) => !droppedIndices.has(index))),
		droppedDates
	};
}
