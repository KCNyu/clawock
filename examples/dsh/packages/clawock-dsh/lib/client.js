window.__ModuleLoader__.load({
  id: "clawock-dsh",
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
const { defineStore } = require("@deepseek-ai/dsh-client-store");
const React = require("react");
//#region node_modules/zod/v4/core/util.js
function getEnumValues(entries) {
	const numericValues = Object.values(entries).filter((v) => typeof v === "number");
	return Object.entries(entries).filter(([k, _]) => numericValues.indexOf(+k) === -1).map(([_, v]) => v);
}
function joinValues(array, separator = "|") {
	return array.map((val) => stringifyPrimitive(val)).join(separator);
}
function jsonStringifyReplacer(_, value) {
	if (typeof value === "bigint") return value.toString();
	return value;
}
function cached(getter) {
	return { get value() {
		{
			const value = getter();
			Object.defineProperty(this, "value", { value });
			return value;
		}
	} };
}
function nullish(input) {
	return input === null || input === void 0;
}
function cleanRegex(source) {
	const start = source.startsWith("^") ? 1 : 0;
	const end = source.endsWith("$") ? source.length - 1 : source.length;
	return source.slice(start, end);
}
function floatSafeRemainder(val, step) {
	const ratio = val / step;
	const roundedRatio = Math.round(ratio);
	const tolerance = 4 * Number.EPSILON * Math.max(Math.abs(ratio), 1);
	if (Math.abs(ratio - roundedRatio) < tolerance) return 0;
	return ratio - roundedRatio;
}
const EVALUATING = /* @__PURE__*/ Symbol("evaluating");
function defineLazy(object, key, getter) {
	let value = void 0;
	Object.defineProperty(object, key, {
		get() {
			if (value === EVALUATING) return;
			if (value === void 0) {
				value = EVALUATING;
				value = getter();
			}
			return value;
		},
		set(v) {
			Object.defineProperty(object, key, { value: v });
		},
		configurable: true
	});
}
function assignProp(target, prop, value) {
	Object.defineProperty(target, prop, {
		value,
		writable: true,
		enumerable: true,
		configurable: true
	});
}
function mergeDefs(...defs) {
	const mergedDescriptors = {};
	for (const def of defs) {
		const descriptors = Object.getOwnPropertyDescriptors(def);
		Object.assign(mergedDescriptors, descriptors);
	}
	return Object.defineProperties({}, mergedDescriptors);
}
function esc$1(str) {
	return JSON.stringify(str);
}
function slugify(input) {
	return input.toLowerCase().trim().replace(/[^\w\s-]/g, "").replace(/[\s_-]+/g, "-").replace(/^-+|-+$/g, "");
}
const captureStackTrace = "captureStackTrace" in Error ? Error.captureStackTrace : (..._args) => {};
function isObject(data) {
	return typeof data === "object" && data !== null && !Array.isArray(data);
}
const allowsEval = /* @__PURE__*/ cached(() => {
	if (globalConfig.jitless) return false;
	if (typeof navigator !== "undefined" && navigator?.userAgent?.includes("Cloudflare")) return false;
	try {
		new Function("");
		return true;
	} catch (_) {
		return false;
	}
});
function isPlainObject(o) {
	if (isObject(o) === false) return false;
	const ctor = o.constructor;
	if (ctor === void 0) return true;
	if (typeof ctor !== "function") return true;
	const prot = ctor.prototype;
	if (isObject(prot) === false) return false;
	if (Object.prototype.hasOwnProperty.call(prot, "isPrototypeOf") === false) return false;
	return true;
}
function shallowClone(o) {
	if (isPlainObject(o)) return { ...o };
	if (Array.isArray(o)) return [...o];
	if (o instanceof Map) return new Map(o);
	if (o instanceof Set) return new Set(o);
	return o;
}
const propertyKeyTypes = /* @__PURE__*/ new Set([
	"string",
	"number",
	"symbol"
]);
function escapeRegex(str) {
	return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
function clone(inst, def, params) {
	const cl = new inst._zod.constr(def ?? inst._zod.def);
	if (!def || params?.parent) cl._zod.parent = inst;
	return cl;
}
function normalizeParams(_params) {
	const params = _params;
	if (!params) return {};
	if (typeof params === "string") return { error: () => params };
	if (params?.message !== void 0) {
		if (params?.error !== void 0) throw new Error("Cannot specify both `message` and `error` params");
		params.error = params.message;
	}
	delete params.message;
	if (typeof params.error === "string") return {
		...params,
		error: () => params.error
	};
	return params;
}
function stringifyPrimitive(value) {
	if (typeof value === "bigint") return value.toString() + "n";
	if (typeof value === "string") return `"${value}"`;
	return `${value}`;
}
function optionalKeys(shape) {
	return Object.keys(shape).filter((k) => {
		return shape[k]._zod.optin !== void 0 && shape[k]._zod.optout === "optional";
	});
}
const NUMBER_FORMAT_RANGES = /*@__PURE__*/ (() => ({
	safeint: [Number.MIN_SAFE_INTEGER, Number.MAX_SAFE_INTEGER],
	int32: [-2147483648, 2147483647],
	uint32: [0, 4294967295],
	float32: [-34028234663852886e22, 34028234663852886e22],
	float64: [-Number.MAX_VALUE, Number.MAX_VALUE]
}))();
function pick(schema, mask) {
	const currDef = schema._zod.def;
	const checks = currDef.checks;
	if (checks && checks.length > 0) throw new Error(".pick() cannot be used on object schemas containing refinements");
	return clone(schema, mergeDefs(schema._zod.def, {
		get shape() {
			const newShape = {};
			for (const key of Reflect.ownKeys(mask)) {
				if (!Object.prototype.hasOwnProperty.call(currDef.shape, key)) throw new Error(`Unrecognized key: "${String(key)}"`);
				if (!mask[key]) continue;
				assignProp(newShape, key, currDef.shape[key]);
			}
			assignProp(this, "shape", newShape);
			return newShape;
		},
		checks: []
	}));
}
function omit(schema, mask) {
	const currDef = schema._zod.def;
	const checks = currDef.checks;
	if (checks && checks.length > 0) throw new Error(".omit() cannot be used on object schemas containing refinements");
	return clone(schema, mergeDefs(schema._zod.def, {
		get shape() {
			const newShape = { ...schema._zod.def.shape };
			for (const key of Reflect.ownKeys(mask)) {
				if (!Object.prototype.hasOwnProperty.call(currDef.shape, key)) throw new Error(`Unrecognized key: "${String(key)}"`);
				if (!mask[key]) continue;
				delete newShape[key];
			}
			assignProp(this, "shape", newShape);
			return newShape;
		},
		checks: []
	}));
}
function extend(schema, shape) {
	if (!isPlainObject(shape)) throw new Error("Invalid input to extend: expected a plain object");
	const checks = schema._zod.def.checks;
	if (checks && checks.length > 0) {
		const existingShape = schema._zod.def.shape;
		for (const key of Reflect.ownKeys(shape)) if (Object.getOwnPropertyDescriptor(existingShape, key) !== void 0) throw new Error("Cannot overwrite keys on object schemas containing refinements. Use `.safeExtend()` instead.");
	}
	return clone(schema, mergeDefs(schema._zod.def, { get shape() {
		const _shape = {
			...schema._zod.def.shape,
			...shape
		};
		assignProp(this, "shape", _shape);
		return _shape;
	} }));
}
function safeExtend(schema, shape) {
	if (!isPlainObject(shape)) throw new Error("Invalid input to safeExtend: expected a plain object");
	return clone(schema, mergeDefs(schema._zod.def, { get shape() {
		const _shape = {
			...schema._zod.def.shape,
			...shape
		};
		assignProp(this, "shape", _shape);
		return _shape;
	} }));
}
function merge(a, b) {
	if (!b?._zod?.def) throw new Error("Invalid input to merge: expected an object schema. To merge a plain shape, use `.extend()`.");
	if (a._zod.def.checks?.length) throw new Error(".merge() cannot be used on object schemas containing refinements. Use .safeExtend() instead.");
	return clone(a, mergeDefs(a._zod.def, {
		get shape() {
			const _shape = {
				...a._zod.def.shape,
				...b._zod.def.shape
			};
			assignProp(this, "shape", _shape);
			return _shape;
		},
		get catchall() {
			return b._zod.def.catchall;
		},
		checks: b._zod.def.checks ?? []
	}));
}
function partial(Class, schema, mask, name = "partial") {
	const checks = schema._zod.def.checks;
	if (checks && checks.length > 0) throw new Error(`.${name}() cannot be used on object schemas containing refinements`);
	return clone(schema, mergeDefs(schema._zod.def, {
		get shape() {
			const oldShape = schema._zod.def.shape;
			const shape = { ...oldShape };
			if (mask) for (const key of Reflect.ownKeys(mask)) {
				if (!Object.prototype.hasOwnProperty.call(oldShape, key)) throw new Error(`Unrecognized key: "${String(key)}"`);
				if (!mask[key]) continue;
				shape[key] = Class ? new Class({
					type: "optional",
					innerType: oldShape[key]
				}) : oldShape[key];
			}
			else for (const key of Reflect.ownKeys(oldShape)) shape[key] = Class ? new Class({
				type: "optional",
				innerType: oldShape[key]
			}) : oldShape[key];
			assignProp(this, "shape", shape);
			return shape;
		},
		checks: []
	}));
}
function required(Class, schema, mask) {
	return clone(schema, mergeDefs(schema._zod.def, { get shape() {
		const oldShape = schema._zod.def.shape;
		const shape = { ...oldShape };
		if (mask) for (const key of Reflect.ownKeys(mask)) {
			if (!Object.prototype.hasOwnProperty.call(shape, key)) throw new Error(`Unrecognized key: "${String(key)}"`);
			if (!mask[key]) continue;
			shape[key] = new Class({
				type: "nonoptional",
				innerType: oldShape[key]
			});
		}
		else for (const key of Reflect.ownKeys(oldShape)) shape[key] = new Class({
			type: "nonoptional",
			innerType: oldShape[key]
		});
		assignProp(this, "shape", shape);
		return shape;
	} }));
}
function aborted(x, startIndex = 0) {
	if (x.aborted === true) return true;
	for (let i = startIndex; i < x.issues.length; i++) if (x.issues[i]?.continue !== true) return true;
	return false;
}
function explicitlyAborted(x, startIndex = 0) {
	if (x.aborted === true) return true;
	for (let i = startIndex; i < x.issues.length; i++) if (x.issues[i]?.continue === false) return true;
	return false;
}
function prefixIssues(path, issues) {
	return issues.map((iss) => {
		var _a;
		(_a = iss).path ?? (_a.path = []);
		iss.path.unshift(path);
		return iss;
	});
}
function unwrapMessage(message) {
	return typeof message === "string" ? message : message?.message;
}
function attachSchema(issues, start, inst) {
	var _a;
	for (let i = start; i < issues.length; i++) (_a = issues[i]).schema ?? (_a.schema = inst);
}
function finalizeIssue(iss, ctx, config) {
	var _a;
	const traits = iss.inst?._zod?.traits;
	if (traits?.has("$ZodType")) {
		if (traits.has("$ZodCheck")) (_a = iss).schema ?? (_a.schema = iss.inst);
		else iss.schema = iss.inst;
	}
	const schemaError = iss.schema !== iss.inst ? iss.schema?._zod.def?.error : void 0;
	const message = iss.message ? iss.message : unwrapMessage(iss.inst?._zod.def?.error?.(iss)) ?? unwrapMessage(schemaError?.(iss)) ?? unwrapMessage(ctx?.error?.(iss)) ?? unwrapMessage(config.customError?.(iss)) ?? unwrapMessage(config.localeError?.(iss)) ?? "Invalid input";
	const { inst: _inst, schema: _schema, continue: _continue, input: _input, ...rest } = iss;
	rest.path ?? (rest.path = []);
	rest.message = message;
	if (ctx?.reportInput) rest.input = _input;
	return rest;
}
const highSurrogate = /[\uD800-\uDBFF]/;
function codePointLength(str) {
	const units = str.length;
	if (!highSurrogate.test(str)) return units;
	let count = units;
	for (let i = 0; i < units - 1; i++) if ((str.charCodeAt(i) & 64512) === 55296 && (str.charCodeAt(i + 1) & 64512) === 56320) {
		count--;
		i++;
	}
	return count;
}
function getLengthableOrigin(input) {
	if (Array.isArray(input)) return "array";
	if (typeof input === "string") return "string";
	return "unknown";
}
function parsedType(data) {
	const t = typeof data;
	switch (t) {
		case "number": return Number.isNaN(data) ? "nan" : "number";
		case "object": {
			if (data === null) return "null";
			if (Array.isArray(data)) return "array";
			const obj = data;
			if (obj && Object.getPrototypeOf(obj) !== Object.prototype && "constructor" in obj && obj.constructor) return obj.constructor.name;
		}
	}
	return t;
}
function issue(...args) {
	const [iss, input, inst] = args;
	if (typeof iss === "string") return {
		message: iss,
		code: "custom",
		input,
		inst
	};
	return { ...iss };
}
/**
* Installs a trait's members on its prototype. Each value builds that member for the instance on first read; the built value shadows the accessor as an own property, so a detached `const { parse } = schema` keeps working.
*
* Call this from a `proto` initializer, which runs once per prototype — never per instance.
*/
function members(proto, table) {
	for (const key in table) {
		const desc = Object.getOwnPropertyDescriptor(table, key);
		if (desc.get) Object.defineProperty(proto, key, {
			...desc,
			enumerable: false
		});
		else defineBound(proto, key, desc.value);
	}
}
/** Shadows a prototype member with an own value, so a getter that builds from the instance runs once. */
function own(inst, key, value, enumerable = true) {
	Object.defineProperty(inst, key, {
		configurable: true,
		writable: true,
		enumerable,
		value
	});
	return value;
}
/** Like {@link own}, for a member that was never an own data property and has to stay out of `Object.keys`. */
function hide(inst, key, value) {
	return own(inst, key, value, false);
}
function defineBound(proto, key, fn) {
	Object.defineProperty(proto, key, {
		configurable: true,
		get() {
			return this == null ? fn : own(this, key, fn.bind(this));
		},
		set(value) {
			own(this, key, value);
		}
	});
}
/** Returns the prototype to install on, or `undefined` if this group is already installed on it. */
function claim(inst, sentinel) {
	const proto = Object.getPrototypeOf(inst);
	return sentinel in proto ? void 0 : proto;
}
let installing;
let broke = false;
const breaker = {
	configurable: true,
	get() {
		broke = true;
	}
};
/**
* Installs a lazily-derived internal on the `_zod` prototype of `inst`'s
* constructor, computed from the internals object itself and cached there on
* first read. One accessor per constructor rather than one per instance.
*/
function defineLazyInternal(inst, key, compute) {
	const proto = Object.getPrototypeOf(inst._zod);
	if (key in proto && installing !== inst._zod) {
		installing = void 0;
		return;
	}
	installing = inst._zod;
	Object.defineProperty(proto, key, {
		configurable: true,
		get() {
			Object.defineProperty(this, key, breaker);
			const outer = broke;
			broke = false;
			try {
				const value = compute(this);
				if (broke) delete this[key];
				else Object.defineProperty(this, key, {
					configurable: true,
					writable: true,
					value
				});
				broke = broke || outer;
				return value;
			} catch (err) {
				delete this[key];
				broke = broke || outer;
				throw err;
			}
		},
		set(value) {
			Object.defineProperty(this, key, {
				configurable: true,
				writable: true,
				value
			});
		}
	});
}
/**
* Installs `key` on `inst`'s prototype, computed by `make` on first read and cached there as an own
* data property. One accessor per constructor rather than one per instance, because an own accessor
* puts every instance after the first into v8 dictionary mode. The key doubles as the sentinel.
*/
function installLazyProp(inst, key, make, enumerable) {
	const proto = claim(inst, key);
	if (!proto) return;
	Object.defineProperty(proto, key, {
		configurable: true,
		get() {
			const desc = {
				configurable: true,
				writable: true,
				enumerable,
				value: void 0
			};
			Object.defineProperty(this, key, desc);
			desc.value = make(this);
			Object.defineProperty(this, key, desc);
			return desc.value;
		},
		set(value) {
			Object.defineProperty(this, key, {
				configurable: true,
				writable: true,
				enumerable,
				value
			});
		}
	});
}
/** Marks the thunk `_catch` synthesises for a constant catch value. `Function.length` cannot tell that thunk from a user callback — rest and defaulted parameters both report arity 0 — and a user callback reads `ctx.error`, whose issues only finalize correctly against the caller's per-parse error map. Provenance can say what arity cannot. A plain string key rather than `Symbol.for`, whose call at module scope no bundler can prove pure — the same shape that anchored `urlCanParse` into every build. */
const CONSTANT_CATCH = "~constantCatch";
/** Wraps a constant catch value in a thunk tagged with {@link CONSTANT_CATCH}. */
function constantCatch(value) {
	const fn = () => value;
	fn[CONSTANT_CATCH] = true;
	return fn;
}
//#endregion
//#region node_modules/zod/v4/core/core.js
var _a$1;
const _zodDesc$1 = {
	value: void 0,
	enumerable: false
};
let _E = "captureStackTrace" in Error ? Error : null;
function newError(Definition) {
	const E = _E;
	if (E) {
		const saved = E.stackTraceLimit;
		if (typeof saved === "number") {
			try {
				E.stackTraceLimit = 0;
			} catch {
				_E = null;
				return new Definition();
			}
			try {
				return new Definition();
			} finally {
				E.stackTraceLimit = saved;
			}
		}
	}
	return new Definition();
}
function $constructor(name, initializer, proto, params) {
	const zodProto = {};
	function Internals(def) {
		this.def = def;
		this.constr = _;
		this.traits = /* @__PURE__ */ new Set();
	}
	Internals.prototype = zodProto;
	const protoMembers = proto;
	const initialized = protoMembers && /* @__PURE__ */ new WeakSet();
	function init(inst, def) {
		if (!inst._zod) {
			_zodDesc$1.value = new Internals(def);
			try {
				Object.defineProperty(inst, "_zod", _zodDesc$1);
			} finally {
				_zodDesc$1.value = void 0;
			}
		}
		if (inst._zod.traits.has(name)) return;
		inst._zod.traits.add(name);
		initializer(inst, def);
		if (initialized) {
			const own = Object.getPrototypeOf(inst);
			const ctorProto = inst._zod.constr.prototype;
			let up = own;
			while (up && up !== ctorProto) up = Object.getPrototypeOf(up);
			const target = up ?? own;
			if (!initialized.has(target)) {
				initialized.add(target);
				members(target, protoMembers);
			}
		}
		const proto = _.prototype;
		for (const k in proto) {
			if (!Object.prototype.hasOwnProperty.call(proto, k)) continue;
			if (!(k in inst)) inst[k] = proto[k].bind(inst);
		}
	}
	const Parent = params?.Parent ?? Object;
	class Definition extends Parent {}
	Object.defineProperty(Definition, "name", { value: name });
	function _(def) {
		const inst = params?.Parent ? newError(Definition) : this;
		init(inst, def);
		const deferred = inst._zod.deferred;
		if (deferred) {
			for (const fn of deferred) fn();
			inst._zod.deferred = void 0;
		}
		const pp = globalThis.__zod_globalConfig?.postProcessor;
		if (pp) pp(inst);
		return inst;
	}
	Object.defineProperty(_, "init", { value: init });
	Object.defineProperty(_, Symbol.hasInstance, { value: (inst) => {
		if (params?.Parent && inst instanceof params.Parent) return true;
		return inst?._zod?.traits?.has(name);
	} });
	Object.defineProperty(_, "name", { value: name });
	return _;
}
var $ZodAsyncError = class extends Error {
	constructor() {
		super(`Encountered Promise during synchronous parse. Use .parseAsync() instead.`);
	}
};
var $ZodEncodeError = class extends Error {
	constructor(name) {
		super(`Encountered unidirectional transform during encode: ${name}`);
		this.name = "ZodEncodeError";
	}
};
(_a$1 = globalThis).__zod_globalConfig ?? (_a$1.__zod_globalConfig = {});
const globalConfig = globalThis.__zod_globalConfig;
function config(newConfig) {
	if (newConfig) Object.assign(globalConfig, newConfig);
	return globalConfig;
}
//#endregion
//#region node_modules/zod/v4/core/errors.js
function _getMessage() {
	const internals = this._zod;
	internals.message ?? (internals.message = JSON.stringify(internals.def, jsonStringifyReplacer, 2));
	return internals.message;
}
function _setMessage(value) {
	this._zod.message = value;
}
const _messageDesc = {
	get: _getMessage,
	set: _setMessage,
	enumerable: true,
	configurable: true
};
const _zodDesc = {
	value: void 0,
	enumerable: false
};
const _issuesDesc = {
	value: void 0,
	enumerable: false
};
const _installedToString = /* @__PURE__ */ new WeakSet([Object.prototype, Error.prototype]);
const initializer$1 = (inst, def) => {
	inst.name = "$ZodError";
	_zodDesc.value = inst._zod;
	Object.defineProperty(inst, "_zod", _zodDesc);
	_issuesDesc.value = def;
	Object.defineProperty(inst, "issues", _issuesDesc);
	_zodDesc.value = void 0;
	_issuesDesc.value = void 0;
	Object.defineProperty(inst, "message", _messageDesc);
	const proto = Object.getPrototypeOf(inst);
	if (!_installedToString.has(proto)) {
		_installedToString.add(proto);
		Object.defineProperty(proto, "toString", {
			configurable: true,
			enumerable: false,
			get() {
				const value = () => this.message;
				Object.defineProperty(this, "toString", {
					value,
					configurable: true,
					writable: true
				});
				return value;
			},
			set(value) {
				Object.defineProperty(this, "toString", {
					value,
					configurable: true,
					writable: true
				});
			}
		});
	}
};
const $ZodError = $constructor("$ZodError", initializer$1);
const $ZodRealError = $constructor("$ZodError", initializer$1, void 0, { Parent: Error });
/** Get-or-create `obj[key]` as an own data property. A path segment naming an inherited member
* ("toString", "constructor") would otherwise read through to the prototype, and assigning
* "__proto__" would hit the setter instead of creating a key. */
function node(obj, key, make) {
	if (!Object.prototype.hasOwnProperty.call(obj, key)) {
		if (key === "__proto__") Object.defineProperty(obj, key, {
			value: make(),
			writable: true,
			enumerable: true,
			configurable: true
		});
		else obj[key] = make();
	}
	return obj[key];
}
function flattenError(error, mapper = (issue) => issue.message) {
	const fieldErrors = {};
	const formErrors = [];
	for (const sub of error.issues) if (sub.path.length > 0) node(fieldErrors, sub.path[0], () => []).push(mapper(sub));
	else formErrors.push(mapper(sub));
	return {
		formErrors,
		fieldErrors
	};
}
function formatError(error, mapper = (issue) => issue.message) {
	const fieldErrors = { _errors: [] };
	const processError = (error, path = []) => {
		for (const issue of error.issues) if (issue.code === "invalid_union" && issue.errors.length) issue.errors.map((issues) => processError({ issues }, [...path, ...issue.path]));
		else if (issue.code === "invalid_key") processError({ issues: issue.issues }, [...path, ...issue.path]);
		else if (issue.code === "invalid_element") processError({ issues: issue.issues }, [...path, ...issue.path]);
		else {
			const fullpath = [...path, ...issue.path];
			if (fullpath.length === 0) fieldErrors._errors.push(mapper(issue));
			else {
				let curr = fieldErrors;
				let i = 0;
				while (i < fullpath.length) {
					const el = fullpath[i];
					const terminal = i === fullpath.length - 1;
					if (el === "_errors") {
						if (terminal) curr._errors.push(mapper(issue));
						i++;
						continue;
					}
					if (!Object.prototype.hasOwnProperty.call(curr, el)) Object.defineProperty(curr, el, {
						value: { _errors: [] },
						enumerable: true,
						writable: true,
						configurable: true
					});
					const node = curr[el];
					if (terminal) node._errors.push(mapper(issue));
					curr = node;
					i++;
				}
			}
		}
	};
	processError(error);
	return fieldErrors;
}
//#endregion
//#region node_modules/zod/v4/core/parse.js
function finalizeParams(callee, params) {
	return {
		callee: params?.callee ?? callee,
		Err: params?.Err
	};
}
const _parse = (_Err) => {
	const fn = (schema, value, _ctx, _params) => {
		const ctx = _ctx ? {
			..._ctx,
			async: false
		} : { async: false };
		const result = schema._zod.run({
			value,
			issues: []
		}, ctx);
		if (result instanceof Promise) throw new $ZodAsyncError();
		if (result.issues.length) {
			const e = new ((_params?.Err) ?? _Err)(result.issues.map((iss) => finalizeIssue(iss, ctx, config())));
			captureStackTrace(e, _params?.callee ?? fn);
			throw e;
		}
		return result.value;
	};
	return fn;
};
const _parseAsync = (_Err) => {
	const fn = async (schema, value, _ctx, params) => {
		const ctx = _ctx ? {
			..._ctx,
			async: true
		} : { async: true };
		let result = schema._zod.run({
			value,
			issues: []
		}, ctx);
		if (result instanceof Promise) result = await result;
		if (result.issues.length) {
			const e = new ((params?.Err) ?? _Err)(result.issues.map((iss) => finalizeIssue(iss, ctx, config())));
			captureStackTrace(e, params?.callee ?? fn);
			throw e;
		}
		return result.value;
	};
	return fn;
};
const _safeParse = (_Err) => (schema, value, _ctx) => {
	const ctx = _ctx ? {
		..._ctx,
		async: false
	} : { async: false };
	const result = schema._zod.run({
		value,
		issues: []
	}, ctx);
	if (result instanceof Promise) throw new $ZodAsyncError();
	return result.issues.length ? {
		success: false,
		error: new (_Err ?? $ZodError)(result.issues.map((iss) => finalizeIssue(iss, ctx, config())))
	} : {
		success: true,
		data: result.value
	};
};
const safeParse$1 = /* @__PURE__*/ _safeParse($ZodRealError);
const _safeParseAsync = (_Err) => async (schema, value, _ctx) => {
	const ctx = _ctx ? {
		..._ctx,
		async: true
	} : { async: true };
	let result = schema._zod.run({
		value,
		issues: []
	}, ctx);
	if (result instanceof Promise) result = await result;
	return result.issues.length ? {
		success: false,
		error: new _Err(result.issues.map((iss) => finalizeIssue(iss, ctx, config())))
	} : {
		success: true,
		data: result.value
	};
};
const safeParseAsync$1 = /* @__PURE__*/ _safeParseAsync($ZodRealError);
const _encode = (_Err) => {
	const parse = _parse(_Err);
	const fn = (schema, value, _ctx, _params) => {
		const ctx = _ctx ? {
			..._ctx,
			direction: "backward"
		} : { direction: "backward" };
		return parse(schema, value, ctx, finalizeParams(fn, _params));
	};
	return fn;
};
const _decode = (_Err) => {
	const parse = _parse(_Err);
	const fn = (schema, value, _ctx, _params) => {
		return parse(schema, value, _ctx, finalizeParams(fn, _params));
	};
	return fn;
};
const _encodeAsync = (_Err) => {
	const parseAsync = _parseAsync(_Err);
	const fn = async (schema, value, _ctx, _params) => {
		const ctx = _ctx ? {
			..._ctx,
			direction: "backward"
		} : { direction: "backward" };
		return await parseAsync(schema, value, ctx, finalizeParams(fn, _params));
	};
	return fn;
};
const _decodeAsync = (_Err) => {
	const parseAsync = _parseAsync(_Err);
	const fn = async (schema, value, _ctx, _params) => {
		return await parseAsync(schema, value, _ctx, finalizeParams(fn, _params));
	};
	return fn;
};
const _safeEncode = (_Err) => (schema, value, _ctx) => {
	const ctx = _ctx ? {
		..._ctx,
		direction: "backward"
	} : { direction: "backward" };
	return _safeParse(_Err)(schema, value, ctx);
};
const _safeDecode = (_Err) => (schema, value, _ctx) => {
	return _safeParse(_Err)(schema, value, _ctx);
};
const _safeEncodeAsync = (_Err) => async (schema, value, _ctx) => {
	const ctx = _ctx ? {
		..._ctx,
		direction: "backward"
	} : { direction: "backward" };
	return _safeParseAsync(_Err)(schema, value, ctx);
};
const _safeDecodeAsync = (_Err) => async (schema, value, _ctx) => {
	return _safeParseAsync(_Err)(schema, value, _ctx);
};
//#endregion
//#region node_modules/zod/v4/core/regexes.js
/**
* @deprecated CUID v1 is deprecated by its authors due to information leakage
* (timestamps embedded in the id). Use {@link cuid2} instead.
* See https://github.com/paralleldrive/cuid.
*/
const cuid = /^[cC][0-9a-z]{6,}$/;
const cuid2 = /^[0-9a-z]+$/;
const ulid = /^[0-7][0-9A-HJKMNP-TV-Za-hjkmnp-tv-z]{25}$/;
const xid = /^[0-9a-vA-V]{20}$/;
const ksuid = /^[A-Za-z0-9]{27}$/;
const nanoid = /^[a-zA-Z0-9_-]{21}$/;
function nanoidOfLength(length) {
	return new RegExp(`^[a-zA-Z0-9_-]{${length}}$`);
}
/** ISO 8601-1 duration regex. Does not support the 8601-2 extensions like negative durations or fractional/negative components. */
const duration = /^P(?:(\d+W)|(?!.*W)(?=\d|T\d)(\d+Y)?(\d+M)?(\d+D)?(T(?=\d)(\d+H)?(\d+M)?(\d+([.,]\d+)?S)?)?)$/;
/** A regex for any UUID-like identifier: 8-4-4-4-12 hex pattern */
const guid = /^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$/;
/** Returns a regex for validating an RFC 9562/4122 UUID.
*
* @param version Optionally specify a version 1-8. If no version is specified, all versions are supported. */
const uuid = (version) => {
	if (!version) return /^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}|00000000-0000-0000-0000-000000000000|ffffffff-ffff-ffff-ffff-ffffffffffff)$/;
	return new RegExp(`^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-${version}[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})$`);
};
/** Practical email validation */
const email = /^(?!\.)(?!.*\.\.)([A-Za-z0-9_'+\-\.]*)[A-Za-z0-9_+-]@([A-Za-z0-9][A-Za-z0-9\-]*\.)+[A-Za-z]{2,}$/;
const _emoji$1 = `^[\\p{Extended_Pictographic}\\p{Emoji_Component}]+$`;
function emoji() {
	return new RegExp(_emoji$1, "u");
}
const ipv4 = /^(?:(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])\.){3}(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])$/;
const ipv6 = /^(([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,7}:|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|:((:[0-9a-fA-F]{1,4}){1,7}|:))$/;
const cidrv4 = /^((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])\.){3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])\/([0-9]|[1-2][0-9]|3[0-2])$/;
const cidrv6 = /^(([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,7}:|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|:((:[0-9a-fA-F]{1,4}){1,7}|:))\/(12[0-8]|1[01][0-9]|[1-9]?[0-9])$/;
const base64 = /^$|^(?:[0-9a-zA-Z+/]{4})*(?:(?:[0-9a-zA-Z+/]{2}==)|(?:[0-9a-zA-Z+/]{3}=))?$/;
const base64url = /^[A-Za-z0-9_-]*$/;
const httpProtocol = /^https?$/;
const e164 = /^\+[1-9]\d{6,14}$/;
const dateSource = `(?:(?:\\d\\d[2468][048]|\\d\\d[13579][26]|\\d\\d0[48]|[02468][048]00|[13579][26]00)-02-29|\\d{4}-(?:(?:0[13578]|1[02])-(?:0[1-9]|[12]\\d|3[01])|(?:0[469]|11)-(?:0[1-9]|[12]\\d|30)|(?:02)-(?:0[1-9]|1\\d|2[0-8])))`;
/** Anchors a pattern source. The interpolation lives here rather than at the call site because
* esbuild will not drop a `@__PURE__` call whose own argument interpolates a variable, but it
* will drop `anchor(dateSource)`. Keeping it inline pinned `date` into every bundle. */
function anchor(source) {
	return new RegExp(`^${source}$`);
}
const date = /*@__PURE__*/ anchor(dateSource);
function timeSource(args) {
	const hhmm = `(?:[01]\\d|2[0-3]):[0-5]\\d`;
	return typeof args.precision === "number" ? args.precision === -1 ? `${hhmm}` : args.precision === 0 ? `${hhmm}:[0-5]\\d` : `${hhmm}:[0-5]\\d\\.\\d{${args.precision}}` : args.seconds ? `${hhmm}:[0-5]\\d(?:\\.\\d+)?` : `${hhmm}(?::[0-5]\\d(?:\\.\\d+)?)?`;
}
function time(args) {
	return new RegExp(`^${timeSource(args)}$`);
}
function datetime(args) {
	const opts = ["Z"];
	if (args.offset) opts.push(`([+-](?:[01]\\d|2[0-3]):[0-5]\\d)`);
	const qualified = `${timeSource({
		precision: args.precision,
		seconds: true
	})}(?:${opts.join("|")})`;
	const timeRegex = args.local ? `${qualified}|${timeSource({ precision: args.precision })}` : qualified;
	return new RegExp(`^${dateSource}T(?:${timeRegex})$`);
}
const string$1 = (params) => {
	const regex = params ? `[\\s\\S]{${params?.minimum ?? 0},${params?.maximum ?? ""}}` : `[\\s\\S]*`;
	return new RegExp(`^${regex}$`);
};
const integer = /^-?\d+$/;
const number$1 = /^-?\d+(?:\.\d+)?$/;
const boolean$1 = /^(?:true|false)$/i;
const lowercase = /^[^A-Z]*$/;
const uppercase = /^[^a-z]*$/;
//#endregion
//#region node_modules/zod/v4/core/checks.js
const $ZodCheck = /*@__PURE__*/ $constructor("$ZodCheck", (inst, def) => {
	var _a;
	inst._zod ?? (inst._zod = {});
	inst._zod.def = def;
	(_a = inst._zod).onattach ?? (_a.onattach = []);
});
/** Default `when` for length-based checks: run only on non-nullish values with a `length`. */
const _whenHasLength = (payload) => {
	const val = payload.value;
	return !nullish(val) && val.length !== void 0;
};
const numericOriginMap = {
	number: "number",
	bigint: "bigint",
	object: "date"
};
const $ZodCheckLessThan = /*@__PURE__*/ $constructor("$ZodCheckLessThan", (inst, def) => {
	$ZodCheck.init(inst, def);
	const origin = numericOriginMap[typeof def.value];
	inst._zod.onattach.push((inst) => {
		const bag = inst._zod.bag;
		const curr = (def.inclusive ? bag.maximum : bag.exclusiveMaximum) ?? Number.POSITIVE_INFINITY;
		if (def.value < curr) {
			if (def.inclusive) bag.maximum = def.value;
			else bag.exclusiveMaximum = def.value;
		}
	});
	inst._zod.check = (payload) => {
		if (def.inclusive ? payload.value <= def.value : payload.value < def.value) return;
		payload.issues.push({
			origin: numericOriginMap[typeof payload.value] ?? origin,
			code: "too_big",
			maximum: typeof def.value === "object" ? def.value.getTime() : def.value,
			input: payload.value,
			inclusive: def.inclusive,
			inst,
			continue: !def.abort
		});
	};
});
const $ZodCheckGreaterThan = /*@__PURE__*/ $constructor("$ZodCheckGreaterThan", (inst, def) => {
	$ZodCheck.init(inst, def);
	const origin = numericOriginMap[typeof def.value];
	inst._zod.onattach.push((inst) => {
		const bag = inst._zod.bag;
		const curr = (def.inclusive ? bag.minimum : bag.exclusiveMinimum) ?? Number.NEGATIVE_INFINITY;
		if (def.value > curr) {
			if (def.inclusive) bag.minimum = def.value;
			else bag.exclusiveMinimum = def.value;
		}
	});
	inst._zod.check = (payload) => {
		if (def.inclusive ? payload.value >= def.value : payload.value > def.value) return;
		payload.issues.push({
			origin: numericOriginMap[typeof payload.value] ?? origin,
			code: "too_small",
			minimum: typeof def.value === "object" ? def.value.getTime() : def.value,
			input: payload.value,
			inclusive: def.inclusive,
			inst,
			continue: !def.abort
		});
	};
});
const $ZodCheckMultipleOf = /*@__PURE__*/ $constructor("$ZodCheckMultipleOf", (inst, def) => {
	$ZodCheck.init(inst, def);
	inst._zod.onattach.push((inst) => {
		var _a;
		(_a = inst._zod.bag).multipleOf ?? (_a.multipleOf = def.value);
	});
	inst._zod.check = (payload) => {
		if (typeof payload.value !== typeof def.value) throw new Error("Cannot mix number and bigint in multiple_of check.");
		if (typeof payload.value === "bigint" ? def.value !== BigInt(0) && payload.value % def.value === BigInt(0) : floatSafeRemainder(payload.value, def.value) === 0) return;
		payload.issues.push({
			origin: typeof payload.value,
			code: "not_multiple_of",
			divisor: def.value,
			input: payload.value,
			inst,
			continue: !def.abort
		});
	};
});
const $ZodCheckNumberFormat = /*@__PURE__*/ $constructor("$ZodCheckNumberFormat", (inst, def) => {
	$ZodCheck.init(inst, def);
	def.format = def.format || "float64";
	const isInt = def.format?.includes("int");
	const origin = isInt ? "int" : "number";
	const [minimum, maximum] = NUMBER_FORMAT_RANGES[def.format];
	inst._zod.onattach.push((inst) => {
		const bag = inst._zod.bag;
		bag.format = def.format;
		bag.minimum = minimum;
		bag.maximum = maximum;
		if (isInt) bag.pattern = integer;
	});
	inst._zod.check = (payload) => {
		const input = payload.value;
		if (isInt) {
			if (!Number.isInteger(input)) {
				payload.issues.push({
					expected: origin,
					format: def.format,
					code: "invalid_type",
					continue: false,
					input,
					inst
				});
				return;
			}
			if (!Number.isSafeInteger(input)) {
				if (input > 0) payload.issues.push({
					input,
					code: "too_big",
					maximum: Number.MAX_SAFE_INTEGER,
					note: "Integers must be within the safe integer range.",
					inst,
					origin,
					inclusive: true,
					continue: !def.abort
				});
				else payload.issues.push({
					input,
					code: "too_small",
					minimum: Number.MIN_SAFE_INTEGER,
					note: "Integers must be within the safe integer range.",
					inst,
					origin,
					inclusive: true,
					continue: !def.abort
				});
				return;
			}
		}
		if (input < minimum) payload.issues.push({
			origin: "number",
			input,
			code: "too_small",
			minimum,
			inclusive: true,
			inst,
			continue: !def.abort
		});
		if (input > maximum) payload.issues.push({
			origin: "number",
			input,
			code: "too_big",
			maximum,
			inclusive: true,
			inst,
			continue: !def.abort
		});
	};
});
const $ZodCheckMaxLength = /*@__PURE__*/ $constructor("$ZodCheckMaxLength", (inst, def) => {
	var _a;
	$ZodCheck.init(inst, def);
	(_a = inst._zod.def).when ?? (_a.when = _whenHasLength);
	inst._zod.onattach.push((inst) => {
		const curr = inst._zod.bag.maximum ?? Number.POSITIVE_INFINITY;
		if (def.maximum < curr) inst._zod.bag.maximum = def.maximum;
	});
	inst._zod.check = (payload) => {
		const input = payload.value;
		const units = input.length;
		if ((typeof input === "string" && units > def.maximum ? codePointLength(input) : units) <= def.maximum) return;
		const origin = getLengthableOrigin(input);
		payload.issues.push({
			origin,
			code: "too_big",
			maximum: def.maximum,
			inclusive: true,
			input,
			inst,
			continue: !def.abort
		});
	};
});
const $ZodCheckMinLength = /*@__PURE__*/ $constructor("$ZodCheckMinLength", (inst, def) => {
	var _a;
	$ZodCheck.init(inst, def);
	(_a = inst._zod.def).when ?? (_a.when = _whenHasLength);
	inst._zod.onattach.push((inst) => {
		const curr = inst._zod.bag.minimum ?? Number.NEGATIVE_INFINITY;
		if (def.minimum > curr) inst._zod.bag.minimum = def.minimum;
	});
	inst._zod.check = (payload) => {
		const input = payload.value;
		const units = input.length;
		if ((typeof input === "string" && units >= def.minimum && units < def.minimum * 2 ? codePointLength(input) : units) >= def.minimum) return;
		const origin = getLengthableOrigin(input);
		payload.issues.push({
			origin,
			code: "too_small",
			minimum: def.minimum,
			inclusive: true,
			input,
			inst,
			continue: !def.abort
		});
	};
});
const $ZodCheckLengthEquals = /*@__PURE__*/ $constructor("$ZodCheckLengthEquals", (inst, def) => {
	var _a;
	$ZodCheck.init(inst, def);
	(_a = inst._zod.def).when ?? (_a.when = _whenHasLength);
	inst._zod.onattach.push((inst) => {
		const bag = inst._zod.bag;
		bag.minimum = def.length;
		bag.maximum = def.length;
		bag.length = def.length;
	});
	inst._zod.check = (payload) => {
		const input = payload.value;
		const units = input.length;
		const length = typeof input === "string" && units >= def.length && units <= def.length * 2 ? codePointLength(input) : units;
		if (length === def.length) return;
		const origin = getLengthableOrigin(input);
		const tooBig = length > def.length;
		payload.issues.push({
			origin,
			...tooBig ? {
				code: "too_big",
				maximum: def.length
			} : {
				code: "too_small",
				minimum: def.length
			},
			inclusive: true,
			exact: true,
			input: payload.value,
			inst,
			continue: !def.abort
		});
	};
});
const $ZodCheckStringFormat = /*@__PURE__*/ $constructor("$ZodCheckStringFormat", (inst, def) => {
	var _a, _b;
	$ZodCheck.init(inst, def);
	inst._zod.onattach.push((inst) => {
		const bag = inst._zod.bag;
		bag.format = def.format;
		if (def.pattern) {
			bag.patterns ?? (bag.patterns = /* @__PURE__ */ new Set());
			bag.patterns.add(def.pattern);
		}
	});
	if (def.pattern) (_a = inst._zod).check ?? (_a.check = (payload) => {
		def.pattern.lastIndex = 0;
		if (def.pattern.test(payload.value)) return;
		payload.issues.push({
			origin: "string",
			code: "invalid_format",
			format: def.format,
			input: payload.value,
			...def.pattern ? { pattern: def.pattern.toString() } : {},
			inst,
			continue: !def.abort
		});
	});
	else (_b = inst._zod).check ?? (_b.check = () => {});
});
const $ZodCheckRegex = /*@__PURE__*/ $constructor("$ZodCheckRegex", (inst, def) => {
	$ZodCheckStringFormat.init(inst, def);
	inst._zod.check = (payload) => {
		def.pattern.lastIndex = 0;
		if (def.pattern.test(payload.value)) return;
		payload.issues.push({
			origin: "string",
			code: "invalid_format",
			format: "regex",
			input: payload.value,
			pattern: def.pattern.toString(),
			inst,
			continue: !def.abort
		});
	};
});
const $ZodCheckLowerCase = /*@__PURE__*/ $constructor("$ZodCheckLowerCase", (inst, def) => {
	def.pattern ?? (def.pattern = lowercase);
	$ZodCheckStringFormat.init(inst, def);
});
const $ZodCheckUpperCase = /*@__PURE__*/ $constructor("$ZodCheckUpperCase", (inst, def) => {
	def.pattern ?? (def.pattern = uppercase);
	$ZodCheckStringFormat.init(inst, def);
});
const $ZodCheckIncludes = /*@__PURE__*/ $constructor("$ZodCheckIncludes", (inst, def) => {
	$ZodCheck.init(inst, def);
	const escapedRegex = escapeRegex(def.includes);
	const pattern = new RegExp(typeof def.position === "number" ? `^.{${def.position},}${escapedRegex}` : escapedRegex);
	def.pattern = pattern;
	inst._zod.onattach.push((inst) => {
		const bag = inst._zod.bag;
		bag.patterns ?? (bag.patterns = /* @__PURE__ */ new Set());
		bag.patterns.add(pattern);
	});
	inst._zod.check = (payload) => {
		if (payload.value.includes(def.includes, def.position)) return;
		payload.issues.push({
			origin: "string",
			code: "invalid_format",
			format: "includes",
			includes: def.includes,
			input: payload.value,
			inst,
			continue: !def.abort
		});
	};
});
const $ZodCheckStartsWith = /*@__PURE__*/ $constructor("$ZodCheckStartsWith", (inst, def) => {
	$ZodCheck.init(inst, def);
	const pattern = new RegExp(`^${escapeRegex(def.prefix)}.*`);
	def.pattern ?? (def.pattern = pattern);
	inst._zod.onattach.push((inst) => {
		const bag = inst._zod.bag;
		bag.patterns ?? (bag.patterns = /* @__PURE__ */ new Set());
		bag.patterns.add(pattern);
	});
	inst._zod.check = (payload) => {
		if (payload.value.startsWith(def.prefix)) return;
		payload.issues.push({
			origin: "string",
			code: "invalid_format",
			format: "starts_with",
			prefix: def.prefix,
			input: payload.value,
			inst,
			continue: !def.abort
		});
	};
});
const $ZodCheckEndsWith = /*@__PURE__*/ $constructor("$ZodCheckEndsWith", (inst, def) => {
	$ZodCheck.init(inst, def);
	const pattern = new RegExp(`.*${escapeRegex(def.suffix)}$`);
	def.pattern ?? (def.pattern = pattern);
	inst._zod.onattach.push((inst) => {
		const bag = inst._zod.bag;
		bag.patterns ?? (bag.patterns = /* @__PURE__ */ new Set());
		bag.patterns.add(pattern);
	});
	inst._zod.check = (payload) => {
		if (payload.value.endsWith(def.suffix)) return;
		payload.issues.push({
			origin: "string",
			code: "invalid_format",
			format: "ends_with",
			suffix: def.suffix,
			input: payload.value,
			inst,
			continue: !def.abort
		});
	};
});
const $ZodCheckOverwrite = /*@__PURE__*/ $constructor("$ZodCheckOverwrite", (inst, def) => {
	$ZodCheck.init(inst, def);
	inst._zod.check = (payload) => {
		payload.value = def.tx(payload.value);
	};
});
//#endregion
//#region node_modules/zod/v4/core/doc.js
var Doc = class {
	constructor(args = [], closed = {}) {
		this.content = [];
		this.indent = 0;
		this.args = args;
		this.closed = closed;
	}
	indented(fn) {
		this.indent += 1;
		fn(this);
		this.indent -= 1;
	}
	write(arg) {
		if (typeof arg === "function") {
			arg(this, { execution: "sync" });
			arg(this, { execution: "async" });
			return;
		}
		const lines = arg.split("\n").filter((x) => x);
		const minIndent = Math.min(...lines.map((x) => x.length - x.trimStart().length));
		const dedented = lines.map((x) => x.slice(minIndent)).map((x) => " ".repeat(this.indent * 2) + x);
		for (const line of dedented) this.content.push(line);
	}
	compile() {
		const F = Function;
		const content = this?.content ?? [``];
		return new F(...Object.keys(this.closed), `return function (${this.args.join(", ")}) {\n${content.join("\n")}\n};`)(...Object.values(this.closed));
	}
};
//#endregion
//#region node_modules/zod/v4/core/versions.js
const version = {
	major: 4,
	minor: 5,
	patch: 4
};
//#endregion
//#region node_modules/zod/v4/core/schemas.js
const $ZodType = /*@__PURE__*/ $constructor("$ZodType", (inst, def) => {
	var _a;
	inst ?? (inst = {});
	inst._zod.def = def;
	inst._zod.bag = inst._zod.bag || {};
	inst._zod.version = version;
	const defChecks = inst._zod.def.checks;
	const checks = inst._zod.traits.has("$ZodCheck") ? [inst, ...defChecks ?? []] : defChecks?.length ? [...defChecks] : [];
	for (const ch of checks) for (const fn of ch._zod.onattach) fn(inst);
	if (checks.length === 0) {
		(_a = inst._zod).deferred ?? (_a.deferred = []);
		inst._zod.deferred?.push(() => {
			inst._zod.run = inst._zod.parse;
		});
	} else {
		const runChecks = (payload, checks, ctx) => {
			if (payload.memo) return payload;
			let isAborted = aborted(payload);
			let asyncResult;
			for (const ch of checks) {
				if (ch._zod.def.when) {
					if (explicitlyAborted(payload)) continue;
					if (!ch._zod.def.when(payload)) continue;
				} else if (isAborted) continue;
				const currLen = payload.issues.length;
				const _ = ch._zod.check(payload);
				if (_ instanceof Promise && ctx?.async === false) throw new $ZodAsyncError();
				if (asyncResult || _ instanceof Promise) asyncResult = (asyncResult ?? Promise.resolve()).then(async () => {
					await _;
					if (payload.issues.length === currLen) return;
					attachSchema(payload.issues, currLen, inst);
					if (!isAborted) isAborted = aborted(payload, currLen);
				});
				else {
					if (payload.issues.length === currLen) continue;
					attachSchema(payload.issues, currLen, inst);
					if (!isAborted) isAborted = aborted(payload, currLen);
				}
			}
			if (asyncResult) return asyncResult.then(() => {
				return payload;
			});
			return payload;
		};
		const handleCanaryResult = (canary, payload, ctx) => {
			if (aborted(canary)) {
				canary.aborted = true;
				return canary;
			}
			const checkResult = runChecks(payload, checks, ctx);
			if (checkResult instanceof Promise) {
				if (ctx.async === false) throw new $ZodAsyncError();
				return checkResult.then((checkResult) => inst._zod.parse(checkResult, ctx));
			}
			return inst._zod.parse(checkResult, ctx);
		};
		inst._zod.run = (payload, ctx) => {
			if (ctx.skipChecks) return inst._zod.parse(payload, ctx);
			if (ctx.direction === "backward") {
				const canary = inst._zod.parse({
					value: payload.value,
					issues: []
				}, {
					...ctx,
					skipChecks: true
				});
				if (canary instanceof Promise) return canary.then((canary) => {
					return handleCanaryResult(canary, payload, ctx);
				});
				return handleCanaryResult(canary, payload, ctx);
			}
			const result = inst._zod.parse(payload, ctx);
			if (result instanceof Promise) {
				if (ctx.async === false) throw new $ZodAsyncError();
				return result.then((result) => runChecks(result, checks, ctx));
			}
			return runChecks(result, checks, ctx);
		};
	}
}, {
	get "~standard"() {
		return hide(this, "~standard", standardProps(this));
	},
	set "~standard"(value) {
		own(this, "~standard", value);
	}
});
/** The Standard Schema surface for `inst`. Shared so wrappers can extend it without forcing it. */
const toStandardResult = (r) => r.success ? { value: r.data } : { issues: r.error?.issues };
function standardProps(inst) {
	return {
		validate: (value) => {
			try {
				return toStandardResult(safeParse$1(inst, value));
			} catch (_) {
				return safeParseAsync$1(inst, value).then(toStandardResult);
			}
		},
		vendor: "zod",
		version: 1
	};
}
const $ZodString = /*@__PURE__*/ $constructor("$ZodString", (inst, def) => {
	$ZodType.init(inst, def);
	inst._zod.pattern = [...inst?._zod.bag?.patterns ?? []].pop() ?? string$1(inst._zod.bag);
	inst._zod.parse = (payload, _) => {
		if (def.coerce) try {
			payload.value = String(payload.value);
		} catch (_) {}
		if (typeof payload.value === "string") return payload;
		payload.issues.push({
			expected: "string",
			code: "invalid_type",
			input: payload.value,
			inst
		});
		return payload;
	};
});
const $ZodStringFormat = /*@__PURE__*/ $constructor("$ZodStringFormat", (inst, def) => {
	$ZodCheckStringFormat.init(inst, def);
	$ZodString.init(inst, def);
});
const $ZodGUID = /*@__PURE__*/ $constructor("$ZodGUID", (inst, def) => {
	def.pattern ?? (def.pattern = guid);
	$ZodStringFormat.init(inst, def);
});
const $ZodUUID = /*@__PURE__*/ $constructor("$ZodUUID", (inst, def) => {
	if (def.version) {
		const v = {
			v1: 1,
			v2: 2,
			v3: 3,
			v4: 4,
			v5: 5,
			v6: 6,
			v7: 7,
			v8: 8
		}[def.version];
		if (v === void 0) throw new Error(`Invalid UUID version: "${def.version}"`);
		def.pattern ?? (def.pattern = uuid(v));
	} else def.pattern ?? (def.pattern = uuid());
	$ZodStringFormat.init(inst, def);
});
const $ZodEmail = /*@__PURE__*/ $constructor("$ZodEmail", (inst, def) => {
	def.pattern ?? (def.pattern = email);
	$ZodStringFormat.init(inst, def);
});
/** Parses a URL for `$ZodURL`, applying the one guard the URL constructor cannot express. Returns the parsed URL, or a code naming the stage that rejected it — the runtime needs that distinction to pick an issue note, and compiled code only needs to know it is not a URL. */
function parseURLObject(trimmed, def) {
	if (!def.normalize && def.protocol?.source === httpProtocol.source && !/^https?:\/\//i.test(trimmed)) return 1;
	try {
		return new URL(trimmed);
	} catch {
		return 2;
	}
}
const asciiTabOrNewline = /[\t\n\r]/g;
/** The URL parser deletes every ASCII tab, LF and CR from its input before it parses, so `new URL("https://exa\nmple.com")` reports on `example.com`. Applying the same deletion to the returned value closes the half of that divergence which can move the host; the parser's other rewrite, stripping C0 controls at the edges, cannot. */
function stripTabAndNewline(value) {
	return value.replace(asciiTabOrNewline, "");
}
function urlHostnameOk(url, hostname) {
	hostname.lastIndex = 0;
	return hostname.test(url.hostname);
}
function urlProtocolOk(url, protocol) {
	protocol.lastIndex = 0;
	return protocol.test(url.protocol.endsWith(":") ? url.protocol.slice(0, -1) : url.protocol);
}
const $ZodURL = /*@__PURE__*/ $constructor("$ZodURL", (inst, def) => {
	$ZodStringFormat.init(inst, def);
	inst._zod.check = (payload) => {
		try {
			const trimmed = payload.value.trim();
			const url = parseURLObject(trimmed, def);
			if (url === 1) {
				payload.issues.push({
					code: "invalid_format",
					format: "url",
					note: "Invalid URL format",
					input: payload.value,
					inst,
					continue: !def.abort
				});
				return;
			}
			if (url === 2) {
				payload.issues.push({
					code: "invalid_format",
					format: "url",
					input: payload.value,
					inst,
					continue: !def.abort
				});
				return;
			}
			if (def.hostname && !urlHostnameOk(url, def.hostname)) payload.issues.push({
				code: "invalid_format",
				format: "url",
				note: "Invalid hostname",
				pattern: def.hostname.source,
				input: payload.value,
				inst,
				continue: !def.abort
			});
			if (def.protocol && !urlProtocolOk(url, def.protocol)) payload.issues.push({
				code: "invalid_format",
				format: "url",
				note: "Invalid protocol",
				pattern: def.protocol.source,
				input: payload.value,
				inst,
				continue: !def.abort
			});
			payload.value = def.normalize ? url.href : stripTabAndNewline(trimmed);
			return;
		} catch (_) {
			payload.issues.push({
				code: "invalid_format",
				format: "url",
				input: payload.value,
				inst,
				continue: !def.abort
			});
		}
	};
});
const $ZodEmoji = /*@__PURE__*/ $constructor("$ZodEmoji", (inst, def) => {
	def.pattern ?? (def.pattern = emoji());
	$ZodStringFormat.init(inst, def);
});
const $ZodNanoID = /*@__PURE__*/ $constructor("$ZodNanoID", (inst, def) => {
	if (def.length !== void 0 && (!Number.isInteger(def.length) || def.length < 1)) throw new Error(`Invalid nanoid length: ${def.length}`);
	def.pattern ?? (def.pattern = def.length === void 0 ? nanoid : nanoidOfLength(def.length));
	$ZodStringFormat.init(inst, def);
});
/**
* @deprecated CUID v1 is deprecated by its authors due to information leakage
* (timestamps embedded in the id). Use {@link $ZodCUID2} instead.
* See https://github.com/paralleldrive/cuid.
*/
const $ZodCUID = /*@__PURE__*/ $constructor("$ZodCUID", (inst, def) => {
	def.pattern ?? (def.pattern = cuid);
	$ZodStringFormat.init(inst, def);
});
const $ZodCUID2 = /*@__PURE__*/ $constructor("$ZodCUID2", (inst, def) => {
	def.pattern ?? (def.pattern = cuid2);
	$ZodStringFormat.init(inst, def);
});
const $ZodULID = /*@__PURE__*/ $constructor("$ZodULID", (inst, def) => {
	def.pattern ?? (def.pattern = ulid);
	$ZodStringFormat.init(inst, def);
});
const $ZodXID = /*@__PURE__*/ $constructor("$ZodXID", (inst, def) => {
	def.pattern ?? (def.pattern = xid);
	$ZodStringFormat.init(inst, def);
});
const $ZodKSUID = /*@__PURE__*/ $constructor("$ZodKSUID", (inst, def) => {
	def.pattern ?? (def.pattern = ksuid);
	$ZodStringFormat.init(inst, def);
});
const $ZodISODateTime = /*@__PURE__*/ $constructor("$ZodISODateTime", (inst, def) => {
	def.pattern ?? (def.pattern = datetime(def));
	$ZodStringFormat.init(inst, def);
	if (def.local || def.precision === -1) {
		inst._zod.bag.laxFormat = true;
		inst._zod.onattach.push((s) => {
			s._zod.bag.laxFormat = true;
		});
	}
});
const $ZodISODate = /*@__PURE__*/ $constructor("$ZodISODate", (inst, def) => {
	def.pattern ?? (def.pattern = date);
	$ZodStringFormat.init(inst, def);
});
const $ZodISOTime = /*@__PURE__*/ $constructor("$ZodISOTime", (inst, def) => {
	def.pattern ?? (def.pattern = time(def));
	$ZodStringFormat.init(inst, def);
});
const $ZodISODuration = /*@__PURE__*/ $constructor("$ZodISODuration", (inst, def) => {
	def.pattern ?? (def.pattern = duration);
	$ZodStringFormat.init(inst, def);
});
const $ZodIPv4 = /*@__PURE__*/ $constructor("$ZodIPv4", (inst, def) => {
	def.pattern ?? (def.pattern = ipv4);
	$ZodStringFormat.init(inst, def);
	inst._zod.bag.format = `ipv4`;
});
/** An IPv6 address is written with hex digits, colons and dots, and nothing else. The guard is what makes the check below an IPv6 check: `new URL("http://[...]")` parses an authority, not an address, so `@` and `\` re-delimit it and `"::@1\\"` validates against the host `0.0.0.1`. The URL parser also deletes ASCII tab, LF and CR rather than failing, which is how `"::1\n"` validated as `::1`. */
const ipv6Alphabet = /^[0-9a-fA-F:.]+$/;
function isValidIPv6(value) {
	if (!ipv6Alphabet.test(value)) return false;
	try {
		new URL(`http://[${value}]`);
		return true;
	} catch {
		return false;
	}
}
const $ZodIPv6 = /*@__PURE__*/ $constructor("$ZodIPv6", (inst, def) => {
	def.pattern ?? (def.pattern = ipv6);
	$ZodStringFormat.init(inst, def);
	inst._zod.bag.format = `ipv6`;
	inst._zod.check = (payload) => {
		if (!isValidIPv6(payload.value)) payload.issues.push({
			code: "invalid_format",
			format: "ipv6",
			input: payload.value,
			inst,
			continue: !def.abort
		});
	};
});
const $ZodCIDRv4 = /*@__PURE__*/ $constructor("$ZodCIDRv4", (inst, def) => {
	def.pattern ?? (def.pattern = cidrv4);
	$ZodStringFormat.init(inst, def);
});
function isValidCIDRv6(value) {
	const parts = value.split("/");
	if (parts.length !== 2) return false;
	const [address, prefix] = parts;
	if (!prefix) return false;
	const prefixNum = Number(prefix);
	if (`${prefixNum}` !== prefix) return false;
	if (prefixNum < 0 || prefixNum > 128) return false;
	return isValidIPv6(address);
}
const $ZodCIDRv6 = /*@__PURE__*/ $constructor("$ZodCIDRv6", (inst, def) => {
	def.pattern ?? (def.pattern = cidrv6);
	$ZodStringFormat.init(inst, def);
	inst._zod.check = (payload) => {
		if (!isValidCIDRv6(payload.value)) payload.issues.push({
			code: "invalid_format",
			format: "cidrv6",
			input: payload.value,
			inst,
			continue: !def.abort
		});
	};
});
function isValidBase64(data) {
	if (data === "") return true;
	if (/\s/.test(data)) return false;
	if (data.length % 4 !== 0) return false;
	try {
		atob(data);
		return true;
	} catch {
		return false;
	}
}
const $ZodBase64 = /*@__PURE__*/ $constructor("$ZodBase64", (inst, def) => {
	def.pattern ?? (def.pattern = base64);
	$ZodStringFormat.init(inst, def);
	inst._zod.bag.contentEncoding = "base64";
	inst._zod.check = (payload) => {
		if (isValidBase64(payload.value)) return;
		payload.issues.push({
			code: "invalid_format",
			format: "base64",
			input: payload.value,
			inst,
			continue: !def.abort
		});
	};
});
function isValidBase64URL(data) {
	if (!base64url.test(data)) return false;
	const base64 = data.replace(/[-_]/g, (c) => c === "-" ? "+" : "/");
	return isValidBase64(base64.padEnd(Math.ceil(base64.length / 4) * 4, "="));
}
const $ZodBase64URL = /*@__PURE__*/ $constructor("$ZodBase64URL", (inst, def) => {
	def.pattern ?? (def.pattern = base64url);
	$ZodStringFormat.init(inst, def);
	inst._zod.bag.contentEncoding = "base64url";
	inst._zod.check = (payload) => {
		if (isValidBase64URL(payload.value)) return;
		payload.issues.push({
			code: "invalid_format",
			format: "base64url",
			input: payload.value,
			inst,
			continue: !def.abort
		});
	};
});
const $ZodE164 = /*@__PURE__*/ $constructor("$ZodE164", (inst, def) => {
	def.pattern ?? (def.pattern = e164);
	$ZodStringFormat.init(inst, def);
});
function isValidJWT(token, algorithm = null) {
	try {
		const tokensParts = token.split(".");
		if (tokensParts.length !== 3) return false;
		const [header] = tokensParts;
		if (!header) return false;
		const parsedHeader = JSON.parse(atob(header));
		if ("typ" in parsedHeader && parsedHeader?.typ !== "JWT") return false;
		if (!parsedHeader.alg) return false;
		if (algorithm && (!("alg" in parsedHeader) || parsedHeader.alg !== algorithm)) return false;
		return true;
	} catch {
		return false;
	}
}
const $ZodJWT = /*@__PURE__*/ $constructor("$ZodJWT", (inst, def) => {
	$ZodStringFormat.init(inst, def);
	inst._zod.check = (payload) => {
		if (isValidJWT(payload.value, def.alg)) return;
		payload.issues.push({
			code: "invalid_format",
			format: "jwt",
			input: payload.value,
			inst,
			continue: !def.abort
		});
	};
});
const $ZodNumber = /*@__PURE__*/ $constructor("$ZodNumber", (inst, def) => {
	$ZodType.init(inst, def);
	inst._zod.pattern = inst._zod.bag.pattern ?? number$1;
	inst._zod.parse = (payload, _ctx) => {
		if (def.coerce) try {
			payload.value = Number(payload.value);
		} catch (_) {}
		const input = payload.value;
		if (typeof input === "number" && !Number.isNaN(input) && Number.isFinite(input)) return payload;
		const received = typeof input === "number" ? Number.isNaN(input) ? "NaN" : !Number.isFinite(input) ? String(input) : void 0 : void 0;
		payload.issues.push({
			expected: "number",
			code: "invalid_type",
			input,
			inst,
			...received ? { received } : {}
		});
		return payload;
	};
});
const $ZodNumberFormat = /*@__PURE__*/ $constructor("$ZodNumberFormat", (inst, def) => {
	$ZodCheckNumberFormat.init(inst, def);
	$ZodNumber.init(inst, def);
});
const $ZodBoolean = /*@__PURE__*/ $constructor("$ZodBoolean", (inst, def) => {
	$ZodType.init(inst, def);
	inst._zod.pattern = boolean$1;
	inst._zod.parse = (payload, _ctx) => {
		if (def.coerce) try {
			payload.value = Boolean(payload.value);
		} catch (_) {}
		const input = payload.value;
		if (typeof input === "boolean") return payload;
		payload.issues.push({
			expected: "boolean",
			code: "invalid_type",
			input,
			inst
		});
		return payload;
	};
});
const $ZodUnknown = /*@__PURE__*/ $constructor("$ZodUnknown", (inst, def) => {
	$ZodType.init(inst, def);
	inst._zod.parse = (payload) => payload;
});
const $ZodNever = /*@__PURE__*/ $constructor("$ZodNever", (inst, def) => {
	$ZodType.init(inst, def);
	inst._zod.parse = (payload, _ctx) => {
		payload.issues.push({
			expected: "never",
			code: "invalid_type",
			input: payload.value,
			inst
		});
		return payload;
	};
});
function handleArrayResult(result, final, index) {
	if (result.issues.length) final.issues.push(...prefixIssues(index, result.issues));
	final.value[index] = result.value;
}
const $ZodArray = /*@__PURE__*/ $constructor("$ZodArray", (inst, def) => {
	$ZodType.init(inst, def);
	const memo = globalConfig.memoizer;
	memo?.attach(inst);
	inst._zod.parse = (payload, ctx) => {
		const input = payload.value;
		if (!Array.isArray(input)) {
			payload.issues.push({
				expected: "array",
				code: "invalid_type",
				input,
				inst
			});
			return payload;
		}
		payload.value = memo ? memo.alloc(inst, payload, Array(input.length), ctx) : Array(input.length);
		const proms = [];
		for (let i = 0; i < input.length; i++) {
			const item = input[i];
			const result = def.element._zod.run({
				value: item,
				issues: []
			}, ctx);
			if (result instanceof Promise) proms.push(result.then((result) => handleArrayResult(result, payload, i)));
			else handleArrayResult(result, payload, i);
		}
		if (proms.length) return Promise.all(proms).then(() => payload);
		return payload;
	};
});
function handlePropertyResult(result, final, key, input, optin, optout) {
	const isPresent = key in input;
	const isOptionalOut = optout === "optional";
	if (!isPresent && isOptionalOut && optin === "optional") return;
	if (result.issues.length) {
		if (optin !== void 0 && isOptionalOut && !isPresent) return;
		final.issues.push(...prefixIssues(key, result.issues));
	}
	if (!isPresent && optin === void 0) {
		if (!result.issues.length) final.issues.push({
			code: "invalid_type",
			expected: "nonoptional",
			input: void 0,
			path: [key]
		});
		return;
	}
	if (result.value === void 0) {
		if (isPresent) final.value[key] = void 0;
	} else final.value[key] = result.value;
}
const NO_SYMBOL_KEYS = [];
function normalizeDef(def) {
	const keys = Object.keys(def.shape);
	const ownSymbols = Object.getOwnPropertySymbols(def.shape);
	const symbolKeys = ownSymbols.length ? ownSymbols : NO_SYMBOL_KEYS;
	const allKeys = symbolKeys.length ? [...keys, ...symbolKeys] : keys;
	for (const k of allKeys) if (!def.shape?.[k]?._zod?.traits?.has("$ZodType")) throw new Error(`Invalid element at key "${String(k)}": expected a Zod schema`);
	const okeys = optionalKeys(def.shape);
	return {
		...def,
		allKeys,
		symbolKeys,
		keySet: new Set(keys),
		numKeys: keys.length,
		optionalKeys: new Set(okeys)
	};
}
function handleCatchall(proms, input, payload, ctx, def, inst) {
	const unrecognized = [];
	const keySet = def.keySet;
	const _catchall = def.catchall._zod;
	const t = _catchall.def.type;
	const optin = _catchall.optin;
	const optout = _catchall.optout;
	for (const key in input) {
		if (keySet.has(key)) continue;
		if (key === "__proto__") {
			if (t === "never") unrecognized.push(key);
			continue;
		}
		if (t === "never") {
			unrecognized.push(key);
			continue;
		}
		const r = _catchall.run({
			value: input[key],
			issues: []
		}, ctx);
		if (r instanceof Promise) proms.push(r.then((r) => handlePropertyResult(r, payload, key, input, optin, optout)));
		else handlePropertyResult(r, payload, key, input, optin, optout);
	}
	if (unrecognized.length) payload.issues.push({
		code: "unrecognized_keys",
		keys: unrecognized,
		input,
		inst,
		continue: true
	});
	if (!proms.length) return payload;
	return Promise.all(proms).then(() => {
		return payload;
	});
}
const propShapes = /* @__PURE__ */ new WeakMap();
const $ZodObject = /*@__PURE__*/ $constructor("$ZodObject", (inst, def) => {
	$ZodType.init(inst, def);
	if (!Object.getOwnPropertyDescriptor(def, "shape")?.get) {
		const sh = def.shape;
		propShapes.set(def, sh);
		Object.defineProperty(def, "shape", { get: () => {
			const newSh = { ...sh };
			Object.defineProperty(def, "shape", { value: newSh });
			propShapes.set(def, newSh);
			return newSh;
		} });
	}
	const _normalized = cached(() => normalizeDef(def));
	defineLazyInternal(inst, "propValues", (zod) => {
		const shape = zod.def.shape;
		const propValues = {};
		for (const key in shape) {
			const field = shape[key]._zod;
			if (field.values) {
				if (!Object.prototype.hasOwnProperty.call(propValues, key)) assignProp(propValues, key, /* @__PURE__ */ new Set());
				for (const v of field.values) propValues[key].add(v);
				if (field.optin !== void 0) propValues[key].add(void 0);
			}
		}
		return propValues;
	});
	const isObject$1 = isObject;
	const catchall = def.catchall;
	let value;
	const memo = globalConfig.memoizer;
	memo?.attach(inst);
	inst._zod.parse = (payload, ctx) => {
		value ?? (value = _normalized.value);
		const input = payload.value;
		if (!isObject$1(input)) {
			payload.issues.push({
				expected: "object",
				code: "invalid_type",
				input,
				inst
			});
			return payload;
		}
		payload.value = memo ? memo.alloc(inst, payload, {}, ctx) : {};
		const proms = [];
		const shape = value.shape;
		for (const key of value.allKeys) {
			if (key === "__proto__") continue;
			const el = shape[key];
			const optin = el._zod.optin;
			const optout = el._zod.optout;
			const r = el._zod.run({
				value: input[key],
				issues: []
			}, ctx);
			if (r instanceof Promise) proms.push(r.then((r) => handlePropertyResult(r, payload, key, input, optin, optout)));
			else handlePropertyResult(r, payload, key, input, optin, optout);
		}
		if (!catchall) return proms.length ? Promise.all(proms).then(() => payload) : payload;
		return handleCatchall(proms, input, payload, ctx, _normalized.value, inst);
	};
});
const $ZodObjectJIT = /*@__PURE__*/ $constructor("$ZodObjectJIT", (inst, def) => {
	$ZodObject.init(inst, def);
	const superParse = inst._zod.parse;
	const _normalized = cached(() => normalizeDef(def));
	const memo = globalConfig.memoizer;
	const generateFastpass = (shape) => {
		const normalized = _normalized.value;
		const syms = normalized.symbolKeys;
		const doc = new Doc(["payload", "ctx"], {
			shape,
			inst,
			memo,
			syms
		});
		const parseStr = (k) => `shape[${k}]._zod.run({ value: input[${k}], issues: [] }, ctx)`;
		const prefixStr = (id, k) => `
          for (let i = 0; i < ${id}.issues.length; i++) {
            const iss = ${id}.issues[i];
            iss.path = iss.path ? [${k}, ...iss.path] : [${k}];
            payload.issues.push(iss);
          }`;
		doc.write(`const input = payload.value;`);
		const ids = Object.create(null);
		let counter = 0;
		for (const key of normalized.allKeys) ids[key] = `key_${counter++}`;
		doc.write(memo ? `const newResult = memo.alloc(inst, payload, {}, ctx);` : `const newResult = {};`);
		for (const key of normalized.allKeys) {
			if (key === "__proto__") continue;
			const id = ids[key];
			const k = typeof key === "symbol" ? `syms[${syms.indexOf(key)}]` : esc$1(key);
			const isPresent = `${k} in input`;
			const schema = shape[key];
			const optin = schema?._zod?.optin;
			const isOptionalIn = optin !== void 0;
			const isOptionalOut = schema?._zod?.optout === "optional";
			doc.write(`const ${id} = ${parseStr(k)};`);
			if (isOptionalIn && isOptionalOut) {
				const assign = optin === "optional" ? `${id}_present` : `${id}.value !== undefined || ${id}_present`;
				doc.write(`
        const ${id}_present = ${isPresent};
        if (!${id}.issues.length || ${id}_present) {
          if (${id}.issues.length) {${prefixStr(id, k)}
          }

          if (${assign}) {
            newResult[${k}] = ${id}.value;
          }
        }

      `);
			} else if (!isOptionalIn) doc.write(`
        const ${id}_present = ${isPresent};
        if (${id}.issues.length) {${prefixStr(id, k)}
        }
        if (!${id}_present && !${id}.issues.length) {
          payload.issues.push({
            code: "invalid_type",
            expected: "nonoptional",
            input: undefined,
            path: [${k}]
          });
        }

        if (${id}_present) {
          newResult[${k}] = ${id}.value;
        }

      `);
			else doc.write(`
        if (${id}.issues.length) {${prefixStr(id, k)}
        }

        if (${id}.value === undefined) {
          if (${isPresent}) {
            newResult[${k}] = undefined;
          }
        } else {
          newResult[${k}] = ${id}.value;
        }

      `);
		}
		doc.write(`payload.value = newResult;`);
		doc.write(`return payload;`);
		return doc.compile();
	};
	let fastpass;
	const isObject$2 = isObject;
	const jit = !globalConfig.jitless;
	const fastEnabled = jit && allowsEval.value;
	const catchall = def.catchall;
	let value;
	inst._zod.parse = (payload, ctx) => {
		value ?? (value = _normalized.value);
		const input = payload.value;
		if (!isObject$2(input)) {
			payload.issues.push({
				expected: "object",
				code: "invalid_type",
				input,
				inst
			});
			return payload;
		}
		if (jit && fastEnabled && ctx?.async === false && ctx.jitless !== true) {
			if (!fastpass) fastpass = generateFastpass(def.shape);
			payload = fastpass(payload, ctx);
			if (!catchall) return payload;
			return handleCatchall([], input, payload, ctx, value, inst);
		}
		return superParse(payload, ctx);
	};
});
function handleUnionResults(results, final, inst, ctx) {
	for (const result of results) if (result.issues.length === 0) {
		final.value = result.value;
		return final;
	}
	const nonaborted = results.filter((r) => !aborted(r));
	if (nonaborted.length === 1) {
		final.value = nonaborted[0].value;
		return nonaborted[0];
	}
	final.issues.push({
		code: "invalid_union",
		input: final.value,
		inst,
		errors: results.map((result) => result.issues.map((iss) => finalizeIssue(iss, ctx, config())))
	});
	return final;
}
const $ZodUnion = /*@__PURE__*/ $constructor("$ZodUnion", (inst, def) => {
	$ZodType.init(inst, def);
	defineLazyInternal(inst, "optin", (zod) => zod.def.options.some((o) => o._zod.optin === "defaulted") ? "defaulted" : zod.def.options.some((o) => o._zod.optin !== void 0) ? "optional" : void 0);
	defineLazyInternal(inst, "optout", (zod) => zod.def.options.some((o) => o._zod.optout === "optional") ? "optional" : void 0);
	defineLazyInternal(inst, "values", (zod) => {
		if (zod.def.options.every((o) => o._zod.values)) return new Set(zod.def.options.flatMap((option) => Array.from(option._zod.values)));
	});
	defineLazyInternal(inst, "pattern", (zod) => {
		if (zod.def.options.every((o) => o._zod.pattern)) {
			const patterns = zod.def.options.map((o) => o._zod.pattern);
			return new RegExp(`^(${patterns.map((p) => cleanRegex(p.source)).join("|")})$`);
		}
	});
	const first = def.options.length === 1 ? def.options[0]._zod.run : null;
	inst._zod.parse = (payload, ctx) => {
		if (first) return first(payload, ctx);
		let async = false;
		const results = [];
		for (const option of def.options) {
			const result = option._zod.run({
				value: payload.value,
				issues: []
			}, ctx);
			if (result instanceof Promise) {
				results.push(result);
				async = true;
			} else {
				if (result.issues.length === 0) return result;
				results.push(result);
			}
		}
		if (!async) return handleUnionResults(results, payload, inst, ctx);
		return Promise.all(results).then((results) => {
			return handleUnionResults(results, payload, inst, ctx);
		});
	};
});
const $ZodIntersection = /*@__PURE__*/ $constructor("$ZodIntersection", (inst, def) => {
	$ZodType.init(inst, def);
	inst._zod.parse = (payload, ctx) => {
		const input = payload.value;
		const left = def.left._zod.run({
			value: input,
			issues: []
		}, ctx);
		const right = def.right._zod.run({
			value: input,
			issues: []
		}, ctx);
		if (left instanceof Promise || right instanceof Promise) return Promise.all([left, right]).then(([left, right]) => {
			return handleIntersectionResults(payload, left, right);
		});
		return handleIntersectionResults(payload, left, right);
	};
});
function mergeValues(a, b) {
	if (a === b) return {
		valid: true,
		data: a
	};
	if (a instanceof Date && b instanceof Date && +a === +b) return {
		valid: true,
		data: a
	};
	if (isPlainObject(a) && isPlainObject(b)) {
		const bKeys = Object.keys(b);
		const sharedKeys = Object.keys(a).filter((key) => bKeys.indexOf(key) !== -1);
		const newObj = {
			...a,
			...b
		};
		if (Object.prototype.hasOwnProperty.call(newObj, "__proto__")) delete newObj.__proto__;
		for (const key of sharedKeys) {
			if (key === "__proto__") continue;
			const sharedValue = mergeValues(a[key], b[key]);
			if (!sharedValue.valid) return {
				valid: false,
				mergeErrorPath: [key, ...sharedValue.mergeErrorPath]
			};
			newObj[key] = sharedValue.data;
		}
		return {
			valid: true,
			data: newObj
		};
	}
	if (Array.isArray(a) && Array.isArray(b)) {
		if (a.length !== b.length) return {
			valid: false,
			mergeErrorPath: []
		};
		const newArray = [];
		for (let index = 0; index < a.length; index++) {
			const itemA = a[index];
			const itemB = b[index];
			const sharedValue = mergeValues(itemA, itemB);
			if (!sharedValue.valid) return {
				valid: false,
				mergeErrorPath: [index, ...sharedValue.mergeErrorPath]
			};
			newArray.push(sharedValue.data);
		}
		return {
			valid: true,
			data: newArray
		};
	}
	return {
		valid: false,
		mergeErrorPath: []
	};
}
function handleIntersectionResults(result, left, right) {
	const unrecKeys = /* @__PURE__ */ new Map();
	let unrecIssue;
	const keyIssues = /* @__PURE__ */ new Map();
	const collect = (iss, side) => {
		let keys;
		if (iss.code === "unrecognized_keys" && !iss.path?.length) {
			unrecIssue ?? (unrecIssue = iss);
			keys = iss.keys;
		} else if (iss.code === "invalid_key" && iss.origin === "record" && iss.path?.length === 1) {
			const k = String(iss.path[0]);
			if (!keyIssues.has(k)) keyIssues.set(k, iss);
			keys = [k];
		} else return false;
		for (const k of keys) {
			if (!unrecKeys.has(k)) unrecKeys.set(k, {});
			unrecKeys.get(k)[side] = true;
		}
		return true;
	};
	for (const iss of left.issues) if (!collect(iss, "l")) result.issues.push(iss);
	for (const iss of right.issues) if (!collect(iss, "r")) result.issues.push(iss);
	const bothKeys = [...unrecKeys].filter(([, f]) => f.l && f.r).map(([k]) => k);
	if (bothKeys.length) {
		const aggregated = unrecIssue ? bothKeys.filter((k) => unrecIssue.keys.includes(k)) : [];
		if (aggregated.length) result.issues.push({
			...unrecIssue,
			keys: aggregated
		});
		for (const k of bothKeys) if (!aggregated.includes(k) && keyIssues.has(k)) result.issues.push(keyIssues.get(k));
	}
	const merged = mergeValues(left.value, right.value);
	if (!merged.valid) {
		if (aborted(result)) return result;
		throw new Error(`Unmergable intersection. Error path: ${JSON.stringify(merged.mergeErrorPath)}`);
	}
	result.value = merged.data;
	return result;
}
const $ZodRecord = /*@__PURE__*/ $constructor("$ZodRecord", (inst, def) => {
	$ZodType.init(inst, def);
	const memo = globalConfig.memoizer;
	memo?.attach(inst);
	inst._zod.parse = (payload, ctx) => {
		const input = payload.value;
		if (!isPlainObject(input)) {
			payload.issues.push({
				expected: "record",
				code: "invalid_type",
				input,
				inst
			});
			return payload;
		}
		const proms = [];
		const values = def.keyType._zod.values;
		if (values && !def.partial) {
			payload.value = memo ? memo.alloc(inst, payload, {}, ctx) : {};
			const recordKeys = /* @__PURE__ */ new Set();
			for (const key of values) if (typeof key === "string" || typeof key === "number" || typeof key === "symbol") {
				recordKeys.add(typeof key === "number" ? key.toString() : key);
				if (key === "__proto__") continue;
				const keyResult = def.keyType._zod.run({
					value: key,
					issues: []
				}, ctx);
				if (keyResult instanceof Promise) throw new Error("Async schemas not supported in object keys currently");
				if (keyResult.issues.length) {
					payload.issues.push({
						code: "invalid_key",
						origin: "record",
						issues: keyResult.issues.map((iss) => finalizeIssue(iss, ctx, config())),
						input: key,
						path: [key],
						inst
					});
					continue;
				}
				const outKey = keyResult.value;
				if (outKey === "__proto__") continue;
				const result = def.valueType._zod.run({
					value: input[key],
					issues: []
				}, ctx);
				if (result instanceof Promise) proms.push(result.then((result) => {
					if (result.issues.length) payload.issues.push(...prefixIssues(key, result.issues));
					payload.value[outKey] = result.value;
				}));
				else {
					if (result.issues.length) payload.issues.push(...prefixIssues(key, result.issues));
					payload.value[outKey] = result.value;
				}
			}
			let unrecognized;
			for (const key in input) if (!recordKeys.has(key)) {
				if (def.mode === "loose") {
					if (key === "__proto__") continue;
					payload.value[key] = input[key];
				} else {
					unrecognized = unrecognized ?? [];
					unrecognized.push(key);
				}
			}
			if (unrecognized && unrecognized.length > 0) payload.issues.push({
				code: "unrecognized_keys",
				input,
				inst,
				keys: unrecognized,
				continue: true
			});
		} else {
			payload.value = memo ? memo.alloc(inst, payload, {}, ctx) : {};
			let unrecognized;
			for (const key of Reflect.ownKeys(input)) {
				if (key === "__proto__") continue;
				if (!Object.prototype.propertyIsEnumerable.call(input, key)) continue;
				let keyResult = def.keyType._zod.run({
					value: key,
					issues: []
				}, ctx);
				if (keyResult instanceof Promise) throw new Error("Async schemas not supported in object keys currently");
				if (typeof key === "string" && number$1.test(key) && keyResult.issues.length) {
					const retryResult = def.keyType._zod.run({
						value: Number(key),
						issues: []
					}, ctx);
					if (retryResult instanceof Promise) throw new Error("Async schemas not supported in object keys currently");
					if (retryResult.issues.length === 0) keyResult = retryResult;
				}
				if (keyResult.issues.length) {
					if (def.mode === "loose") payload.value[key] = input[key];
					else if (values) {
						unrecognized = unrecognized ?? [];
						unrecognized.push(key);
					} else payload.issues.push({
						code: "invalid_key",
						origin: "record",
						issues: keyResult.issues.map((iss) => finalizeIssue(iss, ctx, config())),
						input: key,
						path: [key],
						inst
					});
					continue;
				}
				const outKey = keyResult.value;
				if (outKey === "__proto__") continue;
				const result = def.valueType._zod.run({
					value: input[key],
					issues: []
				}, ctx);
				if (result instanceof Promise) proms.push(result.then((result) => {
					if (result.issues.length) payload.issues.push(...prefixIssues(key, result.issues));
					payload.value[outKey] = result.value;
				}));
				else {
					if (result.issues.length) payload.issues.push(...prefixIssues(key, result.issues));
					payload.value[outKey] = result.value;
				}
			}
			if (unrecognized && unrecognized.length > 0) payload.issues.push({
				code: "unrecognized_keys",
				input,
				inst,
				keys: unrecognized,
				continue: true
			});
		}
		if (proms.length) return Promise.all(proms).then(() => payload);
		return payload;
	};
});
const $ZodEnum = /*@__PURE__*/ $constructor("$ZodEnum", (inst, def) => {
	$ZodType.init(inst, def);
	const values = getEnumValues(def.entries);
	const valuesSet = new Set(values);
	inst._zod.values = valuesSet;
	const patternValues = values.filter((k) => propertyKeyTypes.has(typeof k));
	inst._zod.pattern = new RegExp(patternValues.length ? `^(${patternValues.map((o) => escapeRegex(o.toString())).join("|")})$` : "^[^\\s\\S]$");
	inst._zod.parse = (payload, _ctx) => {
		const input = payload.value;
		if (valuesSet.has(input)) return payload;
		payload.issues.push({
			code: "invalid_value",
			values,
			input,
			inst
		});
		return payload;
	};
});
const $ZodLiteral = /*@__PURE__*/ $constructor("$ZodLiteral", (inst, def) => {
	$ZodType.init(inst, def);
	const values = new Set(def.values);
	inst._zod.values = values;
	inst._zod.pattern = new RegExp(def.values.length ? `^(${def.values.map((o) => typeof o === "string" ? escapeRegex(o) : o ? escapeRegex(o.toString()) : String(o)).join("|")})$` : "^[^\\s\\S]$");
	inst._zod.parse = (payload, _ctx) => {
		const input = payload.value;
		if (values.has(input)) return payload;
		payload.issues.push({
			code: "invalid_value",
			values: def.values,
			input,
			inst
		});
		return payload;
	};
});
const $ZodTransform = /*@__PURE__*/ $constructor("$ZodTransform", (inst, def) => {
	$ZodType.init(inst, def);
	inst._zod.optin = "optional";
	globalConfig.memoizer?.guard(inst);
	inst._zod.parse = (payload, ctx) => {
		if (ctx.direction === "backward") throw new $ZodEncodeError(inst.constructor.name);
		const _out = def.transform(payload.value, payload);
		if (ctx.async) return (_out instanceof Promise ? _out : Promise.resolve(_out)).then((output) => {
			payload.value = output;
			return payload;
		});
		if (_out instanceof Promise) throw new $ZodAsyncError();
		payload.value = _out;
		return payload;
	};
});
function handleOptionalResult(payload, result) {
	payload.value = result.issues.length ? void 0 : result.value;
	return payload;
}
const $ZodOptional = /*@__PURE__*/ $constructor("$ZodOptional", (inst, def) => {
	$ZodType.init(inst, def);
	defineLazyInternal(inst, "optin", (zod) => zod.def.innerType._zod.optin === "defaulted" ? "defaulted" : "optional");
	inst._zod.optout = "optional";
	defineLazyInternal(inst, "values", (zod) => {
		const values = zod.def.innerType._zod.values;
		return values ? /* @__PURE__ */ new Set([...values, void 0]) : void 0;
	});
	defineLazyInternal(inst, "pattern", (zod) => {
		const pattern = zod.def.innerType._zod.pattern;
		return pattern ? new RegExp(`^(${cleanRegex(pattern.source)})?$`) : void 0;
	});
	inst._zod.parse = (payload, ctx) => {
		if (payload.value === void 0) {
			if (def.innerType._zod.optin !== "defaulted") return payload;
			const result = def.innerType._zod.run({
				value: payload.value,
				issues: []
			}, ctx);
			if (result instanceof Promise) return result.then((result) => handleOptionalResult(payload, result));
			return handleOptionalResult(payload, result);
		}
		return def.innerType._zod.run(payload, ctx);
	};
});
const $ZodExactOptional = /*@__PURE__*/ $constructor("$ZodExactOptional", (inst, def) => {
	$ZodOptional.init(inst, def);
	defineLazyInternal(inst, "values", (zod) => zod.def.innerType._zod.values);
	defineLazyInternal(inst, "pattern", (zod) => zod.def.innerType._zod.pattern);
	inst._zod.parse = (payload, ctx) => {
		return def.innerType._zod.run(payload, ctx);
	};
});
const $ZodNullable = /*@__PURE__*/ $constructor("$ZodNullable", (inst, def) => {
	$ZodType.init(inst, def);
	defineLazyInternal(inst, "optin", (zod) => zod.def.innerType._zod.optin);
	defineLazyInternal(inst, "optout", (zod) => zod.def.innerType._zod.optout);
	defineLazyInternal(inst, "pattern", (zod) => {
		const pattern = zod.def.innerType._zod.pattern;
		return pattern ? new RegExp(`^(${cleanRegex(pattern.source)}|null)$`) : void 0;
	});
	defineLazyInternal(inst, "values", (zod) => {
		return zod.def.innerType._zod.values ? /* @__PURE__ */ new Set([...zod.def.innerType._zod.values, null]) : void 0;
	});
	inst._zod.parse = (payload, ctx) => {
		if (payload.value === null) return payload;
		return def.innerType._zod.run(payload, ctx);
	};
});
const $ZodDefault = /*@__PURE__*/ $constructor("$ZodDefault", (inst, def) => {
	$ZodType.init(inst, def);
	inst._zod.optin = "defaulted";
	defineLazyInternal(inst, "values", (zod) => zod.def.innerType._zod.values);
	inst._zod.parse = (payload, ctx) => {
		if (ctx.direction === "backward") return def.innerType._zod.run(payload, ctx);
		if (payload.value === void 0) {
			payload.value = def.defaultValue;
			/**
			* $ZodDefault returns the default value immediately in forward direction.
			* It doesn't pass the default value into the validator ("prefault"). There's no reason to pass the default value through validation. The validity of the default is enforced by TypeScript statically. Otherwise, it's the responsibility of the user to ensure the default is valid. In the case of pipes with divergent in/out types, you can specify the default on the `in` schema of your ZodPipe to set a "prefault" for the pipe.   */
			return payload;
		}
		const result = def.innerType._zod.run(payload, ctx);
		if (result instanceof Promise) return result.then((result) => handleDefaultResult(result, def));
		return handleDefaultResult(result, def);
	};
});
function handleDefaultResult(payload, def) {
	if (payload.value === void 0) payload.value = def.defaultValue;
	return payload;
}
const $ZodPrefault = /*@__PURE__*/ $constructor("$ZodPrefault", (inst, def) => {
	$ZodType.init(inst, def);
	inst._zod.optin = "defaulted";
	defineLazyInternal(inst, "values", (zod) => zod.def.innerType._zod.values);
	inst._zod.parse = (payload, ctx) => {
		if (ctx.direction === "backward") return def.innerType._zod.run(payload, ctx);
		if (payload.value === void 0) payload.value = def.defaultValue;
		return def.innerType._zod.run(payload, ctx);
	};
});
const $ZodNonOptional = /*@__PURE__*/ $constructor("$ZodNonOptional", (inst, def) => {
	$ZodType.init(inst, def);
	defineLazyInternal(inst, "values", (zod) => {
		const v = zod.def.innerType._zod.values;
		return v ? new Set([...v].filter((x) => x !== void 0)) : void 0;
	});
	inst._zod.parse = (payload, ctx) => {
		const result = def.innerType._zod.run(payload, ctx);
		if (result instanceof Promise) return result.then((result) => handleNonOptionalResult(result, inst));
		return handleNonOptionalResult(result, inst);
	};
});
function handleNonOptionalResult(payload, inst) {
	if (!payload.issues.length && payload.value === void 0) payload.issues.push({
		code: "invalid_type",
		expected: "nonoptional",
		input: payload.value,
		inst
	});
	return payload;
}
function handleCatchResult(payload, result, def, ctx) {
	if (!result.issues.length) {
		payload.value = result.value;
		if (result.memo) payload.memo = true;
		return payload;
	}
	payload.value = def.catchValue({
		...result,
		value: payload.value,
		error: { issues: result.issues.map((iss) => finalizeIssue(iss, ctx, config())) },
		input: payload.value
	});
	return payload;
}
const $ZodCatch = /*@__PURE__*/ $constructor("$ZodCatch", (inst, def) => {
	$ZodType.init(inst, def);
	defineLazyInternal(inst, "optin", (zod) => zod.def.innerType._zod.optin === "defaulted" ? "defaulted" : "optional");
	defineLazyInternal(inst, "optout", (zod) => zod.def.innerType._zod.optout);
	defineLazyInternal(inst, "values", (zod) => zod.def.innerType._zod.values);
	inst._zod.parse = (payload, ctx) => {
		if (ctx.direction === "backward") return def.innerType._zod.run(payload, ctx);
		const result = def.innerType._zod.run({
			value: payload.value,
			issues: []
		}, ctx);
		if (result instanceof Promise) return result.then((result) => handleCatchResult(payload, result, def, ctx));
		return handleCatchResult(payload, result, def, ctx);
	};
});
const $ZodPipe = /*@__PURE__*/ $constructor("$ZodPipe", (inst, def) => {
	$ZodType.init(inst, def);
	defineLazyInternal(inst, "values", (zod) => zod.def.in._zod.values);
	defineLazyInternal(inst, "optin", (zod) => zod.def.in._zod.optin);
	defineLazyInternal(inst, "optout", (zod) => zod.def.out._zod.optout);
	defineLazyInternal(inst, "propValues", (zod) => zod.def.in._zod.propValues);
	inst._zod.parse = (payload, ctx) => {
		if (ctx.direction === "backward") {
			const right = def.out._zod.run(payload, ctx);
			if (right instanceof Promise) return right.then((right) => handlePipeResult(right, def.in, ctx));
			return handlePipeResult(right, def.in, ctx);
		}
		const left = def.in._zod.run(payload, ctx);
		if (left instanceof Promise) return left.then((left) => handlePipeResult(left, def.out, ctx));
		return handlePipeResult(left, def.out, ctx);
	};
});
function handlePipeResult(left, next, ctx) {
	if (left.issues.some((iss) => iss.code !== "unrecognized_keys")) {
		left.aborted = true;
		return left;
	}
	return next._zod.run({
		value: left.value,
		issues: left.issues
	}, ctx);
}
const $ZodReadonly = /*@__PURE__*/ $constructor("$ZodReadonly", (inst, def) => {
	$ZodType.init(inst, def);
	defineLazyInternal(inst, "propValues", (zod) => zod.def.innerType._zod.propValues);
	defineLazyInternal(inst, "values", (zod) => zod.def.innerType._zod.values);
	defineLazyInternal(inst, "optin", (zod) => zod.def.innerType?._zod?.optin);
	defineLazyInternal(inst, "optout", (zod) => zod.def.innerType?._zod?.optout);
	inst._zod.parse = (payload, ctx) => {
		if (ctx.direction === "backward") return def.innerType._zod.run(payload, ctx);
		const result = def.innerType._zod.run(payload, ctx);
		if (result instanceof Promise) return result.then(handleReadonlyResult);
		return handleReadonlyResult(result);
	};
});
function handleReadonlyResult(payload) {
	if (!payload.memo) payload.value = Object.freeze(payload.value);
	return payload;
}
const $ZodLazy = /*@__PURE__*/ $constructor("$ZodLazy", (inst, def) => {
	$ZodType.init(inst, def);
	defineLazy(inst._zod, "innerType", () => {
		const d = def;
		if (!d._cachedInner) d._cachedInner = def.getter();
		return d._cachedInner;
	});
	defineLazyInternal(inst, "pattern", (zod) => zod.innerType?._zod?.pattern);
	defineLazyInternal(inst, "propValues", (zod) => zod.innerType?._zod?.propValues);
	defineLazyInternal(inst, "optin", (zod) => zod.innerType?._zod?.optin ?? void 0);
	defineLazyInternal(inst, "optout", (zod) => zod.innerType?._zod?.optout ?? void 0);
	inst._zod.parse = (payload, ctx) => {
		return inst._zod.innerType._zod.run(payload, ctx);
	};
});
const $ZodCustom = /*@__PURE__*/ $constructor("$ZodCustom", (inst, def) => {
	$ZodCheck.init(inst, def);
	$ZodType.init(inst, def);
	inst._zod.parse = (payload, _) => {
		return payload;
	};
	inst._zod.check = (payload) => {
		const input = payload.value;
		const r = def.fn(input);
		if (r instanceof Promise) return r.then((r) => handleRefineResult(r, payload, input, inst));
		handleRefineResult(r, payload, input, inst);
	};
});
function handleRefineResult(result, payload, input, inst) {
	if (!result) {
		const _iss = {
			code: "custom",
			input,
			inst,
			path: [...inst._zod.def.path ?? []],
			continue: !inst._zod.def.abort
		};
		if (inst._zod.def.params) _iss.params = inst._zod.def.params;
		payload.issues.push(issue(_iss));
	}
}
//#endregion
//#region node_modules/zod/v4/core/memoizer.js
var $ZodCyclicError = class extends Error {
	constructor() {
		super(`Cannot parse a reference cycle that closes through a transform`);
		this.name = "ZodCyclicError";
	}
};
/** Keyed off the context object every schema in one parse call already shares. */
const STATE = "~memo";
const NO_ISSUES = [];
function cloneIssues(issues) {
	return issues.map((iss) => iss.path ? {
		...iss,
		path: iss.path.slice()
	} : { ...iss });
}
const recursive = /*@__PURE__*/ new WeakMap();
/** Whether this schema's subtree contains a cycle, so one parse can re-enter it. */
function isRecursive(inst, stack) {
	const cached = recursive.get(inst);
	if (cached !== void 0) return cached;
	if (stack.has(inst)) return true;
	stack.add(inst);
	let result = false;
	const check = (child) => {
		if (!result && child?._zod && isRecursive(child, stack)) result = true;
	};
	const def = inst._zod.def;
	switch (def.type) {
		case "object":
			for (const key of Reflect.ownKeys(def.shape)) check(def.shape[key]);
			check(def.catchall);
			break;
		case "array":
			check(def.element);
			break;
		case "tuple":
			for (const el of def.items) check(el);
			check(def.rest);
			break;
		case "record":
		case "map":
			check(def.keyType);
			check(def.valueType);
			break;
		case "set":
			check(def.valueType);
			break;
		case "union":
			for (const el of def.options) check(el);
			break;
		case "intersection":
			check(def.left);
			check(def.right);
			break;
		case "optional":
		case "nullable":
		case "default":
		case "prefault":
		case "catch":
		case "readonly":
		case "nonoptional":
		case "promise":
		case "success":
			check(def.innerType);
			break;
		case "pipe":
			check(def.in);
			check(def.out);
			break;
		case "function":
			check(def.input);
			check(def.output);
			break;
		case "lazy":
			check(inst._zod.innerType);
			break;
		case "template_literal":
		case "string":
		case "number":
		case "int":
		case "boolean":
		case "bigint":
		case "symbol":
		case "undefined":
		case "null":
		case "void":
		case "never":
		case "any":
		case "unknown":
		case "date":
		case "nan":
		case "enum":
		case "literal":
		case "file":
		case "transform":
		case "custom": break;
		default: for (const key in def) {
			const desc = Object.getOwnPropertyDescriptor(def, key);
			if (!desc || desc.get) continue;
			const value = desc.value;
			if (!value || typeof value !== "object") continue;
			if (value._zod) check(value);
			else if (Array.isArray(value)) for (const el of value) check(el);
		}
	}
	stack.delete(inst);
	recursive.set(inst, result);
	return result;
}
function bucketFor(state, inst) {
	let bucket = state.buckets.get(inst);
	if (!bucket) {
		bucket = /* @__PURE__ */ new Map();
		state.buckets.set(inst, bucket);
	}
	return bucket;
}
let handoff;
const open = [];
const memo = {
	alloc(_inst, payload, empty) {
		const bucket = handoff;
		if (!bucket) return empty;
		handoff = void 0;
		const entry = {
			value: empty,
			issues: null
		};
		bucket.set(payload.value, entry);
		open.push(entry);
		return empty;
	},
	guard(inst) {
		var _a;
		(_a = inst._zod).deferred ?? (_a.deferred = []);
		inst._zod.deferred.push(() => {
			const base = inst._zod.parse;
			const wrapped = (payload, ctx) => {
				if (ctx.direction !== "backward" && isBackEdge(ctx, payload.value)) throw new $ZodCyclicError();
				return base(payload, ctx);
			};
			inst._zod.parse = wrapped;
			if (inst._zod.run === base) inst._zod.run = wrapped;
		});
	},
	attach(inst) {
		var _a;
		let isRecursiveInst;
		let lastCtx;
		let lastBucket;
		(_a = inst._zod).deferred ?? (_a.deferred = []);
		inst._zod.deferred.push(() => {
			const base = inst._zod.parse;
			const wrapped = (payload, ctx) => {
				if (isRecursiveInst === void 0) {
					isRecursiveInst = isRecursive(inst, /* @__PURE__ */ new Set());
					if (!isRecursiveInst) {
						inst._zod.parse = base;
						if (inst._zod.run === wrapped) inst._zod.run = base;
						return base(payload, ctx);
					}
				}
				const input = payload.value;
				if (input === null || typeof input !== "object") return base(payload, ctx);
				let state = ctx[STATE];
				if (!state) {
					state = {
						buckets: /* @__PURE__ */ new Map(),
						backEdges: void 0
					};
					ctx[STATE] = state;
				}
				let bucket;
				if (lastCtx === ctx) bucket = lastBucket;
				else {
					bucket = bucketFor(state, inst);
					lastCtx = ctx;
					lastBucket = bucket;
				}
				const hit = bucket.get(input);
				if (hit) {
					payload.value = hit.value;
					if (hit.issues) {
						if (hit.issues.length) payload.issues.push(...cloneIssues(hit.issues));
					} else {
						payload.memo = true;
						state.backEdges ?? (state.backEdges = /* @__PURE__ */ new Set());
						state.backEdges.add(hit.value);
					}
					return payload;
				}
				handoff = bucket;
				const depth = open.length;
				const result = base(payload, ctx);
				handoff = void 0;
				const entry = open.length > depth ? open.pop() : void 0;
				if (result instanceof Promise) return result.then((r) => {
					if (entry) entry.issues = r.issues.length ? cloneIssues(r.issues) : NO_ISSUES;
					return r;
				});
				if (entry) entry.issues = result.issues.length ? cloneIssues(result.issues) : NO_ISSUES;
				return result;
			};
			inst._zod.parse = wrapped;
			if (inst._zod.run === base) inst._zod.run = wrapped;
		});
	}
};
/** The memoizer that gives containers cycle support. `zod` installs it by default; `zod/mini` opts in with `config({ memoizer: memoizer() })`. */
function memoizer() {
	return memo;
}
/** Whether this value is a node a back-edge resolved to before it finished. */
function isBackEdge(ctx, value) {
	const backEdges = ctx[STATE]?.backEdges;
	return backEdges !== void 0 && value !== null && typeof value === "object" && backEdges.has(value);
}
//#endregion
//#region node_modules/zod/v4/locales/en.js
const error = () => {
	const Sizable = {
		string: {
			unit: "characters",
			verb: "to have"
		},
		file: {
			unit: "bytes",
			verb: "to have"
		},
		array: {
			unit: "items",
			verb: "to have"
		},
		set: {
			unit: "items",
			verb: "to have"
		},
		map: {
			unit: "entries",
			verb: "to have"
		}
	};
	function getSizing(origin) {
		return Sizable[origin] ?? null;
	}
	const FormatDictionary = {
		regex: "input",
		email: "email address",
		url: "URL",
		emoji: "emoji",
		uuid: "UUID",
		uuidv4: "UUIDv4",
		uuidv6: "UUIDv6",
		nanoid: "nanoid",
		guid: "GUID",
		cuid: "cuid",
		cuid2: "cuid2",
		ulid: "ULID",
		xid: "XID",
		ksuid: "KSUID",
		datetime: "ISO datetime",
		date: "ISO date",
		time: "ISO time",
		duration: "ISO duration",
		ipv4: "IPv4 address",
		ipv6: "IPv6 address",
		mac: "MAC address",
		cidrv4: "IPv4 range",
		cidrv6: "IPv6 range",
		base64: "base64-encoded string",
		base64url: "base64url-encoded string",
		json_string: "JSON string",
		e164: "E.164 number",
		credit_card: "credit card number",
		jwt: "JWT",
		template_literal: "input"
	};
	const TypeDictionary = { nan: "NaN" };
	function getTypeName(type, input) {
		if (type === "number" && typeof input === "number" && !Number.isFinite(input)) return String(input);
		return TypeDictionary[type] ?? type;
	}
	return (issue) => {
		switch (issue.code) {
			case "invalid_type": return `Invalid input: expected ${getTypeName(issue.expected)}, received ${getTypeName(parsedType(issue.input), issue.input)}`;
			case "invalid_value":
				if (issue.values.length === 1) return `Invalid input: expected ${stringifyPrimitive(issue.values[0])}`;
				return `Invalid option: expected one of ${joinValues(issue.values, "|")}`;
			case "too_big": {
				const adj = issue.exact ? "exactly " : issue.inclusive ? "<=" : "<";
				const sizing = getSizing(issue.origin);
				if (sizing) return `Too big: expected ${issue.origin ?? "value"} to have ${adj}${issue.maximum.toString()} ${sizing.unit ?? "elements"}`;
				return `Too big: expected ${issue.origin ?? "value"} to be ${adj}${issue.maximum.toString()}`;
			}
			case "too_small": {
				const adj = issue.exact ? "exactly " : issue.inclusive ? ">=" : ">";
				const sizing = getSizing(issue.origin);
				if (sizing) return `Too small: expected ${issue.origin} to have ${adj}${issue.minimum.toString()} ${sizing.unit}`;
				return `Too small: expected ${issue.origin} to be ${adj}${issue.minimum.toString()}`;
			}
			case "invalid_format": {
				const _issue = issue;
				if (_issue.format === "starts_with") return `Invalid string: must start with "${_issue.prefix}"`;
				if (_issue.format === "ends_with") return `Invalid string: must end with "${_issue.suffix}"`;
				if (_issue.format === "includes") return `Invalid string: must include "${_issue.includes}"`;
				if (_issue.format === "regex") return `Invalid string: must match pattern ${_issue.pattern}`;
				return `Invalid ${FormatDictionary[_issue.format] ?? issue.format}`;
			}
			case "not_multiple_of": return `Invalid number: must be a multiple of ${issue.divisor}`;
			case "unrecognized_keys": return `Unrecognized key${issue.keys.length > 1 ? "s" : ""}: ${joinValues(issue.keys, ", ")}`;
			case "invalid_key": return `Invalid key in ${issue.origin}`;
			case "invalid_union":
				if (issue.options && Array.isArray(issue.options) && issue.options.length > 0) return `Invalid discriminator value. Expected ${issue.options.map((o) => `'${o}'`).join(" | ")}`;
				if (issue.inclusive === false) return "Invalid input: more than one option matched";
				return "Invalid input";
			case "invalid_element": return `Invalid value in ${issue.origin}`;
			default: return `Invalid input`;
		}
	};
};
function en_default() {
	return { localeError: error() };
}
//#endregion
//#region node_modules/zod/v4/core/registries.js
var _a;
var $ZodRegistry = class {
	constructor() {
		this._map = /* @__PURE__ */ new WeakMap();
		this._idmap = /* @__PURE__ */ new Map();
	}
	add(schema, ..._meta) {
		const meta = _meta[0];
		this._map.set(schema, meta);
		if (meta && typeof meta === "object" && "id" in meta) this._idmap.set(meta.id, schema);
		return this;
	}
	clear() {
		this._map = /* @__PURE__ */ new WeakMap();
		this._idmap = /* @__PURE__ */ new Map();
		return this;
	}
	remove(schema) {
		const meta = this._map.get(schema);
		if (meta && typeof meta === "object" && "id" in meta) this._idmap.delete(meta.id);
		this._map.delete(schema);
		return this;
	}
	get(schema) {
		const p = schema._zod.parent;
		if (p) {
			const pm = { ...this.get(p) ?? {} };
			delete pm.id;
			const f = {
				...pm,
				...this._map.get(schema)
			};
			return Object.keys(f).length ? f : void 0;
		}
		return this._map.get(schema);
	}
	has(schema) {
		return this._map.has(schema);
	}
};
function registry() {
	return new $ZodRegistry();
}
(_a = globalThis).__zod_globalRegistry ?? (_a.__zod_globalRegistry = registry());
const globalRegistry = globalThis.__zod_globalRegistry;
//#endregion
//#region node_modules/zod/v4/core/api.js
// @__NO_SIDE_EFFECTS__
function _string(Class, params) {
	return new Class({
		type: "string",
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _email(Class, params) {
	return new Class({
		type: "string",
		format: "email",
		check: "string_format",
		abort: false,
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _guid(Class, params) {
	return new Class({
		type: "string",
		format: "guid",
		check: "string_format",
		abort: false,
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _uuid(Class, params) {
	return new Class({
		type: "string",
		format: "uuid",
		check: "string_format",
		abort: false,
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _uuidv4(Class, params) {
	return new Class({
		type: "string",
		format: "uuid",
		check: "string_format",
		abort: false,
		version: "v4",
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _uuidv6(Class, params) {
	return new Class({
		type: "string",
		format: "uuid",
		check: "string_format",
		abort: false,
		version: "v6",
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _uuidv7(Class, params) {
	return new Class({
		type: "string",
		format: "uuid",
		check: "string_format",
		abort: false,
		version: "v7",
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _url(Class, params) {
	return new Class({
		type: "string",
		format: "url",
		check: "string_format",
		abort: false,
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _emoji(Class, params) {
	return new Class({
		type: "string",
		format: "emoji",
		check: "string_format",
		abort: false,
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _nanoid(Class, params) {
	return new Class({
		type: "string",
		format: "nanoid",
		check: "string_format",
		abort: false,
		...normalizeParams(params)
	});
}
/**
* @deprecated CUID v1 is deprecated by its authors due to information leakage
* (timestamps embedded in the id). Use {@link _cuid2} instead.
* See https://github.com/paralleldrive/cuid.
*/
// @__NO_SIDE_EFFECTS__
function _cuid(Class, params) {
	return new Class({
		type: "string",
		format: "cuid",
		check: "string_format",
		abort: false,
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _cuid2(Class, params) {
	return new Class({
		type: "string",
		format: "cuid2",
		check: "string_format",
		abort: false,
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _ulid(Class, params) {
	return new Class({
		type: "string",
		format: "ulid",
		check: "string_format",
		abort: false,
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _xid(Class, params) {
	return new Class({
		type: "string",
		format: "xid",
		check: "string_format",
		abort: false,
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _ksuid(Class, params) {
	return new Class({
		type: "string",
		format: "ksuid",
		check: "string_format",
		abort: false,
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _ipv4(Class, params) {
	return new Class({
		type: "string",
		format: "ipv4",
		check: "string_format",
		abort: false,
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _ipv6(Class, params) {
	return new Class({
		type: "string",
		format: "ipv6",
		check: "string_format",
		abort: false,
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _cidrv4(Class, params) {
	return new Class({
		type: "string",
		format: "cidrv4",
		check: "string_format",
		abort: false,
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _cidrv6(Class, params) {
	return new Class({
		type: "string",
		format: "cidrv6",
		check: "string_format",
		abort: false,
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _base64(Class, params) {
	return new Class({
		type: "string",
		format: "base64",
		check: "string_format",
		abort: false,
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _base64url(Class, params) {
	return new Class({
		type: "string",
		format: "base64url",
		check: "string_format",
		abort: false,
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _e164(Class, params) {
	return new Class({
		type: "string",
		format: "e164",
		check: "string_format",
		abort: false,
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _jwt(Class, params) {
	return new Class({
		type: "string",
		format: "jwt",
		check: "string_format",
		abort: false,
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _isoDateTime(Class, params) {
	return new Class({
		type: "string",
		format: "datetime",
		check: "string_format",
		offset: false,
		local: false,
		precision: null,
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _isoDate(Class, params) {
	return new Class({
		type: "string",
		format: "date",
		check: "string_format",
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _isoTime(Class, params) {
	return new Class({
		type: "string",
		format: "time",
		check: "string_format",
		precision: null,
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _isoDuration(Class, params) {
	return new Class({
		type: "string",
		format: "duration",
		check: "string_format",
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _number(Class, params) {
	return new Class({
		type: "number",
		checks: [],
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _int(Class, params) {
	return new Class({
		type: "number",
		check: "number_format",
		abort: false,
		format: "safeint",
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _boolean(Class, params) {
	return new Class({
		type: "boolean",
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _unknown(Class) {
	return new Class({ type: "unknown" });
}
// @__NO_SIDE_EFFECTS__
function _never(Class, params) {
	return new Class({
		type: "never",
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _lt(value, params) {
	return new $ZodCheckLessThan({
		check: "less_than",
		...normalizeParams(params),
		value,
		inclusive: false
	});
}
// @__NO_SIDE_EFFECTS__
function _lte(value, params) {
	return new $ZodCheckLessThan({
		check: "less_than",
		...normalizeParams(params),
		value,
		inclusive: true
	});
}
// @__NO_SIDE_EFFECTS__
function _gt(value, params) {
	return new $ZodCheckGreaterThan({
		check: "greater_than",
		...normalizeParams(params),
		value,
		inclusive: false
	});
}
// @__NO_SIDE_EFFECTS__
function _gte(value, params) {
	return new $ZodCheckGreaterThan({
		check: "greater_than",
		...normalizeParams(params),
		value,
		inclusive: true
	});
}
// @__NO_SIDE_EFFECTS__
function _multipleOf(value, params) {
	return new $ZodCheckMultipleOf({
		check: "multiple_of",
		...normalizeParams(params),
		value
	});
}
// @__NO_SIDE_EFFECTS__
function _maxLength(maximum, params) {
	return new $ZodCheckMaxLength({
		check: "max_length",
		...normalizeParams(params),
		maximum
	});
}
// @__NO_SIDE_EFFECTS__
function _minLength(minimum, params) {
	return new $ZodCheckMinLength({
		check: "min_length",
		...normalizeParams(params),
		minimum
	});
}
// @__NO_SIDE_EFFECTS__
function _length(length, params) {
	return new $ZodCheckLengthEquals({
		check: "length_equals",
		...normalizeParams(params),
		length
	});
}
// @__NO_SIDE_EFFECTS__
function _regex(pattern, params) {
	return new $ZodCheckRegex({
		check: "string_format",
		format: "regex",
		...normalizeParams(params),
		pattern
	});
}
// @__NO_SIDE_EFFECTS__
function _lowercase(params) {
	return new $ZodCheckLowerCase({
		check: "string_format",
		format: "lowercase",
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _uppercase(params) {
	return new $ZodCheckUpperCase({
		check: "string_format",
		format: "uppercase",
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _includes(includes, params) {
	return new $ZodCheckIncludes({
		check: "string_format",
		format: "includes",
		...normalizeParams(params),
		includes
	});
}
// @__NO_SIDE_EFFECTS__
function _startsWith(prefix, params) {
	return new $ZodCheckStartsWith({
		check: "string_format",
		format: "starts_with",
		...normalizeParams(params),
		prefix
	});
}
// @__NO_SIDE_EFFECTS__
function _endsWith(suffix, params) {
	return new $ZodCheckEndsWith({
		check: "string_format",
		format: "ends_with",
		...normalizeParams(params),
		suffix
	});
}
// @__NO_SIDE_EFFECTS__
function _overwrite(tx) {
	return new $ZodCheckOverwrite({
		check: "overwrite",
		tx
	});
}
// @__NO_SIDE_EFFECTS__
function _normalize(form) {
	return /* @__PURE__ */ _overwrite((input) => input.normalize(form));
}
// @__NO_SIDE_EFFECTS__
function _trim() {
	return /* @__PURE__ */ _overwrite((input) => input.trim());
}
// @__NO_SIDE_EFFECTS__
function _toLowerCase() {
	return /* @__PURE__ */ _overwrite((input) => input.toLowerCase());
}
// @__NO_SIDE_EFFECTS__
function _toUpperCase() {
	return /* @__PURE__ */ _overwrite((input) => input.toUpperCase());
}
// @__NO_SIDE_EFFECTS__
function _slugify() {
	return /* @__PURE__ */ _overwrite((input) => slugify(input));
}
// @__NO_SIDE_EFFECTS__
function _array(Class, element, params) {
	return new Class({
		type: "array",
		element,
		...normalizeParams(params)
	});
}
// @__NO_SIDE_EFFECTS__
function _refine(Class, fn, _params) {
	return new Class({
		type: "custom",
		check: "custom",
		fn,
		...normalizeParams(_params)
	});
}
// @__NO_SIDE_EFFECTS__
function _superRefine(fn, params) {
	const ch = /* @__PURE__ */ _check((payload) => {
		payload.addIssue = (issue$2) => {
			if (typeof issue$2 === "string") payload.issues.push(issue(issue$2, payload.value, ch._zod.def));
			else {
				const _issue = issue$2;
				if (_issue.fatal) _issue.continue = false;
				_issue.code ?? (_issue.code = "custom");
				if (!("input" in _issue)) _issue.input = payload.value;
				_issue.inst ?? (_issue.inst = ch);
				_issue.continue ?? (_issue.continue = !ch._zod.def.abort);
				payload.issues.push(issue(_issue));
			}
		};
		return fn(payload.value, payload);
	}, params);
	return ch;
}
// @__NO_SIDE_EFFECTS__
function _check(fn, params) {
	const ch = new $ZodCheck({
		check: "custom",
		...normalizeParams(params)
	});
	ch._zod.check = fn;
	return ch;
}
//#endregion
//#region node_modules/zod/v4/core/to-json-schema.js
function assignProps(target, ...sources) {
	for (const source of sources) for (const key of Reflect.ownKeys(source)) if (Object.prototype.propertyIsEnumerable.call(source, key)) assignProp(target, key, source[key]);
	return target;
}
function initializeContext(params) {
	let target = params?.target ?? "draft-2020-12";
	if (target === "draft-4") target = "draft-04";
	if (target === "draft-7") target = "draft-07";
	return {
		processors: params.processors ?? {},
		metadataRegistry: params?.metadata ?? globalRegistry,
		target,
		unrepresentable: params?.unrepresentable ?? "throw",
		override: params?.override ?? (() => {}),
		io: params?.io ?? "output",
		counter: 0,
		seen: /* @__PURE__ */ new Map(),
		sharedDefsExtractedFor: void 0,
		sharedEmitDoneFor: void 0,
		cycles: params?.cycles ?? "ref",
		reused: params?.reused ?? "inline",
		intersections: [],
		deferred: [],
		external: params?.external ?? void 0
	};
}
/**
* Applies the `unrepresentable` setting at a site that has no JSON Schema equivalent. Throws
* `message` unless the setting (or the handler's return value) says otherwise. Returns `true` if a
* custom JSON Schema was written into `json`, in which case the caller must not write its own.
*/
function handleUnrepresentable(schema, ctx, json, params, message) {
	const result = typeof ctx.unrepresentable === "function" ? ctx.unrepresentable({
		zodSchema: schema,
		path: params.path,
		message
	}) : ctx.unrepresentable;
	if (result === "any") return false;
	if (result === void 0 || result === "throw") throw new Error(message);
	Object.assign(json, result);
	return true;
}
function process(schema, ctx, _params = {
	path: [],
	schemaPath: []
}) {
	var _a;
	const def = schema._zod.def;
	const seen = ctx.seen.get(schema);
	if (seen) {
		seen.count++;
		if (_params.schemaPath.includes(schema)) seen.cycle = _params.path;
		return seen.schema;
	}
	const result = {
		schema: {},
		count: 1,
		cycle: void 0,
		path: _params.path
	};
	ctx.seen.set(schema, result);
	ctx.sharedDefsExtractedFor = void 0;
	ctx.sharedEmitDoneFor = void 0;
	const overrideSchema = schema._zod.toJSONSchema?.();
	if (overrideSchema) result.schema = overrideSchema;
	else {
		const params = {
			..._params,
			schemaPath: [..._params.schemaPath, schema],
			path: _params.path
		};
		if (schema._zod.processJSONSchema) schema._zod.processJSONSchema(ctx, result.schema, params);
		else {
			const _json = result.schema;
			const processor = ctx.processors[def.type];
			if (!processor) throw new Error(`[toJSONSchema]: Non-representable type encountered: ${def.type}`);
			processor(schema, ctx, _json, params);
		}
		const parent = schema._zod.parent;
		if (parent) {
			if (!result.ref) result.ref = parent;
			process(parent, ctx, params);
			ctx.seen.get(parent).isParent = true;
		}
	}
	const meta = ctx.metadataRegistry.get(schema);
	if (meta) assignProps(result.schema, meta);
	if (ctx.io === "input" && isTransforming(schema)) {
		delete result.schema.examples;
		delete result.schema.default;
	}
	if (ctx.io === "input" && "_prefault" in result.schema) (_a = result.schema).default ?? (_a.default = result.schema._prefault);
	delete result.schema._prefault;
	return ctx.seen.get(schema).schema;
}
function encodeJSONPointerSegment(segment) {
	return segment.replace(/~/g, "~0").replace(/\//g, "~1");
}
function extractDefs(ctx, schema) {
	const root = ctx.seen.get(schema);
	if (!root) throw new Error("Unprocessed schema. This is a bug in Zod.");
	if (ctx.external && ctx.sharedDefsExtractedFor === ctx.external) return;
	const idToSchema = /* @__PURE__ */ new Map();
	for (const entry of ctx.seen.entries()) {
		const id = ctx.metadataRegistry.get(entry[0])?.id;
		if (id) {
			const existing = idToSchema.get(id);
			if (existing && existing !== entry[0]) throw new Error(`Duplicate schema id "${id}" detected during JSON Schema conversion. Two different schemas cannot share the same id when converted together.`);
			idToSchema.set(id, entry[0]);
		}
	}
	const makeURI = (entry) => {
		const defsSegment = ctx.target === "draft-2020-12" ? "$defs" : "definitions";
		if (ctx.external) {
			const externalId = ctx.external.registry.get(entry[0])?.id;
			const uriGenerator = ctx.external.uri ?? ((id) => id);
			if (externalId) return { ref: uriGenerator(externalId) };
			const id = entry[1].defId ?? entry[1].schema.id ?? `schema${ctx.counter++}`;
			entry[1].defId = id;
			return {
				defId: id,
				ref: `${uriGenerator("__shared")}#/${defsSegment}/${encodeJSONPointerSegment(id)}`
			};
		}
		const uriPrefix = `#`;
		const defUriPrefix = `${uriPrefix}/${defsSegment}/`;
		if (entry[1] === root && !entry[1].schema.id) return { ref: uriPrefix };
		const defId = entry[1].schema.id ?? `__schema${ctx.counter++}`;
		return {
			defId,
			ref: defUriPrefix + encodeJSONPointerSegment(defId)
		};
	};
	const extractToDef = (entry) => {
		if (entry[1].schema.$ref) return;
		const seen = entry[1];
		const { ref, defId } = makeURI(entry);
		seen.def = { ...seen.schema };
		if (defId) seen.defId = defId;
		const schema = seen.schema;
		for (const key in schema) delete schema[key];
		schema.$ref = ref;
	};
	if (ctx.cycles === "throw") for (const entry of ctx.seen.entries()) {
		const seen = entry[1];
		if (seen.cycle) throw new Error(`Cycle detected: #/${seen.cycle?.join("/")}/<root>

Set the \`cycles\` parameter to \`"ref"\` to resolve cyclical schemas with defs.`);
	}
	for (const entry of ctx.seen.entries()) {
		const seen = entry[1];
		if (schema === entry[0]) {
			extractToDef(entry);
			continue;
		}
		if (ctx.external) {
			const ext = ctx.external.registry.get(entry[0])?.id;
			if (schema !== entry[0] && ext) {
				extractToDef(entry);
				continue;
			}
		}
		if (ctx.metadataRegistry.get(entry[0])?.id) {
			extractToDef(entry);
			continue;
		}
		if (seen.cycle) {
			extractToDef(entry);
			continue;
		}
		if (seen.count > 1) {
			if (ctx.reused === "ref") {
				extractToDef(entry);
				continue;
			}
		}
	}
	if (ctx.external) ctx.sharedDefsExtractedFor = ctx.external;
}
/** Rewrites `anyOf: [{type: "a"}, {type: "b"}]` to `type: ["a", "b"]`, which every JSON Schema draft treats as equivalent and most consumers render far better for the nullable case. Only branches that are a bare type assertion qualify — anything carrying a constraint, `$ref`, `const` or metadata is left alone. Runs after `flattenRef`, so a branch an override decorated or `$defs` extraction turned into a `$ref` is no longer bare and correctly stays in `anyOf`. `oneOf` is excluded: `integer` and `number` overlap, so "exactly one" and "at least one" are not the same there. OpenAPI 3.0 is excluded: its `type` must be a single string. */
function compactTypeUnion(schema) {
	const options = schema.anyOf;
	if (!Array.isArray(options) || options.length === 0 || schema.type !== void 0) return;
	const types = [];
	for (const option of options) {
		if (!option || typeof option !== "object") return;
		compactTypeUnion(option);
		const keys = Object.keys(option);
		if (keys.length !== 1 || keys[0] !== "type") return;
		const type = option.type;
		for (const member of Array.isArray(type) ? type : [type]) {
			if (typeof member !== "string") return;
			if (!types.includes(member)) types.push(member);
		}
	}
	delete schema.anyOf;
	schema.type = types.length === 1 ? types[0] : types;
}
/** Keywords `foldIntersection` knows how to combine. Anything else — `$ref`, `patternProperties`,
* an annotation like `description` — makes a member unfoldable, so a constraint this does not
* understand leaves the `allOf` alone instead of being silently dropped or misattributed. */
const FOLDABLE_KEYS = /* @__PURE__ */ new Set([
	"type",
	"properties",
	"required",
	"additionalProperties"
]);
const UNION_KEYS = ["oneOf", "anyOf"];
/** A member's constraint on a key it does not declare itself. A `catchall` states one; `false`, an absent `additionalProperties`, and the empty schema a loose object emits state nothing. */
function undeclaredConstraint(member) {
	const extra = member.additionalProperties;
	if (extra === void 0 || extra === false || typeof extra !== "object" || extra === null) return null;
	return Object.keys(extra).length ? extra : null;
}
/** Combines object members into the single object they describe together, or returns `null` if any of them carries a keyword outside {@link FOLDABLE_KEYS}. */
function foldObjects(members) {
	const objects = [];
	for (const member of members) {
		if (typeof member !== "object" || member.type !== "object") return null;
		for (const key in member) if (!FOLDABLE_KEYS.has(key)) return null;
		objects.push(member);
	}
	const properties = {};
	const required = /* @__PURE__ */ new Set();
	for (const object of objects) {
		for (const key in object.properties) {
			if (Object.prototype.hasOwnProperty.call(properties, key)) continue;
			const parts = [];
			for (const other of objects) {
				const part = other.properties?.[key] ?? undeclaredConstraint(other);
				if (part === null || part === void 0) continue;
				if (!parts.some((seen) => JSON.stringify(seen) === JSON.stringify(part))) parts.push(part);
			}
			assignProp(properties, key, parts.length === 1 ? parts[0] : foldObjects(parts) ?? { allOf: parts });
		}
		for (const key of object.required ?? []) required.add(key);
	}
	const folded = {
		type: "object",
		properties
	};
	if (required.size) folded.required = [...required];
	if (objects.every((object) => object.additionalProperties === false)) folded.additionalProperties = false;
	else {
		const constraints = [];
		for (const object of objects) {
			const constraint = undeclaredConstraint(object);
			if (constraint && !constraints.some((seen) => JSON.stringify(seen) === JSON.stringify(constraint))) constraints.push(constraint);
		}
		if (constraints.length === 1) folded.additionalProperties = constraints[0];
		else if (constraints.length > 1) folded.additionalProperties = { allOf: constraints };
	}
	return folded;
}
/** `additionalProperties` in an `allOf` member sees only that member's own `properties`, so two
* closed object members reject each other's keys and the schema validates nothing. Zod's parser
* pools the key sets instead — `handleIntersectionResults` reports a key as unrecognized only when
* *every* side rejects it — so the emitted schema has to pool them too, and folding the members
* into one object is the encoding that says so on every target.
*
* This runs from `finalize`, after `extractDefs`, which is what keeps it clear of the `$ref`
* machinery: a member extracted into `$defs` is already a `$ref` by now and declines to fold, so it
* keeps its reference and its own closedness rather than being inlined as a stale copy. */
function foldIntersection(json) {
	const allOf = json.allOf;
	if (!Array.isArray(allOf) || allOf.length < 2) return;
	for (const key of FOLDABLE_KEYS) if (key in json) return;
	const unions = allOf.filter((m) => UNION_KEYS.some((k) => Array.isArray(m[k])));
	let folded = null;
	if (!unions.length) folded = foldObjects(allOf);
	else {
		const union = unions[0];
		const keyword = UNION_KEYS.find((k) => Array.isArray(union[k]));
		if (Object.keys(union).length !== 1) return;
		const rest = allOf.filter((m) => m !== union);
		const branches = union[keyword].map((branch) => foldObjects([...rest, branch]));
		if (branches.some((b) => !b)) return;
		folded = { [keyword]: branches };
	}
	if (!folded) return;
	delete json.allOf;
	assignProps(json, folded);
}
function finalize(ctx, schema) {
	const root = ctx.seen.get(schema);
	if (!root) throw new Error("Unprocessed schema. This is a bug in Zod.");
	const flattenRef = (zodSchema) => {
		const seen = ctx.seen.get(zodSchema);
		if (seen.ref === null) return;
		const schema = seen.def ?? seen.schema;
		const _cached = { ...schema };
		const ref = seen.ref;
		seen.ref = null;
		if (ref) {
			flattenRef(ref);
			const refSeen = ctx.seen.get(ref);
			const refSchema = refSeen.schema;
			if (refSchema.$ref && (ctx.target === "draft-07" || ctx.target === "draft-04" || ctx.target === "openapi-3.0")) {
				schema.allOf = schema.allOf ?? [];
				schema.allOf.push(refSchema);
			} else assignProps(schema, refSchema);
			assignProps(schema, _cached);
			if (zodSchema._zod.parent === ref) for (const key in schema) {
				if (key === "$ref" || key === "allOf") continue;
				if (!(key in _cached)) delete schema[key];
			}
			if (refSchema.$ref && refSeen.def) for (const key in schema) {
				if (key === "$ref" || key === "allOf") continue;
				if (key in refSeen.def && JSON.stringify(schema[key]) === JSON.stringify(refSeen.def[key])) delete schema[key];
			}
		}
		const parent = zodSchema._zod.parent;
		if (parent && parent !== ref) {
			flattenRef(parent);
			const parentSeen = ctx.seen.get(parent);
			if (parentSeen?.schema.$ref) {
				schema.$ref = parentSeen.schema.$ref;
				if (parentSeen.def) for (const key in schema) {
					if (key === "$ref" || key === "allOf") continue;
					if (key in parentSeen.def && JSON.stringify(schema[key]) === JSON.stringify(parentSeen.def[key])) delete schema[key];
				}
			}
		}
		ctx.override({
			zodSchema,
			jsonSchema: schema,
			path: seen.path ?? []
		});
	};
	if (!ctx.external || ctx.sharedEmitDoneFor !== ctx.external) {
		for (const entry of [...ctx.seen.entries()].reverse()) flattenRef(entry[0]);
		if (ctx.target !== "openapi-3.0") for (const entry of ctx.seen.entries()) compactTypeUnion(entry[1].def ?? entry[1].schema);
		for (const rewrite of ctx.deferred) rewrite();
		if (ctx.intersections.length) {
			const carriers = /* @__PURE__ */ new Map();
			for (const seen of ctx.seen.values()) for (const json of [seen.schema, seen.def]) {
				const allOf = json?.allOf;
				if (!Array.isArray(allOf)) continue;
				const existing = carriers.get(allOf);
				if (existing) existing.push(json);
				else carriers.set(allOf, [json]);
			}
			for (const allOf of ctx.intersections) for (const json of carriers.get(allOf) ?? []) foldIntersection(json);
		}
	}
	const result = {};
	if (ctx.target === "draft-2020-12") result.$schema = "https://json-schema.org/draft/2020-12/schema";
	else if (ctx.target === "draft-07") result.$schema = "http://json-schema.org/draft-07/schema#";
	else if (ctx.target === "draft-04") result.$schema = "http://json-schema.org/draft-04/schema#";
	else if (ctx.target === "openapi-3.0") {}
	if (ctx.external?.uri) {
		const id = ctx.external.registry.get(schema)?.id;
		if (!id) throw new Error("Schema is missing an `id` property");
		result.$id = ctx.external.uri(id);
	}
	assignProps(result, root.defId ? root.schema : root.def ?? root.schema);
	const rootMetaId = ctx.metadataRegistry.get(schema)?.id;
	if (rootMetaId !== void 0 && result.id === rootMetaId) delete result.id;
	const defs = ctx.external?.defs ?? {};
	if (!ctx.external || ctx.sharedEmitDoneFor !== ctx.external) for (const entry of ctx.seen.entries()) {
		const seen = entry[1];
		if (seen.def && seen.defId) {
			if (seen.def.id === seen.defId) delete seen.def.id;
			assignProp(defs, seen.defId, seen.def);
		}
	}
	if (ctx.external) ctx.sharedEmitDoneFor = ctx.external;
	if (ctx.external) {} else if (Object.keys(defs).length > 0) {
		if (ctx.target === "draft-2020-12") result.$defs = defs;
		else result.definitions = defs;
	}
	try {
		const finalized = JSON.parse(JSON.stringify(result));
		Object.defineProperty(finalized, "~standard", {
			value: {
				...schema["~standard"],
				jsonSchema: {
					input: createStandardJSONSchemaMethod(schema, "input", ctx.processors),
					output: createStandardJSONSchemaMethod(schema, "output", ctx.processors)
				}
			},
			enumerable: false,
			writable: false
		});
		return finalized;
	} catch (_err) {
		throw new Error("Error converting schema to JSON.");
	}
}
function isTransforming(_schema, _ctx) {
	const ctx = _ctx ?? { seen: /* @__PURE__ */ new Set() };
	if (ctx.seen.has(_schema)) return false;
	ctx.seen.add(_schema);
	const def = _schema._zod.def;
	if (def.type === "transform") return true;
	if (def.type === "array") return isTransforming(def.element, ctx);
	if (def.type === "set") return isTransforming(def.valueType, ctx);
	if (def.type === "lazy") return isTransforming(def.getter(), ctx);
	if (def.type === "promise" || def.type === "optional" || def.type === "nonoptional" || def.type === "nullable" || def.type === "readonly" || def.type === "default" || def.type === "prefault" || def.type === "catch") return isTransforming(def.innerType, ctx);
	if (def.type === "intersection") return isTransforming(def.left, ctx) || isTransforming(def.right, ctx);
	if (def.type === "record" || def.type === "map") return isTransforming(def.keyType, ctx) || isTransforming(def.valueType, ctx);
	if (def.type === "pipe") {
		if (_schema._zod.traits.has("$ZodCodec")) return true;
		return isTransforming(def.in, ctx) || isTransforming(def.out, ctx);
	}
	if (def.type === "object") {
		for (const key in def.shape) if (isTransforming(def.shape[key], ctx)) return true;
		return false;
	}
	if (def.type === "union") {
		for (const option of def.options) if (isTransforming(option, ctx)) return true;
		return false;
	}
	if (def.type === "tuple") {
		for (const item of def.items) if (isTransforming(item, ctx)) return true;
		if (def.rest && isTransforming(def.rest, ctx)) return true;
		return false;
	}
	return false;
}
/**
* Creates a toJSONSchema method for a schema instance.
* This encapsulates the logic of initializing context, processing, extracting defs, and finalizing.
*/
const createToJSONSchemaMethod = (schema, processors = {}) => (params) => {
	const ctx = initializeContext({
		...params,
		processors
	});
	process(schema, ctx);
	extractDefs(ctx, schema);
	return finalize(ctx, schema);
};
const createStandardJSONSchemaMethod = (schema, io, processors = {}) => (params) => {
	const { libraryOptions, target } = params ?? {};
	const ctx = initializeContext({
		...libraryOptions ?? {},
		target,
		io,
		processors
	});
	process(schema, ctx);
	extractDefs(ctx, schema);
	return finalize(ctx, schema);
};
//#endregion
//#region node_modules/zod/v4/core/json-schema-processors.js
const formatMap = {
	guid: "uuid",
	url: "uri",
	datetime: "date-time",
	json_string: "json-string",
	regex: ""
};
const stringProcessor = (schema, ctx, _json, _params) => {
	const json = _json;
	json.type = "string";
	const { minimum, maximum, format, patterns, contentEncoding, laxFormat } = schema._zod.bag;
	if (typeof minimum === "number") json.minLength = minimum;
	if (typeof maximum === "number") json.maxLength = maximum;
	if (format) {
		json.format = formatMap[format] ?? format;
		if (json.format === "") delete json.format;
		if (format === "time" || laxFormat) delete json.format;
	}
	if (contentEncoding) json.contentEncoding = contentEncoding;
	if (patterns && patterns.size > 0) {
		const patternList = [...patterns];
		if (patternList.length === 1) json.pattern = patternList[0].source;
		else if (patternList.length > 1) json.allOf = [...patternList.map((regex) => ({
			...ctx.target === "draft-07" || ctx.target === "draft-04" || ctx.target === "openapi-3.0" ? { type: "string" } : {},
			pattern: regex.source
		}))];
	}
};
const numberProcessor = (schema, ctx, _json, params) => {
	const json = _json;
	const { minimum, maximum, format, multipleOf, exclusiveMaximum, exclusiveMinimum } = schema._zod.bag;
	if (typeof format === "string" && format.includes("int")) json.type = "integer";
	else json.type = "number";
	const exMin = typeof exclusiveMinimum === "number" && exclusiveMinimum >= (minimum ?? Number.NEGATIVE_INFINITY);
	const exMax = typeof exclusiveMaximum === "number" && exclusiveMaximum <= (maximum ?? Number.POSITIVE_INFINITY);
	const legacy = ctx.target === "draft-04" || ctx.target === "openapi-3.0";
	if (exMin) {
		if (legacy) {
			json.minimum = exclusiveMinimum;
			json.exclusiveMinimum = true;
		} else json.exclusiveMinimum = exclusiveMinimum;
	} else if (typeof minimum === "number") json.minimum = minimum;
	if (exMax) {
		if (legacy) {
			json.maximum = exclusiveMaximum;
			json.exclusiveMaximum = true;
		} else json.exclusiveMaximum = exclusiveMaximum;
	} else if (typeof maximum === "number") json.maximum = maximum;
	if (typeof multipleOf === "number") {
		if (Number.isFinite(multipleOf) && multipleOf !== 0) json.multipleOf = Math.abs(multipleOf);
		else handleUnrepresentable(schema, ctx, json, params, `A multipleOf divisor of ${multipleOf} cannot be represented in JSON Schema`);
	}
};
const booleanProcessor = (_schema, _ctx, json, _params) => {
	json.type = "boolean";
};
const neverProcessor = (_schema, _ctx, json, _params) => {
	json.not = {};
};
const enumProcessor = (schema, _ctx, json, _params) => {
	const def = schema._zod.def;
	const values = getEnumValues(def.entries);
	if (values.length === 0) {
		json.not = {};
		return;
	}
	if (values.every((v) => typeof v === "number")) json.type = "number";
	if (values.every((v) => typeof v === "string")) json.type = "string";
	json.enum = values;
};
const literalProcessor = (schema, ctx, json, params) => {
	const def = schema._zod.def;
	if (def.values.length === 0) {
		json.not = {};
		return;
	}
	const vals = [];
	for (const val of def.values) if (val === void 0) {
		if (handleUnrepresentable(schema, ctx, json, params, "Literal `undefined` cannot be represented in JSON Schema")) return;
	} else if (typeof val === "bigint") {
		if (handleUnrepresentable(schema, ctx, json, params, "BigInt literals cannot be represented in JSON Schema")) return;
		vals.push(Number(val));
	} else vals.push(val);
	if (vals.length === 0) {} else if (vals.length === 1) {
		const val = vals[0];
		json.type = val === null ? "null" : typeof val;
		if (ctx.target === "draft-04" || ctx.target === "openapi-3.0") json.enum = [val];
		else json.const = val;
	} else {
		if (vals.every((v) => typeof v === "number")) json.type = "number";
		if (vals.every((v) => typeof v === "string")) json.type = "string";
		if (vals.every((v) => typeof v === "boolean")) json.type = "boolean";
		if (vals.every((v) => v === null)) json.type = "null";
		json.enum = vals;
	}
};
const customProcessor = (schema, ctx, json, params) => {
	handleUnrepresentable(schema, ctx, json, params, "Custom types cannot be represented in JSON Schema");
};
const transformProcessor = (schema, ctx, json, params) => {
	handleUnrepresentable(schema, ctx, json, params, "Transforms cannot be represented in JSON Schema");
};
const arrayProcessor = (schema, ctx, _json, params) => {
	const json = _json;
	const def = schema._zod.def;
	const { minimum, maximum } = schema._zod.bag;
	if (typeof minimum === "number") json.minItems = minimum;
	if (typeof maximum === "number") json.maxItems = maximum;
	json.type = "array";
	json.items = process(def.element, ctx, {
		...params,
		path: [...params.path, "items"]
	});
};
function inputOptin(schema) {
	const def = schema._zod.def;
	if (def.type === "pipe" && def.in._zod.traits.has("$ZodTransform")) return inputOptin(def.out);
	if (def.type === "catch") return inputOptin(def.innerType);
	return schema._zod.optin;
}
const objectProcessor = (schema, ctx, _json, params) => {
	const json = _json;
	const def = schema._zod.def;
	const shape = def.shape;
	if (Object.getOwnPropertySymbols(shape).length && handleUnrepresentable(schema, ctx, json, params, "Symbol keys cannot be represented in JSON Schema")) return;
	json.type = "object";
	json.properties = {};
	for (const key in shape) assignProp(json.properties, key, process(shape[key], ctx, {
		...params,
		path: [
			...params.path,
			"properties",
			key
		]
	}));
	const allKeys = new Set(Object.keys(shape));
	const requiredKeys = new Set([...allKeys].filter((key) => {
		const field = def.shape[key];
		if (ctx.io === "input") return inputOptin(field) === void 0;
		else return field._zod.optout === void 0;
	}));
	if (requiredKeys.size > 0) json.required = Array.from(requiredKeys);
	if (def.catchall?._zod.def.type === "never") json.additionalProperties = false;
	else if (!def.catchall) {
		if (ctx.io === "output") json.additionalProperties = false;
	} else if (def.catchall) json.additionalProperties = process(def.catchall, ctx, {
		...params,
		path: [...params.path, "additionalProperties"]
	});
};
const unionProcessor = (schema, ctx, json, params) => {
	const def = schema._zod.def;
	const isExclusive = def.inclusive === false;
	const options = def.options.map((x, i) => process(x, ctx, {
		...params,
		path: [
			...params.path,
			isExclusive ? "oneOf" : "anyOf",
			i
		]
	}));
	if (isExclusive) json.oneOf = options;
	else json.anyOf = options;
};
const intersectionProcessor = (schema, ctx, json, params) => {
	const def = schema._zod.def;
	const a = process(def.left, ctx, {
		...params,
		path: [
			...params.path,
			"allOf",
			0
		]
	});
	const b = process(def.right, ctx, {
		...params,
		path: [
			...params.path,
			"allOf",
			1
		]
	});
	const isSimpleIntersection = (val) => "allOf" in val && Object.keys(val).length === 1;
	const allOf = [...isSimpleIntersection(a) ? a.allOf : [a], ...isSimpleIntersection(b) ? b.allOf : [b]];
	json.allOf = allOf;
	ctx.intersections.push(allOf);
};
/** JSON object keys are always strings, so a numeric record key schema is re-expressed over the
* numeric-string form the record parser matches. Deferred to `finalize`, after the flatten: a key
* behind a wrapper only carries its own `type` before then, and a union key only has its branches.
*
* A numeric bound cannot apply to a property name, so `minimum` and its siblings are dropped rather
* than carried over: keeping them beside `type: "string"` reproduces the match-nothing schema this
* exists to fix. A key that carries one therefore emits wider than the record parses — `z.record(z.number().min(5), V)`
* accepts `"3"` — which is the deliberate trade, since throwing on it would reject an ordinary schema
* outright. */
function stringifyKeyNames(bySchema, json, visited) {
	if (json.$ref) {
		if (visited.has(json)) return json;
		visited.add(json);
		const def = bySchema.get(json)?.def;
		if (!def) return json;
		const inlined = stringifyKeyNames(bySchema, def, visited);
		return inlined === def ? json : inlined;
	}
	for (const keyword of ["anyOf", "oneOf"]) {
		const branches = json[keyword];
		if (!Array.isArray(branches)) continue;
		const mapped = branches.map((branch) => stringifyKeyNames(bySchema, branch, visited));
		if (mapped.some((branch, i) => branch !== branches[i])) json = {
			...json,
			[keyword]: mapped
		};
	}
	const types = Array.isArray(json.type) ? json.type : [json.type];
	const numericType = !types.includes("string") && types.some((t) => t === "number" || t === "integer");
	const values = json.enum ?? (json.const !== void 0 ? [json.const] : void 0);
	if (!numericType && !values?.some((v) => typeof v === "number")) return json;
	const { minimum, maximum, exclusiveMinimum, exclusiveMaximum, multipleOf, format, id, ...rest } = json;
	if (rest.enum) rest.enum = rest.enum.map((v) => typeof v === "number" ? String(v) : v);
	else if (typeof rest.const === "number") rest.const = String(rest.const);
	if (!numericType) return rest;
	rest.type = "string";
	if (!values) rest.pattern = (types.includes("number") ? number$1 : integer).source;
	return rest;
}
/** Every record of one conversion, so the carriers are found in a single pass rather than once per record. */
const pendingRecords = /* @__PURE__ */ new WeakMap();
function rewriteKeyNames(ctx) {
	const bySchema = /* @__PURE__ */ new Map();
	for (const entry of ctx.seen.values()) if (entry.def && !bySchema.has(entry.schema)) bySchema.set(entry.schema, entry);
	const rewrites = /* @__PURE__ */ new Map();
	for (const record of pendingRecords.get(ctx) ?? []) {
		const seen = ctx.seen.get(record);
		const names = (seen?.def ?? seen?.schema)?.propertyNames;
		if (!names || names === true || rewrites.has(names)) continue;
		const rewritten = stringifyKeyNames(bySchema, names, /* @__PURE__ */ new Set());
		if (rewritten !== names) rewrites.set(names, rewritten);
	}
	if (!rewrites.size) return;
	for (const entry of ctx.seen.values()) for (const carrier of [entry.schema, entry.def]) {
		const rewritten = carrier && rewrites.get(carrier.propertyNames);
		if (rewritten) carrier.propertyNames = rewritten;
	}
}
const recordProcessor = (schema, ctx, _json, params) => {
	const json = _json;
	const def = schema._zod.def;
	json.type = "object";
	const keyType = def.keyType;
	const patterns = keyType._zod.bag?.patterns;
	if (def.mode === "loose" && patterns && patterns.size > 0) {
		const valueSchema = process(def.valueType, ctx, {
			...params,
			path: [
				...params.path,
				"patternProperties",
				"*"
			]
		});
		json.patternProperties = {};
		for (const pattern of patterns) assignProp(json.patternProperties, pattern.source, valueSchema);
	} else {
		if (ctx.target === "draft-07" || ctx.target === "draft-2020-12") {
			json.propertyNames = process(def.keyType, ctx, {
				...params,
				path: [...params.path, "propertyNames"]
			});
			let pending = pendingRecords.get(ctx);
			if (!pending) {
				pending = [];
				pendingRecords.set(ctx, pending);
				ctx.deferred.push(() => rewriteKeyNames(ctx));
			}
			pending.push(schema);
		}
		json.additionalProperties = process(def.valueType, ctx, {
			...params,
			path: [...params.path, "additionalProperties"]
		});
	}
	const keyValues = keyType._zod.values;
	const omittableOnInput = ctx.io === "input" && inputOptin(def.valueType) !== void 0;
	if (keyValues && !def.partial && !omittableOnInput) {
		const validKeyValues = [...keyValues].filter((v) => typeof v === "string" || typeof v === "number");
		if (validKeyValues.length > 0) json.required = validKeyValues.map(String);
	}
};
const nullableProcessor = (schema, ctx, json, params) => {
	const def = schema._zod.def;
	const inner = process(def.innerType, ctx, params);
	const seen = ctx.seen.get(schema);
	if (ctx.target === "openapi-3.0") {
		seen.ref = def.innerType;
		json.nullable = true;
	} else json.anyOf = [inner, { type: "null" }];
};
const nonoptionalProcessor = (schema, ctx, _json, params) => {
	const def = schema._zod.def;
	process(def.innerType, ctx, params);
	const seen = ctx.seen.get(schema);
	seen.ref = def.innerType;
};
/** Round-trips a default value through JSON so the emitted schema is guaranteed to be valid JSON.
* A BigInt has no reliable encoding, so it goes through `unrepresentable` like any other
* unrepresentable value. Returns a sentinel when the caller must not write a default of its own. */
const UNREPRESENTABLE_DEFAULT = Symbol();
function serializeDefaultValue(value, schema, ctx, json, params) {
	let unrepresentable = false;
	const serialized = JSON.stringify(value, (_, val) => {
		if (typeof val !== "bigint") return val;
		unrepresentable = true;
		return null;
	});
	if (!unrepresentable) return JSON.parse(serialized);
	handleUnrepresentable(schema, ctx, json, params, "BigInt defaults cannot be represented in JSON Schema");
	return UNREPRESENTABLE_DEFAULT;
}
const defaultProcessor = (schema, ctx, json, params) => {
	const def = schema._zod.def;
	process(def.innerType, ctx, params);
	const seen = ctx.seen.get(schema);
	seen.ref = def.innerType;
	const value = serializeDefaultValue(def.defaultValue, schema, ctx, json, params);
	if (value !== UNREPRESENTABLE_DEFAULT) json.default = value;
};
const prefaultProcessor = (schema, ctx, json, params) => {
	const def = schema._zod.def;
	process(def.innerType, ctx, params);
	const seen = ctx.seen.get(schema);
	seen.ref = def.innerType;
	if (ctx.io !== "input") return;
	const value = serializeDefaultValue(def.defaultValue, schema, ctx, json, params);
	if (value !== UNREPRESENTABLE_DEFAULT) json._prefault = value;
};
const catchProcessor = (schema, ctx, json, params) => {
	const def = schema._zod.def;
	process(def.innerType, ctx, params);
	const seen = ctx.seen.get(schema);
	seen.ref = def.innerType;
	let catchValue;
	try {
		catchValue = def.catchValue(void 0);
	} catch {
		handleUnrepresentable(schema, ctx, json, params, "Dynamic catch values are not supported in JSON Schema");
		return;
	}
	json.default = catchValue;
};
const pipeProcessor = (schema, ctx, _json, params) => {
	const def = schema._zod.def;
	const inIsTransform = def.in._zod.traits.has("$ZodTransform");
	const innerType = ctx.io === "input" ? inIsTransform ? def.out : def.in : def.out;
	process(innerType, ctx, params);
	const seen = ctx.seen.get(schema);
	seen.ref = innerType;
};
const readonlyProcessor = (schema, ctx, json, params) => {
	const def = schema._zod.def;
	process(def.innerType, ctx, params);
	const seen = ctx.seen.get(schema);
	seen.ref = def.innerType;
	json.readOnly = true;
};
const optionalProcessor = (schema, ctx, _json, params) => {
	const def = schema._zod.def;
	process(def.innerType, ctx, params);
	const seen = ctx.seen.get(schema);
	seen.ref = def.innerType;
};
const lazyProcessor = (schema, ctx, _json, params) => {
	const innerType = schema._zod.innerType;
	process(innerType, ctx, params);
	const seen = ctx.seen.get(schema);
	seen.ref = innerType;
};
//#endregion
//#region node_modules/zod/v4/classic/errors.js
const _installedErrorProtos = /* @__PURE__ */ new WeakSet([Object.prototype, Error.prototype]);
function _lazyMethod(proto, key, make) {
	Object.defineProperty(proto, key, {
		configurable: true,
		enumerable: false,
		get() {
			const value = make(this);
			Object.defineProperty(this, key, {
				value,
				configurable: true,
				writable: true
			});
			return value;
		},
		set(value) {
			Object.defineProperty(this, key, {
				value,
				configurable: true,
				writable: true
			});
		}
	});
}
const initializer = (inst, issues) => {
	$ZodError.init(inst, issues);
	inst.name = "ZodError";
	const proto = Object.getPrototypeOf(inst);
	if (_installedErrorProtos.has(proto)) return;
	_installedErrorProtos.add(proto);
	_lazyMethod(proto, "format", (self) => (mapper) => formatError(self, mapper));
	_lazyMethod(proto, "flatten", (self) => (mapper) => flattenError(self, mapper));
	_lazyMethod(proto, "addIssue", (self) => (issue) => {
		self.issues.push(issue);
		self.message = JSON.stringify(self.issues, jsonStringifyReplacer, 2);
	});
	_lazyMethod(proto, "addIssues", (self) => (issues) => {
		self.issues.push(...issues);
		self.message = JSON.stringify(self.issues, jsonStringifyReplacer, 2);
	});
	Object.defineProperty(proto, "isEmpty", {
		configurable: true,
		enumerable: false,
		get() {
			return this.issues.length === 0;
		}
	});
};
const ZodRealError = /*@__PURE__*/ $constructor("ZodError", initializer, void 0, { Parent: Error });
//#endregion
//#region node_modules/zod/v4/classic/parse.js
const parse = /* @__PURE__ */ _parse(ZodRealError);
const parseAsync = /* @__PURE__ */ _parseAsync(ZodRealError);
const safeParse = /* @__PURE__ */ _safeParse(ZodRealError);
const safeParseAsync = /* @__PURE__ */ _safeParseAsync(ZodRealError);
const encode = /* @__PURE__ */ _encode(ZodRealError);
const decode = /* @__PURE__ */ _decode(ZodRealError);
const encodeAsync = /* @__PURE__ */ _encodeAsync(ZodRealError);
const decodeAsync = /* @__PURE__ */ _decodeAsync(ZodRealError);
const safeEncode = /* @__PURE__ */ _safeEncode(ZodRealError);
const safeDecode = /* @__PURE__ */ _safeDecode(ZodRealError);
const safeEncodeAsync = /* @__PURE__ */ _safeEncodeAsync(ZodRealError);
const safeDecodeAsync = /* @__PURE__ */ _safeDecodeAsync(ZodRealError);
//#endregion
//#region node_modules/zod/v4/classic/schemas.js
function _ensureDefaultLocale() {
	if (!globalConfig.localeError) config(en_default());
}
function _ensureDefaultMemoizer() {
	if (!globalConfig.memoizer) config({ memoizer: memoizer() });
}
const ZodType = /*@__PURE__*/ $constructor("ZodType", (inst, def) => {
	_ensureDefaultLocale();
	$ZodType.init(inst, def);
	inst.def = def;
	inst.type = def.type;
	return inst;
}, {
	check(...chks) {
		const def = this.def;
		return this.clone(mergeDefs(def, { checks: [...def.checks ?? [], ...chks.map((ch) => typeof ch === "function" ? { _zod: {
			check: ch,
			def: { check: "custom" },
			onattach: []
		} } : ch)] }), { parent: true });
	},
	with(...chks) {
		return this.check(...chks);
	},
	clone(def, params) {
		return clone(this, def, params);
	},
	brand() {
		return this;
	},
	register(reg, meta) {
		reg.add(this, meta);
		return this;
	},
	refine(check, params) {
		return this.check(refine(check, params));
	},
	superRefine(refinement, params) {
		return this.check(superRefine(refinement, params));
	},
	overwrite(fn) {
		return this.check(/* @__PURE__ */ _overwrite(fn));
	},
	optional() {
		return optional(this);
	},
	exactOptional() {
		return exactOptional(this);
	},
	nullable() {
		return nullable(this);
	},
	nullish() {
		return optional(nullable(this));
	},
	nonoptional(params) {
		return nonoptional(this, params);
	},
	array() {
		return array(this);
	},
	or(arg) {
		return union([this, arg]);
	},
	and(arg) {
		return intersection(this, arg);
	},
	transform(tx) {
		return pipe(this, transform(tx));
	},
	default(d) {
		return _default(this, d);
	},
	prefault(d) {
		return prefault(this, d);
	},
	catch(params) {
		return _catch(this, params);
	},
	pipe(target) {
		return pipe(this, target);
	},
	readonly() {
		return readonly(this);
	},
	describe(description) {
		const cl = this.clone();
		globalRegistry.add(cl, { description });
		return cl;
	},
	meta(...args) {
		if (args.length === 0) return globalRegistry.get(this);
		const cl = this.clone();
		globalRegistry.add(cl, args[0]);
		return cl;
	},
	isOptional() {
		return this.safeParse(void 0).success;
	},
	isNullable() {
		return this.safeParse(null).success;
	},
	apply(fn, ...args) {
		return args.length === 0 ? fn(this) : fn(this, ...args);
	},
	get "~standard"() {
		return hide(this, "~standard", {
			...standardProps(this),
			jsonSchema: {
				input: createStandardJSONSchemaMethod(this, "input"),
				output: createStandardJSONSchemaMethod(this, "output")
			}
		});
	},
	set "~standard"(value) {
		own(this, "~standard", value);
	},
	parse: function _parse(data, params) {
		return parse(this, data, params, { callee: _parse });
	},
	parseAsync: async function _parseAsync(data, params) {
		return await parseAsync(this, data, params, { callee: _parseAsync });
	},
	safeParse(data, params) {
		return safeParse(this, data, params);
	},
	async safeParseAsync(data, params) {
		return safeParseAsync(this, data, params);
	},
	get spa() {
		return this?.safeParseAsync;
	},
	set spa(value) {
		own(this, "spa", value);
	},
	encode: function _encode(data, params) {
		return encode(this, data, params, { callee: _encode });
	},
	decode: function _decode(data, params) {
		return decode(this, data, params, { callee: _decode });
	},
	encodeAsync: async function _encodeAsync(data, params) {
		return await encodeAsync(this, data, params, { callee: _encodeAsync });
	},
	decodeAsync: async function _decodeAsync(data, params) {
		return await decodeAsync(this, data, params, { callee: _decodeAsync });
	},
	safeEncode(data, params) {
		return safeEncode(this, data, params);
	},
	safeDecode(data, params) {
		return safeDecode(this, data, params);
	},
	async safeEncodeAsync(data, params) {
		return safeEncodeAsync(this, data, params);
	},
	async safeDecodeAsync(data, params) {
		return safeDecodeAsync(this, data, params);
	},
	toJSONSchema(params) {
		return createToJSONSchemaMethod(this, {})(params);
	},
	get description() {
		return globalRegistry.get(this)?.description;
	},
	get _def() {
		return this._zod.def;
	}
});
/** @internal */
const _ZodString = /*@__PURE__*/ $constructor("_ZodString", (inst, def) => {
	$ZodString.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => stringProcessor(inst, ctx, json, params);
	const bag = inst._zod.bag;
	inst.format = bag.format ?? null;
	inst.minLength = bag.minimum ?? null;
	inst.maxLength = bag.maximum ?? null;
}, {
	regex(...args) {
		return this.check(/* @__PURE__ */ _regex(...args));
	},
	includes(...args) {
		return this.check(/* @__PURE__ */ _includes(...args));
	},
	startsWith(...args) {
		return this.check(/* @__PURE__ */ _startsWith(...args));
	},
	endsWith(...args) {
		return this.check(/* @__PURE__ */ _endsWith(...args));
	},
	min(...args) {
		return this.check(/* @__PURE__ */ _minLength(...args));
	},
	max(...args) {
		return this.check(/* @__PURE__ */ _maxLength(...args));
	},
	length(...args) {
		return this.check(/* @__PURE__ */ _length(...args));
	},
	nonempty(...args) {
		return this.check(/* @__PURE__ */ _minLength(1, ...args));
	},
	lowercase(params) {
		return this.check(/* @__PURE__ */ _lowercase(params));
	},
	uppercase(params) {
		return this.check(/* @__PURE__ */ _uppercase(params));
	},
	trim() {
		return this.check(/* @__PURE__ */ _trim());
	},
	normalize(...args) {
		return this.check(/* @__PURE__ */ _normalize(...args));
	},
	toLowerCase() {
		return this.check(/* @__PURE__ */ _toLowerCase());
	},
	toUpperCase() {
		return this.check(/* @__PURE__ */ _toUpperCase());
	},
	slugify() {
		return this.check(/* @__PURE__ */ _slugify());
	}
});
const ZodString = /*@__PURE__*/ $constructor("ZodString", (inst, def) => {
	$ZodString.init(inst, def);
	_ZodString.init(inst, def);
}, {
	email(params) {
		return this.check(/* @__PURE__ */ _email(ZodEmail, params));
	},
	url(params) {
		return this.check(/* @__PURE__ */ _url(ZodURL, params));
	},
	jwt(params) {
		return this.check(/* @__PURE__ */ _jwt(ZodJWT, params));
	},
	emoji(params) {
		return this.check(/* @__PURE__ */ _emoji(ZodEmoji, params));
	},
	guid(params) {
		return this.check(/* @__PURE__ */ _guid(ZodGUID, params));
	},
	uuid(params) {
		return this.check(/* @__PURE__ */ _uuid(ZodUUID, params));
	},
	uuidv4(params) {
		return this.check(/* @__PURE__ */ _uuidv4(ZodUUID, params));
	},
	uuidv6(params) {
		return this.check(/* @__PURE__ */ _uuidv6(ZodUUID, params));
	},
	uuidv7(params) {
		return this.check(/* @__PURE__ */ _uuidv7(ZodUUID, params));
	},
	nanoid(params) {
		return this.check(/* @__PURE__ */ _nanoid(ZodNanoID, params));
	},
	cuid(params) {
		return this.check(/* @__PURE__ */ _cuid(ZodCUID, params));
	},
	cuid2(params) {
		return this.check(/* @__PURE__ */ _cuid2(ZodCUID2, params));
	},
	ulid(params) {
		return this.check(/* @__PURE__ */ _ulid(ZodULID, params));
	},
	base64(params) {
		return this.check(/* @__PURE__ */ _base64(ZodBase64, params));
	},
	base64url(params) {
		return this.check(/* @__PURE__ */ _base64url(ZodBase64URL, params));
	},
	xid(params) {
		return this.check(/* @__PURE__ */ _xid(ZodXID, params));
	},
	ksuid(params) {
		return this.check(/* @__PURE__ */ _ksuid(ZodKSUID, params));
	},
	ipv4(params) {
		return this.check(/* @__PURE__ */ _ipv4(ZodIPv4, params));
	},
	ipv6(params) {
		return this.check(/* @__PURE__ */ _ipv6(ZodIPv6, params));
	},
	cidrv4(params) {
		return this.check(/* @__PURE__ */ _cidrv4(ZodCIDRv4, params));
	},
	cidrv6(params) {
		return this.check(/* @__PURE__ */ _cidrv6(ZodCIDRv6, params));
	},
	e164(params) {
		return this.check(/* @__PURE__ */ _e164(ZodE164, params));
	},
	datetime(params) {
		return this.check(/* @__PURE__ */ _isoDateTime(ZodISODateTime, params));
	},
	date(params) {
		return this.check(/* @__PURE__ */ _isoDate(ZodISODate, params));
	},
	time(params) {
		return this.check(/* @__PURE__ */ _isoTime(ZodISOTime, params));
	},
	duration(params) {
		return this.check(/* @__PURE__ */ _isoDuration(ZodISODuration, params));
	}
});
function string(params) {
	return /* @__PURE__ */ _string(ZodString, params);
}
const ZodStringFormat = /*@__PURE__*/ $constructor("ZodStringFormat", (inst, def) => {
	$ZodStringFormat.init(inst, def);
	_ZodString.init(inst, def);
});
const ZodISODateTime = /*@__PURE__*/ $constructor("ZodISODateTime", (inst, def) => {
	$ZodISODateTime.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodISODate = /*@__PURE__*/ $constructor("ZodISODate", (inst, def) => {
	$ZodISODate.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodISOTime = /*@__PURE__*/ $constructor("ZodISOTime", (inst, def) => {
	$ZodISOTime.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodISODuration = /*@__PURE__*/ $constructor("ZodISODuration", (inst, def) => {
	$ZodISODuration.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodEmail = /*@__PURE__*/ $constructor("ZodEmail", (inst, def) => {
	$ZodEmail.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodGUID = /*@__PURE__*/ $constructor("ZodGUID", (inst, def) => {
	$ZodGUID.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodUUID = /*@__PURE__*/ $constructor("ZodUUID", (inst, def) => {
	$ZodUUID.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodURL = /*@__PURE__*/ $constructor("ZodURL", (inst, def) => {
	$ZodURL.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodEmoji = /*@__PURE__*/ $constructor("ZodEmoji", (inst, def) => {
	$ZodEmoji.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodNanoID = /*@__PURE__*/ $constructor("ZodNanoID", (inst, def) => {
	$ZodNanoID.init(inst, def);
	ZodStringFormat.init(inst, def);
});
/**
* @deprecated CUID v1 is deprecated by its authors due to information leakage
* (timestamps embedded in the id). Use {@link ZodCUID2} instead.
* See https://github.com/paralleldrive/cuid.
*/
const ZodCUID = /*@__PURE__*/ $constructor("ZodCUID", (inst, def) => {
	$ZodCUID.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodCUID2 = /*@__PURE__*/ $constructor("ZodCUID2", (inst, def) => {
	$ZodCUID2.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodULID = /*@__PURE__*/ $constructor("ZodULID", (inst, def) => {
	$ZodULID.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodXID = /*@__PURE__*/ $constructor("ZodXID", (inst, def) => {
	$ZodXID.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodKSUID = /*@__PURE__*/ $constructor("ZodKSUID", (inst, def) => {
	$ZodKSUID.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodIPv4 = /*@__PURE__*/ $constructor("ZodIPv4", (inst, def) => {
	$ZodIPv4.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodIPv6 = /*@__PURE__*/ $constructor("ZodIPv6", (inst, def) => {
	$ZodIPv6.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodCIDRv4 = /*@__PURE__*/ $constructor("ZodCIDRv4", (inst, def) => {
	$ZodCIDRv4.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodCIDRv6 = /*@__PURE__*/ $constructor("ZodCIDRv6", (inst, def) => {
	$ZodCIDRv6.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodBase64 = /*@__PURE__*/ $constructor("ZodBase64", (inst, def) => {
	$ZodBase64.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodBase64URL = /*@__PURE__*/ $constructor("ZodBase64URL", (inst, def) => {
	$ZodBase64URL.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodE164 = /*@__PURE__*/ $constructor("ZodE164", (inst, def) => {
	$ZodE164.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodJWT = /*@__PURE__*/ $constructor("ZodJWT", (inst, def) => {
	$ZodJWT.init(inst, def);
	ZodStringFormat.init(inst, def);
});
const ZodNumber = /*@__PURE__*/ $constructor("ZodNumber", (inst, def) => {
	$ZodNumber.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => numberProcessor(inst, ctx, json, params);
	const bag = inst._zod.bag;
	inst.minValue = Math.max(bag.minimum ?? Number.NEGATIVE_INFINITY, bag.exclusiveMinimum ?? Number.NEGATIVE_INFINITY) ?? null;
	inst.maxValue = Math.min(bag.maximum ?? Number.POSITIVE_INFINITY, bag.exclusiveMaximum ?? Number.POSITIVE_INFINITY) ?? null;
	inst.isInt = (bag.format ?? "").includes("int") || Number.isSafeInteger(bag.multipleOf ?? .5);
	inst.isFinite = true;
	inst.format = bag.format ?? null;
}, {
	gt(value, params) {
		return this.check(/* @__PURE__ */ _gt(value, params));
	},
	gte(value, params) {
		return this.check(/* @__PURE__ */ _gte(value, params));
	},
	min(value, params) {
		return this.check(/* @__PURE__ */ _gte(value, params));
	},
	lt(value, params) {
		return this.check(/* @__PURE__ */ _lt(value, params));
	},
	lte(value, params) {
		return this.check(/* @__PURE__ */ _lte(value, params));
	},
	max(value, params) {
		return this.check(/* @__PURE__ */ _lte(value, params));
	},
	int(params) {
		return this.check(int(params));
	},
	safe(params) {
		return this.check(int(params));
	},
	positive(params) {
		return this.check(/* @__PURE__ */ _gt(0, params));
	},
	nonnegative(params) {
		return this.check(/* @__PURE__ */ _gte(0, params));
	},
	negative(params) {
		return this.check(/* @__PURE__ */ _lt(0, params));
	},
	nonpositive(params) {
		return this.check(/* @__PURE__ */ _lte(0, params));
	},
	multipleOf(value, params) {
		return this.check(/* @__PURE__ */ _multipleOf(value, params));
	},
	step(value, params) {
		return this.check(/* @__PURE__ */ _multipleOf(value, params));
	},
	finite() {
		return this;
	}
});
function number(params) {
	return /* @__PURE__ */ _number(ZodNumber, params);
}
const ZodNumberFormat = /*@__PURE__*/ $constructor("ZodNumberFormat", (inst, def) => {
	$ZodNumberFormat.init(inst, def);
	ZodNumber.init(inst, def);
});
function int(params) {
	return /* @__PURE__ */ _int(ZodNumberFormat, params);
}
const ZodBoolean = /*@__PURE__*/ $constructor("ZodBoolean", (inst, def) => {
	$ZodBoolean.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => booleanProcessor(inst, ctx, json, params);
});
function boolean(params) {
	return /* @__PURE__ */ _boolean(ZodBoolean, params);
}
const ZodUnknown = /*@__PURE__*/ $constructor("ZodUnknown", (inst, def) => {
	$ZodUnknown.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => void 0;
});
function unknown() {
	return /* @__PURE__ */ _unknown(ZodUnknown);
}
const ZodNever = /*@__PURE__*/ $constructor("ZodNever", (inst, def) => {
	$ZodNever.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => neverProcessor(inst, ctx, json, params);
});
function never(params) {
	return /* @__PURE__ */ _never(ZodNever, params);
}
const ZodArray = /*@__PURE__*/ $constructor("ZodArray", (inst, def) => {
	_ensureDefaultMemoizer();
	$ZodArray.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => arrayProcessor(inst, ctx, json, params);
	inst.element = def.element;
}, {
	min(n, params) {
		return this.check(/* @__PURE__ */ _minLength(n, params));
	},
	nonempty(params) {
		return this.check(/* @__PURE__ */ _minLength(1, params));
	},
	max(n, params) {
		return this.check(/* @__PURE__ */ _maxLength(n, params));
	},
	length(n, params) {
		return this.check(/* @__PURE__ */ _length(n, params));
	},
	unwrap() {
		return this.element;
	}
});
function array(element, params) {
	return /* @__PURE__ */ _array(ZodArray, element, params);
}
const ZodObject = /*@__PURE__*/ $constructor("ZodObject", (inst, def) => {
	_ensureDefaultMemoizer();
	$ZodObjectJIT.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => objectProcessor(inst, ctx, json, params);
	installLazyProp(inst, "shape", (self) => self._zod.def.shape, false);
}, {
	keyof() {
		return _enum(Object.keys(this._zod.def.shape));
	},
	catchall(catchall) {
		return this.clone({
			...this._zod.def,
			catchall
		});
	},
	passthrough() {
		return this.clone({
			...this._zod.def,
			catchall: unknown()
		});
	},
	loose() {
		return this.clone({
			...this._zod.def,
			catchall: unknown()
		});
	},
	strict() {
		return this.clone({
			...this._zod.def,
			catchall: never()
		});
	},
	strip() {
		return this.clone({
			...this._zod.def,
			catchall: void 0
		});
	},
	extend(incoming) {
		return extend(this, incoming);
	},
	safeExtend(incoming) {
		return safeExtend(this, incoming);
	},
	merge(other) {
		return merge(this, other);
	},
	pick(mask) {
		return pick(this, mask);
	},
	omit(mask) {
		return omit(this, mask);
	},
	partial(...args) {
		return partial(ZodOptional, this, args[0]);
	},
	exactPartial(...args) {
		return partial(ZodExactOptional, this, args[0], "exactPartial");
	},
	required(...args) {
		return required(ZodNonOptional, this, args[0]);
	}
});
function object(shape, params) {
	const def = {
		type: "object",
		shape: shape ?? {},
		...normalizeParams(params)
	};
	return new ZodObject(def);
}
const ZodUnion = /*@__PURE__*/ $constructor("ZodUnion", (inst, def) => {
	$ZodUnion.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => unionProcessor(inst, ctx, json, params);
	inst.options = def.options;
});
function union(options, params) {
	return new ZodUnion({
		type: "union",
		options,
		...normalizeParams(params)
	});
}
const ZodIntersection = /*@__PURE__*/ $constructor("ZodIntersection", (inst, def) => {
	$ZodIntersection.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => intersectionProcessor(inst, ctx, json, params);
});
function intersection(left, right) {
	return new ZodIntersection({
		type: "intersection",
		left,
		right
	});
}
const ZodRecord = /*@__PURE__*/ $constructor("ZodRecord", (inst, def) => {
	_ensureDefaultMemoizer();
	$ZodRecord.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => recordProcessor(inst, ctx, json, params);
	inst.keyType = def.keyType;
	inst.valueType = def.valueType;
});
function record(keyType, valueType, params) {
	if (!valueType || !valueType._zod) return new ZodRecord({
		type: "record",
		keyType: string(),
		valueType: keyType,
		...normalizeParams(valueType)
	});
	return new ZodRecord({
		type: "record",
		keyType,
		valueType,
		...normalizeParams(params)
	});
}
const ZodEnum = /*@__PURE__*/ $constructor("ZodEnum", (inst, def) => {
	$ZodEnum.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => enumProcessor(inst, ctx, json, params);
	inst.enum = def.entries;
	inst.options = Object.values(def.entries);
	const keys = new Set(Object.keys(def.entries));
	inst.extract = (values, params) => {
		const newEntries = {};
		for (const value of values) if (keys.has(value)) newEntries[value] = def.entries[value];
		else throw new Error(`Key ${value} not found in enum`);
		return new ZodEnum({
			...def,
			checks: [],
			...normalizeParams(params),
			entries: newEntries
		});
	};
	inst.exclude = (values, params) => {
		const newEntries = { ...def.entries };
		for (const value of values) if (keys.has(value)) delete newEntries[value];
		else throw new Error(`Key ${value} not found in enum`);
		return new ZodEnum({
			...def,
			checks: [],
			...normalizeParams(params),
			entries: newEntries
		});
	};
});
function _enum(values, params) {
	const entries = Array.isArray(values) ? Object.fromEntries(values.map((v) => [v, v])) : values;
	return new ZodEnum({
		type: "enum",
		entries,
		...normalizeParams(params)
	});
}
const ZodLiteral = /*@__PURE__*/ $constructor("ZodLiteral", (inst, def) => {
	$ZodLiteral.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => literalProcessor(inst, ctx, json, params);
	inst.values = new Set(def.values);
	Object.defineProperty(inst, "value", { get() {
		if (def.values.length > 1) throw new Error("This schema contains multiple valid literal values. Use `.values` instead.");
		return def.values[0];
	} });
});
function literal(value, params) {
	return new ZodLiteral({
		type: "literal",
		values: Array.isArray(value) ? value : [value],
		...normalizeParams(params)
	});
}
const ZodTransform = /*@__PURE__*/ $constructor("ZodTransform", (inst, def) => {
	_ensureDefaultMemoizer();
	$ZodTransform.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => transformProcessor(inst, ctx, json, params);
	inst._zod.parse = (payload, _ctx) => {
		if (_ctx.direction === "backward") throw new $ZodEncodeError(inst.constructor.name);
		payload.addIssue = (issue$1) => {
			if (typeof issue$1 === "string") payload.issues.push(issue(issue$1, payload.value, def));
			else {
				const _issue = issue$1;
				if (_issue.fatal) _issue.continue = false;
				_issue.code ?? (_issue.code = "custom");
				if (!("input" in _issue)) _issue.input = payload.value;
				_issue.inst ?? (_issue.inst = inst);
				payload.issues.push(issue(_issue));
			}
		};
		const output = def.transform(payload.value, payload);
		if (output instanceof Promise) return output.then((output) => {
			payload.value = output;
			return payload;
		});
		payload.value = output;
		return payload;
	};
});
function transform(fn) {
	return new ZodTransform({
		type: "transform",
		transform: fn
	});
}
const ZodOptional = /*@__PURE__*/ $constructor("ZodOptional", (inst, def) => {
	$ZodOptional.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => optionalProcessor(inst, ctx, json, params);
	inst.unwrap = () => inst._zod.def.innerType;
});
function optional(innerType) {
	return new ZodOptional({
		type: "optional",
		innerType
	});
}
const ZodExactOptional = /*@__PURE__*/ $constructor("ZodExactOptional", (inst, def) => {
	$ZodExactOptional.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => optionalProcessor(inst, ctx, json, params);
	inst.unwrap = () => inst._zod.def.innerType;
});
function exactOptional(innerType) {
	return new ZodExactOptional({
		type: "optional",
		innerType
	});
}
const ZodNullable = /*@__PURE__*/ $constructor("ZodNullable", (inst, def) => {
	$ZodNullable.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => nullableProcessor(inst, ctx, json, params);
	inst.unwrap = () => inst._zod.def.innerType;
});
function nullable(innerType) {
	return new ZodNullable({
		type: "nullable",
		innerType
	});
}
const ZodDefault = /*@__PURE__*/ $constructor("ZodDefault", (inst, def) => {
	$ZodDefault.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => defaultProcessor(inst, ctx, json, params);
	inst.unwrap = () => inst._zod.def.innerType;
	inst.removeDefault = inst.unwrap;
});
function _default(innerType, defaultValue) {
	return new ZodDefault({
		type: "default",
		innerType,
		get defaultValue() {
			return typeof defaultValue === "function" ? defaultValue() : shallowClone(defaultValue);
		}
	});
}
const ZodPrefault = /*@__PURE__*/ $constructor("ZodPrefault", (inst, def) => {
	$ZodPrefault.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => prefaultProcessor(inst, ctx, json, params);
	inst.unwrap = () => inst._zod.def.innerType;
});
function prefault(innerType, defaultValue) {
	return new ZodPrefault({
		type: "prefault",
		innerType,
		get defaultValue() {
			return typeof defaultValue === "function" ? defaultValue() : shallowClone(defaultValue);
		}
	});
}
const ZodNonOptional = /*@__PURE__*/ $constructor("ZodNonOptional", (inst, def) => {
	$ZodNonOptional.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => nonoptionalProcessor(inst, ctx, json, params);
	inst.unwrap = () => inst._zod.def.innerType;
});
function nonoptional(innerType, params) {
	return new ZodNonOptional({
		type: "nonoptional",
		innerType,
		...normalizeParams(params)
	});
}
const ZodCatch = /*@__PURE__*/ $constructor("ZodCatch", (inst, def) => {
	$ZodCatch.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => catchProcessor(inst, ctx, json, params);
	inst.unwrap = () => inst._zod.def.innerType;
	inst.removeCatch = inst.unwrap;
});
function _catch(innerType, catchValue) {
	return new ZodCatch({
		type: "catch",
		innerType,
		catchValue: typeof catchValue === "function" ? catchValue : constantCatch(catchValue)
	});
}
const ZodPipe = /*@__PURE__*/ $constructor("ZodPipe", (inst, def) => {
	$ZodPipe.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => pipeProcessor(inst, ctx, json, params);
	inst.in = def.in;
	inst.out = def.out;
});
function pipe(in_, out) {
	return new ZodPipe({
		type: "pipe",
		in: in_,
		out
	});
}
const ZodReadonly = /*@__PURE__*/ $constructor("ZodReadonly", (inst, def) => {
	$ZodReadonly.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => readonlyProcessor(inst, ctx, json, params);
	inst.unwrap = () => inst._zod.def.innerType;
});
function readonly(innerType) {
	return new ZodReadonly({
		type: "readonly",
		innerType
	});
}
const ZodLazy = /*@__PURE__*/ $constructor("ZodLazy", (inst, def) => {
	$ZodLazy.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => lazyProcessor(inst, ctx, json, params);
	inst.unwrap = () => inst._zod.def.getter();
});
function lazy(getter) {
	return new ZodLazy({
		type: "lazy",
		getter
	});
}
const ZodCustom = /*@__PURE__*/ $constructor("ZodCustom", (inst, def) => {
	$ZodCustom.init(inst, def);
	ZodType.init(inst, def);
	inst._zod.processJSONSchema = (ctx, json, params) => customProcessor(inst, ctx, json, params);
});
function refine(fn, _params = {}) {
	return /* @__PURE__ */ _refine(ZodCustom, fn, _params);
}
function superRefine(fn, params) {
	return /* @__PURE__ */ _superRefine(fn, params);
}
//#endregion
//#region lib/typert.remote-client.js
const JsonValueRemoteCodec$schema = union([
	literal(null),
	string(),
	number(),
	literal(false),
	literal(true),
	array(lazy(() => JsonValueRemoteCodec$schema)),
	record(string(), lazy(() => JsonValueRemoteCodec$schema))
]);
const JsonValueRemoteCodec$schema2 = union([
	literal(null),
	string(),
	number(),
	literal(false),
	literal(true),
	array(lazy(() => JsonValueRemoteCodec$schema2)),
	record(string(), lazy(() => JsonValueRemoteCodec$schema2))
]);
const JsonValueRemoteCodec$schema3 = union([
	literal(null),
	string(),
	number(),
	literal(false),
	literal(true),
	array(lazy(() => JsonValueRemoteCodec$schema3)),
	record(string(), lazy(() => JsonValueRemoteCodec$schema3))
]);
const clawock_dsh_clawockStudio_balance_parameter_0$schema = boolean();
const clawock_dsh_clawockStudio_balance_result$schema = object({
	"providers": array(object({
		"provider": string(),
		"label": string(),
		"result": object({
			"configured": boolean(),
			"snapshot": union([literal(null), object({
				"isAvailable": boolean(),
				"unit": string(),
				"currency": string(),
				"totalBalance": string(),
				"grantedBalance": string(),
				"toppedUpBalance": string(),
				"asOf": string(),
				"note": string(),
				"windows": array(object({
					"label": string(),
					"percent": union([number(), literal(null)]),
					"resetAt": string()
				}))
			})]),
			"status": union([
				literal("fresh"),
				literal("cached"),
				literal("stale"),
				literal("failed"),
				literal("no-key")
			]),
			"low": boolean(),
			"message": union([literal(null), string()]),
			"threshold": number(),
			"refreshMs": number()
		})
	})),
	"refreshMs": number()
});
const clawock_dsh_clawockStudio_get_parameter_0$schema = string();
const clawock_dsh_clawockStudio_get_result$schema = object({
	"runId": string(),
	"request": union([
		literal(null),
		string(),
		number(),
		literal(false),
		literal(true),
		array(lazy(() => JsonValueRemoteCodec$schema2)),
		record(string(), lazy(() => JsonValueRemoteCodec$schema2))
	]),
	"decision": union([
		literal(null),
		string(),
		number(),
		literal(false),
		literal(true),
		array(lazy(() => JsonValueRemoteCodec$schema2)),
		record(string(), lazy(() => JsonValueRemoteCodec$schema2))
	]),
	"manifest": union([
		literal(null),
		string(),
		number(),
		literal(false),
		literal(true),
		array(lazy(() => JsonValueRemoteCodec$schema2)),
		record(string(), lazy(() => JsonValueRemoteCodec$schema2))
	])
});
const clawock_dsh_clawockStudio_ledger_result$schema = object({
	"entries": array(union([
		literal(null),
		string(),
		number(),
		literal(false),
		literal(true),
		array(lazy(() => JsonValueRemoteCodec$schema3)),
		record(string(), lazy(() => JsonValueRemoteCodec$schema3))
	])),
	"path": string()
});
const clawock_dsh_clawockStudio_list_result$schema = object({ "runs": array(object({
	"runId": string(),
	"subject": union([literal(null), string()]),
	"decisionSubject": union([literal(null), string()]),
	"decisionAction": union([literal(null), string()]),
	"asOf": union([literal(null), string()]),
	"task": union([literal(null), string()]),
	"workflow": union([
		literal(null),
		string(),
		number(),
		literal(false),
		literal(true),
		array(lazy(() => JsonValueRemoteCodec$schema)),
		record(string(), lazy(() => JsonValueRemoteCodec$schema))
	]),
	"gates": union([
		literal(null),
		string(),
		number(),
		literal(false),
		literal(true),
		array(lazy(() => JsonValueRemoteCodec$schema)),
		record(string(), lazy(() => JsonValueRemoteCodec$schema))
	]),
	"documentCount": number(),
	"decisionPresent": boolean(),
	"receiptPresent": boolean(),
	"mtimeMs": number()
})) });
const clawock_dsh_clawockStudio_plans_result$schema = object({ "plans": array(object({
	"date": string(),
	"decisions": number(),
	"title": union([literal(null), string()])
})) });
const clawock_dsh_clawockStudio_portfolio_result$schema = object({
	"books": array(object({
		"name": string(),
		"currency": union([literal(null), string()]),
		"truePrincipal": union([literal(null), number()]),
		"holdings": array(object({
			"ticker": string(),
			"shares": number(),
			"cost": union([literal(null), number()]),
			"price": union([literal(null), number()]),
			"pnlPct": union([literal(null), number()]),
			"pnlAbs": union([literal(null), number()])
		}))
	})),
	"trades": array(object({
		"ticker": string(),
		"market": string(),
		"currency": string(),
		"date": union([literal(null), string()]),
		"action": string(),
		"shares": number(),
		"price": union([literal(null), number()]),
		"realizedPnl": union([literal(null), number()]),
		"note": union([literal(null), string()])
	})),
	"lastUpdated": union([literal(null), string()])
});
const clawock_dsh_clawockStudio_traces_result$schema = object({
	"workspaceKey": string(),
	"signature": string(),
	"trades": array(object({
		"holdPnl": union([literal(null), number()]),
		"t1": union([literal(null), object({
			"date": string(),
			"price": number(),
			"delta": number(),
			"verdict": string(),
			"tone": union([
				literal("win"),
				literal("loss"),
				literal("flat")
			])
		})]),
		"decision": union([literal(null), object({
			"planDate": union([literal(null), string()]),
			"action": union([literal(null), string()]),
			"confidence": union([literal(null), number()]),
			"drivenBy": union([literal(null), string()]),
			"rationale": union([literal(null), string()]),
			"bull": union([literal(null), string()]),
			"bear": union([literal(null), string()]),
			"emotion": union([literal(null), string()]),
			"emotionNote": union([literal(null), string()]),
			"execution": union([literal(null), string()]),
			"condition": union([literal(null), string()]),
			"sizeShares": union([literal(null), number()]),
			"sizePct": union([literal(null), number()]),
			"plannedPrice": union([literal(null), number()]),
			"source": union([literal(null), string()]),
			"alignment": union([
				literal("same"),
				literal("opposite"),
				literal("other"),
				literal(null)
			])
		})]),
		"ticker": string(),
		"market": string(),
		"currency": string(),
		"date": union([literal(null), string()]),
		"action": string(),
		"shares": number(),
		"price": union([literal(null), number()]),
		"realizedPnl": union([literal(null), number()]),
		"note": union([literal(null), string()])
	})),
	"rate": union([literal(null), number()]),
	"rateSource": union([literal(null), string()]),
	"lastUpdated": union([literal(null), string()])
});
const TYPERT_REMOTE = {
	package: "clawock-dsh",
	descriptors: [
		{
			id: "clawock-dsh#clawockStudio/balance",
			service: "clawockStudio",
			namespace: "clawockStudio",
			method: "balance",
			invocation: { kind: "direct" },
			parameters: [{
				name: "force",
				wire: "force",
				source: "json",
				codec: {
					mode: "strict",
					typeSymbol: "clawock-dsh#clawockStudio/balance:force",
					schema: clawock_dsh_clawockStudio_balance_parameter_0$schema
				}
			}],
			result: {
				mode: "strict",
				typeSymbol: "clawock-dsh/types#BalancesResult",
				schema: clawock_dsh_clawockStudio_balance_result$schema
			},
			sourceLocation: {
				"file": "packages/clawock-dsh/src/index.ts",
				"line": 121,
				"column": 3
			}
		},
		{
			id: "clawock-dsh#clawockStudio/get",
			service: "clawockStudio",
			namespace: "clawockStudio",
			method: "get",
			invocation: { kind: "direct" },
			parameters: [{
				name: "runId",
				wire: "runId",
				source: "json",
				codec: {
					mode: "strict",
					typeSymbol: "clawock-dsh#clawockStudio/get:runId",
					schema: clawock_dsh_clawockStudio_get_parameter_0$schema
				}
			}],
			result: {
				mode: "strict",
				typeSymbol: "clawock-dsh/types#RunDetailResult",
				schema: clawock_dsh_clawockStudio_get_result$schema
			},
			sourceLocation: {
				"file": "packages/clawock-dsh/src/index.ts",
				"line": 45,
				"column": 3
			}
		},
		{
			id: "clawock-dsh#clawockStudio/ledger",
			service: "clawockStudio",
			namespace: "clawockStudio",
			method: "ledger",
			invocation: { kind: "direct" },
			parameters: [],
			result: {
				mode: "strict",
				typeSymbol: "clawock-dsh/types#LedgerResult",
				schema: clawock_dsh_clawockStudio_ledger_result$schema
			},
			sourceLocation: {
				"file": "packages/clawock-dsh/src/index.ts",
				"line": 51,
				"column": 3
			}
		},
		{
			id: "clawock-dsh#clawockStudio/list",
			service: "clawockStudio",
			namespace: "clawockStudio",
			method: "list",
			invocation: { kind: "direct" },
			parameters: [],
			result: {
				mode: "strict",
				typeSymbol: "clawock-dsh/types#ListRunsResult",
				schema: clawock_dsh_clawockStudio_list_result$schema
			},
			sourceLocation: {
				"file": "packages/clawock-dsh/src/index.ts",
				"line": 35,
				"column": 3
			}
		},
		{
			id: "clawock-dsh#clawockStudio/plans",
			service: "clawockStudio",
			namespace: "clawockStudio",
			method: "plans",
			invocation: { kind: "direct" },
			parameters: [],
			result: {
				mode: "strict",
				typeSymbol: "clawock-dsh/types#PlansResult",
				schema: clawock_dsh_clawockStudio_plans_result$schema
			},
			sourceLocation: {
				"file": "packages/clawock-dsh/src/index.ts",
				"line": 63,
				"column": 3
			}
		},
		{
			id: "clawock-dsh#clawockStudio/portfolio",
			service: "clawockStudio",
			namespace: "clawockStudio",
			method: "portfolio",
			invocation: { kind: "direct" },
			parameters: [],
			result: {
				mode: "strict",
				typeSymbol: "clawock-dsh/types#PortfolioResult",
				schema: clawock_dsh_clawockStudio_portfolio_result$schema
			},
			sourceLocation: {
				"file": "packages/clawock-dsh/src/index.ts",
				"line": 57,
				"column": 3
			}
		},
		{
			id: "clawock-dsh#clawockStudio/traces",
			service: "clawockStudio",
			namespace: "clawockStudio",
			method: "traces",
			invocation: { kind: "direct" },
			parameters: [],
			result: {
				mode: "strict",
				typeSymbol: "clawock-dsh/types#TracesResult",
				schema: clawock_dsh_clawockStudio_traces_result$schema
			},
			sourceLocation: {
				"file": "packages/clawock-dsh/src/index.ts",
				"line": 76,
				"column": 3
			}
		}
	]
};
//#endregion
//#region \0dsh-css:src/styles.module.css.mjs
const css = ".SPgITW_dmt,.SPgITW_pbc{--fs-nano:9.5px;--fs-micro:10px;--fs-caption:10.5px;--fs-xs:11px;--fs-xs-l:11.5px;--fs-sm:12px;--fs-sm-l:12.5px;--fs-md:13px;--fs-md-l:13.5px;--fs-lg:14px;--fs-lg-l:14.5px;--fs-xl:15px;--fs-xl-l:15.5px;--fs-2xl:16px }.SPgITW_dmt{--col:var(--dsh-chat-content-width,748px);--page:var(--dsw-alias-bg-base,#f7f8fa);--surface:var(--dsw-alias-bg-layer-1,#fff);--text:var(--dsw-alias-label-primary,#15171b);--text2:var(--dsw-alias-label-secondary,#61666b);--text3:var(--dsw-alias-label-tertiary,#81858c);--cap:var(--dsw-alias-label-caption,#adb2b8);--brand:var(--dsw-alias-state-business-primary,#4176e6);--border:var(--dsw-alias-border-l1,#1118270f);--border2:var(--dsw-alias-border-l2,#1118271a);--hover:var(--dsw-alias-interactive-bg-hover,#1118270d);--ok:#18763e;--ok-soft:#e6faed;--bad:#c01313;--bad-soft:#fdebee;--warn:#8f571b;--warn-soft:#8f571b1a;--shadow-sm:0 1px 2px #1018280a;--tint-soft:#00000008;--tint-border:#0000000d;--tint-mid:#00000014;--tint-strong:#0000001f;--t1-up-border:#18763e2e;--t1-down-border:#c013132e;--canvas:#f0f2f7;--glass-fill:color-mix(in srgb, var(--surface) 74%, transparent);--glass-fill-2:color-mix(in srgb, var(--surface) 66%, transparent);--sheen:linear-gradient(180deg, #ffffffb8, #ffffff29 34px, #fff0 108px);--edge-light:#ffffffe6;--edge-dark:#1018280d;--shadow-ambient:0 1px 2px -1px #1018281a, 0 18px 44px -20px #10182857;--tray-fill:linear-gradient(180deg, #1018280e, #10182807 64px);--tray-shadow:inset 0 1px 3px -1px #10182821;--card-solid:#f3f4f6;--glow-1:#4176e629;--glow-2:#686cee1d;--glow-3:#4176e612;--radius:12px;--font:var(--dsw-font-family,-apple-system,BlinkMacSystemFont,\"Segoe UI\",\"PingFang SC\",\"Hiragino Sans GB\",\"Microsoft YaHei\",sans-serif);--mono:var(--ds-font-family-code,ui-monospace,SFMono-Regular,Menlo,Consolas,monospace);font:var(--fs-md)/1.45 var(--font);color:var(--text);-webkit-font-smoothing:antialiased;background-color:var(--canvas);background-image:radial-gradient(900px 420px at 20% -40px, var(--glow-1), transparent 70%), radial-gradient(980px 460px at 88% 260px, var(--glow-2), transparent 72%), radial-gradient(820px 400px at 44% 100%, var(--glow-3), transparent 70%);background-repeat:no-repeat;min-height:100%}body[data-ds-dark-theme] .SPgITW_dmt{--ok:#3fcb74;--ok-soft:#153824;--bad:#fa716a;--bad-soft:#3b1516;--warn:#e0a752;--warn-soft:#e0a75224;--shadow-sm:0 1px 2px #0000004d;--tint-soft:#ffffff0f;--tint-border:#ffffff14;--tint-mid:#ffffff1f;--tint-strong:#ffffff2e;--t1-up-border:#3fcb7459;--t1-down-border:#fa716a59;--canvas:var(--page);--glass-fill:color-mix(in srgb, var(--surface) 70%, transparent);--glass-fill-2:color-mix(in srgb, var(--surface) 62%, transparent);--sheen:linear-gradient(180deg, #ffffff1a, #ffffff08 40px, #fff0 170px);--edge-light:#ffffff24;--edge-dark:#0000004d;--shadow-ambient:0 1px 2px -1px #00000080, 0 20px 48px -22px #000000b8;--tray-fill:linear-gradient(180deg, #0000004d, #00000029 64px);--tray-shadow:inset 0 1px 3px -1px #00000073;--card-solid:#232324;--glow-1:#6c97f233;--glow-2:#927cf226;--glow-3:#6c97f21a}.SPgITW_dmt .SPgITW_top{box-sizing:border-box;padding:10px 0 0}.SPgITW_dmt .SPgITW_tin{box-sizing:border-box;max-width:calc(var(--col) - 28px);background:var(--surface);background:var(--sheen), var(--glass-fill-2);backdrop-filter:blur(28px)saturate(1.85);border:1px solid var(--border2);border-radius:var(--radius);box-shadow:var(--shadow-ambient), inset 0 1px 0 var(--edge-light), inset 0 -1px 0 var(--edge-dark);margin:0 auto;padding:10px 12px 11px}.SPgITW_dmt .SPgITW_tt{font:650 var(--fs-xl)/1.3 var(--font);letter-spacing:-.01em;flex-wrap:wrap;align-items:baseline;gap:3px 8px;display:flex}.SPgITW_dmt .SPgITW_tt:before{content:\"\";background:var(--brand);border-radius:3px;flex:none;align-self:center;width:8px;height:8px}.SPgITW_dmt .SPgITW_tt .SPgITW_rate{font:400 var(--fs-xs)/1.3 var(--font);color:var(--cap);font-variant-numeric:tabular-nums;white-space:nowrap;margin-left:auto}.SPgITW_dmt .SPgITW_ts{min-width:0;font:400 var(--fs-xs-l)/1.4 var(--font);color:var(--cap);text-overflow:ellipsis;white-space:nowrap;flex:0 auto;overflow:hidden}.SPgITW_dmt .SPgITW_stats{flex-wrap:wrap;align-items:baseline;gap:6px 18px;margin-top:8px;display:flex}.SPgITW_dmt .SPgITW_sg{align-items:baseline;gap:6px;min-width:0;display:flex}.SPgITW_dmt .SPgITW_sl{font:500 var(--fs-caption)/1.3 var(--font);color:var(--cap);letter-spacing:.03em}.SPgITW_dmt .SPgITW_sv{font:650 var(--fs-md-l)/1.3 var(--font);color:var(--text);font-variant-numeric:tabular-nums;white-space:nowrap}.SPgITW_dmt .SPgITW_sv.SPgITW_focus{font:700 var(--fs-2xl)/1.2 var(--font)}.SPgITW_dmt .SPgITW_sv.SPgITW_up{color:var(--ok)}.SPgITW_dmt .SPgITW_sv.SPgITW_down{color:var(--bad)}.SPgITW_dmt .SPgITW_bar{box-sizing:border-box;z-index:20;background:var(--canvas);background:color-mix(in srgb, var(--canvas) 62%, transparent);backdrop-filter:blur(24px)saturate(1.8);padding:8px 0 6px;position:sticky;top:0}.SPgITW_dmt .SPgITW_bar:after{content:\"\";pointer-events:none;background:linear-gradient(180deg, color-mix(in srgb, var(--canvas) 45%, transparent), transparent);height:9px;position:absolute;top:100%;left:0;right:0}.SPgITW_dmt .SPgITW_bin{box-sizing:border-box;max-width:calc(var(--col) - 28px);margin:0 auto}.SPgITW_dmt .SPgITW_filters{flex-wrap:wrap;gap:2px;margin-left:2px;display:flex}.SPgITW_dmt .SPgITW_ft{color:var(--text3);font:600 var(--fs-sm)/1.4 var(--font);cursor:pointer;background:0 0;border:0;border-radius:7px;padding:5px 10px;transition:background .12s,color .12s,transform .16s cubic-bezier(.23,1,.32,1)}.SPgITW_dmt .SPgITW_ft:active{transform:scale(.97)}@media (hover:hover) and (pointer:fine){.SPgITW_dmt .SPgITW_ft:hover{background:var(--hover)}}.SPgITW_dmt .SPgITW_ft.SPgITW_on{color:var(--text);background:var(--hover)}.SPgITW_dmt .SPgITW_ft:focus-visible{outline:1px solid var(--brand);outline-offset:1px}.SPgITW_dmt .SPgITW_list{box-sizing:border-box;max-width:var(--col);padding:0 14px calc(var(--dsh-composer-height,152px) + 24px);margin:0 auto}.SPgITW_dmt .SPgITW_day{font:650 var(--fs-sm-l)/1.3 var(--font);color:var(--text2);align-items:center;gap:8px;margin:18px 0 6px;display:flex}.SPgITW_dmt .SPgITW_day .SPgITW_n{color:var(--cap);font:400 var(--fs-caption)/1.3 var(--mono);margin-left:auto}.SPgITW_dmt .SPgITW_day:after{content:\"\";background:var(--border);flex:1;height:1px;margin-left:6px}.SPgITW_dmt .SPgITW_day.SPgITW_fold{cursor:pointer;border-radius:8px;margin-left:-6px;padding:3px 6px;transition:background .12s}.SPgITW_dmt .SPgITW_day.SPgITW_fold:active{background:var(--tint-mid)}@media (hover:hover) and (pointer:fine){.SPgITW_dmt .SPgITW_day.SPgITW_fold:hover{background:var(--hover)}}.SPgITW_dmt .SPgITW_day.SPgITW_fold:focus-visible{outline:1px solid var(--brand);outline-offset:1px}.SPgITW_dmt .SPgITW_day.SPgITW_fold .SPgITW_chev{text-align:center;width:12px;font-size:var(--fs-micro);color:var(--cap);flex:none;margin-left:0}.SPgITW_dmt .SPgITW_group{border:1px solid var(--border2);border-radius:var(--radius);background:var(--surface);background:var(--sheen), var(--glass-fill);backdrop-filter:blur(20px)saturate(1.7);box-shadow:var(--shadow-ambient), inset 0 1px 0 var(--edge-light), inset 0 -1px 0 var(--edge-dark);grid-template-columns:2px 8px auto minmax(64px,auto) auto minmax(0,1fr) auto auto 104px 12px 2px;gap:0 10px;display:grid;overflow:hidden}.SPgITW_dmt .SPgITW_cell{grid-column:1/-1;grid-template-columns:2px 8px auto minmax(64px,auto) auto minmax(0,1fr) auto auto 104px 12px 2px;grid-template-columns:subgrid;cursor:pointer;align-items:center;gap:0 10px;padding:9px 0;transition:background .12s;display:grid;position:relative}.SPgITW_dmt .SPgITW_cell+.SPgITW_cell{border-top:1px solid var(--border)}.SPgITW_dmt .SPgITW_cell:active{background:var(--tint-mid)}@media (hover:hover) and (pointer:fine){.SPgITW_dmt .SPgITW_cell:hover{background:var(--hover)}.SPgITW_dmt .SPgITW_cell:not(.SPgITW_open):hover .SPgITW_chev{color:var(--text2);transform:translateY(1px)}}.SPgITW_dmt .SPgITW_cell:focus-visible{outline:1px solid var(--brand);outline-offset:-2px}.SPgITW_dmt .SPgITW_cell.SPgITW_open:before{content:\"\";background:linear-gradient(180deg, var(--brand), color-mix(in srgb, var(--brand) 14%, transparent));border-radius:2px;width:3px;position:absolute;top:10px;bottom:10px;left:0}.SPgITW_dmt .SPgITW_main,.SPgITW_dmt .SPgITW_sub{display:contents}.SPgITW_dmt .SPgITW_dotm{background:var(--cap);border-radius:50%;grid-area:1/2;width:6px;height:6px}.SPgITW_dmt .SPgITW_cell.SPgITW_hasdec .SPgITW_dotm{background:var(--brand)}.SPgITW_dmt .SPgITW_sub .SPgITW_date{font:400 var(--fs-xs)/1.4 var(--mono);color:var(--cap);font-variant-numeric:tabular-nums;white-space:nowrap;grid-area:1/3}.SPgITW_dmt .SPgITW_tk{min-width:0;font:650 var(--fs-lg)/1.4 var(--font);letter-spacing:-.01em;text-overflow:ellipsis;white-space:nowrap;grid-area:1/4;overflow:hidden}.SPgITW_dmt .SPgITW_mkt{font:700 var(--fs-nano)/1 var(--font);vertical-align:2px;color:var(--brand);margin-left:3px}.SPgITW_dmt .SPgITW_mkt.SPgITW_hk{color:var(--text3)}.SPgITW_dmt .SPgITW_tag{border:1px solid var(--tint-border);background:var(--tint-soft);height:20px;font:600 var(--fs-xs-l)/1 var(--font);color:var(--text2);letter-spacing:.02em;white-space:nowrap;border-radius:6px;grid-area:1/5;justify-self:start;align-items:center;padding:0 7px;display:inline-flex}.SPgITW_dmt .SPgITW_qty{min-width:0;font:500 var(--fs-sm-l)/1.4 var(--mono);color:var(--text2);font-variant-numeric:tabular-nums;white-space:nowrap;text-overflow:ellipsis;grid-area:1/6;justify-self:start;overflow:hidden}.SPgITW_dmt .SPgITW_sp{display:none}.SPgITW_dmt .SPgITW_pnl{text-align:right;font:700 var(--fs-xl-l)/1.2 var(--font);font-variant-numeric:tabular-nums;letter-spacing:-.01em;grid-area:1/9;justify-self:end}.SPgITW_dmt .SPgITW_pnl.SPgITW_up{color:var(--ok)}.SPgITW_dmt .SPgITW_pnl.SPgITW_down{color:var(--bad)}.SPgITW_dmt .SPgITW_pnl.SPgITW_na{color:var(--cap);font-weight:500;font-size:var(--fs-md)}.SPgITW_dmt .SPgITW_pnlk{font:600 var(--fs-caption)/1.2 var(--font);color:var(--cap);letter-spacing:0;margin-right:3px}.SPgITW_dmt .SPgITW_t1{height:19px;font:600 var(--fs-caption)/1 var(--font);white-space:nowrap;font-variant-numeric:tabular-nums;border-radius:5px;grid-area:1/8;justify-self:end;align-items:center;padding:0 6px;display:inline-flex}.SPgITW_dmt .SPgITW_t1.SPgITW_up{color:var(--ok);background:var(--ok-soft);border:1px solid var(--t1-up-border)}.SPgITW_dmt .SPgITW_t1.SPgITW_down{color:var(--bad);background:var(--bad-soft);border:1px solid var(--t1-down-border)}.SPgITW_dmt .SPgITW_t1.SPgITW_flat{color:var(--text2);background:var(--tint-soft)}.SPgITW_dmt .SPgITW_al{height:19px;font:600 var(--fs-caption)/1 var(--font);white-space:nowrap;letter-spacing:.02em;border-radius:5px;grid-area:1/7;justify-self:end;align-items:center;padding:0 6px;display:inline-flex}.SPgITW_dmt .SPgITW_al.SPgITW_opp{color:var(--warn);background:var(--warn-soft);border:1px solid var(--t1-down-border)}.SPgITW_dmt .SPgITW_chev{color:var(--cap);font-size:var(--fs-micro);grid-area:1/10;justify-self:end;transition:transform .15s}.SPgITW_dmt .SPgITW_cell.SPgITW_open .SPgITW_chev{transform:rotate(180deg)}.SPgITW_dmt .SPgITW_detail{opacity:0;grid-area:2/1/auto/-1;grid-template-rows:0fr;transition:grid-template-rows .24s cubic-bezier(.22,1,.36,1),opacity .15s;display:grid;overflow:hidden}.SPgITW_dmt .SPgITW_cell.SPgITW_open .SPgITW_detail{opacity:1;grid-template-rows:1fr;margin-top:9px}.SPgITW_dmt .SPgITW_dinner{min-height:0;padding:0;overflow:hidden}.SPgITW_dmt .SPgITW_dbody{border:1px solid var(--tint-border);background:var(--tray-fill);box-shadow:var(--tray-shadow), inset 0 -1px 0 var(--edge-light);border-radius:10px;margin:0 10px 10px;padding:12px}.SPgITW_dmt .SPgITW_trhead{font:500 var(--fs-caption)/1.3 var(--font);color:var(--cap);letter-spacing:.05em;align-items:center;gap:6px;margin-bottom:8px;display:flex}.SPgITW_dmt .SPgITW_trhead:before{content:\"\";background:var(--brand);border-radius:50%;width:6px;height:6px}.SPgITW_dmt .SPgITW_trace{padding-left:22px;position:relative}.SPgITW_dmt .SPgITW_trace:before{content:\"\";background:var(--tint-mid);width:2px;position:absolute;top:12px;bottom:10px;left:5px}.SPgITW_dmt .SPgITW_tnode{padding:2px 0 14px;position:relative}.SPgITW_dmt .SPgITW_tnode:last-child{padding-bottom:2px}.SPgITW_dmt .SPgITW_tnode:before{content:\"\";background:var(--card-solid);border:2px solid var(--cap);box-sizing:border-box;border-radius:50%;width:10px;height:10px;position:absolute;top:5px;left:-22px}.SPgITW_dmt .SPgITW_tnode.SPgITW_dec:before{border-color:var(--brand)}.SPgITW_dmt .SPgITW_tnode.SPgITW_follow:before{border-color:var(--ok)}.SPgITW_dmt .SPgITW_tnode.SPgITW_skip:before{border-color:var(--warn)}.SPgITW_dmt .SPgITW_tnode.SPgITW_win:before{border-color:var(--ok)}.SPgITW_dmt .SPgITW_tnode.SPgITW_loss:before{border-color:var(--bad)}.SPgITW_dmt .SPgITW_tnode .SPgITW_tw{font:400 var(--fs-micro)/1.4 var(--mono);color:var(--cap);margin-bottom:1px}.SPgITW_dmt .SPgITW_tnode .SPgITW_n{font:500 var(--fs-caption)/1.3 var(--font);color:var(--cap);letter-spacing:.04em;margin-bottom:2px}.SPgITW_dmt .SPgITW_tnode .SPgITW_v{font:600 var(--fs-md)/1.4 var(--font)}.SPgITW_dmt .SPgITW_tnode.SPgITW_win .SPgITW_v{color:var(--ok)}.SPgITW_dmt .SPgITW_tnode.SPgITW_loss .SPgITW_v{color:var(--bad)}.SPgITW_dmt .SPgITW_tnode.SPgITW_follow .SPgITW_v{color:var(--ok)}.SPgITW_dmt .SPgITW_tnode.SPgITW_skip .SPgITW_v{color:var(--warn)}.SPgITW_dmt .SPgITW_pchips{flex-wrap:wrap;gap:6px;margin:4px 0 8px;display:flex}.SPgITW_dmt .SPgITW_pc{font:400 var(--fs-xs)/1.4 var(--font);background:var(--tint-soft);border:1px solid var(--border2);color:var(--text2);border-radius:6px;padding:2px 8px}.SPgITW_dmt .SPgITW_tnote{border-left:3px solid var(--tint-strong);font:400 var(--fs-xs-l)/1.6 var(--font);color:var(--text2);white-space:pre-wrap;overflow-wrap:anywhere;margin:7px 0;padding:3px 0 3px 10px}.SPgITW_dmt .SPgITW_tnote.SPgITW_why{border-left-color:var(--brand)}.SPgITW_dmt .SPgITW_tnote.SPgITW_emo{border-left-color:var(--warn)}.SPgITW_dmt .SPgITW_tnote .SPgITW_k{color:var(--cap);font:600 var(--fs-caption)/1.4 var(--font)}.SPgITW_dmt .SPgITW_tmiss{border:1px dashed var(--border2);font:400 var(--fs-xs-l)/1.5 var(--font);color:var(--cap);border-radius:6px;margin-top:8px;padding:7px 10px}.SPgITW_dmt .SPgITW_empty{text-align:center;color:var(--cap);font:400 var(--fs-md)/1.5 var(--font);border:1px dashed var(--tint-border);border-radius:var(--radius);background:var(--glass-fill);box-shadow:inset 0 1px 0 var(--edge-light), inset 0 -1px 0 var(--edge-dark);padding:48px 20px}.SPgITW_dmt .SPgITW_trace-more{border:1px dashed var(--border2);width:100%;color:var(--text2);font:600 var(--fs-sm)/1.4 var(--font);cursor:pointer;background:0 0;border-radius:10px;margin:12px 0 0;padding:9px 12px;transition:background .12s,border-color .12s,color .12s,transform .16s cubic-bezier(.23,1,.32,1);display:block}.SPgITW_dmt .SPgITW_trace-more:active{transform:scale(.98)}@media (hover:hover) and (pointer:fine){.SPgITW_dmt .SPgITW_trace-more:hover{background:var(--hover);border-color:var(--brand);color:var(--text)}}.SPgITW_dmt .SPgITW_skel{border:1px solid var(--border2);border-radius:var(--radius);background:var(--surface);background:var(--sheen), var(--glass-fill);backdrop-filter:blur(20px)saturate(1.7);box-shadow:var(--shadow-ambient), inset 0 1px 0 var(--edge-light), inset 0 -1px 0 var(--edge-dark);align-items:center;gap:12px;margin:8px 0;padding:13px 12px;display:flex}.SPgITW_dmt .SPgITW_skel-dot{background:var(--tint-strong);border-radius:50%;flex:none;width:6px;height:6px}.SPgITW_dmt .SPgITW_skel-bar{background:var(--tint-mid);border-radius:5px;height:10px;position:relative;overflow:hidden}.SPgITW_dmt .SPgITW_skel-bar:after{content:\"\";background:linear-gradient(90deg, transparent, var(--tint-strong), transparent);animation:1.2s ease-in-out infinite SPgITW_clawock-shimmer;position:absolute;inset:0;transform:translate(-100%)}@keyframes SPgITW_clawock-shimmer{to{transform:translate(100%)}}.SPgITW_dmt .SPgITW_day,.SPgITW_dmt .SPgITW_group{animation:.28s cubic-bezier(.22,1,.36,1) both SPgITW_clawock-rise}@keyframes SPgITW_clawock-rise{0%{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}.SPgITW_dmt .SPgITW_skel-bar.SPgITW_w40{width:40%}.SPgITW_dmt .SPgITW_skel-bar.SPgITW_w20{width:20%}@media (prefers-reduced-motion:reduce){.SPgITW_dmt .SPgITW_chev{transition:none}.SPgITW_dmt .SPgITW_detail{transition:opacity .15s}.SPgITW_dmt .SPgITW_ft,.SPgITW_dmt .SPgITW_trace-more{transition:background .12s,color .12s,border-color .12s}.SPgITW_dmt .SPgITW_skel-bar:after,.SPgITW_dmt .SPgITW_day,.SPgITW_dmt .SPgITW_group{animation:none}}@media (width<=520px){.SPgITW_dmt .SPgITW_top{padding:8px 10px 0}.SPgITW_dmt .SPgITW_bar{padding:6px 10px}.SPgITW_dmt .SPgITW_bin{max-width:none}.SPgITW_dmt .SPgITW_tin{max-width:none;padding:10px 12px 9px}.SPgITW_dmt .SPgITW_ts{white-space:normal;flex:1 0 100%}.SPgITW_dmt .SPgITW_stats{margin-top:6px;display:block}.SPgITW_dmt .SPgITW_sg{justify-content:space-between;gap:10px;padding:3px 0}.SPgITW_dmt .SPgITW_sg+.SPgITW_sg{border-top:1px solid var(--border)}.SPgITW_dmt .SPgITW_sv{white-space:normal;text-align:right}.SPgITW_dmt .SPgITW_ft{min-height:32px;padding:6px 11px}.SPgITW_dmt .SPgITW_list{padding:0 10px calc(var(--dsh-composer-height,152px) + 24px)}.SPgITW_dmt .SPgITW_day.SPgITW_fold{padding:7px 6px}.SPgITW_dmt .SPgITW_group{display:block}.SPgITW_dmt .SPgITW_cell{padding:0;display:block}.SPgITW_dmt .SPgITW_main{align-items:center;gap:8px;padding:10px 12px 2px;display:flex}.SPgITW_dmt .SPgITW_sub{align-items:center;gap:8px;padding:2px 12px 10px;display:flex}.SPgITW_dmt .SPgITW_dotm{flex:none;width:7px;height:7px}.SPgITW_dmt .SPgITW_tk{font-size:var(--fs-lg-l);flex:0 auto}.SPgITW_dmt .SPgITW_tag{flex:none;height:19px;padding:0 6px}.SPgITW_dmt .SPgITW_qty{font-size:var(--fs-sm);flex:0 auto}.SPgITW_dmt .SPgITW_sp{flex:auto;min-width:6px;display:block}.SPgITW_dmt .SPgITW_pnl{font-size:var(--fs-xl);flex:none}.SPgITW_dmt .SPgITW_t1,.SPgITW_dmt .SPgITW_al,.SPgITW_dmt .SPgITW_sub .SPgITW_date{flex:none}.SPgITW_dmt .SPgITW_chev{flex:none;margin-left:auto}.SPgITW_dmt .SPgITW_cell.SPgITW_open .SPgITW_detail{margin-top:0}.SPgITW_dmt .SPgITW_dbody{margin:0 8px 8px;padding:10px 11px 11px}.SPgITW_dmt .SPgITW_trace{padding-left:16px}.SPgITW_dmt .SPgITW_tnode:before{left:-16px}.SPgITW_dmt .SPgITW_trace:before{left:3px}.SPgITW_dmt .SPgITW_tin{backdrop-filter:blur(14px)saturate(1.85)}.SPgITW_dmt .SPgITW_group,.SPgITW_dmt .SPgITW_skel{backdrop-filter:blur(10px)saturate(1.7)}.SPgITW_dmt .SPgITW_bar{backdrop-filter:blur(12px)saturate(1.8)}}@media (prefers-reduced-transparency:reduce){.SPgITW_dmt{background-image:none}.SPgITW_dmt .SPgITW_tin,.SPgITW_dmt .SPgITW_group,.SPgITW_dmt .SPgITW_skel{background:var(--surface);backdrop-filter:none;box-shadow:var(--dsw-shadow-lv2,var(--shadow-sm))}.SPgITW_dmt .SPgITW_dbody{background:var(--tint-soft);box-shadow:none}.SPgITW_dmt .SPgITW_bar{background:var(--canvas);backdrop-filter:none}.SPgITW_dmt .SPgITW_bar:after{content:none}}.SPgITW_pbc{--surface:var(--dsw-alias-bg-layer-1,#fff);--text:var(--dsw-alias-label-primary,#15171b);--text3:var(--dsw-alias-label-tertiary,#81858c);--cap:var(--dsw-alias-label-caption,#adb2b8);--brand:var(--dsw-alias-state-business-primary,#4176e6);--hover:var(--dsw-alias-interactive-bg-hover,#1118270d);--ok:#18763e;--bad:#c01313;--warn:#8f571b;--shadow-lg:0 16px 40px #10182829, 0 2px 10px #10182814;--tint-border:#0000000d;--pop-surface:#ffffffb8;--edge-light:#ffffff8c;--font:var(--dsw-font-family,-apple-system,BlinkMacSystemFont,\"Segoe UI\",\"PingFang SC\",\"Hiragino Sans GB\",\"Microsoft YaHei\",sans-serif);display:inline-flex;position:relative}body[data-ds-dark-theme] .SPgITW_pbc{--ok:#3fcb74;--bad:#fa716a;--warn:#e0a752;--shadow-lg:0 16px 40px #00000085, 0 2px 10px #0000005c;--tint-border:#ffffff14;--pop-surface:#1c1e22c7;--edge-light:#ffffff1f}.SPgITW_pbc .SPgITW_bchip{border:1px solid var(--tint-border);background:var(--surface);background:color-mix(in srgb, var(--surface) 58%, transparent);backdrop-filter:blur(12px)saturate(1.75);height:26px;box-shadow:var(--dsw-shadow-lv1,0 1px 2px #1018280a), inset 0 1px 0 var(--edge-light);font:500 var(--fs-sm)/1 var(--font);color:var(--text3);cursor:pointer;border-radius:13px;align-items:center;gap:10px;padding:0 11px;transition:background .12s,color .12s,transform .16s cubic-bezier(.23,1,.32,1);display:inline-flex;position:relative}.SPgITW_pbc .SPgITW_bchip:after{content:\"\";border-radius:20px;position:absolute;inset:-7px}.SPgITW_pbc .SPgITW_bchip:active{transform:scale(.96)}@media (hover:hover) and (pointer:fine){.SPgITW_pbc .SPgITW_bchip:hover{background:color-mix(in srgb, var(--surface) 80%, transparent)}}.SPgITW_pbc .SPgITW_bchip:focus-visible{outline:1px solid var(--brand);outline-offset:1px}.SPgITW_pbc .SPgITW_bchip-item{align-items:center;gap:5px;display:inline-flex}.SPgITW_pbc .SPgITW_bchip-dot{background:var(--cap);border-radius:50%;flex:none;width:6px;height:6px;transition:background .15s}.SPgITW_pbc .SPgITW_bchip-item[data-balance-state=ok] .SPgITW_bchip-dot{background:var(--ok)}.SPgITW_pbc .SPgITW_bchip-item[data-balance-state=low] .SPgITW_bchip-dot{background:var(--bad)}.SPgITW_pbc .SPgITW_bchip-item[data-balance-state=stale] .SPgITW_bchip-dot{background:var(--warn)}.SPgITW_pbc .SPgITW_bchip-v{font:600 var(--fs-sm)/1 var(--font);font-variant-numeric:tabular-nums;letter-spacing:-.01em;white-space:nowrap;color:var(--text)}.SPgITW_pbc .SPgITW_bchip-v[data-balance-state=low]{color:var(--bad)}.SPgITW_pbc .SPgITW_bchip-v[data-balance-state=none]{color:var(--cap);font-weight:500}.SPgITW_pbc .SPgITW_bchip-v[data-used-level=ok]{color:var(--ok)}.SPgITW_pbc .SPgITW_bchip-v[data-used-level=mid],.SPgITW_pbc .SPgITW_bchip-v[data-balance-state=stale]{color:var(--warn)}.SPgITW_pbc .SPgITW_bchip-reset{font-family:var(--mono);font-size:var(--fs-xs);font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--cap);font-weight:500}.SPgITW_pbc .SPgITW_bchip-sub{font:500 var(--fs-xs)/1 var(--font);font-variant-numeric:tabular-nums;letter-spacing:.01em;white-space:nowrap;color:var(--text3)}.SPgITW_pbc .SPgITW_bp{z-index:60;border:1px solid var(--tint-border);background:var(--surface);background:color-mix(in srgb, var(--pop-surface) 100%, transparent);backdrop-filter:blur(30px)saturate(1.9);width:max-content;min-width:min(220px,100vw - 24px);max-width:min(300px,100vw - 24px);box-shadow:var(--shadow-lg), inset 0 1px 0 var(--edge-light);transform-origin:100% 0;border-radius:12px;padding:10px 12px 8px;transition:transform .16s cubic-bezier(.23,1,.32,1),opacity .16s cubic-bezier(.23,1,.32,1);position:absolute;top:calc(100% + 8px);right:0}.SPgITW_pbc .SPgITW_bp[data-open=false]{opacity:0;pointer-events:none;transform:scale(.97)translateY(-4px)}.SPgITW_pbc .SPgITW_bp-head{justify-content:space-between;align-items:center;margin-bottom:2px;display:flex}.SPgITW_pbc .SPgITW_bp-title{font:600 var(--fs-xs)/1.3 var(--font);letter-spacing:.04em;color:var(--cap)}.SPgITW_pbc .SPgITW_bp-row{width:100%;font:inherit;color:inherit;text-align:left;cursor:pointer;background:0 0;border:0;border-radius:8px;grid-template-columns:auto auto 1fr;align-items:center;gap:3px 8px;margin:0 -6px;padding:8px 6px;transition:background .12s,transform .16s cubic-bezier(.23,1,.32,1);display:grid}.SPgITW_pbc .SPgITW_bp-row+.SPgITW_bp-row{border-radius:0 0 8px 8px;position:relative}.SPgITW_pbc .SPgITW_bp-row+.SPgITW_bp-row:before{content:\"\";background:var(--tint-border);height:1px;position:absolute;top:0;left:6px;right:6px}@media (hover:hover) and (pointer:fine){.SPgITW_pbc .SPgITW_bp-row:hover{background:var(--hover)}}.SPgITW_pbc .SPgITW_bp-row:active{background:var(--hover);transform:scale(.98)}.SPgITW_pbc .SPgITW_bp-row:focus-visible{outline:1px solid var(--brand);outline-offset:-1px}.SPgITW_pbc .SPgITW_bp-dot{background:var(--cap);border-radius:50%;width:7px;height:7px}.SPgITW_pbc .SPgITW_bp-dot[data-balance-state=ok]{background:var(--ok)}.SPgITW_pbc .SPgITW_bp-dot[data-balance-state=low]{background:var(--bad)}.SPgITW_pbc .SPgITW_bp-dot[data-balance-state=stale]{background:var(--warn)}.SPgITW_pbc .SPgITW_bp-label{font:500 var(--fs-sm)/1.4 var(--font);color:var(--text);align-items:center;gap:5px;display:inline-flex}.SPgITW_pbc .SPgITW_bp-pin{background:var(--brand);border-radius:50%;flex:none;width:5px;height:5px}.SPgITW_pbc .SPgITW_bp-v{font:650 var(--fs-md)/1.2 var(--font);font-variant-numeric:tabular-nums;letter-spacing:-.01em;white-space:nowrap;color:var(--text);justify-self:end}.SPgITW_pbc .SPgITW_bp-v.SPgITW_bad{color:var(--bad)}.SPgITW_pbc .SPgITW_bp-wins{flex-direction:column;grid-column:1/-1;gap:6px;margin-top:2px;display:flex}.SPgITW_pbc .SPgITW_bp-win{font-size:var(--fs-xs);flex-direction:column;gap:3px;display:flex}.SPgITW_pbc .SPgITW_bp-win-line{align-items:baseline;gap:8px;line-height:1.5;display:flex}.SPgITW_pbc .SPgITW_bp-win-label{color:var(--cap);letter-spacing:.02em;min-width:30px}.SPgITW_pbc .SPgITW_bp-win-pct{color:var(--text);font-variant-numeric:tabular-nums;margin-left:auto;font-weight:600}.SPgITW_pbc .SPgITW_bp-win-reset{color:var(--cap);font-family:var(--mono);font-size:var(--fs-caption);text-align:right;font-variant-numeric:tabular-nums;min-width:58px}.SPgITW_pbc .SPgITW_bp-win-bar{background:color-mix(in srgb, var(--text) 9%, transparent);border-radius:2px;height:3px;overflow:hidden}.SPgITW_pbc .SPgITW_bp-win-fill{background:var(--ok);border-radius:2px;height:100%;transition:background .15s}.SPgITW_pbc .SPgITW_bp-win-fill[data-balance-state=mid]{background:var(--warn)}.SPgITW_pbc .SPgITW_bp-win-fill[data-balance-state=low]{background:var(--bad)}.SPgITW_pbc .SPgITW_bp-win-fill[data-balance-state=stale]{background:var(--warn)}.SPgITW_pbc .SPgITW_bp-note,.SPgITW_pbc .SPgITW_bp-sub{font:400 var(--fs-xs)/1.5 var(--font);overflow-wrap:anywhere;grid-column:1/-1}.SPgITW_pbc .SPgITW_bp-sub{color:var(--cap)}.SPgITW_pbc .SPgITW_bp-note.SPgITW_warn{color:var(--warn)}.SPgITW_pbc .SPgITW_bp-note.SPgITW_bad{color:var(--bad)}.SPgITW_pbc .SPgITW_bp-empty{font:400 var(--fs-sm)/1.5 var(--font);color:var(--cap);padding:8px 0 10px}.SPgITW_pbc .SPgITW_bal-rf{width:22px;height:22px;color:var(--text3);font:600 var(--fs-sm)/1 var(--font);cursor:pointer;background:0 0;border:0;border-radius:50%;justify-content:center;align-items:center;padding:0;transition:background .12s,color .12s,transform .16s cubic-bezier(.23,1,.32,1);display:inline-flex;position:relative}.SPgITW_pbc .SPgITW_bal-rf:after{content:\"\";border-radius:50%;position:absolute;inset:-9px}.SPgITW_pbc .SPgITW_bal-rf:active{transform:scale(.95)}@media (hover:hover) and (pointer:fine){.SPgITW_pbc .SPgITW_bal-rf:hover{background:var(--hover);color:var(--text)}}.SPgITW_pbc .SPgITW_bal-rf:focus-visible{outline:1px solid var(--brand);outline-offset:1px}.SPgITW_pbc .SPgITW_bal-rf.SPgITW_spin{animation:.8s linear infinite SPgITW_clawock-spin}.SPgITW_pbc .SPgITW_bal-rf.SPgITW_flash-ok{color:var(--brand)}.SPgITW_pbc .SPgITW_bal-rf.SPgITW_flash-same{color:var(--ok)}@keyframes SPgITW_clawock-spin{to{transform:rotate(360deg)}}@media (prefers-reduced-motion:reduce){.SPgITW_pbc .SPgITW_bchip,.SPgITW_pbc .SPgITW_bal-rf{transition:background .12s,color .12s}.SPgITW_pbc .SPgITW_bp{transition:opacity .16s}.SPgITW_pbc .SPgITW_bp[data-open=false],.SPgITW_pbc .SPgITW_bchip:active,.SPgITW_pbc .SPgITW_bal-rf:active{transform:none}.SPgITW_pbc .SPgITW_bal-rf.SPgITW_spin{animation:none}.SPgITW_pbc .SPgITW_bp-win-fill{transition:none}}@media (width<=520px){.SPgITW_pbc .SPgITW_bchip{backdrop-filter:blur(7px)saturate(1.4)}.SPgITW_pbc .SPgITW_bp{backdrop-filter:blur(14px)saturate(1.5)}}@media (prefers-reduced-transparency:reduce){.SPgITW_pbc .SPgITW_bchip,.SPgITW_pbc .SPgITW_bp{background:var(--surface);backdrop-filter:none}}";
const tagId = "clawock-dsh/styles.module.css";
if (typeof document !== "undefined" && document.querySelector("style[data-plugin-css=" + JSON.stringify(tagId) + "]") === null) {
	const tag = document.createElement("style");
	tag.dataset.plugin = "clawock-dsh";
	tag.dataset.pluginCss = tagId;
	tag.textContent = css;
	document.head.appendChild(tag);
}
var styles_module_css_default = {
	"al": "SPgITW_al",
	"bad": "SPgITW_bad",
	"bal-rf": "SPgITW_bal-rf",
	"bar": "SPgITW_bar",
	"bchip": "SPgITW_bchip",
	"bchip-dot": "SPgITW_bchip-dot",
	"bchip-item": "SPgITW_bchip-item",
	"bchip-reset": "SPgITW_bchip-reset",
	"bchip-sub": "SPgITW_bchip-sub",
	"bchip-v": "SPgITW_bchip-v",
	"bin": "SPgITW_bin",
	"bp": "SPgITW_bp",
	"bp-dot": "SPgITW_bp-dot",
	"bp-empty": "SPgITW_bp-empty",
	"bp-head": "SPgITW_bp-head",
	"bp-label": "SPgITW_bp-label",
	"bp-note": "SPgITW_bp-note",
	"bp-pin": "SPgITW_bp-pin",
	"bp-row": "SPgITW_bp-row",
	"bp-sub": "SPgITW_bp-sub",
	"bp-title": "SPgITW_bp-title",
	"bp-v": "SPgITW_bp-v",
	"bp-win": "SPgITW_bp-win",
	"bp-win-bar": "SPgITW_bp-win-bar",
	"bp-win-fill": "SPgITW_bp-win-fill",
	"bp-win-label": "SPgITW_bp-win-label",
	"bp-win-line": "SPgITW_bp-win-line",
	"bp-win-pct": "SPgITW_bp-win-pct",
	"bp-win-reset": "SPgITW_bp-win-reset",
	"bp-wins": "SPgITW_bp-wins",
	"cell": "SPgITW_cell",
	"chev": "SPgITW_chev",
	"clawock-rise": "SPgITW_clawock-rise",
	"clawock-shimmer": "SPgITW_clawock-shimmer",
	"clawock-spin": "SPgITW_clawock-spin",
	"date": "SPgITW_date",
	"day": "SPgITW_day",
	"dbody": "SPgITW_dbody",
	"dec": "SPgITW_dec",
	"detail": "SPgITW_detail",
	"dinner": "SPgITW_dinner",
	"dmt": "SPgITW_dmt",
	"dotm": "SPgITW_dotm",
	"down": "SPgITW_down",
	"emo": "SPgITW_emo",
	"empty": "SPgITW_empty",
	"filters": "SPgITW_filters",
	"flash-ok": "SPgITW_flash-ok",
	"flash-same": "SPgITW_flash-same",
	"flat": "SPgITW_flat",
	"focus": "SPgITW_focus",
	"fold": "SPgITW_fold",
	"follow": "SPgITW_follow",
	"ft": "SPgITW_ft",
	"group": "SPgITW_group",
	"hasdec": "SPgITW_hasdec",
	"hk": "SPgITW_hk",
	"k": "SPgITW_k",
	"list": "SPgITW_list",
	"loss": "SPgITW_loss",
	"main": "SPgITW_main",
	"mkt": "SPgITW_mkt",
	"n": "SPgITW_n",
	"na": "SPgITW_na",
	"on": "SPgITW_on",
	"open": "SPgITW_open",
	"opp": "SPgITW_opp",
	"pbc": "SPgITW_pbc",
	"pc": "SPgITW_pc",
	"pchips": "SPgITW_pchips",
	"pnl": "SPgITW_pnl",
	"pnlk": "SPgITW_pnlk",
	"qty": "SPgITW_qty",
	"rate": "SPgITW_rate",
	"sg": "SPgITW_sg",
	"skel": "SPgITW_skel",
	"skel-bar": "SPgITW_skel-bar",
	"skel-dot": "SPgITW_skel-dot",
	"skip": "SPgITW_skip",
	"sl": "SPgITW_sl",
	"sp": "SPgITW_sp",
	"spin": "SPgITW_spin",
	"stats": "SPgITW_stats",
	"sub": "SPgITW_sub",
	"sv": "SPgITW_sv",
	"t1": "SPgITW_t1",
	"tag": "SPgITW_tag",
	"tin": "SPgITW_tin",
	"tk": "SPgITW_tk",
	"tmiss": "SPgITW_tmiss",
	"tnode": "SPgITW_tnode",
	"tnote": "SPgITW_tnote",
	"top": "SPgITW_top",
	"trace": "SPgITW_trace",
	"trace-more": "SPgITW_trace-more",
	"trhead": "SPgITW_trhead",
	"ts": "SPgITW_ts",
	"tt": "SPgITW_tt",
	"tw": "SPgITW_tw",
	"up": "SPgITW_up",
	"v": "SPgITW_v",
	"w20": "SPgITW_w20",
	"w40": "SPgITW_w40",
	"warn": "SPgITW_warn",
	"why": "SPgITW_why",
	"win": "SPgITW_win"
};
//#endregion
//#region src/client.ts
/**
* clawock-dsh browser bundle: the Decision Mind conversation-view tab.
*
* One organic view — the decision trace: real fills as the spine, the shared
* decision ledger (memory/decisions.jsonl) soft-paired (±3 days) as the "why"
* layer, and canonical bar closes (memory/bars/, never snapshot current_price
* — see readBarCloses) as the T+1 verdict. Fills without a decision say so
* explicitly. Visual language: modern SaaS on DSH tokens, with the P&L
* figure as the focal number and a GitHub-style vertical timeline in the
* expandable detail.
*
* Official client discipline (`packages/client/AGENTS.md` in the Harness
* tree), all four rules this file has to satisfy:
*   - registration happens inside `apply` through `ctx.slots.register`, and
*     the module body has no side effects — styles arrive as a CSS Modules
*     import, whose `<style data-plugin>` tag the loader owns and removes on
*     unload;
*   - the store is an exported `createDecisionMindStore()` factory called in
*     `apply`, never a module-level handle (a disguised singleton);
*   - live data reaches render through the props shares only, so the trace
*     cache lives in the apply closure and is read through `inject`;
*   - components take named props and the wire types from `./types.ts`.
*/
const { createElement, useEffect, useRef, useState } = React;
const h = createElement;
/** Class tokens declared in styles.module.css, mapped to their hashed names. */
function cx(...tokens) {
	const out = [];
	for (const token of tokens) {
		if (token === "" || token === false || token === null || token === void 0) continue;
		out.push(styles_module_css_default[token] ?? token);
	}
	return out.join(" ");
}
/** Newest date groups rendered expanded; older days arrive in batches. */
const DEFAULT_VISIBLE_DATES = 3;
const BATCH_GROUPS = 5;
/**
* Store factory — called once inside `apply`. Never a module-level handle:
* the module cache would make it a singleton shared across plugin reloads.
*/
function createDecisionMindStore() {
	return defineStore({
		init: () => ({
			filter: "all",
			open: null,
			visibleDateCount: DEFAULT_VISIBLE_DATES,
			foldedDates: [],
			scrollTop: 0
		}),
		actions: {
			setFilter: (draft, value) => {
				draft.filter = value;
			},
			toggleOpen: (draft, key) => {
				draft.open = draft.open === key ? null : key;
			},
			showMoreDates: (draft, count) => {
				draft.visibleDateCount = draft.visibleDateCount + count;
			},
			resetDates: (draft) => {
				draft.visibleDateCount = DEFAULT_VISIBLE_DATES;
			},
			toggleDate: (draft, date) => {
				draft.foldedDates = draft.foldedDates.indexOf(date) >= 0 ? draft.foldedDates.filter((d) => d !== date) : draft.foldedDates.concat([date]);
			},
			setScrollTop: (draft, value) => {
				draft.scrollTop = value;
			}
		}
	});
}
const ACT = {
	buy: "买入",
	add: "加仓",
	trim: "减仓",
	sell: "卖出",
	cut: "割肉",
	hold: "持有",
	hold_and_watch: "持有",
	trim_on_rebound: "反弹减仓",
	t_only: "仅T+0",
	add_only_on_trigger: "触发加仓",
	reject: "不加",
	watch: "观望",
	abstain: "弃权"
};
const DRV = {
	technical: "技术面",
	fundamental: "基本面",
	sentiment: "情绪面",
	mixed: "混合",
	risk_rule: "风控规则"
};
/**
* The ledger's `execution.status`, in words.
*
* This grades the PLAN — "was this plan followed" — and it is not a statement
* about the fill on the row, which happened either way. Rendering 「未执行」 as
* that row's 执行 verdict read as a flat contradiction on a completed buy, and
* on live data 8 rows said 已遵守 while the plan's action still differed from
* the fill's. So it renders as 账本自评 and never as the fill's own status; the
* plan-vs-fill relation is `decision.alignment` below.
*/
const EXE = {
	followed: "遵守了计划",
	not_followed: "没按计划",
	unknown: "未标注"
};
/** The plan-vs-fill relation, stated instead of left to be inferred. */
const ALIGN = {
	same: ["与计划同向", "follow"],
	opposite: ["与计划反向", "skip"],
	other: ["计划未指向买卖", ""]
};
const EMO = {
	fomo: "追高冲动",
	revenge: "报复性",
	averaging_down: "摊薄冲动",
	fear: "恐慌",
	euphoria: "亢奋",
	calm: "平静",
	mixed: "混合"
};
const FILTER_LABEL = {
	all: "全部",
	miss: "无当日计划",
	sold: "卖出复盘",
	dec: "有当日计划"
};
/**
* React escapes string children itself; the old extra `<` → `&lt;` pass here
* double-escaped (the literal text "&lt;" once React escaped the ampersand).
* String coercion is all a text slot needs.
*/
function esc(value) {
	return String(value === null || value === void 0 ? "" : value);
}
/**
* The T+1 tone is decided host-side (`t1ToneOf` in ledger.ts) and shipped on
* the trace as `t1.tone`. These two helpers only map that single reading onto
* the two CSS vocabularies used here — the trace node's win/loss and the
* chip's up/down. They deliberately take no thresholds: three independent
* dead zones used to colour the same fill grey-"持平" in the chip and red in
* the node, and to paint a buy at exactly 0% green while the text read 跌.
*/
function t1NodeClass(tone) {
	return tone === "win" || tone === "loss" ? tone : "";
}
function t1ChipClass(tone) {
	if (tone === "win") return "up";
	if (tone === "loss") return "down";
	return "flat";
}
function fmtMoney(value) {
	if (value === null || !isFinite(value)) return "—";
	return (value > 0 ? "+" : "") + value.toLocaleString(void 0, { maximumFractionDigits: 0 });
}
function fmtPct(value, digits = 1) {
	if (value === null || !isFinite(value)) return "—";
	return (value > 0 ? "+" : "") + value.toFixed(digits) + "%";
}
/** Display projection of one trace (test seam). */
function _displayEntry(trace) {
	return {
		ticker: trace.ticker || "?",
		market: trace.market || "US",
		currency: trace.currency || "USD",
		date: trace.date ?? null,
		action: trace.action || "?",
		shares: trace.shares || 0,
		price: trace.price ?? null,
		realizedPnl: trace.realizedPnl ?? null,
		note: trace.note ?? null,
		t1: trace.t1 ?? null,
		holdPnl: trace.holdPnl ?? null,
		decision: trace.decision ?? null,
		side: trace.side === "reduce" || trace.side === "add" ? trace.side : null
	};
}
function Chip(props) {
	return h("span", { className: cx("tag") }, props.children);
}
function TraceDetail(props) {
	const trace = props.trace;
	const decision = trace.decision;
	const sym = trace.currency === "HKD" ? "HK$" : "$";
	const fillText = (ACT[trace.action] ?? trace.action) + " " + trace.shares + " 股 @ " + sym + trace.price;
	if (decision === null) {
		const t1miss = trace.t1 === null ? null : h("div", { className: cx("tnode", t1NodeClass(trace.t1.tone)) }, h("div", { className: cx("tw") }, trace.t1.date), h("div", { className: cx("n") }, "T+1 收盘"), h("div", { className: cx("v") }, (trace.t1.delta >= 0 ? "+" : "") + trace.t1.delta + "% · " + trace.t1.verdict));
		return h("div", { className: cx("dbody") }, h("div", { className: cx("trhead") }, "决策轨迹 · 无当日计划"), h("div", { className: cx("trace") }, h("div", { className: cx("tnode", "dec") }, h("div", { className: cx("n") }, "当时的计划"), h("div", {
			className: cx("v"),
			style: { color: "var(--cap)" }
		}, "这一天没有该标的的计划记录")), h("div", { className: cx("tnode", "follow") }, h("div", { className: cx("tw") }, trace.date ?? ""), h("div", { className: cx("n") }, "真实成交"), h("div", { className: cx("v") }, fillText)), t1miss), trace.note === null ? null : h("div", { className: cx("tnote") }, esc(trace.note)), h("div", { className: cx("tmiss") }, "这笔成交在决策账本里找不到前后 3 天的同标的计划:成交是真的,当时的判断没有留下记录。"));
	}
	const [alignLabel, alignTone] = ALIGN[decision.alignment ?? ""] ?? ["", ""];
	const planned = (ACT[decision.action ?? ""] ?? decision.action ?? "") + (decision.sizeShares === null ? "" : " " + decision.sizeShares + " 股") + (decision.plannedPrice === null ? "" : " @ " + decision.plannedPrice) + (decision.confidence === null ? "" : " · 信心 " + Math.round(decision.confidence * 100) + "%") + (decision.drivenBy === null ? "" : " · " + (DRV[decision.drivenBy] ?? decision.drivenBy));
	const why = decision.rationale ?? decision.bull ?? "";
	const emotion = decision.emotion !== null && decision.emotion !== "calm" ? EMO[decision.emotion] ?? decision.emotion : null;
	const chips = [];
	if (decision.condition !== null) chips.push(h("span", {
		className: cx("pc"),
		key: "c"
	}, "触发条件: " + decision.condition));
	if (decision.execution !== null) chips.push(h("span", {
		className: cx("pc"),
		key: "e"
	}, "账本自评: " + (EXE[decision.execution] ?? decision.execution)));
	const t1node = trace.t1 === null ? null : h("div", { className: cx("tnode", t1NodeClass(trace.t1.tone)) }, h("div", { className: cx("tw") }, trace.t1.date), h("div", { className: cx("n") }, "T+1 收盘"), h("div", { className: cx("v") }, (trace.t1.delta >= 0 ? "+" : "") + trace.t1.delta + "% · " + trace.t1.verdict));
	let pnlText;
	let pnlTone;
	let pnlLabel;
	if (trace.realizedPnl !== null) {
		pnlText = (trace.realizedPnl >= 0 ? "+" : "") + trace.realizedPnl.toFixed(2) + " " + sym;
		pnlTone = trace.realizedPnl >= 0 ? "win" : "loss";
		pnlLabel = "本笔已实现";
	} else if (trace.holdPnl !== null) {
		pnlText = fmtPct(trace.holdPnl);
		pnlTone = trace.holdPnl >= 0 ? "win" : "loss";
		pnlLabel = "该持仓当前浮动 (" + trace.ticker + " 全仓,非本笔)";
	} else {
		pnlText = "— 未平仓";
		pnlTone = "";
		pnlLabel = "本笔盈亏";
	}
	return h("div", { className: cx("dbody") }, h("div", { className: cx("trhead") }, "决策轨迹 · " + (decision.planDate ?? "")), h("div", { className: cx("trace") }, h("div", { className: cx("tnode", "dec") }, h("div", { className: cx("tw") }, decision.planDate ?? ""), h("div", { className: cx("n") }, "当时的计划"), h("div", { className: cx("v") }, planned)), h("div", { className: cx("tnode", alignTone) }, h("div", { className: cx("tw") }, trace.date ?? ""), h("div", { className: cx("n") }, "真实成交"), h("div", { className: cx("v") }, fillText, alignLabel === "" ? null : h("span", { className: cx("pc", alignTone) }, alignLabel))), t1node, h("div", { className: cx("tnode", pnlTone) }, h("div", { className: cx("n") }, pnlLabel), h("div", { className: cx("v") }, pnlText))), chips.length === 0 ? null : h("div", { className: cx("pchips") }, chips), why === "" ? null : h("div", { className: cx("tnote", "why") }, h("span", { className: cx("k") }, "为什么 "), esc(why)), emotion === null ? null : h("div", { className: cx("tnote", "emo") }, h("span", { className: cx("k") }, "情绪 "), "⚡ " + emotion), trace.note === null ? null : h("div", { className: cx("tnote") }, h("span", { className: cx("k") }, "备注 "), esc(trace.note)));
}
function TraceCell(props) {
	const trace = props.trace;
	const sym = trace.currency === "HKD" ? "HK$" : "$";
	let pnl;
	if (trace.realizedPnl !== null) pnl = h("span", { className: cx("pnl", trace.realizedPnl >= 0 ? "up" : "down") }, (trace.realizedPnl >= 0 ? "+" : "") + trace.realizedPnl.toFixed(2) + " " + sym);
	else if (trace.holdPnl !== null) pnl = h("span", { className: cx("pnl", trace.holdPnl >= 0 ? "up" : "down") }, h("span", { className: cx("pnlk") }, "持仓"), fmtPct(trace.holdPnl));
	else pnl = h("span", { className: cx("pnl", "na") }, "—");
	let t1tag;
	if (trace.t1 !== null) {
		const tone = t1ChipClass(trace.t1.tone);
		const label = "T+1 " + (trace.t1.delta >= 0 ? "+" : "") + trace.t1.delta + "% " + trace.t1.verdict;
		t1tag = h("span", {
			className: cx("t1", tone),
			"data-tone": tone
		}, label);
	} else t1tag = h("span", {
		className: cx("t1", "flat"),
		"data-tone": "flat"
	}, "T+1 未判");
	let alignTag = null;
	if (trace.decision?.alignment === "opposite") alignTag = h("span", {
		className: cx("al", "opp"),
		"data-align": "opposite"
	}, "反向");
	return h("div", {
		className: cx("cell", trace.decision !== null && "hasdec", props.open && "open"),
		"data-cell": "trace",
		role: "button",
		tabIndex: 0,
		"aria-expanded": props.open,
		onClick: props.onToggle,
		onKeyDown: props.onKeyDown
	}, h("div", { className: cx("main") }, h("span", { className: cx("dotm") }), h("span", { className: cx("tk") }, trace.ticker, h("span", { className: cx("mkt", trace.market === "HK" && "hk") }, trace.market === "HK" ? "港" : "美")), h(Chip, null, ACT[trace.action] ?? trace.action), h("span", { className: cx("qty") }, trace.shares + " @" + trace.price), h("span", { className: cx("sp") }), pnl), h("div", { className: cx("sub") }, t1tag, alignTag, h("span", { className: cx("date") }, (trace.date ?? "").slice(5)), h("span", { className: cx("chev") }, "▾")), h("div", { className: cx("detail") }, h("div", { className: cx("dinner") }, props.open ? h(TraceDetail, { trace }) : null)));
}
/** Skeleton row for the cold-start loading state (no cache yet). */
function SkeletonRow() {
	return h("div", { className: cx("skel") }, h("div", { className: cx("skel-dot") }), h("div", { className: cx("skel-bar", "w40") }), h("div", { className: cx("skel-bar", "w20") }));
}
function messageOf(error) {
	return error instanceof Error ? error.message : String(error);
}
function todayIso() {
	const now = /* @__PURE__ */ new Date();
	return now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" + String(now.getDate()).padStart(2, "0");
}
function relativeDay(iso, today) {
	if (iso === today) return "今天";
	const at = (date) => (/* @__PURE__ */ new Date(date + "T00:00:00")).getTime();
	const days = Math.round((at(today) - at(iso)) / 864e5);
	if (days === 1) return "昨天";
	if (days >= 2 && days <= 7) return days + "天前";
	return parseInt(iso.slice(5, 7)) + "月" + parseInt(iso.slice(8, 10)) + "日";
}
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
/**
* Display projection of ONE provider's answer (test seam, like _displayEntry):
* the chip and panel render only these fields, so the view never keeps
* a second copy of the tone rules — the host already decided status and low.
* The title is the whole hover story: split, quota windows, stale reason,
* fetch time. Quota rows ('pct' unit) read as USED percent (kcn: 「已使用」
* 比「剩余」直观), not money, and carry the second window ('周'/'本周') as a
* muted pill suffix — both limits visible at the header without opening the
* panel. An exhausted window gets no caption at all (kcn 反馈: 文案只会重复):
* the reading itself says 100% and `reset` carries when it frees up.
*/
function _rowDisplay(result) {
	if (result === null) return {
		tone: "none",
		value: "—",
		sub: null,
		reset: null,
		level: null,
		title: "余额加载中"
	};
	if (!result.configured) return {
		tone: "none",
		value: "未配置",
		sub: null,
		reset: null,
		level: null,
		title: result.message ?? "未配置 API Key"
	};
	if (result.snapshot === null) return {
		tone: "none",
		value: "—",
		sub: null,
		reset: null,
		level: null,
		title: result.message ?? "余额获取失败"
	};
	const snapshot = result.snapshot;
	const isPct = snapshot.unit === "pct";
	const symbol = isPct ? "" : snapshot.currency === "USD" ? "$" : snapshot.currency === "CNY" ? "¥" : "";
	const pctWins = isPct && Array.isArray(snapshot.windows) ? snapshot.windows.filter((w) => w.percent !== null) : [];
	const parsed = Number.parseFloat(snapshot.totalBalance);
	const value = isFinite(parsed) ? isPct ? String(Math.round(parsed)) + "%" : symbol + parsed.toLocaleString(void 0, { maximumFractionDigits: 2 }) : pctWins.length > 0 ? String(Math.round(pctWins[0].percent)) + "%" : snapshot.totalBalance === "" ? "—" : symbol + snapshot.totalBalance;
	const second = pctWins.length > 1 ? pctWins[1] : null;
	const reset = pctWins.length > 0 && pctWins[0].resetAt !== "" ? pctWins[0].resetAt : null;
	const sub = second !== null ? "· " + second.label + " " + Math.round(second.percent) + "%" + (second.resetAt !== "" ? " ↻" + second.resetAt : "") : null;
	const tone = result.status === "stale" ? "stale" : result.low || !snapshot.isAvailable ? "low" : "ok";
	const parts = [
		snapshot.unit === "pct" ? snapshot.note !== "" ? snapshot.note : "配额窗口已使用" : "API 余额",
		!isPct && snapshot.grantedBalance !== "" ? "赠金 " + symbol + snapshot.grantedBalance : null,
		!isPct && snapshot.toppedUpBalance !== "" ? "充值 " + symbol + snapshot.toppedUpBalance : null,
		snapshot.isAvailable || isPct ? null : "官方接口判定余额不足",
		result.status === "stale" && result.message !== null ? "刷新失败,显示最近一次: " + result.message : null
	].filter((part) => part !== null);
	const shownPct = isPct ? isFinite(parsed) ? parsed : pctWins.length > 0 ? pctWins[0].percent : null : null;
	return {
		tone,
		value,
		sub,
		reset,
		level: shownPct === null ? null : _usedLevel(Math.round(shownPct), result.threshold),
		title: parts.join(" · ")
	};
}
/**
* The one line a panel row says out loud when something is wrong — stale
* reason, unconfigured key, insufficient money balance. A healthy number
* earns no caption at all; null means silence. An exhausted quota window
* is silence too (kcn 反馈): its 100% bar and reset stamp in the per-window
* rows are the message; a caption would only replace them.
*/
function _balanceNote(result) {
	if (result === null) return null;
	if (!result.configured) return result.message ?? "未配置 API Key";
	if (result.snapshot === null) return result.message ?? "余额获取失败";
	if (result.status === "stale") return "刷新失败,显示最近一次" + (result.message !== null ? ":" + result.message : "");
	if (!result.snapshot.isAvailable) return result.snapshot.unit === "pct" ? null : "官方接口判定余额不足";
	if (result.low) {
		if (result.snapshot.unit === "pct") return "窗口已使用达 " + (100 - result.threshold) + "%";
		return "余额偏低,低于阈值 " + (result.snapshot.currency === "USD" ? "$" : result.snapshot.currency === "CNY" ? "¥" : "") + result.threshold;
	}
	return null;
}
/** Store factory — called inside `apply`, never a module-level handle. */
function createBalanceStore() {
	return defineStore({
		init: () => ({ selected: null }),
		actions: { select: (draft, provider) => {
			draft.selected = provider;
		} }
	});
}
/**
* The session-header chip (#871's final home): account status is app chrome,
* not decision data and not its own tab. The pill headlines ONE provider —
* the pinned one (registration store) or the first configured row — and the
* panel lists every provider; clicking a row pins it as the headline, which
* reads as "the balance of whichever service I'm actually burning". Same
* contracts: [data-balance-state], [data-pb-provider], [data-pb-role],
* [data-refresh], no emoji.
*/
/**
* The per-provider detail under its headline: quota providers get one line
* per window — label / remaining / reset right-aligned — so the 5h and week
* resets scan as a column instead of drowning in a sentence. Money rows keep
* their granted/topped-up split. A note does NOT suppress this detail when
* readable windows exist (kcn 反馈 #908: 变色只改颜色,绝不动信息量)——
* the watermark/stale caption rides along; only data-less abnormal rows
* (unconfigured / fetch-failed) speak through the note alone.
*/
function renderRowDetail(row) {
	const wins = row.result.snapshot?.windows ?? [];
	if (wins.length > 0) return h("div", { className: cx("bp-wins") }, wins.map((w) => {
		const pct = w.percent === null ? null : Math.max(0, Math.min(100, Math.round(w.percent)));
		const state = row.view.tone === "stale" ? "stale" : _usedLevel(pct, row.result.threshold);
		return h("div", {
			className: cx("bp-win"),
			key: w.label
		}, h("div", { className: cx("bp-win-line") }, h("span", { className: cx("bp-win-label") }, w.label), h("span", { className: cx("bp-win-pct") }, w.percent === null ? "—" : Math.round(w.percent) + "%"), h("span", { className: cx("bp-win-reset") }, w.resetAt === "" ? "" : "↻ " + w.resetAt)), h("div", { className: cx("bp-win-bar") }, h("div", {
			className: cx("bp-win-fill"),
			style: pct === null ? { width: "0%" } : { width: pct + "%" },
			"data-balance-state": state
		})));
	}));
	if (row.note !== null) return null;
	const title = row.view.title;
	if (title === "") return null;
	const body = title.startsWith("API 余额 · ") ? title.slice(9) : title;
	return h("div", { className: cx("bp-sub") }, body);
}
function ProviderBalanceChip(props) {
	const mountedRef = useRef(true);
	const [data, setData] = useState(() => ({
		result: props.cachedBalances(),
		loading: false
	}));
	const selected = props.useStore((state) => state.selected);
	const select = (provider) => {
		props.actions.select(provider);
	};
	const [open, setOpen] = useState(false);
	const [flash, setFlash] = useState(null);
	const flashTimerRef = useRef(null);
	const rootRef = useRef(null);
	const runBalances = (force) => {
		props.fetchBalances(force).then((result) => {
			if (!mountedRef.current) return;
			setData({
				result,
				loading: false
			});
			if (force) {
				setFlash(result.providers.some((p) => p.result.status === "fresh") ? "ok" : "same");
				if (flashTimerRef.current !== null) clearTimeout(flashTimerRef.current);
				flashTimerRef.current = setTimeout(() => {
					setFlash(null);
				}, 1200);
			}
		}, () => {
			if (mountedRef.current) setData((current) => ({
				...current,
				loading: false
			}));
		});
	};
	useEffect(() => {
		mountedRef.current = true;
		runBalances(false);
		return () => {
			mountedRef.current = false;
			if (flashTimerRef.current !== null) clearTimeout(flashTimerRef.current);
		};
	}, [props.sessionId]);
	useEffect(() => {
		const intervalMs = Math.max(6e4, data.result?.refreshMs ?? 6e4);
		const timer = setInterval(() => {
			runBalances(false);
		}, intervalMs);
		return () => clearInterval(timer);
	}, [data.result?.refreshMs, props.sessionId]);
	useEffect(() => {
		if (!open || typeof document === "undefined") return void 0;
		const onKey = (event) => {
			if (event.key === "Escape") setOpen(false);
		};
		const onDown = (event) => {
			const root = rootRef.current;
			if (root !== null && event.target instanceof Node && !root.contains(event.target)) setOpen(false);
		};
		document.addEventListener("keydown", onKey);
		document.addEventListener("mousedown", onDown);
		return () => {
			document.removeEventListener("keydown", onKey);
			document.removeEventListener("mousedown", onDown);
		};
	}, [open]);
	const rows = (data.result?.providers ?? []).map((provider) => ({
		...provider,
		view: _rowDisplay(provider.result),
		note: _balanceNote(provider.result)
	}));
	const primary = rows.find((row) => row.provider === selected) ?? rows[0];
	const refresh = () => {
		setData((current) => ({
			...current,
			loading: true
		}));
		runBalances(true);
	};
	return h("span", {
		className: cx("pbc"),
		ref: rootRef
	}, h("button", {
		type: "button",
		className: cx("bchip"),
		"data-balance-state": primary !== void 0 ? primary.view.tone : "none",
		"data-pb-provider": primary !== void 0 ? primary.provider : "",
		"aria-expanded": open,
		"aria-haspopup": "dialog",
		"aria-label": "各模型服务余额",
		title: primary !== void 0 ? primary.label + " · " + primary.view.title + (rows.length > 1 ? "(点击查看其他服务)" : "") : "余额加载中",
		onClick: () => {
			setOpen(!open);
		}
	}, primary === void 0 ? h("span", { className: cx("bchip-item") }, h("span", { className: cx("bchip-dot") }), "—") : h("span", {
		className: cx("bchip-item"),
		"data-pb-provider": primary.provider,
		"data-pb-role": "chip",
		"data-balance-state": primary.view.tone
	}, h("span", { className: cx("bchip-dot") }), h("span", {
		className: cx("bchip-v"),
		"data-balance-state": primary.view.tone,
		"data-used-level": primary.view.level === null ? void 0 : primary.view.level
	}, primary.view.value), primary.view.reset === null ? null : h("span", { className: cx("bchip-reset") }, "↻ " + primary.view.reset), primary.view.sub === null ? null : h("span", {
		className: cx("bchip-sub"),
		"aria-hidden": "true"
	}, primary.view.sub))), h("div", {
		className: cx("bp"),
		"data-open": open ? "true" : "false",
		role: open ? "dialog" : "none",
		"aria-label": "各模型服务余额"
	}, h("div", { className: cx("bp-head") }, h("span", { className: cx("bp-title") }, "API 余额"), h("button", {
		type: "button",
		className: cx("bal-rf", data.loading && "spin", flash === "ok" && "flash-ok", flash === "same" && "flash-same"),
		"data-refresh": "true",
		"aria-label": "刷新全部余额",
		title: "立即刷新",
		onClick: refresh
	}, flash === "ok" ? "✓" : "↻")), rows.length === 0 ? h("div", { className: cx("bp-empty") }, "正在读取各服务余额…") : rows.map((row) => h("button", {
		type: "button",
		key: row.provider,
		className: cx("bp-row"),
		"data-pb-provider": row.provider,
		"data-pb-role": "panel",
		"aria-pressed": row.provider === (primary !== void 0 ? primary.provider : ""),
		onClick: () => {
			select(row.provider);
		}
	}, h("span", {
		className: cx("bp-dot"),
		"data-balance-state": row.view.tone
	}), h("span", { className: cx("bp-label") }, row.label, row.provider === (primary !== void 0 ? primary.provider : "") ? h("span", { className: cx("bp-pin") }) : null), h("span", {
		className: cx("bp-v", row.view.tone === "low" ? "bad" : ""),
		"data-balance-state": row.view.tone
	}, row.view.value), [row.note !== null ? h("div", {
		className: cx("bp-note", row.view.tone === "stale" ? "warn" : "bad"),
		key: "note"
	}, row.note) : null, renderRowDetail(row)]))));
}
function DecisionMind(props) {
	const filter = props.useStore((state) => state.filter);
	const open = props.useStore((state) => state.open);
	const visibleDateCount = props.useStore((state) => state.visibleDateCount);
	const foldedDates = props.useStore((state) => state.foldedDates);
	const scrollTop = props.useStore((state) => state.scrollTop);
	const actions = props.actions;
	const rootRef = useRef(null);
	const [data, setData] = useState(() => {
		const cached = props.cachedTraces();
		return cached === null ? {
			trades: [],
			rate: null,
			loading: true,
			error: null,
			stale: false
		} : {
			trades: cached.trades,
			rate: cached.rate,
			loading: false,
			error: null,
			stale: false
		};
	});
	useEffect(() => {
		let alive = true;
		props.fetchTraces().then((fetched) => {
			if (!alive || !fetched.changed) return;
			setData({
				trades: fetched.snapshot.trades,
				rate: fetched.snapshot.rate,
				loading: false,
				error: null,
				stale: false
			});
		}, (error) => {
			if (!alive) return;
			if (props.cachedTraces() !== null) setData((current) => ({
				...current,
				stale: true
			}));
			else setData({
				trades: [],
				rate: null,
				loading: false,
				error: messageOf(error),
				stale: false
			});
		});
		return () => {
			alive = false;
		};
	}, [props.sessionId]);
	useEffect(() => {
		if (data.loading) return;
		const root = rootRef.current;
		if (root === null) return;
		let scroller = root;
		while (scroller.parentElement !== null && scroller.scrollHeight <= scroller.clientHeight + 1) scroller = scroller.parentElement;
		if (scrollTop > 0 && scroller.scrollHeight > scroller.clientHeight + 1) scroller.scrollTop = scrollTop;
		const onScroll = () => {
			actions.setScrollTop(scroller.scrollTop);
		};
		scroller.addEventListener("scroll", onScroll, { passive: true });
		return () => {
			scroller.removeEventListener("scroll", onScroll);
		};
	}, [data.loading]);
	if (data.error !== null) return h("div", {
		className: cx("dmt"),
		ref: rootRef
	}, h("div", { className: cx("empty") }, "Decision Mind: " + data.error));
	if (data.loading) return h("div", {
		className: cx("dmt"),
		ref: rootRef
	}, h("div", { className: cx("top") }, h("div", { className: cx("tin") }, h("div", { className: cx("tt") }, "决策轨迹", h("span", { className: cx("ts") }, "一笔真实成交 + 当时写下的计划 + 官方收盘给的结果")))), h("div", { className: cx("list") }, h(SkeletonRow, { key: "sk1" }), h(SkeletonRow, { key: "sk2" }), h(SkeletonRow, { key: "sk3" })));
	const traces = data.trades.map(_displayEntry);
	let filtered = traces;
	if (filter === "miss") filtered = traces.filter((trace) => trace.decision === null);
	if (filter === "sold") filtered = traces.filter((trace) => trace.side === "reduce");
	if (filter === "dec") filtered = traces.filter((trace) => trace.decision !== null);
	const sumRealized = (currency) => traces.filter((trace) => trace.realizedPnl !== null && trace.currency === currency).reduce((sum, trace) => sum + (trace.realizedPnl ?? 0), 0);
	const rate = data.rate;
	const hkdRealized = sumRealized("HKD");
	const totalUsd = sumRealized("USD") + (rate === null ? 0 : hkdRealized / rate);
	const totalLabel = rate === null && hkdRealized !== 0 ? "已实现 (USD 等值 · HKD 未折算)" : "已实现 (USD 等值)";
	const sells = traces.filter((trace) => trace.side === "reduce");
	const sideless = traces.filter((trace) => trace.side === null).length;
	const sellsRated = sells.filter((trace) => trace.t1 !== null).length;
	const soldEarly = sells.filter((trace) => trace.t1?.verdict === "卖飞").length;
	const soldRight = sells.filter((trace) => trace.t1?.verdict === "卖对").length;
	const matched = traces.filter((trace) => trace.decision !== null).length;
	const reversed = traces.filter((trace) => trace.decision?.alignment === "opposite").length;
	const groups = {};
	for (const trace of filtered) {
		const day = (trace.date ?? "").slice(0, 10);
		(groups[day] ??= []).push(trace);
	}
	const dates = Object.keys(groups).sort().reverse();
	const today = todayIso();
	const visibleDates = dates.slice(0, visibleDateCount);
	const moreFills = dates.slice(visibleDateCount, visibleDateCount + BATCH_GROUPS).reduce((sum, date) => sum + (groups[date]?.length ?? 0), 0);
	const renderDate = (date) => {
		const folded = foldedDates.indexOf(date) >= 0;
		const rows = groups[date] ?? [];
		return h("div", { key: date }, h("div", {
			className: cx("day", "fold"),
			"data-day": date,
			role: "button",
			tabIndex: 0,
			"aria-expanded": folded ? "false" : "true",
			onClick: () => {
				actions.toggleDate(date);
			},
			onKeyDown: (event) => {
				if (event.key === "Enter" || event.key === " ") {
					event.preventDefault();
					actions.toggleDate(date);
				}
			}
		}, h("span", { className: cx("chev") }, folded ? "▸" : "▾"), relativeDay(date, today), h("span", null, date), h("span", { className: cx("n") }, rows.length)), folded ? null : h("div", { className: cx("group") }, rows.map((trace, index) => {
			const key = trace.ticker + trace.date + trace.shares + ":" + index;
			return h(TraceCell, {
				key,
				trace,
				open: open === key,
				onToggle: () => {
					actions.toggleOpen(key);
				},
				onKeyDown: (event) => {
					if (event.key === "Enter" || event.key === " ") {
						event.preventDefault();
						actions.toggleOpen(key);
					}
				}
			});
		})));
	};
	let moreButton = null;
	if (visibleDates.length < dates.length) moreButton = h("button", {
		key: "more",
		className: cx("trace-more"),
		onClick: () => {
			actions.showMoreDates(BATCH_GROUPS);
		}
	}, "显示更早的 " + moreFills + " 笔成交");
	else if (visibleDateCount > DEFAULT_VISIBLE_DATES) moreButton = h("button", {
		key: "more",
		className: cx("trace-more"),
		onClick: () => {
			actions.resetDates();
		}
	}, "收起,只显示最近 3 组");
	let body;
	if (filtered.length === 0) body = h("div", { className: cx("empty") }, "没有符合条件的成交");
	else {
		const kids = visibleDates.map(renderDate);
		if (moreButton !== null) kids.push(moreButton);
		body = h("div", null, kids);
	}
	const stats = h("div", { className: cx("stats") }, h("div", { className: cx("sg") }, h("span", { className: cx("sl") }, totalLabel), h("span", { className: cx("sv", "focus", totalUsd >= 0 ? "up" : "down") }, fmtMoney(totalUsd))), h("div", { className: cx("sg") }, h("span", { className: cx("sl") }, "T+1 卖飞/卖对 · 判出 " + sellsRated + "/" + sells.length + " 笔卖出" + (sideless === 0 ? "" : " · " + sideless + " 笔无侧向")), h("span", { className: cx("sv") }, h("span", { className: cx("down") }, soldEarly), " / ", h("span", { className: cx("up") }, soldRight))), h("div", { className: cx("sg") }, h("span", { className: cx("sl") }, "有当日计划" + (reversed === 0 ? "" : " · 反向 " + reversed)), h("span", { className: cx("sv") }, matched + "/" + traces.length)));
	const filters = h("div", { className: cx("filters") }, [
		"all",
		"miss",
		"sold",
		"dec"
	].map((value) => h("button", {
		key: value,
		className: cx("ft", filter === value && "on"),
		"aria-pressed": filter === value,
		onClick: () => {
			actions.setFilter(value);
		}
	}, FILTER_LABEL[value])));
	return h("div", {
		className: cx("dmt"),
		ref: rootRef
	}, h("div", { className: cx("top") }, h("div", { className: cx("tin") }, h("div", { className: cx("tt") }, "决策轨迹", h("span", { className: cx("ts") }, "一笔真实成交 + 当时写下的计划 + 官方收盘给的结果" + (data.stale ? " · 更新失败,显示此前快照" : "")), h("span", { className: cx("rate") }, traces.length + " 笔成交" + (rate === null ? "" : " · @" + rate))), stats)), h("div", { className: cx("bar") }, h("div", { className: cx("bin") }, filters)), h("div", { className: cx("list") }, body));
}
/** Services required by the registration and the mounted Remote face. */
const inject = ["slots", "remote"];
/** Register the Decision Mind tab into the conversation view ring. */
async function apply(ctx) {
	await ctx.remote.$mount(TYPERT_REMOTE);
	const studioRemote = ctx.get("remote.clawockStudio");
	let cached = null;
	let cachedBalances = null;
	const call = async (method, args = []) => {
		const result = await studioRemote[method](...args);
		if (!result.ok) throw new Error("clawockStudio." + method + " failed: " + result.error.code + ": " + result.error.message);
		return result.value;
	};
	const injected = () => ({
		cachedTraces: () => cached,
		fetchTraces: async () => {
			const result = await call("traces");
			const snapshot = {
				workspaceKey: result.workspaceKey,
				signature: result.signature,
				trades: result.trades,
				rate: result.rate
			};
			const changed = cached === null || cached.workspaceKey !== snapshot.workspaceKey || cached.signature !== snapshot.signature;
			cached = snapshot;
			return {
				snapshot,
				changed
			};
		}
	});
	const balancesInjected = () => ({
		cachedBalances: () => cachedBalances,
		fetchBalances: async (force) => {
			const result = await call("balance", [force]);
			cachedBalances = result;
			return result;
		}
	});
	const store = createDecisionMindStore();
	ctx.slots.inject("conversation.view", () => ctx.slots.register({
		name: "conversation.view",
		id: "decision-studio",
		order: 30,
		label: () => "Decision Mind",
		store,
		inject: injected
	}, DecisionMind));
	const balancesStore = createBalanceStore();
	ctx.slots.inject("conversation.session.header.utilities", () => ctx.slots.register({
		name: "conversation.session.header.utilities",
		id: "provider-balance",
		order: 90,
		store: balancesStore,
		inject: balancesInjected
	}, ProviderBalanceChip));
}
//#endregion

    Object.assign(exports, { DecisionMind, ProviderBalanceChip, _balanceNote, _displayEntry, _rowDisplay, _usedLevel, apply, createBalanceStore, createDecisionMindStore, inject, t1ChipClass, t1NodeClass });
    return module.exports;
  }
});
