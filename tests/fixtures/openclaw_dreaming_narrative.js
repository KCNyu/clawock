// OpenClaw 2026.7.1-2 (MIT): original narrative loop and error classifier.
// Kept as a compatibility fixture for the host backport, not a runtime copy.
function isConfiguredModelUnavailableNarrativeError(raw) {
	const message = raw.trim();
	if (!message) return false;
	if (/requested model may be(?: temporarily)? unavailable/i.test(message)) return true;
	if (/model unavailable/i.test(message)) return true;
	if (/no endpoints found for/i.test(message)) return true;
	if (/unknown model/i.test(message)) return true;
	if (/model(?:[_\-\s])?not(?:[_\-\s])?found/i.test(message)) return true;
	if (/\b404\b/.test(message) && /not(?:[_\-\s])?found/i.test(message)) return true;
	if (/not_found_error/i.test(message)) return true;
	if (/models\/[^\s]+ is not found/i.test(message)) return true;
	if (/model/i.test(message) && /does not exist/i.test(message)) return true;
	if (/unsupported model/i.test(message)) return true;
	if (/is not a valid model id/i.test(message)) return true;
	return false;
}
function formatNarrativeTerminalStatus(params) {
	const detail = params.error?.trim();
	return detail ? `status=${params.status} (${detail})` : `status=${params.status}`;
}
async function generateAndAppendDreamNarrative(params) {
	const nowMs = Number.isFinite(params.nowMs) ? params.nowMs : Date.now();
	if (params.data.snippets.length === 0 && !params.data.promotions?.length) return;
	const sessionKey = buildNarrativeSessionKey({
		workspaceDir: params.workspaceDir,
		phase: params.data.phase
	});
	const message = buildNarrativePrompt(params.data);
	await withNarrativeSessionLock(sessionKey, async () => {
		const attempts = [];
		let successfulSessionKey = null;
		try {
			const attemptModels = params.model ? [params.model, void 0] : [void 0];
			for (const [attemptIndex, attemptModel] of attemptModels.entries()) {
				const attemptSessionKey = buildNarrativeAttemptSessionKey(sessionKey, attemptIndex);
				const attempt = {
					sessionKey: attemptSessionKey,
					runId: null
				};
				attempts.push(attempt);
				try {
					try {
						await params.subagent.deleteSession({ sessionKey: attemptSessionKey });
					} catch (preCleanupErr) {
						if (!isRequestScopedSubagentRuntimeError(preCleanupErr)) params.logger.warn(`memory-core: narrative pre-cleanup failed for ${params.data.phase} phase: ${formatErrorMessage(preCleanupErr)}`);
					}
					const runId = await startNarrativeRunOrFallback({
						subagent: params.subagent,
						sessionKey: attemptSessionKey,
						message,
						data: params.data,
						workspaceDir: params.workspaceDir,
						nowMs,
						timezone: params.timezone,
						model: attemptModel,
						logger: params.logger
					});
					if (!runId) return;
					attempt.runId = runId;
					const result = await params.subagent.waitForRun({
						runId,
						timeoutMs: NARRATIVE_TIMEOUT_MS
					});
					if (result.status === "ok") {
						successfulSessionKey = attemptSessionKey;
						break;
					}
					if (attemptModel && result.status === "error" && isConfiguredModelUnavailableNarrativeError(result.error ?? "")) {
						params.logger.warn(`memory-core: narrative generation ended with ${formatNarrativeTerminalStatus({
							status: result.status,
							error: result.error
						})} for ${params.data.phase} phase using configured model "${attemptModel}"; retrying with the session default.`);
						continue;
					}
					params.logger.warn(`memory-core: narrative generation ended with ${formatNarrativeTerminalStatus({
						status: result.status,
						error: result.error
					})} for ${params.data.phase} phase; writing fallback diary entry.`);
					await appendFallbackNarrativeEntry({
						workspaceDir: params.workspaceDir,
						data: params.data,
						nowMs,
						timezone: params.timezone,
						logger: params.logger,
						reason: `the narrative run ended with ${formatNarrativeTerminalStatus({
							status: result.status,
							error: result.error
						})}`
					});
					return;
				} catch (err) {
					if (attemptModel && isConfiguredModelUnavailableNarrativeError(formatErrorMessage(err))) {
						params.logger.warn(`memory-core: narrative generation could not start with configured model "${attemptModel}" for ${params.data.phase} phase; retrying with the session default (${formatErrorMessage(err)}).`);
						continue;
					}
					throw err;
				}
			}
			if (!successfulSessionKey) return;
			const narrative = await readSettledNarrativeText({
				subagent: params.subagent,
				sessionKey: successfulSessionKey
			});
			if (!narrative) {
				params.logger.warn(`memory-core: narrative generation produced no text for ${params.data.phase} phase; writing fallback diary entry.`);
				await appendFallbackNarrativeEntry({
					workspaceDir: params.workspaceDir,
					data: params.data,
					nowMs,
					timezone: params.timezone,
					logger: params.logger,
					reason: "the narrative run produced no text"
				});
				return;
			}
			await appendNarrativeEntry({
				workspaceDir: params.workspaceDir,
				narrative,
				nowMs,
				timezone: params.timezone
			});
			params.logger.info(`memory-core: dream diary entry written for ${params.data.phase} phase [workspace=${params.workspaceDir}].`);
		} catch (err) {
			params.logger.warn(`memory-core: narrative generation failed for ${params.data.phase} phase: ${formatErrorMessage(err)}`);
		} finally {
			const cleanedSessionKeys = /* @__PURE__ */ new Set();
			for (const attempt of attempts) {
				if (!attempt.runId || cleanedSessionKeys.has(attempt.sessionKey)) continue;
				cleanedSessionKeys.add(attempt.sessionKey);
				try {
					await params.subagent.deleteSession({ sessionKey: attempt.sessionKey });
				} catch (cleanupErr) {
					params.logger.warn(`memory-core: narrative session cleanup failed for ${params.data.phase} phase: ${formatErrorMessage(cleanupErr)}`);
				}
			}
			await scrubDreamingNarrativeArtifacts(params.logger).catch((scrubErr) => {
				params.logger.warn(`memory-core: dreaming cleanup scrub failed for ${params.data.phase} phase: ${formatErrorMessage(scrubErr)}`);
			});
		}
	});
}
const DETACHED_NARRATIVE_CONCURRENCY = 3;
