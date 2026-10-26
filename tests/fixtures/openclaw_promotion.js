async function applyShortTermPromotions(options) {
	const workspaceDir = options.workspaceDir.trim();
	const nowMs = resolveMemoryCoreNowMs(options.nowMs);
	const nowIso = resolveMemoryCoreTimestamp(nowMs);
	const limit = Number.isFinite(options.limit) ? Math.max(0, Math.floor(options.limit)) : options.candidates.length;
	const minScore = toFiniteScore(options.minScore, DEFAULT_PROMOTION_MIN_SCORE);
	const minRecallCount = toFiniteNonNegativeInt(options.minRecallCount, 3);
	const minUniqueQueries = toFiniteNonNegativeInt(options.minUniqueQueries, 2);
	const maxAgeDays = toFiniteNonNegativeInt(options.maxAgeDays, -1);
	const memoryPath = path.join(workspaceDir, "MEMORY.md");
	return await withShortTermLock(workspaceDir, async () => {
		const store = await readStore(workspaceDir, nowIso);
		const selected = options.candidates.filter((candidate) => {
			if (isContaminatedDreamingSnippet(candidate.snippet)) return false;
			if (candidate.promotedAt) return false;
			if (candidate.score < minScore) return false;
			if (Math.max(0, candidate.signalCount ?? totalSignalCountForEntry({
				recallCount: candidate.recallCount,
				dailyCount: candidate.dailyCount,
				groundedCount: candidate.groundedCount
			})) < minRecallCount) return false;
			if (Math.max(candidate.uniqueQueries, candidate.recallDays.length) < minUniqueQueries) return false;
			if (maxAgeDays >= 0 && candidate.ageDays > maxAgeDays) return false;
			if (store.entries[candidate.key]?.promotedAt) return false;
			return true;
		}).slice(0, limit);
		const rehydratedSelected = [];
		for (const candidate of selected) {
			const rehydrated = await rehydratePromotionCandidate(workspaceDir, candidate);
			if (rehydrated && !isContaminatedDreamingSnippet(rehydrated.snippet)) rehydratedSelected.push(rehydrated);
		}
		if (rehydratedSelected.length === 0) return {
			memoryPath,
			applied: 0,
			appended: 0,
			reconciledExisting: 0,
			appliedCandidates: [],
			compactedSections: 0,
			compactedDates: []
		};
		const existingMemory = await fs.readFile(memoryPath, "utf-8").catch((err) => {
			if (err?.code === "ENOENT") return "";
			throw err;
		});
		const existingMarkers = extractPromotionMarkers(existingMemory);
		const alreadyWritten = rehydratedSelected.filter((candidate) => existingMarkers.has(candidate.key));
		const toAppend = rehydratedSelected.filter((candidate) => !existingMarkers.has(candidate.key));
		let compactedDates = [];
		if (toAppend.length > 0) {
			const section = buildPromotionSection(toAppend, nowMs, options.timezone, options.maxPromotedSnippetTokens);
			const compaction = compactMemoryForBudget({
				existingMemory,
				newSection: section,
				budgetChars: typeof options.memoryFileMaxChars === "number" && Number.isFinite(options.memoryFileMaxChars) ? Math.max(0, Math.floor(options.memoryFileMaxChars)) : DEFAULT_MEMORY_FILE_MAX_CHARS
			});
			compactedDates = compaction.droppedDates;
			const baseMemory = compaction.compacted;
			const header = baseMemory.trim().length > 0 ? "" : "# Long-Term Memory\n\n";
			await fs.writeFile(memoryPath, `${header}${withTrailingNewline(baseMemory)}${section}`, "utf-8");
		}
		for (const candidate of rehydratedSelected) {
			const entry = store.entries[candidate.key];
			if (!entry) continue;
			entry.startLine = candidate.startLine;
			entry.endLine = candidate.endLine;
			entry.snippet = candidate.snippet;
			entry.promotedAt = nowIso;
		}
		store.updatedAt = nowIso;
		await writeStore(workspaceDir, store);
		await appendMemoryHostEvent(workspaceDir, {
			type: "memory.promotion.applied",
			timestamp: nowIso,
			memoryPath,
			applied: rehydratedSelected.length,
			candidates: rehydratedSelected.map((candidate) => ({
				key: candidate.key,
				path: candidate.path,
				startLine: candidate.startLine,
				endLine: candidate.endLine,
				score: candidate.score,
				recallCount: candidate.recallCount
			}))
		});
		return {
			memoryPath,
			applied: rehydratedSelected.length,
			appended: toAppend.length,
			reconciledExisting: alreadyWritten.length,
			appliedCandidates: rehydratedSelected,
			compactedSections: compactedDates.length,
			compactedDates
		};
	});
}
