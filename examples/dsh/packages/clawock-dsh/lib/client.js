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
var Cached = class {
	constructor(getter) {
		this._getter = getter;
		this._value = void 0;
	}
	get value() {
		const getter = this._getter;
		if (getter !== void 0) {
			this._value = getter();
			this._getter = void 0;
		}
		return this._value;
	}
};
function cached(getter) {
	return new Cached(getter);
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
/**
* Whichever object a def's `shape` currently answers from: the one the caller passed until the first read, the frozen copy after it.
*
* Its keys and descriptors read without invoking anything, which is what lets a discriminated union check its discriminator, and the cycle walk read a shape, without resolving a getter that references the schema being constructed. A def that answers `shape` from an accessor of its own has none.
*/
function rawShape(def) {
	const desc = Object.getOwnPropertyDescriptor(def, "shape");
	return desc?.get ? desc.get.raw : desc?.value;
}
function sourceShape(schema) {
	return rawShape(schema._zod.def) ?? schema._zod.def.shape;
}
function deferProp(target, key, getter) {
	Object.defineProperty(target, key, {
		get() {
			const value = getter();
			assignProp(this, key, value);
			return value;
		},
		enumerable: true,
		configurable: true
	});
}
function putProp(target, key, value) {
	if (key in target) assignProp(target, key, value);
	else target[key] = value;
}
/**
* Copies `keys` of `source`'s shape onto `target`, each value passed through `wrap`.
*
* A key the source has resolved is copied through now, so the derived shape states it outright and nothing has to resolve it to learn what it holds. A key the source still defers stays deferred, and reads back through the source's own `shape`, so it resolves once and both shapes get that one schema.
*/
function mirrorShape(target, source, keys, wrap) {
	const raw = sourceShape(source);
	for (const key of keys) {
		const desc = Object.getOwnPropertyDescriptor(raw, key);
		if (!desc.enumerable) continue;
		if (desc.get) deferProp(target, key, () => {
			const value = source._zod.def.shape[key];
			return wrap ? wrap(value, key) : value;
		});
		else putProp(target, key, wrap ? wrap(desc.value, key) : desc.value);
	}
}
function mirrorProps(target, source) {
	for (const key of Reflect.ownKeys(source)) {
		const desc = Object.getOwnPropertyDescriptor(source, key);
		if (!desc.enumerable) continue;
		if (desc.get) deferProp(target, key, () => source[key]);
		else putProp(target, key, desc.value);
	}
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
const BIGINT_FORMAT_RANGES = {
	int64: [/* @__PURE__*/ BigInt("-9223372036854775808"), /* @__PURE__*/ BigInt("9223372036854775807")],
	uint64: [/* @__PURE__*/ BigInt(0), /* @__PURE__*/ BigInt("18446744073709551615")]
};
function pick(schema, mask) {
	const currDef = schema._zod.def;
	const checks = currDef.checks;
	if (checks && checks.length > 0) throw new Error(".pick() cannot be used on object schemas containing refinements");
	const newShape = {};
	mirrorShape(newShape, schema, maskedKeys(schema, mask));
	return clone(schema, mergeDefs(currDef, {
		shape: newShape,
		checks: []
	}));
}
function maskedKeys(schema, mask) {
	const raw = sourceShape(schema);
	const keys = [];
	for (const key of Reflect.ownKeys(mask)) {
		if (!Object.getOwnPropertyDescriptor(raw, key)?.enumerable) throw new Error(`Unrecognized key: "${String(key)}"`);
		if (mask[key]) keys.push(key);
	}
	return keys;
}
function omit(schema, mask) {
	const currDef = schema._zod.def;
	const checks = currDef.checks;
	if (checks && checks.length > 0) throw new Error(".omit() cannot be used on object schemas containing refinements");
	const omitted = new Set(maskedKeys(schema, mask));
	const newShape = {};
	mirrorShape(newShape, schema, Reflect.ownKeys(sourceShape(schema)).filter((key) => !omitted.has(key)));
	return clone(schema, mergeDefs(currDef, {
		shape: newShape,
		checks: []
	}));
}
function extend(schema, shape) {
	if (!isPlainObject(shape)) throw new Error("Invalid input to extend: expected a plain object");
	const checks = schema._zod.def.checks;
	if (checks && checks.length > 0) {
		const existingShape = sourceShape(schema);
		for (const key of Reflect.ownKeys(shape)) if (Object.getOwnPropertyDescriptor(existingShape, key) !== void 0) throw new Error("Cannot overwrite keys on object schemas containing refinements. Use `.safeExtend()` instead.");
	}
	return clone(schema, mergeDefs(schema._zod.def, { shape: extended(schema, shape) }));
}
function extended(schema, shape) {
	const newShape = {};
	mirrorShape(newShape, schema, Reflect.ownKeys(sourceShape(schema)));
	mirrorProps(newShape, shape);
	return newShape;
}
function safeExtend(schema, shape) {
	if (!isPlainObject(shape)) throw new Error("Invalid input to safeExtend: expected a plain object");
	return clone(schema, mergeDefs(schema._zod.def, { shape: extended(schema, shape) }));
}
function merge(a, b) {
	if (!b?._zod?.def) throw new Error("Invalid input to merge: expected an object schema. To merge a plain shape, use `.extend()`.");
	if (a._zod.def.checks?.length) throw new Error(".merge() cannot be used on object schemas containing refinements. Use .safeExtend() instead.");
	const newShape = {};
	mirrorShape(newShape, a, Reflect.ownKeys(sourceShape(a)));
	mirrorShape(newShape, b, Reflect.ownKeys(sourceShape(b)));
	return clone(a, mergeDefs(a._zod.def, {
		shape: newShape,
		get catchall() {
			return b._zod.def.catchall;
		},
		checks: b._zod.def.checks ?? []
	}));
}
function partial(Class, schema, mask, name = "partial") {
	const checks = schema._zod.def.checks;
	if (checks && checks.length > 0) throw new Error(`.${name}() cannot be used on object schemas containing refinements`);
	const selected = mask ? new Set(maskedKeys(schema, mask)) : void 0;
	const newShape = {};
	mirrorShape(newShape, schema, Reflect.ownKeys(sourceShape(schema)), Class && ((value, key) => selected && !selected.has(key) ? value : new Class({
		type: "optional",
		innerType: value
	})));
	return clone(schema, mergeDefs(schema._zod.def, {
		shape: newShape,
		checks: []
	}));
}
function required(Class, schema, mask) {
	const selected = mask ? new Set(maskedKeys(schema, mask)) : void 0;
	const newShape = {};
	mirrorShape(newShape, schema, Reflect.ownKeys(sourceShape(schema)), (value, key) => selected && !selected.has(key) ? value : new Class({
		type: "nonoptional",
		innerType: value
	}));
	return clone(schema, mergeDefs(schema._zod.def, { shape: newShape }));
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
	const full = {};
	for (const k of Object.keys(iss)) {
		if (k === "inst" || k === "schema" || k === "continue" || k === "input" || k === "__proto__") continue;
		full[k] = iss[k];
	}
	full.path ?? (full.path = []);
	full.message = message;
	if (ctx?.reportInput) full.input = iss.input;
	return full;
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
/** Adds members a table derives from the instance: each builds on first read and shadows as own data, and assignment shadows the same way, as when these were own properties. */
function derived(computes, table) {
	for (const key in computes) {
		const compute = computes[key];
		Object.defineProperty(table, key, {
			configurable: true,
			enumerable: true,
			get() {
				return own(this, key, compute(this));
			},
			set(value) {
				own(this, key, value);
			}
		});
	}
	return table;
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
const _zodDesc = {
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
			_zodDesc.value = new Internals(def);
			try {
				Object.defineProperty(inst, "_zod", _zodDesc);
			} finally {
				_zodDesc.value = void 0;
			}
		} else if (inst._zod.traits.has(name)) return;
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
const _issuesDesc = {
	value: void 0,
	enumerable: false
};
const _installedToString = /* @__PURE__ */ new WeakSet([Object.prototype, Error.prototype]);
const initializer$1 = (inst, def) => {
	inst.name = "$ZodError";
	_issuesDesc.value = def;
	Object.defineProperty(inst, "issues", _issuesDesc);
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
$constructor("$ZodError", initializer$1, void 0, { Parent: Error });
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
	return result.issues.length ? failure(_Err, result.issues, ctx) : {
		success: true,
		data: result.value
	};
};
function failure(Err, issues, ctx) {
	let error;
	return {
		success: false,
		get error() {
			if (!error) {
				error = new Err(issues.map((iss) => finalizeIssue(iss, ctx, config())));
				issues = void 0;
				ctx = void 0;
			}
			return error;
		},
		set error(e) {
			error = e;
			issues = void 0;
			ctx = void 0;
		}
	};
}
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
	return result.issues.length ? failure(_Err, result.issues, ctx) : {
		success: true,
		data: result.value
	};
};
const COMPILE_INVALID = /* @__PURE__ */ Symbol.for("zod.compile.invalid");
const COMPILE_FALLBACK = /* @__PURE__ */ Symbol.for("zod.compile.fallback");
const validate = ((schema, value, _ctx) => {
	const validator = schema._zod.bag.validator;
	if (validator !== void 0) {
		if (validator(value) !== COMPILE_INVALID) return true;
		if (validator.definite === true && _ctx === void 0) return false;
	}
	return validateFallback(schema, value, _ctx);
});
function validateFallback(schema, value, _ctx) {
	const ctx = _ctx ? {
		..._ctx,
		async: false,
		abortEarly: true
	} : {
		async: false,
		abortEarly: true
	};
	const fallbackRun = schema._zod.bag.fallbackRun;
	let result;
	if (fallbackRun) {
		ctx[COMPILE_FALLBACK] = true;
		result = fallbackRun({
			value,
			issues: []
		}, ctx);
	} else result = schema._zod.run({
		value,
		issues: []
	}, ctx);
	if (result instanceof Promise) throw new $ZodAsyncError();
	return result.issues.length === 0;
}
const validateAsync$1 = async (schema, value, _ctx) => {
	const ctx = _ctx ? {
		..._ctx,
		async: true,
		abortEarly: true
	} : {
		async: true,
		abortEarly: true
	};
	let result = schema._zod.run({
		value,
		issues: []
	}, ctx);
	if (result instanceof Promise) result = await result;
	return result.issues.length === 0;
};
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
const email = /^(?:[A-Za-z0-9_'+\-]+\.)*[A-Za-z0-9_'+\-]*[A-Za-z0-9_+-]@(?:[A-Za-z0-9][A-Za-z0-9\-]*\.)+[A-Za-z]{2,}$/;
const _emoji$1 = `^(?=[\\s\\S]*[\\p{Extended_Pictographic}\\p{Regional_Indicator}\\u20E3])[\\p{Extended_Pictographic}\\p{Emoji_Component}]+$`;
function emoji() {
	return new RegExp(_emoji$1, "u");
}
const ipv4 = /^(?:(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])\.){3}(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])$/;
const ipv6 = /^(([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,7}:|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|:((:[0-9a-fA-F]{1,4}){1,7}|:))$/;
const cidrv4 = /^((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])\.){3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])\/([0-9]|[1-2][0-9]|3[0-2])$/;
const cidrv6 = /^(([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,7}:|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|:((:[0-9a-fA-F]{1,4}){1,7}|:))\/(12[0-8]|1[01][0-9]|[1-9]?[0-9])$/;
const base64 = /^$|^(?:[0-9a-zA-Z+/]{4})*(?:(?:[0-9a-zA-Z+/]{2}==)|(?:[0-9a-zA-Z+/]{3}=))?$/;
const base64url = /^(?:[A-Za-z0-9_-]{4})*(?:[A-Za-z0-9_-]{2,3})?$/;
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
const anyString = /^[\s\S]{0,}$/;
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
	def.pattern = new RegExp(typeof def.position === "number" ? `^.{${def.position},}${escapedRegex}` : escapedRegex);
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
		try {
			fn(this);
		} finally {
			this.indent -= 1;
		}
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
	minor: 6,
	patch: 5
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
const toStandardResult = (r, ctx) => r.issues.length ? { issues: r.issues.map((iss) => finalizeIssue(iss, ctx, config())) } : { value: r.value };
async function validateAsync(inst, value) {
	const ctx = { async: true };
	return toStandardResult(await inst._zod.run({
		value,
		issues: []
	}, ctx), ctx);
}
function standardProps(inst) {
	return {
		validate: (value) => {
			const ctx = { async: false };
			try {
				const r = inst._zod.run({
					value,
					issues: []
				}, ctx);
				if (!(r instanceof Promise)) return toStandardResult(r, ctx);
			} catch (_) {}
			return validateAsync(inst, value);
		},
		vendor: "zod",
		version: 1
	};
}
const $ZodString = /*@__PURE__*/ $constructor("$ZodString", (inst, def) => {
	$ZodType.init(inst, def);
	inst._zod.pattern = def.pattern ?? anyString;
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
function canParseURL(input) {
	try {
		if (typeof URL !== "undefined" && typeof URL.canParse === "function") return URL.canParse(input);
		new URL(input);
		return true;
	} catch {
		return false;
	}
}
function validateURL(trimmed, def) {
	if (!("normalize" in def) && !("hostname" in def) && !("protocol" in def)) return canParseURL(trimmed) || 2;
	return parseURLObject(trimmed, def);
}
/** Parses a URL while preserving the non-normalizing HTTP guard. */
function parseURLObject(trimmed, def) {
	if (!def.normalize && def.protocol?.source === httpProtocol.source && !/^https?:\/\//i.test(trimmed)) return 1;
	try {
		if (typeof URL !== "undefined") {
			const URLStatic = URL;
			if (typeof URLStatic.parse === "function") return URLStatic.parse(trimmed) ?? 2;
		}
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
			const url = validateURL(trimmed, def);
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
			if (url === true) {
				payload.value = stripTabAndNewline(trimmed);
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
});
/** An IPv6 address is written with hex digits, colons and dots, and nothing else. The guard is what makes the check below an IPv6 check: `new URL("http://[...]")` parses an authority, not an address, so `@` and `\` re-delimit it and `"::@1\\"` validates against the host `0.0.0.1`. The URL parser also deletes ASCII tab, LF and CR rather than failing, which is how `"::1\n"` validated as `::1`. */
const ipv6Alphabet = /^[0-9a-fA-F:.]+$/;
function isValidIPv6(value) {
	if (!ipv6Alphabet.test(value)) return false;
	return canParseURL(`http://[${value}]`);
}
const $ZodIPv6 = /*@__PURE__*/ $constructor("$ZodIPv6", (inst, def) => {
	def.pattern ?? (def.pattern = ipv6);
	$ZodStringFormat.init(inst, def);
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
const base64Charset = /^[0-9a-zA-Z+/]*={0,2}$/;
const $ZodBase64 = /*@__PURE__*/ $constructor("$ZodBase64", (inst, def) => {
	def.pattern ?? (def.pattern = base64Charset);
	$ZodStringFormat.init(inst, def);
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
const base64urlCharset = /^[A-Za-z0-9_-]*$/;
function isValidBase64URL(data) {
	if (!base64urlCharset.test(data)) return false;
	const base64 = data.replace(/[-_]/g, (c) => c === "-" ? "+" : "/");
	return isValidBase64(base64.padEnd(Math.ceil(base64.length / 4) * 4, "="));
}
const $ZodBase64URL = /*@__PURE__*/ $constructor("$ZodBase64URL", (inst, def) => {
	def.pattern ?? (def.pattern = base64urlCharset);
	$ZodStringFormat.init(inst, def);
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
	inst._zod.pattern = number$1;
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
		const abortEarly = ctx?.abortEarly;
		for (let i = 0; i < input.length; i++) {
			const item = input[i];
			const result = def.element._zod.run({
				value: item,
				issues: []
			}, ctx);
			if (result instanceof Promise) proms.push(result.then((result) => handleArrayResult(result, payload, i)));
			else {
				handleArrayResult(result, payload, i);
				if (abortEarly && result.issues.length !== 0 && aborted(result)) break;
			}
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
		if (isPresent || optin === "defaulted" && !isOptionalOut) final.value[key] = void 0;
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
function handleCatchall(proms, input, payload, ctx, def, inst, abortEarly) {
	const unrecognized = [];
	const keySet = def.keySet;
	const _catchall = def.catchall._zod;
	const t = _catchall.def.type;
	const optin = _catchall.optin;
	const optout = _catchall.optout;
	let seen = 0;
	for (const key in input) {
		if (abortEarly && payload.issues.length !== seen) {
			if (aborted(payload, seen)) break;
			seen = payload.issues.length;
		}
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
const $ZodObject = /*@__PURE__*/ $constructor("$ZodObject", (inst, def) => {
	$ZodType.init(inst, def);
	const desc = Object.getOwnPropertyDescriptor(def, "shape");
	const sh = desc?.get ? desc.get.raw : def.shape ?? {};
	if (sh) {
		const get = () => {
			const newSh = { ...sh };
			Object.defineProperty(def, "shape", { value: newSh });
			get.raw = newSh;
			return newSh;
		};
		get.raw = sh;
		Object.defineProperty(def, "shape", { get });
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
	const isObject$2 = isObject;
	const catchall = def.catchall;
	let value;
	const memo = globalConfig.memoizer;
	memo?.attach(inst);
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
		payload.value = memo ? memo.alloc(inst, payload, {}, ctx) : {};
		const proms = [];
		const shape = value.shape;
		const abortEarly = ctx?.abortEarly;
		let seen = payload.issues.length;
		for (const key of value.allKeys) {
			if (abortEarly && payload.issues.length !== seen) {
				if (aborted(payload, seen)) break;
				seen = payload.issues.length;
			}
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
		return handleCatchall(proms, input, payload, ctx, _normalized.value, inst, abortEarly === true);
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
          let ${id}_ab = false;
          for (let i = 0; i < ${id}.issues.length; i++) {
            const iss = ${id}.issues[i];
            iss.path = iss.path ? [${k}, ...iss.path] : [${k}];
            payload.issues.push(iss);
            if (iss.continue !== true) ${id}_ab = true;
          }
          if (${id}_ab && ctx && ctx.abortEarly) {
            payload.value = newResult;
            return payload;
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
          if (ctx && ctx.abortEarly) {
            payload.value = newResult;
            return payload;
          }
        }

        if (${id}_present) {
          newResult[${k}] = ${id}.value;
        }

      `);
			else {
				doc.write(`
        if (${id}.issues.length) {${prefixStr(id, k)}
        }
      `);
				if (optin === "defaulted") doc.write(`newResult[${k}] = ${id}.value;`);
				else doc.write(`
        if (${id}.value !== undefined || ${isPresent}) {
          newResult[${k}] = ${id}.value;
        }
      `);
			}
		}
		doc.write(`payload.value = newResult;`);
		doc.write(`return payload;`);
		return doc.compile();
	};
	let fastpass;
	const isObject$1 = isObject;
	const jit = !globalConfig.jitless;
	const fastEnabled = jit && allowsEval.value;
	const catchall = def.catchall;
	let value;
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
		if (jit && fastEnabled && ctx?.async === false && ctx.jitless !== true) {
			if (!fastpass) fastpass = generateFastpass(def.shape);
			payload = fastpass(payload, ctx);
			if (!catchall) return payload;
			return handleCatchall([], input, payload, ctx, value, inst, ctx?.abortEarly === true);
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
	defineLazyInternal(inst, "pattern", (zod) => {
		const patternValues = getEnumValues(zod.def.entries).filter((k) => propertyKeyTypes.has(typeof k));
		return new RegExp(patternValues.length ? `^(${patternValues.map((o) => escapeRegex(o.toString())).join("|")})$` : "^[^\\s\\S]$");
	});
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
	defineLazyInternal(inst, "pattern", (zod) => {
		const vals = zod.def.values;
		return new RegExp(vals.length ? `^(${vals.map((o) => typeof o === "string" ? escapeRegex(o) : o ? escapeRegex(o.toString()) : String(o)).join("|")})$` : "^[^\\s\\S]$");
	});
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
function isRef(value) {
	return value !== null && typeof value === "object";
}
function cloneIssues(issues) {
	return issues.map((iss) => iss.path ? {
		...iss,
		path: iss.path.slice()
	} : { ...iss });
}
const recursive = /*@__PURE__*/ new WeakMap();
/** What the walk established, in order of certainty: ordered so the strongest answer among children wins. */
const NONE = 0;
const ASSUMED = 1;
const PROVEN = 2;
/** Whether this schema's subtree contains a cycle, so one parse can re-enter it. */
function isRecursive(inst, stack, resolve) {
	const cached = recursive.get(inst);
	if (cached !== void 0) return cached ? PROVEN : NONE;
	if (stack.has(inst)) return PROVEN;
	stack.add(inst);
	let result = NONE;
	const check = (child) => {
		if (result !== PROVEN && child?._zod) {
			const answer = isRecursive(child, stack, resolve);
			if (answer > result) result = answer;
		}
	};
	const shape = (sh, spread) => {
		let answer = NONE;
		for (const key of Reflect.ownKeys(sh)) {
			const desc = Object.getOwnPropertyDescriptor(sh, key);
			if (spread && !desc.enumerable) continue;
			const child = desc.get ? ASSUMED : desc.value?._zod ? isRecursive(desc.value, stack, resolve) : NONE;
			if (child > answer) answer = child;
		}
		return answer;
	};
	const merge = (answer) => {
		if (answer > result) result = answer;
	};
	const def = inst._zod.def;
	switch (def.type) {
		case "object": {
			const raw = rawShape(def);
			merge(raw ? shape(raw, true) : ASSUMED);
			check(def.catchall);
			break;
		}
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
		case "lazy": {
			const inner = def._cachedInner ?? (resolve ? inst._zod.innerType : void 0);
			merge(inner ? isRecursive(inner, stack, false) : ASSUMED);
			break;
		}
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
	return settle(inst, result);
}
/** An assumed answer must not outlive the resolution that settles it, so only a certain one is cached. */
function settle(inst, answer) {
	if (answer !== ASSUMED) recursive.set(inst, answer === PROVEN);
	return answer;
}
function bucketFor(state, inst) {
	let bucket = state.buckets.get(inst);
	if (!bucket) {
		bucket = /* @__PURE__ */ new WeakMap();
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
		let rechecked = false;
		let lastCtx;
		let lastBucket;
		(_a = inst._zod).deferred ?? (_a.deferred = []);
		inst._zod.deferred.push(() => {
			const base = inst._zod.parse;
			const wrapped = (payload, ctx) => {
				if (isRecursiveInst === void 0) {
					const walked = isRecursive(inst, /* @__PURE__ */ new Set(), false);
					if (walked === NONE) {
						inst._zod.parse = base;
						if (inst._zod.run === wrapped) inst._zod.run = base;
						return base(payload, ctx);
					}
					if (walked === PROVEN || rechecked) isRecursiveInst = true;
					else rechecked = true;
				}
				const input = payload.value;
				if (!isRef(input)) return base(payload, ctx);
				let state = ctx[STATE];
				if (!state) {
					state = {
						buckets: /* @__PURE__ */ new WeakMap(),
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
						state.backEdges ?? (state.backEdges = /* @__PURE__ */ new WeakSet());
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
	return backEdges !== void 0 && isRef(value) && backEdges.has(value);
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
		currency_code: "currency code",
		credit_card: "credit card number",
		iban: "IBAN",
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
function snapshotChecks(def) {
	if (def.checks) def.checks = [...def.checks];
	return def;
}
// @__NO_SIDE_EFFECTS__
function _string(Class, params) {
	return new Class(snapshotChecks({
		type: "string",
		...normalizeParams(params)
	}));
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
	return new Class(snapshotChecks({
		type: "number",
		checks: [],
		...normalizeParams(params)
	}));
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
function processSchema(schema, ctx, _params = {
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
			processSchema(parent, ctx, params);
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
			if (ctx.reused === "ref") extractToDef(entry);
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
	processSchema(schema, ctx);
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
	processSchema(schema, ctx);
	extractDefs(ctx, schema);
	return finalize(ctx, schema);
};
//#endregion
//#region node_modules/zod/v4/core/json-schema-processors.js
const narrowMin = (agg, key, value) => {
	if (agg[key] === void 0 || value > agg[key]) agg[key] = value;
};
const narrowMax = (agg, key, value) => {
	if (agg[key] === void 0 || value < agg[key]) agg[key] = value;
};
const narrowBoth = (agg, value) => {
	narrowMin(agg, "minimum", value);
	narrowMax(agg, "maximum", value);
};
const addDivisor = (agg, value) => {
	agg.multipleOf ?? (agg.multipleOf = []);
	if (!agg.multipleOf.includes(value)) agg.multipleOf.push(value);
};
const addPattern = (agg, pattern) => {
	agg.patterns ?? (agg.patterns = /* @__PURE__ */ new Set());
	agg.patterns.add(pattern);
};
const intersectMime = (agg, mime) => {
	agg.mime = agg.mime ? agg.mime.filter((m) => mime.includes(m)) : [...mime];
};
const setFormat = (agg, format) => {
	agg.format = format;
	if (format.includes("int")) agg.isInt = true;
};
const minContributor = (agg, def) => narrowMin(agg, "minimum", def.minimum);
const maxContributor = (agg, def) => narrowMax(agg, "maximum", def.maximum);
const formatContributor = (ranges) => (agg, def) => {
	setFormat(agg, def.format);
	const [minimum, maximum] = ranges[def.format];
	narrowMin(agg, "minimum", minimum);
	narrowMax(agg, "maximum", maximum);
};
const contributors = {
	greater_than: (agg, def) => narrowMin(agg, def.inclusive ? "minimum" : "exclusiveMinimum", def.value),
	less_than: (agg, def) => narrowMax(agg, def.inclusive ? "maximum" : "exclusiveMaximum", def.value),
	multiple_of: (agg, def) => addDivisor(agg, def.value),
	number_format: formatContributor(NUMBER_FORMAT_RANGES),
	bigint_format: formatContributor(BIGINT_FORMAT_RANGES),
	min_length: minContributor,
	max_length: maxContributor,
	length_equals: (agg, def) => narrowBoth(agg, def.length),
	min_size: minContributor,
	max_size: maxContributor,
	size_equals: (agg, def) => narrowBoth(agg, def.size),
	string_format: (agg, def) => {
		setFormat(agg, def.format);
		if (def.pattern) addPattern(agg, def.pattern);
		if (def.format === "base64" || def.format === "base64url") agg.contentEncoding = def.format;
		if (def.local || def.precision === -1) agg.laxFormat = true;
	},
	mime_type: (agg, def) => intersectMime(agg, def.mime)
};
function aggregateChecks(schema) {
	const agg = {};
	const def = schema._zod.def;
	const list = schema._zod.traits.has("$ZodCheck") ? [schema, ...def.checks ?? []] : def.checks ?? [];
	for (const ch of list) contributors[ch._zod.def.check]?.(agg, ch._zod.def);
	const bag = schema._zod.bag;
	if (bag.minimum !== void 0) narrowMin(agg, "minimum", bag.minimum);
	if (bag.exclusiveMinimum !== void 0) narrowMin(agg, "exclusiveMinimum", bag.exclusiveMinimum);
	if (bag.maximum !== void 0) narrowMax(agg, "maximum", bag.maximum);
	if (bag.exclusiveMaximum !== void 0) narrowMax(agg, "exclusiveMaximum", bag.exclusiveMaximum);
	if (bag.multipleOf !== void 0) addDivisor(agg, bag.multipleOf);
	if (bag.format !== void 0) {
		agg.format ?? (agg.format = bag.format);
		if (bag.format.includes("int")) agg.isInt = true;
	}
	if (bag.mime) intersectMime(agg, bag.mime);
	for (const pattern of bag.patterns ?? []) addPattern(agg, pattern);
	return agg;
}
const formatMap = {
	guid: "uuid",
	url: "uri",
	datetime: "date-time",
	json_string: "json-string",
	regex: ""
};
const exactPatterns = /* @__PURE__ */ new Map([[base64Charset, base64], [base64urlCharset, base64url]]);
const exactPattern = (p) => exactPatterns.get(p) ?? p;
const stringProcessor = (schema, ctx, _json, _params) => {
	const json = _json;
	json.type = "string";
	const { minimum, maximum, format, patterns, contentEncoding, laxFormat } = aggregateChecks(schema);
	if (typeof minimum === "number") json.minLength = minimum;
	if (typeof maximum === "number") json.maxLength = maximum;
	if (format) {
		json.format = formatMap[format] ?? format;
		if (json.format === "") delete json.format;
		if (format === "time" || laxFormat) delete json.format;
	}
	if (contentEncoding) json.contentEncoding = contentEncoding;
	if (patterns && patterns.size > 0) {
		const patternList = [...patterns].map(exactPattern);
		if (patternList.length === 1) json.pattern = patternList[0].source;
		else if (patternList.length > 1) json.allOf = [...patternList.map((regex) => ({
			...ctx.target === "draft-07" || ctx.target === "draft-04" || ctx.target === "openapi-3.0" ? { type: "string" } : {},
			pattern: regex.source
		}))];
	}
};
const numberProcessor = (schema, ctx, _json, params) => {
	const json = _json;
	const { minimum, maximum, multipleOf, exclusiveMaximum, exclusiveMinimum, isInt } = aggregateChecks(schema);
	json.type = isInt ? "integer" : "number";
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
	if (multipleOf) {
		const divisors = /* @__PURE__ */ new Set();
		for (const divisor of multipleOf) if (Number.isFinite(divisor) && divisor !== 0) divisors.add(Math.abs(divisor));
		else handleUnrepresentable(schema, ctx, json, params, `A multipleOf divisor of ${divisor} cannot be represented in JSON Schema`);
		const [first, ...rest] = divisors;
		if (first !== void 0) json.multipleOf = first;
		if (rest.length) json.allOf = [...json.allOf ?? [], ...rest.map((m) => ({ multipleOf: m }))];
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
	const { minimum, maximum } = aggregateChecks(schema);
	if (typeof minimum === "number") json.minItems = minimum;
	if (typeof maximum === "number") json.maxItems = maximum;
	json.type = "array";
	json.items = processSchema(def.element, ctx, {
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
	for (const key in shape) assignProp(json.properties, key, processSchema(shape[key], ctx, {
		...params,
		path: [
			...params.path,
			"properties",
			key
		]
	}));
	const requiredKeys = [];
	for (const key of Object.keys(shape)) {
		const field = def.shape[key];
		if (ctx.io === "input" ? inputOptin(field) === void 0 : field._zod.optout === void 0) requiredKeys.push(key);
	}
	if (requiredKeys.length > 0) json.required = requiredKeys;
	if (def.catchall?._zod.def.type === "never") json.additionalProperties = false;
	else if (!def.catchall) {
		if (ctx.io === "output") json.additionalProperties = false;
	} else if (def.catchall) json.additionalProperties = processSchema(def.catchall, ctx, {
		...params,
		path: [...params.path, "additionalProperties"]
	});
};
const unionProcessor = (schema, ctx, json, params) => {
	const def = schema._zod.def;
	const isExclusive = def.inclusive === false;
	const options = def.options.map((x, i) => processSchema(x, ctx, {
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
	const a = processSchema(def.left, ctx, {
		...params,
		path: [
			...params.path,
			"allOf",
			0
		]
	});
	const b = processSchema(def.right, ctx, {
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
	const patterns = aggregateChecks(keyType).patterns;
	if (def.mode === "loose" && patterns && patterns.size > 0) {
		const valueSchema = processSchema(def.valueType, ctx, {
			...params,
			path: [
				...params.path,
				"patternProperties",
				"*"
			]
		});
		json.patternProperties = {};
		for (const pattern of patterns) assignProp(json.patternProperties, exactPattern(pattern).source, valueSchema);
	} else {
		if (ctx.target === "draft-07" || ctx.target === "draft-2020-12") {
			json.propertyNames = processSchema(def.keyType, ctx, {
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
		json.additionalProperties = processSchema(def.valueType, ctx, {
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
	const inner = processSchema(def.innerType, ctx, params);
	const seen = ctx.seen.get(schema);
	if (ctx.target === "openapi-3.0") {
		seen.ref = def.innerType;
		json.nullable = true;
	} else json.anyOf = [inner, { type: "null" }];
};
const nonoptionalProcessor = (schema, ctx, _json, params) => {
	const def = schema._zod.def;
	processSchema(def.innerType, ctx, params);
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
	processSchema(def.innerType, ctx, params);
	const seen = ctx.seen.get(schema);
	seen.ref = def.innerType;
	const value = serializeDefaultValue(def.defaultValue, schema, ctx, json, params);
	if (value !== UNREPRESENTABLE_DEFAULT) json.default = value;
};
const prefaultProcessor = (schema, ctx, json, params) => {
	const def = schema._zod.def;
	processSchema(def.innerType, ctx, params);
	const seen = ctx.seen.get(schema);
	seen.ref = def.innerType;
	if (ctx.io !== "input") return;
	const value = serializeDefaultValue(def.defaultValue, schema, ctx, json, params);
	if (value !== UNREPRESENTABLE_DEFAULT) json._prefault = value;
};
const catchProcessor = (schema, ctx, json, params) => {
	const def = schema._zod.def;
	processSchema(def.innerType, ctx, params);
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
	processSchema(innerType, ctx, params);
	const seen = ctx.seen.get(schema);
	seen.ref = innerType;
};
const readonlyProcessor = (schema, ctx, json, params) => {
	const def = schema._zod.def;
	processSchema(def.innerType, ctx, params);
	const seen = ctx.seen.get(schema);
	seen.ref = def.innerType;
	json.readOnly = true;
};
const optionalProcessor = (schema, ctx, _json, params) => {
	const def = schema._zod.def;
	processSchema(def.innerType, ctx, params);
	const seen = ctx.seen.get(schema);
	seen.ref = def.innerType;
};
const lazyProcessor = (schema, ctx, _json, params) => {
	const innerType = schema._zod.innerType;
	processSchema(innerType, ctx, params);
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
	validate(data, params) {
		return validate(this, data, params);
	},
	validateAsync(data, params) {
		return validateAsync$1(this, data, params);
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
}, /*@__PURE__*/ derived({
	format: (inst) => aggregateChecks(inst).format ?? null,
	minLength: (inst) => aggregateChecks(inst).minimum ?? null,
	maxLength: (inst) => aggregateChecks(inst).maximum ?? null
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
}));
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
	inst.isFinite = true;
}, /*@__PURE__*/ derived({
	minValue: (inst) => {
		const { minimum, exclusiveMinimum } = aggregateChecks(inst);
		return Math.max(minimum ?? Number.NEGATIVE_INFINITY, exclusiveMinimum ?? Number.NEGATIVE_INFINITY);
	},
	maxValue: (inst) => {
		const { maximum, exclusiveMaximum } = aggregateChecks(inst);
		return Math.min(maximum ?? Number.POSITIVE_INFINITY, exclusiveMaximum ?? Number.POSITIVE_INFINITY);
	},
	isInt: (inst) => {
		const { isInt, multipleOf } = aggregateChecks(inst);
		return !!isInt || !!multipleOf?.some(Number.isSafeInteger);
	},
	format: (inst) => aggregateChecks(inst).format ?? null
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
}));
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
		return this.clone(mergeDefs(this._zod.def, { catchall }));
	},
	passthrough() {
		return this.clone(mergeDefs(this._zod.def, { catchall: unknown() }));
	},
	loose() {
		return this.clone(mergeDefs(this._zod.def, { catchall: unknown() }));
	},
	strict() {
		return this.clone(mergeDefs(this._zod.def, { catchall: never() }));
	},
	strip() {
		return this.clone(mergeDefs(this._zod.def, { catchall: void 0 }));
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
	inst.options = [...inst._zod.values];
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
					"resetAt": string(),
					"durationMins": union([number(), literal(null)]),
					"resetAtMs": union([number(), literal(null)])
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
const clawock_dsh_clawockStudio_queueAction_parameter_0$schema = string();
const clawock_dsh_clawockStudio_queueAction_parameter_1$schema = string();
const clawock_dsh_clawockStudio_queueAction_parameter_2$schema = string();
const clawock_dsh_clawockStudio_queueAction_result$schema = object({
	"ok": boolean(),
	"code": number(),
	"action": string(),
	"id": string(),
	"message": string(),
	"detail": string()
});
const clawock_dsh_clawockStudio_taskQueue_parameter_0$schema = boolean();
const clawock_dsh_clawockStudio_taskQueue_task$schema = object({
	"id": string(),
	"name": string(),
	"agent": string(),
	"model": string(),
	"state": string(),
	"waiting": string(),
	"slot": string(),
	"attempts": number(),
	"stalls": number().optional(),
	"outcome": string(),
	"startedAtMs": union([number(), literal(null)]),
	"updatedAtMs": union([number(), literal(null)]),
	"wakeAtMs": union([number(), literal(null)]),
	"patrol": boolean(),
	"summary": string(),
	"lastEvent": string(),
	"lastEventAtMs": union([number(), literal(null)]),
	"queuedAtMs": union([number(), literal(null)]).optional(),
	"waitMs": union([number(), literal(null)]).optional(),
	"position": union([number(), literal(null)]).optional(),
	"priority": number().optional(),
	"protected": boolean().optional(),
	"modelRequested": string().optional(),
	"modelUsed": string().optional(),
	"effortRequested": string().optional(),
	"effortUsed": string().optional(),
	"notify": array(string()).optional(),
	"notified": array(string()).optional(),
	"notifyFailed": array(string()).optional(),
	"notifyAtMs": union([number(), literal(null)]).optional(),
	"runnerApi": number().optional(),
	"session": string().optional(),
	"cancelling": boolean().optional(),
	"deadlineAtMs": union([number(), literal(null)]).optional(),
	"maxAttempts": union([number(), literal(null)]).optional(),
	"quotaResumes": union([number(), literal(null)]).optional(),
	"quotaResumesUsed": union([number(), literal(null)]).optional(),
	"tokensIn": union([number(), literal(null)]).optional(),
	"tokensCacheW": union([number(), literal(null)]).optional(),
	"tokensCacheR": union([number(), literal(null)]).optional(),
	"tokensOut": union([number(), literal(null)]).optional(),
	"tokensTotal": union([number(), literal(null)]).optional(),
	"costUsd": string().optional()
});
const clawock_dsh_clawockStudio_taskQueue_result$schema = object({
	"available": boolean(),
	"status": union([
		literal("fresh"),
		literal("cached"),
		literal("stale"),
		literal("failed")
	]),
	"message": union([literal(null), string()]),
	"asOf": string(),
	"refreshMs": number(),
	"maxRunning": number(),
	"slotLimits": array(object({
		"agent": string(),
		"max": number()
	})).optional(),
	"opencodePool": array(string()).optional(),
	"running": number(),
	"active": array(clawock_dsh_clawockStudio_taskQueue_task$schema),
	"recent": array(clawock_dsh_clawockStudio_taskQueue_task$schema),
	"patrol": object({
		"service": string(),
		"phase": union([
			literal("running"),
			literal("yielding"),
			literal("waiting"),
			literal("stopped"),
			literal("unknown")
		]),
		"round": string(),
		"detail": string(),
		"untilMs": union([number(), literal(null)]),
		"rounds": array(object({
			"endedAt": string(),
			"round": string(),
			"axis": string(),
			"result": string(),
			"seconds": union([number(), literal(null)])
		}))
	}),
	"queues": array(object({
		"agent": string(),
		"held": boolean(),
		"holder": string(),
		"holderNote": string().optional(),
		"order": array(string()),
		"quotaUntilMs": union([number(), literal(null)]),
		"quotaBy": string()
	})).optional(),
	"ops": object({
		"available": boolean(),
		"version": string(),
		"repoVersion": string(),
		"api": number(),
		"runnerApi": number(),
		"fairWaitSec": number(),
		"error": string()
	}).optional(),
	"logDir": string().optional()
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
		"side": union([
			literal("add"),
			literal("reduce"),
			literal(null)
		]),
		"holdPnl": union([literal(null), number()]),
		"t1": union([literal(null), object({
			"date": string(),
			"price": number(),
			"delta": number(),
			"verdictKind": union([
				literal("up"),
				literal("down"),
				literal("soldEarly"),
				literal("soldRight"),
				literal("flat")
			]),
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
					create: () => clawock_dsh_clawockStudio_balance_parameter_0$schema
				}
			}],
			result: {
				mode: "strict",
				typeSymbol: "clawock-dsh/types#BalancesResult",
				create: () => clawock_dsh_clawockStudio_balance_result$schema
			},
			sourceLocation: {
				"file": "packages/clawock-dsh/src/index.ts",
				"line": 121,
				"column": 3
			}
		},
		{
			id: "clawock-dsh#clawockStudio/taskQueue",
			service: "clawockStudio",
			namespace: "clawockStudio",
			method: "taskQueue",
			invocation: { kind: "direct" },
			parameters: [{
				name: "force",
				wire: "force",
				source: "json",
				codec: {
					mode: "strict",
					typeSymbol: "clawock-dsh#clawockStudio/taskQueue:force",
					create: () => clawock_dsh_clawockStudio_taskQueue_parameter_0$schema
				}
			}],
			result: {
				mode: "strict",
				typeSymbol: "clawock-dsh/types#TaskQueueResult",
				create: () => clawock_dsh_clawockStudio_taskQueue_result$schema
			},
			sourceLocation: {
				"file": "packages/clawock-dsh/src/index.ts",
				"line": 254,
				"column": 3
			}
		},
		{
			id: "clawock-dsh#clawockStudio/queueAction",
			service: "clawockStudio",
			namespace: "clawockStudio",
			method: "queueAction",
			invocation: { kind: "direct" },
			parameters: [
				{
					name: "action",
					wire: "action",
					source: "json",
					codec: {
						mode: "strict",
						typeSymbol: "clawock-dsh#clawockStudio/queueAction:action",
						create: () => clawock_dsh_clawockStudio_queueAction_parameter_0$schema
					}
				},
				{
					name: "id",
					wire: "id",
					source: "json",
					codec: {
						mode: "strict",
						typeSymbol: "clawock-dsh#clawockStudio/queueAction:id",
						create: () => clawock_dsh_clawockStudio_queueAction_parameter_1$schema
					}
				},
				{
					name: "arg",
					wire: "arg",
					source: "json",
					codec: {
						mode: "strict",
						typeSymbol: "clawock-dsh#clawockStudio/queueAction:arg",
						create: () => clawock_dsh_clawockStudio_queueAction_parameter_2$schema
					}
				}
			],
			result: {
				mode: "strict",
				typeSymbol: "clawock-dsh/types#QueueActionResult",
				create: () => clawock_dsh_clawockStudio_queueAction_result$schema
			},
			sourceLocation: {
				"file": "packages/clawock-dsh/src/index.ts",
				"line": 281,
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
					create: () => clawock_dsh_clawockStudio_get_parameter_0$schema
				}
			}],
			result: {
				mode: "strict",
				typeSymbol: "clawock-dsh/types#RunDetailResult",
				create: () => clawock_dsh_clawockStudio_get_result$schema
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
				create: () => clawock_dsh_clawockStudio_ledger_result$schema
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
				create: () => clawock_dsh_clawockStudio_list_result$schema
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
				create: () => clawock_dsh_clawockStudio_plans_result$schema
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
				create: () => clawock_dsh_clawockStudio_portfolio_result$schema
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
				create: () => clawock_dsh_clawockStudio_traces_result$schema
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
const css = ".SPgITW_dmt,.SPgITW_pbc{--fs-micro:10px;--fs-xs:11px;--fs-sm:12px;--fs-md:13px;--fs-lg:14px;--fs-xl:15px;--fs-2xl:16px;--surface:var(--dsw-alias-bg-layer-1,#fff);--glass-saturate:1.45;--glass-card-blur:20px;--glass-header-blur:28px;--glass-chip-blur:12px;--glass-popover-blur:28px;--glass-fill-card:color-mix(in srgb, var(--surface) 74%, transparent);--glass-fill-header:color-mix(in srgb, var(--surface) 80%, transparent);--glass-fill-chip:color-mix(in srgb, var(--surface) 54%, transparent);--glass-fill-popover:color-mix(in srgb, var(--surface) 88%, transparent);--glass-sheen:linear-gradient(180deg, #ffffff61, #fff0 72px);--glass-rim:#ffffffb8;--glass-under-edge:#1018280d;--glass-border:var(--dsw-alias-border-l2,#1118271a);--glass-shadow:0 1px 2px -1px #1018281a, 0 18px 44px -20px #10182847;--glass-float-shadow:0 2px 8px -2px #10182821, 0 20px 48px -18px #10182852}body[data-ds-dark-theme] :is(.SPgITW_dmt,.SPgITW_pbc){--glass-fill-card:color-mix(in srgb, var(--surface) 70%, transparent);--glass-fill-header:color-mix(in srgb, var(--surface) 78%, transparent);--glass-fill-chip:color-mix(in srgb, var(--surface) 58%, transparent);--glass-fill-popover:color-mix(in srgb, var(--surface) 88%, transparent);--glass-sheen:linear-gradient(180deg, #ffffff1a, #fff0 72px);--glass-rim:#ffffff24;--glass-under-edge:#0000004d;--glass-shadow:0 1px 2px -1px #00000080, 0 20px 48px -22px #000000b8;--glass-float-shadow:0 2px 8px -2px #00000080, 0 22px 52px -18px #000000bf}.SPgITW_dmt{--col:var(--dsh-chat-content-width,748px);--page:var(--dsw-alias-bg-base,#f7f8fa);--text:var(--dsw-alias-label-primary,#15171b);--text2:var(--dsw-alias-label-secondary,#61666b);--text3:var(--dsw-alias-label-tertiary,#81858c);--cap:var(--dsw-alias-label-caption,#adb2b8);--ink-accent:var(--dsw-alias-label-secondary,#61666b);--border:var(--dsw-alias-border-l1,#1118270f);--border2:var(--dsw-alias-border-l2,#1118271a);--hover:var(--dsw-alias-interactive-bg-hover,#1118270d);--row-hover:color-mix(in srgb, var(--hover) 18%, transparent);--ok:#18763e;--ok-soft:#e6faed;--bad:#c01313;--bad-soft:#fdebee;--warn:#8f571b;--warn-soft:#8f571b1a;--shadow-sm:0 1px 2px #1018280a;--tint-soft:var(--dsw-alias-interactive-bg-hover,#1118270d);--tint-border:var(--dsw-alias-border-l1,#1118270f);--tint-mid:var(--dsw-alias-interactive-bg-active,#11182714);--row-press:color-mix(in srgb, var(--tint-mid) 12%, transparent);--tint-strong:color-mix(in srgb, var(--text) 12%, transparent);--t1-up-border:#18763e2e;--t1-down-border:#c013132e;--canvas:var(--dsw-static-neutral-bluish-75,#f1f3f5);--tray-fill:color-mix(in srgb, var(--dsw-static-neutral-bluish-100,#ebeef2) 58%, transparent);--tray-shadow:inset 0 1px 3px -1px #10182821;--card-solid:var(--dsw-static-neutral-bluish-60,#f5f6f7);--radius-card:12px;--radius-inset:10px;--radius-chip:6px;--card-gutter:12px;--font:var(--dsw-font-family,-apple-system,BlinkMacSystemFont,\"Segoe UI\",\"PingFang SC\",\"Hiragino Sans GB\",\"Microsoft YaHei\",sans-serif);--mono:var(--ds-font-family-code,ui-monospace,SFMono-Regular,Menlo,Consolas,monospace);font:var(--fs-md)/1.45 var(--font);color:var(--text);-webkit-font-smoothing:antialiased;background-color:var(--canvas);background-image:none;min-height:100%}body[data-ds-dark-theme] .SPgITW_dmt{--ok:#3fcb74;--ok-soft:#153824;--bad:#fa716a;--bad-soft:#3b1516;--warn:#e0a752;--warn-soft:#e0a75224;--shadow-sm:0 1px 2px #0000004d;--t1-up-border:#3fcb7459;--t1-down-border:#fa716a59;--canvas:var(--page);--tray-fill:color-mix(in srgb, var(--dsw-static-neutral-bluish-950,#151517) 55%, transparent);--tray-shadow:inset 0 1px 3px -1px #00000073;--card-solid:var(--dsw-static-neutral-bluish-875,#232324)}.SPgITW_dmt .SPgITW_top{box-sizing:border-box;padding:10px 0 0}.SPgITW_dmt .SPgITW_tin{box-sizing:border-box;max-width:calc(var(--col) - 28px);padding:10px var(--card-gutter) 11px;background:var(--surface);background:var(--glass-sheen), var(--glass-fill-header);backdrop-filter:blur(var(--glass-header-blur)) saturate(var(--glass-saturate));border:1px solid var(--border2);border-radius:var(--radius-card);box-shadow:var(--glass-shadow), inset 0 1px 0 var(--glass-rim), inset 0 -1px 0 var(--glass-under-edge);margin:0 auto}.SPgITW_dmt .SPgITW_tt{font:650 var(--fs-xl)/1.3 var(--font);letter-spacing:-.01em;flex-wrap:wrap;align-items:baseline;gap:3px 8px;display:flex}.SPgITW_dmt .SPgITW_tt:before{content:\"\";background:var(--ink-accent);border-radius:3px;flex:none;align-self:center;width:8px;height:8px}.SPgITW_dmt .SPgITW_tt .SPgITW_rate{font:400 var(--fs-xs)/1.3 var(--font);color:var(--cap);font-variant-numeric:tabular-nums;white-space:nowrap;margin-left:auto}.SPgITW_dmt .SPgITW_ts{min-width:0;font:400 var(--fs-sm)/1.4 var(--font);color:var(--cap);text-overflow:ellipsis;white-space:nowrap;flex:0 auto;overflow:hidden}.SPgITW_dmt .SPgITW_stats{flex-wrap:wrap;align-items:baseline;gap:6px 18px;margin-top:8px;display:flex}.SPgITW_dmt .SPgITW_sg{align-items:baseline;gap:6px;min-width:0;display:flex}.SPgITW_dmt .SPgITW_sl{font:500 var(--fs-xs)/1.3 var(--font);color:var(--cap);letter-spacing:.03em}.SPgITW_dmt .SPgITW_sv{font:650 var(--fs-lg)/1.3 var(--font);color:var(--text);font-variant-numeric:tabular-nums;white-space:nowrap}.SPgITW_dmt .SPgITW_sv.SPgITW_focus{font:700 var(--fs-2xl)/1.2 var(--font)}.SPgITW_dmt .SPgITW_sv.SPgITW_up{color:var(--ok)}.SPgITW_dmt .SPgITW_sv.SPgITW_down{color:var(--bad)}.SPgITW_dmt .SPgITW_bar{box-sizing:border-box;z-index:20;background:var(--canvas);background:color-mix(in srgb, var(--canvas) 62%, transparent);backdrop-filter:blur(var(--glass-card-blur)) saturate(var(--glass-saturate));padding:8px 0 6px;position:sticky;top:0}.SPgITW_dmt .SPgITW_bar:after{content:\"\";pointer-events:none;background:linear-gradient(180deg, color-mix(in srgb, var(--canvas) 45%, transparent), transparent);height:9px;position:absolute;top:100%;left:0;right:0}.SPgITW_dmt .SPgITW_bin{box-sizing:border-box;max-width:calc(var(--col) - 28px);margin:0 auto}.SPgITW_dmt .SPgITW_filters{flex-wrap:wrap;gap:2px;margin-left:2px;display:flex}.SPgITW_dmt .SPgITW_ft{color:var(--text3);font:600 var(--fs-sm)/1.4 var(--font);cursor:pointer;background:0 0;border:0;border-radius:7px;padding:5px 10px;transition:background .12s,color .12s,transform .16s cubic-bezier(.23,1,.32,1)}.SPgITW_dmt .SPgITW_ft:active{transform:scale(.97)}@media (hover:hover) and (pointer:fine){.SPgITW_dmt .SPgITW_ft:hover{background:var(--hover)}}.SPgITW_dmt .SPgITW_ft.SPgITW_on{color:var(--text);background:var(--hover)}.SPgITW_dmt .SPgITW_ft:focus-visible{outline:1px solid var(--ink-accent);outline-offset:1px}.SPgITW_dmt .SPgITW_list{box-sizing:border-box;max-width:var(--col);padding:0 14px calc(var(--dsh-composer-height,152px) + 24px);margin:0 auto}.SPgITW_dmt .SPgITW_day{font:650 var(--fs-sm)/1.3 var(--font);color:var(--text2);align-items:center;gap:8px;margin:18px 0 6px;display:flex}.SPgITW_dmt .SPgITW_day .SPgITW_n{color:var(--cap);font:400 var(--fs-xs)/1.3 var(--mono);margin-left:auto}.SPgITW_dmt .SPgITW_day:after{content:\"\";background:var(--border);flex:1;height:1px;margin-left:6px}.SPgITW_dmt .SPgITW_day.SPgITW_fold{cursor:pointer;border-radius:8px;margin-left:-6px;padding:3px 6px}.SPgITW_dmt .SPgITW_day.SPgITW_fold:active{background:var(--tint-mid)}@media (hover:hover) and (pointer:fine){.SPgITW_dmt .SPgITW_day.SPgITW_fold:hover{background:var(--hover)}}.SPgITW_dmt .SPgITW_day.SPgITW_fold:focus-visible{outline:1px solid var(--ink-accent);outline-offset:1px}.SPgITW_dmt .SPgITW_day.SPgITW_fold .SPgITW_chev{text-align:center;width:12px;font-size:var(--fs-micro);color:var(--cap);flex:none;margin-left:0}.SPgITW_dmt .SPgITW_group{border:1px solid var(--border2);border-radius:var(--radius-card);background:var(--surface);background:var(--glass-sheen), var(--glass-fill-card);backdrop-filter:blur(var(--glass-card-blur)) saturate(var(--glass-saturate));box-shadow:var(--glass-shadow), inset 0 1px 0 var(--glass-rim), inset 0 -1px 0 var(--glass-under-edge);grid-template-columns:2px 8px auto minmax(64px,auto) auto minmax(0,1fr) auto auto 104px 12px 2px;gap:0 10px;display:grid;overflow:hidden}.SPgITW_dmt .SPgITW_cell{grid-column:1/-1;grid-template-columns:2px 8px auto minmax(64px,auto) auto minmax(0,1fr) auto auto 104px 12px 2px;grid-template-columns:subgrid;cursor:pointer;align-items:center;gap:0 10px;padding:9px 0;display:grid;position:relative}.SPgITW_dmt .SPgITW_cell+.SPgITW_cell{border-top:1px solid var(--border)}.SPgITW_dmt .SPgITW_cell:active{background:var(--row-press)}@media (hover:hover) and (pointer:fine){.SPgITW_dmt .SPgITW_cell:hover{background:var(--row-hover)}.SPgITW_dmt .SPgITW_cell:not(.SPgITW_open):hover .SPgITW_chev{color:var(--text2);transform:translateY(1px)}}.SPgITW_dmt .SPgITW_cell:focus-visible{outline:1px solid var(--ink-accent);outline-offset:-2px}.SPgITW_dmt .SPgITW_cell.SPgITW_open:before{content:\"\";background:linear-gradient(180deg, var(--ink-accent), color-mix(in srgb, var(--ink-accent) 14%, transparent));border-radius:2px;width:3px;position:absolute;top:10px;bottom:10px;left:0}.SPgITW_dmt .SPgITW_main,.SPgITW_dmt .SPgITW_sub{display:contents}.SPgITW_dmt .SPgITW_dotm{background:var(--cap);border-radius:50%;grid-area:1/2;width:6px;height:6px}.SPgITW_dmt .SPgITW_cell.SPgITW_hasdec .SPgITW_dotm{background:var(--ink-accent)}.SPgITW_dmt .SPgITW_sub .SPgITW_date{font:400 var(--fs-xs)/1.4 var(--mono);color:var(--cap);font-variant-numeric:tabular-nums;white-space:nowrap;grid-area:1/3}.SPgITW_dmt .SPgITW_tk{min-width:0;font:650 var(--fs-lg)/1.4 var(--font);letter-spacing:-.01em;text-overflow:ellipsis;white-space:nowrap;grid-area:1/4;overflow:hidden}.SPgITW_dmt .SPgITW_mkt{font:700 var(--fs-micro)/1 var(--font);vertical-align:2px;color:var(--ink-accent);margin-left:3px}.SPgITW_dmt .SPgITW_mkt.SPgITW_hk{color:var(--text3)}.SPgITW_dmt .SPgITW_tag{border-radius:var(--radius-chip);border:1px solid var(--tint-border);background:var(--tint-soft);height:20px;font:600 var(--fs-sm)/1 var(--font);color:var(--text2);letter-spacing:.02em;white-space:nowrap;grid-area:1/5;justify-self:start;align-items:center;padding:0 7px;display:inline-flex}.SPgITW_dmt .SPgITW_qty{min-width:0;font:500 var(--fs-sm)/1.4 var(--mono);color:var(--text2);font-variant-numeric:tabular-nums;white-space:nowrap;text-overflow:ellipsis;grid-area:1/6;justify-self:start;overflow:hidden}.SPgITW_dmt .SPgITW_sp{display:none}.SPgITW_dmt .SPgITW_pnl{text-align:right;font:700 var(--fs-2xl)/1.2 var(--font);font-variant-numeric:tabular-nums;letter-spacing:-.01em;grid-area:1/9;justify-self:end}.SPgITW_dmt .SPgITW_pnl.SPgITW_up{color:var(--ok)}.SPgITW_dmt .SPgITW_pnl.SPgITW_down{color:var(--bad)}.SPgITW_dmt .SPgITW_pnl.SPgITW_na{color:var(--cap);font-weight:500;font-size:var(--fs-md)}.SPgITW_dmt .SPgITW_pnlk{font:600 var(--fs-xs)/1.2 var(--font);color:var(--cap);letter-spacing:0;margin-right:3px}.SPgITW_dmt .SPgITW_t1{height:19px;font:600 var(--fs-xs)/1 var(--font);white-space:nowrap;font-variant-numeric:tabular-nums;border-radius:5px;grid-area:1/8;justify-self:end;align-items:center;padding:0 6px;display:inline-flex}.SPgITW_dmt .SPgITW_t1.SPgITW_up{color:var(--ok);background:var(--ok-soft);border:1px solid var(--t1-up-border)}.SPgITW_dmt .SPgITW_t1.SPgITW_down{color:var(--bad);background:var(--bad-soft);border:1px solid var(--t1-down-border)}.SPgITW_dmt .SPgITW_t1.SPgITW_flat{color:var(--text2);background:var(--tint-soft)}.SPgITW_dmt .SPgITW_al{height:19px;font:600 var(--fs-xs)/1 var(--font);white-space:nowrap;letter-spacing:.02em;border-radius:5px;grid-area:1/7;justify-self:end;align-items:center;padding:0 6px;display:inline-flex}.SPgITW_dmt .SPgITW_al.SPgITW_opp{color:var(--warn);background:var(--warn-soft);border:1px solid var(--t1-down-border)}.SPgITW_dmt .SPgITW_chev{color:var(--cap);font-size:var(--fs-micro);grid-area:1/10;justify-self:end}.SPgITW_dmt .SPgITW_cell.SPgITW_open .SPgITW_chev{transform:rotate(180deg)}.SPgITW_dmt .SPgITW_detail{opacity:0;grid-area:2/1/auto/-1;grid-template-rows:0fr;display:grid;overflow:hidden}.SPgITW_dmt .SPgITW_cell.SPgITW_open .SPgITW_detail{opacity:1;grid-template-rows:1fr;margin-top:9px}.SPgITW_dmt .SPgITW_dinner{min-height:0;padding:0;overflow:hidden}.SPgITW_dmt .SPgITW_dbody{padding:var(--card-gutter);border:1px solid var(--tint-border);border-radius:var(--radius-inset);background:var(--tray-fill);box-shadow:var(--tray-shadow), inset 0 -1px 0 var(--glass-rim);margin:0 10px 10px}.SPgITW_dmt .SPgITW_trhead{font:500 var(--fs-xs)/1.3 var(--font);color:var(--cap);letter-spacing:.05em;align-items:center;gap:6px;margin-bottom:8px;display:flex}.SPgITW_dmt .SPgITW_trhead:before{content:\"\";background:var(--ink-accent);border-radius:50%;width:6px;height:6px}.SPgITW_dmt .SPgITW_trace{padding-left:22px;position:relative}.SPgITW_dmt .SPgITW_trace:before{content:\"\";background:var(--tint-mid);width:2px;position:absolute;top:12px;bottom:10px;left:5px}.SPgITW_dmt .SPgITW_tnode{padding:2px 0 14px;position:relative}.SPgITW_dmt .SPgITW_tnode:last-child{padding-bottom:2px}.SPgITW_dmt .SPgITW_tnode:before{content:\"\";background:var(--card-solid);border:2px solid var(--cap);box-sizing:border-box;border-radius:50%;width:10px;height:10px;position:absolute;top:5px;left:-22px}.SPgITW_dmt .SPgITW_tnode.SPgITW_dec:before{border-color:var(--ink-accent)}.SPgITW_dmt .SPgITW_tnode.SPgITW_follow:before{border-color:var(--ok)}.SPgITW_dmt .SPgITW_tnode.SPgITW_skip:before{border-color:var(--warn)}.SPgITW_dmt .SPgITW_tnode.SPgITW_win:before{border-color:var(--ok)}.SPgITW_dmt .SPgITW_tnode.SPgITW_loss:before{border-color:var(--bad)}.SPgITW_dmt .SPgITW_tnode .SPgITW_tw{font:400 var(--fs-micro)/1.4 var(--mono);color:var(--cap);margin-bottom:1px}.SPgITW_dmt .SPgITW_tnode .SPgITW_n{font:500 var(--fs-xs)/1.3 var(--font);color:var(--cap);letter-spacing:.04em;margin-bottom:2px}.SPgITW_dmt .SPgITW_tnode .SPgITW_v{font:600 var(--fs-md)/1.4 var(--font)}.SPgITW_dmt .SPgITW_tnode .SPgITW_fill-v{overflow-wrap:anywhere;flex-wrap:wrap;align-items:baseline;gap:4px 6px;display:flex}.SPgITW_dmt .SPgITW_tnode.SPgITW_win .SPgITW_v{color:var(--ok)}.SPgITW_dmt .SPgITW_tnode.SPgITW_loss .SPgITW_v{color:var(--bad)}.SPgITW_dmt .SPgITW_tnode.SPgITW_follow .SPgITW_v{color:var(--ok)}.SPgITW_dmt .SPgITW_tnode.SPgITW_skip .SPgITW_v{color:var(--warn)}.SPgITW_dmt .SPgITW_pchips{flex-wrap:wrap;gap:6px;margin:4px 0 8px;display:flex}.SPgITW_dmt .SPgITW_pc{font:400 var(--fs-xs)/1.4 var(--font);box-sizing:border-box;overflow-wrap:anywhere;border-radius:var(--radius-chip);background:var(--glass-fill-chip);border:1px solid var(--glass-border);min-width:0;max-width:100%;box-shadow:inset 0 1px 0 var(--glass-rim);color:var(--text2);padding:2px 8px}.SPgITW_dmt .SPgITW_tnote{border-left:3px solid var(--tint-strong);font:400 var(--fs-sm)/1.6 var(--font);color:var(--text2);white-space:pre-wrap;overflow-wrap:anywhere;margin:7px 0;padding:3px 0 3px 10px}.SPgITW_dmt .SPgITW_tnote.SPgITW_why{border-left-color:var(--ink-accent)}.SPgITW_dmt .SPgITW_tnote.SPgITW_emo{border-left-color:var(--warn)}.SPgITW_dmt .SPgITW_tnote .SPgITW_k{color:var(--cap);font:600 var(--fs-xs)/1.4 var(--font)}.SPgITW_dmt .SPgITW_tmiss{border:1px dashed var(--border2);border-radius:var(--radius-chip);font:400 var(--fs-sm)/1.5 var(--font);color:var(--cap);margin-top:8px;padding:7px 10px}.SPgITW_dmt .SPgITW_empty{text-align:center;color:var(--cap);font:400 var(--fs-md)/1.5 var(--font);border:1px dashed var(--tint-border);border-radius:var(--radius-card);background:var(--glass-fill-card);box-shadow:inset 0 1px 0 var(--glass-rim), inset 0 -1px 0 var(--glass-under-edge);padding:48px 20px}.SPgITW_dmt .SPgITW_trace-more{border:1px dashed var(--border2);border-radius:var(--radius-inset);width:100%;color:var(--text2);font:600 var(--fs-sm)/1.4 var(--font);cursor:pointer;background:0 0;margin:12px 0 0;padding:9px 12px;transition:background .12s,border-color .12s,color .12s,transform .16s cubic-bezier(.23,1,.32,1);display:block}.SPgITW_dmt .SPgITW_trace-more:active{transform:scale(.98)}@media (hover:hover) and (pointer:fine){.SPgITW_dmt .SPgITW_trace-more:hover{background:var(--hover);border-color:var(--ink-accent);color:var(--text)}}.SPgITW_dmt .SPgITW_skel{padding:13px var(--card-gutter);border:1px solid var(--border2);border-radius:var(--radius-card);background:var(--surface);background:var(--glass-sheen), var(--glass-fill-card);backdrop-filter:blur(var(--glass-card-blur)) saturate(var(--glass-saturate));box-shadow:var(--glass-shadow), inset 0 1px 0 var(--glass-rim), inset 0 -1px 0 var(--glass-under-edge);align-items:center;gap:12px;margin:8px 0;display:flex}.SPgITW_dmt .SPgITW_skel-dot{background:var(--tint-strong);border-radius:50%;flex:none;width:6px;height:6px}.SPgITW_dmt .SPgITW_skel-bar{background:var(--tint-mid);border-radius:5px;height:10px;position:relative;overflow:hidden}.SPgITW_dmt .SPgITW_skel-bar:after{content:\"\";background:linear-gradient(90deg, transparent, var(--tint-strong), transparent);animation:1.2s ease-in-out infinite SPgITW_clawock-shimmer;position:absolute;inset:0;transform:translate(-100%)}@keyframes SPgITW_clawock-shimmer{to{transform:translate(100%)}}.SPgITW_dmt .SPgITW_skel-bar.SPgITW_w40{width:40%}.SPgITW_dmt .SPgITW_skel-bar.SPgITW_w20{width:20%}@media (prefers-reduced-motion:reduce){.SPgITW_dmt .SPgITW_detail{transition:opacity .15s}.SPgITW_dmt .SPgITW_ft,.SPgITW_dmt .SPgITW_trace-more{transition:background .12s,color .12s,border-color .12s,transform}.SPgITW_dmt .SPgITW_ft:active,.SPgITW_dmt .SPgITW_trace-more:active{transform:none}.SPgITW_dmt .SPgITW_skel-bar:after{animation:none}}@media (width<=520px){.SPgITW_dmt .SPgITW_top{padding:8px 10px 0}.SPgITW_dmt .SPgITW_bar{padding:6px 10px}.SPgITW_dmt .SPgITW_bin{max-width:none}.SPgITW_dmt .SPgITW_tin{max-width:none;padding:10px var(--card-gutter) 9px}.SPgITW_dmt .SPgITW_ts{white-space:normal;flex:1 0 100%}.SPgITW_dmt .SPgITW_stats{margin-top:6px;display:block}.SPgITW_dmt .SPgITW_sg{justify-content:space-between;gap:10px;padding:3px 0}.SPgITW_dmt .SPgITW_sl{min-width:0}.SPgITW_dmt .SPgITW_sg+.SPgITW_sg{border-top:1px solid var(--border)}.SPgITW_dmt .SPgITW_sv{white-space:nowrap;text-align:right;flex:none}.SPgITW_dmt .SPgITW_ft{min-height:32px;padding:6px 11px}.SPgITW_dmt .SPgITW_list{padding:0 10px calc(var(--dsh-composer-height,152px) + 24px)}.SPgITW_dmt .SPgITW_day.SPgITW_fold{padding:7px 6px}.SPgITW_dmt .SPgITW_group{display:block}.SPgITW_dmt .SPgITW_cell{padding:0;display:block}.SPgITW_dmt .SPgITW_main{grid-template-columns:7px minmax(0,1fr) max-content;align-items:center;gap:2px 8px;padding:10px 12px 2px;display:grid}.SPgITW_dmt .SPgITW_main .SPgITW_dotm{grid-area:1/1}.SPgITW_dmt .SPgITW_main .SPgITW_tk{grid-area:1/2}.SPgITW_dmt .SPgITW_main .SPgITW_pnl{grid-area:1/3}.SPgITW_dmt .SPgITW_main .SPgITW_tag{grid-area:2/2}.SPgITW_dmt .SPgITW_main .SPgITW_qty{grid-area:2/3;justify-self:end}.SPgITW_dmt .SPgITW_sub{align-items:center;gap:8px;padding:2px 12px 10px;display:flex}.SPgITW_dmt .SPgITW_dotm{flex:none;width:7px;height:7px}.SPgITW_dmt .SPgITW_tk{font-size:var(--fs-lg)}.SPgITW_dmt .SPgITW_tag{justify-self:start;height:19px;padding:0 6px}.SPgITW_dmt .SPgITW_qty{font-size:var(--fs-sm)}.SPgITW_dmt .SPgITW_sp{display:none}.SPgITW_dmt .SPgITW_pnl{font-size:var(--fs-xl)}.SPgITW_dmt .SPgITW_t1,.SPgITW_dmt .SPgITW_al,.SPgITW_dmt .SPgITW_sub .SPgITW_date{flex:none}.SPgITW_dmt .SPgITW_chev{flex:none;margin-left:auto}.SPgITW_dmt .SPgITW_cell.SPgITW_open .SPgITW_detail{margin-top:0}.SPgITW_dmt .SPgITW_dbody{padding:10px var(--card-gutter) 11px;margin:0 8px 8px}.SPgITW_dmt .SPgITW_trace{padding-left:16px}.SPgITW_dmt .SPgITW_tnode:before{left:-16px}.SPgITW_dmt .SPgITW_trace:before{left:3px}.SPgITW_dmt,.SPgITW_pbc{--glass-header-blur:14px;--glass-card-blur:10px;--glass-chip-blur:8px;--glass-popover-blur:18px}}@media (pointer:coarse){.SPgITW_dmt .SPgITW_ft,.SPgITW_dmt .SPgITW_day.SPgITW_fold,.SPgITW_dmt .SPgITW_trace-more{min-height:44px}.SPgITW_dmt .SPgITW_day.SPgITW_fold{box-sizing:border-box}.SPgITW_pbc.SPgITW_pbf.SPgITW_rail .SPgITW_bchip:after{content:\"\";border-radius:22px;inset:-4px}}@media (prefers-reduced-transparency:reduce){.SPgITW_dmt{background-image:none}.SPgITW_dmt .SPgITW_tin,.SPgITW_dmt .SPgITW_group,.SPgITW_dmt .SPgITW_skel{background:var(--surface);backdrop-filter:none;box-shadow:var(--dsw-shadow-lv2,var(--shadow-sm))}.SPgITW_dmt .SPgITW_dbody{background:var(--tint-soft);box-shadow:none}.SPgITW_dmt .SPgITW_bar{background:var(--canvas);backdrop-filter:none}.SPgITW_dmt .SPgITW_bar:after{content:none}}.SPgITW_pbc{--text:var(--dsw-alias-label-primary,#15171b);--text3:var(--dsw-alias-label-tertiary,#81858c);--cap:var(--dsw-alias-label-caption,#adb2b8);--ink-accent:var(--dsw-alias-label-secondary,#61666b);--hover:var(--dsw-alias-interactive-bg-hover,#1118270d);--ok:#18763e;--bad:#c01313;--warn:#8f571b;--bad-soft:#fcebeb;--warn-soft:#f6ede2;--label-2:var(--dsw-alias-label-secondary,#545860);--glass-separator:var(--dsw-alias-border-l2,#1118271a);--font:var(--dsw-font-family,-apple-system,BlinkMacSystemFont,\"Segoe UI\",\"PingFang SC\",\"Hiragino Sans GB\",\"Microsoft YaHei\",sans-serif);--mono:var(--ds-font-family-code,ui-monospace,SFMono-Regular,Menlo,Consolas,monospace);display:inline-flex;position:relative}body[data-ds-dark-theme] .SPgITW_pbc{--ok:#3fcb74;--bad:#fa716a;--warn:#e0a752;--bad-soft:#402628;--warn-soft:#3b3224;--label-2:var(--dsw-alias-label-secondary,#a9adb4);--glass-separator:var(--dsw-alias-border-l2,#ffffff1f)}.SPgITW_pbc .SPgITW_bchip{box-sizing:border-box;border:.5px solid var(--glass-border);background:var(--glass-sheen), var(--glass-fill-chip);height:28px;backdrop-filter:blur(var(--glass-chip-blur)) saturate(var(--glass-saturate));box-shadow:inset 0 1px 0 var(--glass-rim), inset 0 -1px 0 var(--glass-under-edge);font:500 var(--fs-sm)/1 var(--font);color:var(--label-2);cursor:pointer;border-radius:14px;align-items:center;gap:10px;padding:0 11px;transition:background .12s,color .12s,transform .16s cubic-bezier(.23,1,.32,1);display:inline-flex;position:relative}.SPgITW_pbc .SPgITW_bchip:after{content:\"\";border-radius:20px;position:absolute;inset:-7px}.SPgITW_pbc .SPgITW_bchip:active{transform:scale(.96)}@media (hover:hover) and (pointer:fine){.SPgITW_pbc .SPgITW_bchip:hover{background:var(--hover)}}.SPgITW_pbc .SPgITW_bchip[aria-expanded=true]{background:var(--hover)}.SPgITW_pbc .SPgITW_bchip:focus-visible{outline:1px solid var(--ink-accent);outline-offset:1px}.SPgITW_pbc .SPgITW_bchip-item{align-items:center;gap:5px;display:inline-flex}.SPgITW_pbc .SPgITW_bchip-dot{background:var(--cap);border-radius:50%;flex:none;width:6px;height:6px;transition:background .15s}.SPgITW_pbc .SPgITW_bchip-item[data-balance-state=ok] .SPgITW_bchip-dot{background:var(--ok)}.SPgITW_pbc .SPgITW_bchip-item[data-balance-state=low] .SPgITW_bchip-dot{background:var(--bad)}.SPgITW_pbc .SPgITW_bchip-item[data-balance-state=stale] .SPgITW_bchip-dot{background:var(--warn)}.SPgITW_pbc .SPgITW_bchip-v{font:600 var(--fs-sm)/1 var(--font);font-variant-numeric:tabular-nums;letter-spacing:-.01em;white-space:nowrap;color:var(--text)}.SPgITW_pbc .SPgITW_bchip-v[data-balance-state=low]{color:var(--bad)}.SPgITW_pbc .SPgITW_bchip-v[data-balance-state=none]{color:var(--cap);font-weight:500}.SPgITW_pbc .SPgITW_bchip-v[data-used-level=ok]{color:var(--ok)}.SPgITW_pbc .SPgITW_bchip-v[data-used-level=mid],.SPgITW_pbc .SPgITW_bchip-v[data-balance-state=stale]{color:var(--warn)}.SPgITW_pbc .SPgITW_bchip-reset{font-family:var(--mono);font-size:var(--fs-xs);font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--cap);font-weight:500}.SPgITW_pbc .SPgITW_bchip-sub{font:500 var(--fs-xs)/1 var(--font);font-variant-numeric:tabular-nums;letter-spacing:.01em;white-space:nowrap;color:var(--text3)}.SPgITW_pbc .SPgITW_bp{--text:var(--dsw-alias-label-primary,#15171b);--text3:var(--dsw-alias-label-secondary,#61666b);--cap:var(--dsw-alias-label-secondary,#61666b);z-index:60;border:.5px solid var(--glass-border);background:var(--surface);background:var(--glass-sheen), var(--glass-fill-popover);width:max-content;min-width:min(220px,100vw - 24px);max-width:min(300px,100vw - 24px);backdrop-filter:blur(var(--glass-popover-blur)) saturate(var(--glass-saturate));box-shadow:var(--glass-float-shadow), inset 0 1px 0 var(--glass-rim), inset 0 -1px 0 var(--glass-under-edge);transform-origin:100% 0;border-radius:18px;padding:12px 14px 8px;transition:transform .16s cubic-bezier(.23,1,.32,1);position:absolute;top:calc(100% + 8px);right:0}body[data-ds-dark-theme] .SPgITW_pbc .SPgITW_bp{--text:var(--dsw-alias-label-primary,#f7f8fa);--text3:var(--dsw-alias-label-secondary,#dadee5);--cap:var(--dsw-alias-label-secondary,#dadee5)}.SPgITW_pbc .SPgITW_bp :is(.SPgITW_bp-label,.SPgITW_bp-sub,.SPgITW_bp-note,.SPgITW_bp-empty,.SPgITW_bp-win-label,.SPgITW_bp-win-reset){letter-spacing:.02em;font-weight:550}.SPgITW_pbc .SPgITW_bp[data-open=false]{opacity:0;pointer-events:none;transform:scale(.97)translateY(-4px)}.SPgITW_pbc .SPgITW_bp[data-open=true]{opacity:1;pointer-events:auto}.SPgITW_pbc .SPgITW_bp-head{justify-content:space-between;align-items:center;margin-bottom:2px;display:flex}.SPgITW_pbc .SPgITW_bp-title{font:600 var(--fs-xs)/1.3 var(--font);letter-spacing:.04em;color:var(--text3)}.SPgITW_pbc .SPgITW_bp-row{width:100%;font:inherit;color:inherit;text-align:left;cursor:pointer;background:0 0;border:0;border-radius:8px;grid-template-columns:auto auto 1fr;align-items:center;gap:3px 8px;margin:0 -6px;padding:8px 6px;transition:background .12s,transform .16s cubic-bezier(.23,1,.32,1);display:grid}.SPgITW_pbc .SPgITW_bp-row+.SPgITW_bp-row{border-radius:0 0 8px 8px;position:relative}.SPgITW_pbc .SPgITW_bp-row+.SPgITW_bp-row:before{content:\"\";background:var(--glass-separator);height:.5px;position:absolute;top:0;left:6px;right:6px}@media (hover:hover) and (pointer:fine){.SPgITW_pbc .SPgITW_bp-row:hover{background:var(--hover)}}.SPgITW_pbc .SPgITW_bp-row:active{background:var(--hover);transform:scale(.98)}.SPgITW_pbc .SPgITW_bp-row:focus-visible{outline:1px solid var(--ink-accent);outline-offset:-1px}.SPgITW_pbc .SPgITW_bp-dot{background:var(--cap);border-radius:50%;width:7px;height:7px}.SPgITW_pbc .SPgITW_bp-dot[data-balance-state=ok]{background:var(--ok)}.SPgITW_pbc .SPgITW_bp-dot[data-balance-state=low]{background:var(--bad)}.SPgITW_pbc .SPgITW_bp-dot[data-balance-state=stale]{background:var(--warn)}.SPgITW_pbc .SPgITW_bp-label{font:500 var(--fs-sm)/1.4 var(--font);color:var(--text);align-items:center;gap:5px;display:inline-flex}.SPgITW_pbc .SPgITW_bp-pin{background:var(--ink-accent);border-radius:50%;flex:none;width:5px;height:5px}.SPgITW_pbc .SPgITW_bp-v{font:650 var(--fs-md)/1.2 var(--font);font-variant-numeric:tabular-nums;letter-spacing:-.01em;white-space:nowrap;color:var(--text);justify-self:end}.SPgITW_pbc .SPgITW_bp-v.SPgITW_bad{color:var(--bad)}.SPgITW_pbc .SPgITW_bp-wins{flex-direction:column;grid-column:1/-1;gap:6px;margin-top:2px;display:flex}.SPgITW_pbc .SPgITW_bp-win{font-size:var(--fs-xs);flex-direction:column;gap:3px;display:flex}.SPgITW_pbc .SPgITW_bp-win-line{align-items:baseline;gap:8px;line-height:1.5;display:flex}.SPgITW_pbc .SPgITW_bp-win-label{color:var(--cap);letter-spacing:.02em;min-width:30px}.SPgITW_pbc .SPgITW_bp-win-pct{color:var(--text);font-variant-numeric:tabular-nums;margin-left:auto;font-weight:600}.SPgITW_pbc .SPgITW_bp-win-reset{color:var(--cap);font-family:var(--mono);font-size:var(--fs-xs);text-align:right;font-variant-numeric:tabular-nums;min-width:58px}.SPgITW_pbc .SPgITW_bp-win-bar{background:color-mix(in srgb, var(--text) 9%, transparent);border-radius:2px;height:3px;overflow:hidden}.SPgITW_pbc .SPgITW_bp-win-fill{background:var(--ok);border-radius:2px;height:100%;transition:background .15s}.SPgITW_pbc .SPgITW_bp-win-fill[data-balance-state=mid]{background:var(--warn)}.SPgITW_pbc .SPgITW_bp-win-fill[data-balance-state=low]{background:var(--bad)}.SPgITW_pbc .SPgITW_bp-win-fill[data-balance-state=stale]{background:var(--warn)}.SPgITW_pbc .SPgITW_bp-note,.SPgITW_pbc .SPgITW_bp-sub{font:400 var(--fs-xs)/1.5 var(--font);overflow-wrap:anywhere;grid-column:1/-1}.SPgITW_pbc .SPgITW_bp-sub{color:var(--cap)}.SPgITW_pbc .SPgITW_bp-note.SPgITW_warn{color:var(--warn)}.SPgITW_pbc .SPgITW_bp-note.SPgITW_bad{color:var(--bad)}.SPgITW_pbc .SPgITW_bp-empty{font:400 var(--fs-sm)/1.5 var(--font);color:var(--cap);padding:8px 0 10px}.SPgITW_pbc .SPgITW_bal-rf{width:22px;height:22px;color:var(--text3);font:600 var(--fs-sm)/1 var(--font);cursor:pointer;background:0 0;border:0;border-radius:50%;justify-content:center;align-items:center;padding:0;transition:background .12s,color .12s,transform .16s cubic-bezier(.23,1,.32,1);display:inline-flex;position:relative}.SPgITW_pbc .SPgITW_bal-rf:after{content:\"\";border-radius:50%;position:absolute;inset:-9px}.SPgITW_pbc .SPgITW_bal-rf:active{transform:scale(.95)}@media (hover:hover) and (pointer:fine){.SPgITW_pbc .SPgITW_bal-rf:hover{background:var(--hover);color:var(--text)}}.SPgITW_pbc .SPgITW_bal-rf:focus-visible{outline:1px solid var(--ink-accent);outline-offset:1px}.SPgITW_pbc .SPgITW_bal-rf.SPgITW_spin{animation:.8s linear infinite SPgITW_clawock-spin}.SPgITW_pbc .SPgITW_bal-rf.SPgITW_flash-ok{color:var(--ink-accent)}.SPgITW_pbc .SPgITW_bal-rf.SPgITW_flash-same{color:var(--ok)}@keyframes SPgITW_clawock-spin{to{transform:rotate(360deg)}}@media (prefers-reduced-motion:reduce){.SPgITW_pbc .SPgITW_bchip,.SPgITW_pbc .SPgITW_bal-rf{transition:background .12s,color .12s,transform}.SPgITW_pbc .SPgITW_bp{transition:none}.SPgITW_pbc .SPgITW_bp[data-open=false],.SPgITW_pbc .SPgITW_bchip:active,.SPgITW_pbc .SPgITW_bal-rf:active{transform:none}.SPgITW_pbc .SPgITW_bal-rf.SPgITW_spin{animation:none}.SPgITW_pbc .SPgITW_bp-win-fill{transition:none}}@media (width<=520px){.SPgITW_pbc .SPgITW_bp{--glass-fill-popover:color-mix(in srgb, var(--surface) 97%, transparent)}}@media (prefers-reduced-transparency:reduce){.SPgITW_pbc .SPgITW_bp{background:var(--surface);backdrop-filter:none}}.SPgITW_pbc.SPgITW_pbf{align-items:center;width:100%;height:42px;margin:8px 0 0;display:flex}.SPgITW_pbc.SPgITW_pbf .SPgITW_bchip{backdrop-filter:none;width:calc(100% + 4px);height:42px;box-shadow:none;color:var(--text);font:400 var(--fs-lg)/22px var(--font);background:0 0;border:0;border-radius:12px;justify-content:flex-start;gap:8px;margin:0 -2px;padding:0 10px 0 8px;transition:none;overflow:hidden}.SPgITW_pbc.SPgITW_pbf .SPgITW_bchip:after{content:none}.SPgITW_pbc.SPgITW_pbf .SPgITW_bchip:active{background:var(--hover);transform:none}@media (hover:hover) and (pointer:fine){.SPgITW_pbc.SPgITW_pbf .SPgITW_bchip:hover{background:var(--hover)}}.SPgITW_pbc.SPgITW_pbf .SPgITW_bchip[data-active]{background:var(--hover)}.SPgITW_pbc.SPgITW_pbf .SPgITW_bchip:focus-visible{outline:revert;outline-offset:revert}.SPgITW_pbc.SPgITW_pbf .SPgITW_bchip-item{gap:8px;min-width:0;overflow:hidden}.SPgITW_pbc.SPgITW_pbf .SPgITW_bchip-sub{text-overflow:ellipsis;min-width:0;overflow:hidden}.SPgITW_pbc .SPgITW_bchip-name{font:500 var(--fs-sm)/1 var(--font);color:var(--text);white-space:nowrap}.SPgITW_pbc.SPgITW_pbf .SPgITW_bchip-name{font:400 var(--fs-lg)/22px var(--font)}.SPgITW_pbc.SPgITW_pbf.SPgITW_rail{width:36px;height:36px;margin:0}.SPgITW_pbc.SPgITW_pbf.SPgITW_rail .SPgITW_bchip{border-radius:50%;justify-content:center;width:36px;height:36px;margin:0;padding:0}.SPgITW_pbc .SPgITW_bal-lead{color:var(--text);flex:none;justify-content:center;align-items:center;display:inline-flex}.SPgITW_pbc .SPgITW_bal-glyph{display:block;overflow:visible}.SPgITW_pbc .SPgITW_bal-badge{fill:var(--cap);transition:fill .15s,stroke .15s}.SPgITW_pbc .SPgITW_bal-badge[data-balance-state=ok]{fill:var(--ok)}.SPgITW_pbc .SPgITW_bal-badge[data-balance-state=low]{fill:var(--bad)}.SPgITW_pbc .SPgITW_bal-badge[data-balance-state=stale]{fill:none;stroke:var(--warn);stroke-width:1.3px}@media (prefers-reduced-motion:reduce){.SPgITW_pbc .SPgITW_bal-badge{transition:none}}.SPgITW_pbc.SPgITW_pbf .SPgITW_bp{z-index:30;transform-origin:0 100%;position:fixed;top:auto;right:auto}.SPgITW_pbc.SPgITW_pbf .SPgITW_bp[data-open=false]{transform:scale(.97)translateY(4px)}@media (prefers-reduced-motion:reduce){.SPgITW_pbc.SPgITW_pbf .SPgITW_bp[data-open=false]{transform:none}}:has(>.SPgITW_pbc.SPgITW_tqf),:has(>[data-slot]>.SPgITW_pbc.SPgITW_tqf){flex-direction:column}:has(>.SPgITW_pbc.SPgITW_tqf.SPgITW_rail),:has(>[data-slot]>.SPgITW_pbc.SPgITW_tqf.SPgITW_rail){align-items:center}.SPgITW_pbc.SPgITW_tqf{--tq-run:var(--dsw-alias-state-business-primary);--tq-wait:var(--dsw-alias-state-warn-primary);--tq-bad:var(--dsw-alias-state-error-primary);--tq-text-warn:var(--warn);--tq-text-bad:var(--bad);--tq-idle:var(--dsw-alias-state-idle-primary);--tq-ink:var(--dsw-alias-label-primary);--tq-ink-2:var(--dsw-alias-label-secondary);--tq-ink-3:var(--dsw-alias-label-tertiary);--tq-cap:var(--dsw-alias-label-caption);--tq-fill-hover:var(--dsw-alias-interactive-bg-hover);--tq-fill-press:var(--dsw-alias-interactive-bg-active);--tq-fill-danger:var(--dsw-alias-interactive-bg-hover-danger);--tq-fill-inset:var(--dsw-alias-button-ghost-active-fill);--tq-hairline:var(--dsw-alias-border-l2);--tq-pill-border:var(--dsw-alias-border-l3);--tq-chip-fill:var(--dsw-alias-button-ghost-active-fill);--tq-chip-edge:var(--dsw-alias-border-l2);--tq-chip-run-fill:color-mix(in srgb, var(--tq-run) 10%, transparent);--tq-chip-warn-fill:var(--warn-soft);--tq-chip-bad-fill:var(--bad-soft);--tq-radius:var(--dsw-radius-md);--tq-radius-sm:var(--dsw-radius-sm);--tq-radius-xs:var(--dsw-radius-xs);--tq-press-scale:.97;--tq-focus-ring:var(--dsw-focus-ring-width) solid var(--dsw-focus-ring-color,var(--tq-run));--tq-ease:var(--ds-ease-in-out);--tq-fast:var(--ds-transition-duration-fast);--tq-mono:var(--ds-font-family-code);--tq-lead:14px;--tq-gap:8px;--tq-when:64px;--tq-took:64px;--tq-aside:104px;--tq-grid:var(--tq-lead) var(--tq-when) var(--tq-took) minmax(0, 1fr) var(--tq-aside);--tq-main-inset:calc(var(--tq-lead) + var(--tq-gap));--tq-well:var(--dsw-alias-interactive-bg-hover);--tq-text-ok:var(--ok)}.SPgITW_pbc.SPgITW_pbf.SPgITW_tqf .SPgITW_bchip{color:var(--tq-ink)}.SPgITW_pbc.SPgITW_pbf.SPgITW_tqf .SPgITW_bchip:focus-visible{outline:var(--tq-focus-ring);outline-offset:-2px}.SPgITW_pbc.SPgITW_pbf.SPgITW_tqf .SPgITW_bchip-item{flex:auto}.SPgITW_pbc.SPgITW_tqf .SPgITW_tq-count{font:var(--dsw-font-xxs-12);font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--tq-ink-3);flex:none;margin-left:auto;line-height:16px}.SPgITW_pbc.SPgITW_tqf .SPgITW_bal-badge[data-balance-state=ok]{fill:var(--tq-run)}.SPgITW_pbc.SPgITW_tqf .SPgITW_bal-badge[data-balance-state=low]{fill:var(--tq-bad)}.SPgITW_pbc.SPgITW_tqf .SPgITW_bal-badge[data-balance-state=stale]{fill:none;stroke:var(--tq-wait)}.SPgITW_pbc.SPgITW_pbf.SPgITW_tqf .SPgITW_bp{box-sizing:border-box;isolation:isolate;border-radius:var(--tq-radius);backdrop-filter:none;width:min(380px,100vw - 24px);min-width:0;max-width:none;box-shadow:var(--dsw-elevation-prominent);background:0 0;border:0;flex-direction:column;padding:0;display:flex;overflow:hidden}.SPgITW_pbc.SPgITW_pbf.SPgITW_tqf .SPgITW_bp:before{content:\"\";z-index:-1;border-radius:inherit;background:var(--dsw-specific-menu);backdrop-filter:var(--dsw-menu-backdrop-filter);pointer-events:none;position:absolute;inset:0}.SPgITW_pbc .SPgITW_tq-list,.SPgITW_pbc .SPgITW_tq-layer,.SPgITW_pbc .SPgITW_tq-detail{flex-direction:column;flex:auto;min-height:0;display:flex}.SPgITW_pbc .SPgITW_tq-list[inert]{display:none}.SPgITW_pbc .SPgITW_tq-head{box-sizing:border-box;flex:none;justify-content:space-between;align-items:center;gap:8px;min-height:44px;padding:10px 12px;display:flex}.SPgITW_pbc .SPgITW_tq-title{font:var(--dsw-font-s-strong-14);color:var(--tq-ink);line-height:20px}.SPgITW_pbc .SPgITW_tq-caption{font:var(--dsw-font-xxs-12);color:var(--tq-ink-3);line-height:16px}.SPgITW_pbc .SPgITW_tq-scroll{overscroll-behavior:contain;scrollbar-width:thin;flex:auto;min-height:0;padding:0 12px 12px;overflow-y:auto}.SPgITW_pbc .SPgITW_tq-group+.SPgITW_tq-group{border-top:.5px solid var(--tq-hairline);margin-top:8px;padding-top:8px}.SPgITW_pbc .SPgITW_tq-group+.SPgITW_tq-section{border-top:0;margin-top:14px;padding-top:0}.SPgITW_pbc .SPgITW_tq-sub{text-overflow:ellipsis;white-space:nowrap;min-width:0;max-width:100%;font:var(--dsw-font-xxs-12);letter-spacing:0;color:var(--tq-ink-3);font-weight:400;line-height:16px;overflow:hidden}.SPgITW_pbc .SPgITW_tq-agent-glyph{color:var(--tq-ink-2);flex:none}.SPgITW_pbc .SPgITW_tq-dot{background:var(--tq-idle);border-radius:50%;flex:none;width:6px;height:6px}.SPgITW_pbc .SPgITW_tq-dot[data-balance-state=ok]{background:var(--tq-run)}.SPgITW_pbc .SPgITW_tq-dot[data-balance-state=stale]{background:var(--tq-wait)}.SPgITW_pbc .SPgITW_tq-dot[data-balance-state=low]{background:var(--tq-bad)}.SPgITW_pbc .SPgITW_tq-item{align-items:center;gap:2px;margin:0 -8px;display:flex;position:relative}.SPgITW_pbc [data-tq-row]{grid-template-columns:var(--tq-grid);column-gap:var(--tq-gap);align-content:center;align-items:baseline;row-gap:0;min-width:0;display:grid}.SPgITW_pbc .SPgITW_tq-row{box-sizing:border-box;border-radius:var(--tq-radius);font:inherit;text-align:left;color:inherit;cursor:pointer;transition:background-color var(--tq-fast) var(--tq-ease), transform var(--tq-fast) var(--tq-ease);background:0 0;border:0;flex:auto;padding:6px 8px}.SPgITW_pbc .SPgITW_tq-row.SPgITW_tq-static{cursor:default}.SPgITW_pbc .SPgITW_tq-row:active{background:var(--tq-fill-press)}.SPgITW_pbc .SPgITW_tq-row.SPgITW_tq-static:active{background:0 0}.SPgITW_pbc .SPgITW_tq-lead{height:20px;color:var(--tq-ink-2);grid-column:1;justify-content:center;align-self:center;align-items:center;display:flex}.SPgITW_pbc .SPgITW_tq-name{min-width:0;font:var(--dsw-font-xs-13);overflow-wrap:anywhere;color:var(--tq-ink);grid-column:2;line-height:20px}.SPgITW_pbc .SPgITW_tq-value{font:var(--dsw-font-xs-strong-13);font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--tq-ink);grid-column:3;justify-self:end;line-height:20px}.SPgITW_pbc .SPgITW_tq-value[data-used-level=mid],.SPgITW_pbc .SPgITW_tq-value[data-balance-state=stale]{color:var(--tq-text-warn)}.SPgITW_pbc .SPgITW_tq-value[data-used-level=low],.SPgITW_pbc .SPgITW_tq-value[data-balance-state=low]{color:var(--tq-text-bad)}.SPgITW_pbc .SPgITW_tq-row>.SPgITW_tq-name{grid-column:2/5}.SPgITW_pbc .SPgITW_tq-row>.SPgITW_tq-value{grid-column:5}.SPgITW_pbc .SPgITW_tq-row>.SPgITW_tq-chip[data-tq-chip=status]{grid-column:5;justify-self:stretch}.SPgITW_pbc .SPgITW_tq-row>[data-tq-fact=model]{grid-area:2/2/3/5}.SPgITW_pbc .SPgITW_tq-row>:is([data-tq-fact=tries],[data-tq-fact=receipt]){grid-area:2/5/3/6}.SPgITW_pbc .SPgITW_tq-row>[data-tq-fact=when]{grid-area:3/2/4/3}.SPgITW_pbc .SPgITW_tq-row>[data-tq-fact=took]{grid-area:3/3/4/4}.SPgITW_pbc .SPgITW_tq-row>[data-tq-fact=cost]{grid-area:3/5/4/6;justify-self:end}.SPgITW_pbc .SPgITW_tq-row>.SPgITW_tq-caption-line{grid-area:2/2/3/-1}.SPgITW_pbc .SPgITW_tq-fact{min-width:0;font:var(--dsw-font-xxs-12);font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--tq-ink-3);padding-top:2px;line-height:16px}.SPgITW_pbc .SPgITW_tq-fact[data-tq-fact=model]{white-space:normal;color:var(--tq-ink-2)}.SPgITW_pbc .SPgITW_tq-fact[data-voice=warn],.SPgITW_pbc .SPgITW_tq-caption-line [data-voice=warn]{color:var(--tq-text-warn)}.SPgITW_pbc .SPgITW_tq-caption-line{min-width:0;font:var(--dsw-font-xxs-12);font-variant-numeric:tabular-nums;overflow-wrap:anywhere;color:var(--tq-ink-3);padding-top:2px;line-height:16px}.SPgITW_pbc .SPgITW_tq-row[data-tq-row=source]>:is(.SPgITW_tq-name,.SPgITW_tq-value){font:var(--dsw-font-s-strong-14);line-height:20px}.SPgITW_pbc .SPgITW_tq-row[data-tq-row=head]>.SPgITW_tq-name{font:var(--dsw-font-xxs-strong-12);color:var(--tq-ink-3);line-height:20px}.SPgITW_pbc .SPgITW_tq-row[data-tq-row=head]>.SPgITW_tq-lead{color:var(--tq-ink-3)}.SPgITW_pbc .SPgITW_tq-tag{border:.5px solid var(--tq-pill-border);font:var(--dsw-font-xxs-12);color:var(--tq-ink-3);border-radius:999px;flex:none;padding:0 4px;line-height:16px}.SPgITW_pbc .SPgITW_tq-well{margin:4px 0 2px var(--tq-main-inset);border-radius:var(--tq-radius);background:var(--tq-well);overflow:hidden}.SPgITW_pbc .SPgITW_tq-group>.SPgITW_tq-item>.SPgITW_tq-row:is([data-tq-row=source],[data-tq-row=head]){padding-right:16px}.SPgITW_pbc .SPgITW_pp-allowance,.SPgITW_pbc .SPgITW_tq-group>.SPgITW_tq-note{margin-right:8px}.SPgITW_pbc .SPgITW_tq-well>.SPgITW_tq-item{margin:0}.SPgITW_pbc .SPgITW_tq-well .SPgITW_tq-row{border-radius:0;padding:8px}.SPgITW_pbc .SPgITW_tq-well>.SPgITW_tq-item+.SPgITW_tq-item:before{content:\"\";top:0;right:0;left:calc(8px + var(--tq-main-inset));background:var(--tq-hairline);pointer-events:none;height:.5px;position:absolute}.SPgITW_pbc .SPgITW_tq-well>.SPgITW_tq-item>.SPgITW_tq-up{width:24px;height:24px;position:absolute;top:28px;left:1px}.SPgITW_pbc .SPgITW_tq-notify{align-items:center;gap:8px;display:inline-flex}.SPgITW_pbc .SPgITW_tq-receipt{color:var(--tq-ink-3);align-items:center;gap:1px;display:inline-flex}.SPgITW_pbc .SPgITW_tq-receipt[data-state=sent]{color:var(--tq-text-ok)}.SPgITW_pbc .SPgITW_tq-receipt[data-state=failed]{color:var(--tq-text-bad)}.SPgITW_pbc .SPgITW_tq-notify-glyph,.SPgITW_pbc .SPgITW_tq-receipt-glyph{flex:none;display:block}.SPgITW_pbc .SPgITW_tq-mark{vertical-align:top;color:var(--tq-text-warn);align-items:center;gap:2px;margin-left:6px;display:inline-flex}.SPgITW_pbc .SPgITW_tq-icon-btn{width:28px;height:28px;color:var(--tq-ink-3);cursor:pointer;transition:background-color var(--tq-fast) var(--tq-ease), transform var(--tq-fast) var(--tq-ease);background:0 0;border:0;border-radius:999px;flex:none;justify-content:center;align-items:center;padding:0;display:inline-flex;position:relative}.SPgITW_pbc .SPgITW_tq-icon-btn:active{transform:scale(var(--tq-press-scale));background:var(--tq-fill-press)}.SPgITW_pbc .SPgITW_tq-icon-btn:disabled{opacity:.4;cursor:default}.SPgITW_pbc .SPgITW_tq-icon-btn.SPgITW_spin svg{animation:.8s linear infinite SPgITW_clawock-spin}.SPgITW_pbc .SPgITW_tq-actions{flex-wrap:wrap;align-items:center;gap:6px;display:flex}.SPgITW_pbc .SPgITW_tq-pill{box-sizing:border-box;border:.5px solid var(--tq-pill-border);height:26px;font:var(--dsw-font-xxs-12);font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--tq-ink);cursor:pointer;transition:background-color var(--tq-fast) var(--tq-ease), transform var(--tq-fast) var(--tq-ease);background:0 0;border-radius:999px;justify-content:center;align-items:center;gap:4px;padding:0 10px;line-height:16px;display:inline-flex;position:relative}.SPgITW_pbc .SPgITW_tq-pill[data-tq-kind=view]{background:var(--tq-fill-inset);color:var(--tq-ink-2);border-color:#0000;padding:0 10px 0 8px}.SPgITW_pbc .SPgITW_tq-pill-glyph{color:var(--tq-ink-3);flex:none;display:block}.SPgITW_pbc .SPgITW_tq-pill.SPgITW_tq-danger{color:var(--tq-text-bad)}.SPgITW_pbc .SPgITW_tq-pill[data-armed]{border-color:var(--tq-wait);background:var(--tq-chip-warn-fill);color:var(--tq-text-warn)}.SPgITW_pbc .SPgITW_tq-pill.SPgITW_tq-danger[data-armed]{border-color:var(--tq-bad);background:var(--tq-chip-bad-fill);color:var(--tq-text-bad)}.SPgITW_pbc .SPgITW_tq-pill:active{transform:scale(var(--tq-press-scale));background:var(--tq-fill-press)}.SPgITW_pbc .SPgITW_tq-pill:disabled{opacity:.4;cursor:default}.SPgITW_pbc .SPgITW_tq-pill:focus-visible{outline:var(--tq-focus-ring);outline-offset:1px}.SPgITW_pbc :is(.SPgITW_tq-row,.SPgITW_tq-icon-btn,.SPgITW_tq-back):focus-visible{outline:var(--tq-focus-ring);outline-offset:-2px}@media (hover:hover) and (pointer:fine){.SPgITW_pbc :is(.SPgITW_tq-row:not(.SPgITW_tq-static),.SPgITW_tq-icon-btn,.SPgITW_tq-back):hover:not(:disabled){background:var(--tq-fill-hover)}.SPgITW_pbc .SPgITW_tq-icon-btn:hover:not(:disabled){color:var(--tq-ink-2)}.SPgITW_pbc .SPgITW_tq-pill:hover:not(:disabled):not([data-armed]){background:var(--tq-fill-hover)}.SPgITW_pbc .SPgITW_tq-pill.SPgITW_tq-danger:hover:not(:disabled):not([data-armed]){background:var(--tq-fill-danger)}}.SPgITW_pbc .SPgITW_tq-note{min-width:0;font:var(--dsw-font-xxs-12);align-items:center;gap:6px;margin:4px 0;line-height:16px;display:flex}.SPgITW_pbc .SPgITW_tq-note.SPgITW_tq-ok{color:var(--tq-ink-2)}.SPgITW_pbc .SPgITW_tq-note.SPgITW_tq-bad{color:var(--tq-text-bad)}.SPgITW_pbc .SPgITW_tq-note.SPgITW_tq-warn{color:var(--tq-text-warn)}.SPgITW_pbc .SPgITW_tq-empty{font:var(--dsw-font-xxs-12);color:var(--tq-ink-3);padding:4px 0 6px;line-height:16px}.SPgITW_pbc .SPgITW_tq-sub.SPgITW_tq-wrap{text-overflow:clip;white-space:normal;overflow-wrap:anywhere;max-width:none;overflow:visible}.SPgITW_pbc .SPgITW_tq-chips{flex-wrap:wrap;align-items:center;gap:4px;min-width:0;display:flex}.SPgITW_pbc .SPgITW_tq-chip{box-sizing:border-box;background:var(--tq-chip-fill);max-width:100%;height:20px;font:var(--dsw-font-xxs-12);font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--tq-ink-2);border:1px solid #0000;border-radius:999px;flex:none;align-items:center;gap:4px;padding:0 8px 0 6px;line-height:16px;display:inline-flex}.SPgITW_pbc .SPgITW_tq-chip-text{min-width:0}.SPgITW_pbc .SPgITW_tq-role-glyph{flex:none;display:block}.SPgITW_pbc .SPgITW_tq-chip[data-role=run]{background:var(--tq-chip-run-fill);color:var(--tq-run)}.SPgITW_pbc .SPgITW_tq-chip[data-role=queue]{border-color:var(--tq-run);color:var(--tq-run);background:0 0}.SPgITW_pbc .SPgITW_tq-chip:is([data-role=sleep],[data-role=partial]){background:var(--tq-chip-warn-fill);color:var(--tq-text-warn)}.SPgITW_pbc .SPgITW_tq-chip:is([data-role=wait],[data-role=fallback]){border-color:var(--tq-wait);color:var(--tq-text-warn);background:0 0}.SPgITW_pbc .SPgITW_tq-chip[data-role=fail]{background:var(--tq-chip-bad-fill);color:var(--tq-text-bad)}.SPgITW_pbc .SPgITW_tq-chip[data-role=done]{background:var(--tq-chip-fill);color:var(--tq-ink-2)}.SPgITW_pbc .SPgITW_tq-chip[data-role=off]{border-color:var(--tq-chip-edge);color:var(--tq-ink-3);background:0 0}.SPgITW_pbc .SPgITW_tq-chip[data-role=unknown]{border-style:dashed;border-color:var(--tq-pill-border);color:var(--tq-ink-3);background:0 0}.SPgITW_pbc .SPgITW_tq-fold{margin:4px 0 2px var(--tq-main-inset)}.SPgITW_pbc .SPgITW_tq-fold-summary{box-sizing:border-box;border:.5px solid var(--tq-pill-border);height:26px;font:var(--dsw-font-xxs-12);color:var(--tq-ink-2);cursor:pointer;-webkit-user-select:none;user-select:none;transition:background-color var(--tq-fast) var(--tq-ease), transform var(--tq-fast) var(--tq-ease);border-radius:999px;align-items:center;gap:4px;padding:0 10px 0 7px;line-height:16px;list-style:none;display:inline-flex;position:relative}.SPgITW_pbc .SPgITW_tq-fold-summary::-webkit-details-marker{display:none}.SPgITW_pbc .SPgITW_tq-fold-summary::marker{content:\"\"}.SPgITW_pbc .SPgITW_tq-fold-chev{color:var(--tq-ink-3);transition:transform var(--tq-fast) var(--tq-ease);flex:none}.SPgITW_pbc .SPgITW_tq-fold[open]>.SPgITW_tq-fold-summary .SPgITW_tq-fold-chev{transform:rotate(90deg)}.SPgITW_pbc .SPgITW_tq-fold-summary:active{transform:scale(var(--tq-press-scale));background:var(--tq-fill-press)}.SPgITW_pbc .SPgITW_tq-fold-summary:focus-visible{outline:var(--tq-focus-ring);outline-offset:1px}@media (hover:hover) and (pointer:fine){.SPgITW_pbc .SPgITW_tq-fold-summary:hover{background:var(--tq-fill-hover)}}.SPgITW_pbc .SPgITW_tq-fold-body{margin:2px 0 0 calc(-1 * var(--tq-main-inset))}.SPgITW_pbc .SPgITW_tq-fold-body>.SPgITW_tq-log{margin:2px 0 4px var(--tq-main-inset)}.SPgITW_pbc .SPgITW_tq-foot{border-top:.5px solid var(--tq-hairline);font:var(--dsw-font-xxs-12);color:var(--tq-ink-3);margin-top:8px;padding-top:6px;line-height:16px}.SPgITW_pbc .SPgITW_tq-foot.SPgITW_tq-bad{color:var(--tq-text-bad)}.SPgITW_pbc .SPgITW_tq-d-head{padding-bottom:6px}.SPgITW_pbc .SPgITW_tq-back{height:28px;font:var(--dsw-font-xs-strong-13);color:var(--tq-ink);cursor:pointer;transition:background-color var(--tq-fast) var(--tq-ease), transform var(--tq-fast) var(--tq-ease);background:0 0;border:0;border-radius:999px;align-items:center;gap:4px;margin-left:-6px;padding:0 10px 0 8px;display:inline-flex;position:relative}.SPgITW_pbc .SPgITW_tq-back:active{transform:scale(var(--tq-press-scale));background:var(--tq-fill-press)}.SPgITW_pbc .SPgITW_tq-back-chev{border-bottom:1.5px solid;border-left:1.5px solid;width:6px;height:6px;transform:translate(1px)rotate(45deg)}.SPgITW_pbc .SPgITW_tq-d-scroll{scroll-padding-block:12px}.SPgITW_pbc .SPgITW_tq-d-sec+.SPgITW_tq-d-sec{margin-top:14px}.SPgITW_pbc .SPgITW_tq-d-sec-title{margin:0 0 2px var(--tq-main-inset);font:var(--dsw-font-xxs-strong-12);color:var(--tq-ink-3);line-height:20px}.SPgITW_pbc .SPgITW_tq-d-hero{grid-template-columns:var(--tq-grid);column-gap:var(--tq-gap);align-items:baseline;padding-top:2px;display:grid}.SPgITW_pbc .SPgITW_tq-d-hero>.SPgITW_tq-lead{grid-area:1/1}.SPgITW_pbc .SPgITW_tq-d-name{min-width:0;font:var(--dsw-font-s-strong-14);overflow-wrap:anywhere;color:var(--tq-ink);grid-area:1/2/2/5;line-height:20px}.SPgITW_pbc .SPgITW_tq-d-hero>.SPgITW_tq-chip{grid-area:1/5;justify-self:stretch}.SPgITW_pbc .SPgITW_tq-d-status{font:var(--dsw-font-xxs-12);overflow-wrap:anywhere;color:var(--tq-ink-2);grid-area:2/2/3/-1;padding-top:4px;line-height:16px}.SPgITW_pbc .SPgITW_tq-d-status[data-balance-state=ok]{color:var(--tq-ink-2)}.SPgITW_pbc .SPgITW_tq-d-status[data-balance-state=stale]{color:var(--tq-text-warn)}.SPgITW_pbc .SPgITW_tq-d-status[data-balance-state=low]{color:var(--tq-text-bad)}.SPgITW_pbc .SPgITW_tq-d-fields{margin:0;padding:0}.SPgITW_pbc .SPgITW_tq-d-field{grid-template-columns:var(--tq-grid);column-gap:var(--tq-gap);align-items:baseline;padding:3px 0;display:grid}.SPgITW_pbc .SPgITW_tq-d-field>:is(dt,dd){min-width:0;margin:0}.SPgITW_pbc .SPgITW_tq-d-k{font:var(--dsw-font-xxs-12);overflow-wrap:break-word;color:var(--tq-ink-3);grid-area:1/2;line-height:16px}.SPgITW_pbc .SPgITW_tq-d-v{font:var(--dsw-font-xxs-12);font-variant-numeric:tabular-nums;overflow-wrap:break-word;color:var(--tq-ink);grid-area:1/3/2/-1;line-height:16px}.SPgITW_pbc .SPgITW_tq-d-has-control>.SPgITW_tq-d-v{grid-column:3/5}.SPgITW_pbc .SPgITW_tq-d-v[data-voice=warn]{color:var(--tq-text-warn)}.SPgITW_pbc .SPgITW_tq-d-v.SPgITW_tq-mono{word-break:break-all;color:var(--tq-ink-2)}.SPgITW_pbc .SPgITW_tq-d-sub{font:var(--dsw-font-xxs-12);overflow-wrap:break-word;color:var(--tq-ink-3);grid-area:2/3/3/-1;padding-top:2px;line-height:16px}.SPgITW_pbc .SPgITW_tq-d-control{grid-area:1/5;justify-self:end;gap:6px;display:flex}.SPgITW_pbc .SPgITW_tq-d-control-wide{flex-wrap:wrap;grid-area:3/3/4/-1;justify-self:start;padding-top:6px}.SPgITW_pbc .SPgITW_tq-d-after{grid-area:4/2/5/-1}.SPgITW_pbc .SPgITW_tq-d-after>:first-child{margin-top:6px}.SPgITW_pbc .SPgITW_tq-d-lines{flex-direction:column;gap:4px;display:flex}.SPgITW_pbc .SPgITW_pp-allowance.SPgITW_tq-d-windows{margin:0}.SPgITW_pbc .SPgITW_tq-d-sec>:is(.SPgITW_tq-actions,.SPgITW_tq-brief,.SPgITW_tq-log,.SPgITW_tq-d-summary,.SPgITW_tq-empty,.SPgITW_tq-note){margin-left:var(--tq-main-inset)}.SPgITW_pbc .SPgITW_tq-d-sec>:is(.SPgITW_tq-brief,.SPgITW_tq-log,.SPgITW_tq-note){margin-top:8px}.SPgITW_pbc .SPgITW_tq-confirm{flex-direction:column;align-items:flex-start;gap:6px}.SPgITW_pbc .SPgITW_tq-d-notice{border-top:.5px solid var(--tq-hairline);font:var(--dsw-font-xxs-12);overflow-wrap:anywhere;color:var(--tq-ink-2);flex:none;padding:8px 12px;line-height:16px}.SPgITW_pbc .SPgITW_tq-d-notice:empty{border-top:0;padding:0}.SPgITW_pbc .SPgITW_tq-d-notice.SPgITW_tq-bad{color:var(--tq-text-bad)}@media (pointer:coarse){.SPgITW_pbc .SPgITW_tq-d-sec .SPgITW_tq-pill:after{inset:-9px -8px}}.SPgITW_pbc .SPgITW_tq-inline{flex-wrap:wrap;align-items:center;gap:5px;display:inline-flex}.SPgITW_pbc .SPgITW_tq-mono{font-family:var(--tq-mono)}.SPgITW_pbc .SPgITW_tq-picker{border-radius:var(--tq-radius-sm);background:var(--tq-fill-hover);flex-direction:column;gap:6px;margin-top:8px;padding:10px;display:flex}.SPgITW_pbc .SPgITW_tq-field{font:var(--dsw-font-xxs-12);color:var(--tq-ink-3);grid-template-columns:auto minmax(0,1fr);align-items:center;gap:8px;display:grid}.SPgITW_pbc .SPgITW_tq-field select{border:.5px solid var(--tq-pill-border);border-radius:var(--tq-radius-sm);min-width:0;height:28px;font:inherit;color:var(--tq-ink-2);background:0 0;padding:0 8px}.SPgITW_pbc .SPgITW_tq-field select:focus-visible{outline:var(--tq-focus-ring);outline-offset:-2px}.SPgITW_pbc .SPgITW_tq-log{border-radius:var(--tq-radius-sm);background:var(--tq-fill-hover);max-height:220px;font:var(--dsw-font-markdown-code-block);white-space:pre-wrap;overflow-wrap:anywhere;color:var(--tq-ink-2);margin:10px 0 0;padding:8px 10px;overflow:auto}.SPgITW_pbc .SPgITW_tq-picker-actions{gap:6px;display:flex}.SPgITW_pbc .SPgITW_tq-d-summary{border-radius:var(--tq-radius-sm);background:var(--tq-fill-hover);font:var(--dsw-font-xxs-12);white-space:pre-wrap;overflow-wrap:anywhere;color:var(--tq-ink-2);margin:0;padding:8px 10px}@media (prefers-reduced-transparency:reduce){.SPgITW_pbc.SPgITW_pbf.SPgITW_tqf .SPgITW_bp:before{background:var(--dsw-alias-bg-layer-1);backdrop-filter:none}}@supports not (backdrop-filter:blur(1px)){.SPgITW_pbc.SPgITW_pbf.SPgITW_tqf .SPgITW_bp:before{background:var(--dsw-alias-bg-layer-1)}}@media (prefers-reduced-motion:reduce){.SPgITW_pbc .SPgITW_tq-icon-btn.SPgITW_spin svg{animation:none}.SPgITW_pbc :is(.SPgITW_tq-icon-btn,.SPgITW_tq-pill,.SPgITW_tq-back,.SPgITW_tq-fold-summary):active{transform:none}.SPgITW_pbc .SPgITW_tq-fold-chev{transition:none}}@media (pointer:coarse){.SPgITW_pbc .SPgITW_tq-row:not(.SPgITW_tq-static){min-height:44px}.SPgITW_pbc :is(.SPgITW_tq-icon-btn,.SPgITW_tq-pill,.SPgITW_tq-back,.SPgITW_tq-fold-summary):after{content:\"\";position:absolute;inset:-8px}.SPgITW_pbc .SPgITW_tq-fold-summary:after{inset:-9px -8px}.SPgITW_pbc .SPgITW_tq-field select{height:36px}}@media (width<=520px){.SPgITW_pbc.SPgITW_pbf.SPgITW_tqf .SPgITW_bp{width:min(360px,100vw - 24px)}}@media (width<=380px){.SPgITW_pbc.SPgITW_tqf{--tq-when:60px;--tq-took:60px;--tq-aside:104px}}.SPgITW_pbc.SPgITW_pbf.SPgITW_ppf{height:auto;margin:8px 0 0;display:block}.SPgITW_pbc.SPgITW_pbf.SPgITW_ppf.SPgITW_rail{width:36px;height:36px;margin:0;display:flex}.SPgITW_pbc.SPgITW_ppf .SPgITW_pp-rows{grid-template-columns:calc(var(--tq-lead) + 8px) minmax(0, 1fr) auto auto;column-gap:var(--tq-gap);margin:0 -2px;display:grid}.SPgITW_pbc.SPgITW_ppf .SPgITW_pp-row{grid-column:1/-1;grid-template-columns:var(--tq-grid);grid-template-columns:subgrid;box-sizing:border-box;border-radius:var(--tq-radius);width:100%;min-height:28px;font:var(--dsw-font-xxs-12);text-align:left;color:var(--tq-ink);cursor:pointer;transition:background-color var(--tq-fast) var(--tq-ease), transform var(--tq-fast) var(--tq-ease);background:0 0;border:0;padding:0 8px;line-height:16px}.SPgITW_pbc.SPgITW_ppf .SPgITW_pp-row>.SPgITW_tq-name{white-space:nowrap;max-width:96px;overflow:hidden}.SPgITW_pbc.SPgITW_ppf .SPgITW_pp-row>.SPgITW_tq-chip[data-tq-chip=status]{grid-column:4;justify-self:stretch}.SPgITW_pbc.SPgITW_ppf .SPgITW_pp-row[data-active]{background:var(--tq-fill-hover)}.SPgITW_pbc.SPgITW_ppf .SPgITW_pp-row:active{background:var(--tq-fill-press)}.SPgITW_pbc.SPgITW_ppf .SPgITW_pp-row:focus-visible,.SPgITW_pbc.SPgITW_ppf .SPgITW_pp-group:focus-visible,.SPgITW_pbc .SPgITW_tq-file:focus-visible{outline:var(--tq-focus-ring);outline-offset:-2px}.SPgITW_pbc.SPgITW_ppf .SPgITW_pp-group:focus{outline:none}.SPgITW_pbc.SPgITW_ppf .SPgITW_pp-group:focus-visible{border-radius:var(--tq-radius-sm)}@media (hover:hover) and (pointer:fine){.SPgITW_pbc.SPgITW_ppf .SPgITW_pp-row:hover,.SPgITW_pbc .SPgITW_tq-file:hover{background:var(--tq-fill-hover)}}.SPgITW_pbc.SPgITW_ppf .SPgITW_pp-empty{align-items:center;gap:var(--tq-gap);display:flex}.SPgITW_pbc.SPgITW_ppf .SPgITW_pp-name{font:var(--dsw-font-xs-strong-13);flex:none;line-height:16px}.SPgITW_pbc.SPgITW_ppf .SPgITW_pp-last{text-overflow:ellipsis;white-space:nowrap;min-width:0;color:var(--tq-ink-3);overflow:hidden}.SPgITW_pbc.SPgITW_ppf .SPgITW_bal-badge[data-balance-state=low]{fill:var(--tq-wait)}.SPgITW_pbc.SPgITW_ppf .SPgITW_bal-badge[data-balance-state=stale]{fill:none;stroke:var(--tq-bad)}.SPgITW_pbc .SPgITW_tq-inset{margin-left:var(--tq-main-inset)}.SPgITW_pbc .SPgITW_pp-allowance{margin-top:0;margin-bottom:6px}.SPgITW_pbc .SPgITW_pp-allowance :is(.SPgITW_bp-win-label,.SPgITW_bp-win-reset,.SPgITW_bp-sub){font:var(--dsw-font-xxs-12);letter-spacing:0;font-variant-numeric:tabular-nums;color:var(--tq-ink-2);line-height:16px}.SPgITW_pbc .SPgITW_pp-allowance .SPgITW_bp-win-pct{font:var(--dsw-font-xxs-strong-12);font-variant-numeric:tabular-nums;color:var(--tq-ink);line-height:16px}.SPgITW_pbc .SPgITW_tq-brief{flex-direction:column;gap:2px;margin-top:8px;display:flex}.SPgITW_pbc .SPgITW_tq-file{border-radius:var(--tq-radius);min-height:28px;font:var(--dsw-font-xxs-12);text-align:left;color:var(--tq-ink-2);cursor:pointer;transition:background-color var(--tq-fast) var(--tq-ease), transform var(--tq-fast) var(--tq-ease);background:0 0;border:0;justify-content:space-between;align-items:center;gap:8px;margin:0 -8px;padding:4px 8px;display:flex;position:relative}.SPgITW_pbc .SPgITW_tq-file:active{background:var(--tq-fill-press)}.SPgITW_pbc .SPgITW_tq-file-name{text-overflow:ellipsis;white-space:nowrap;text-underline-offset:2px;min-width:0;text-decoration:underline;overflow:hidden}.SPgITW_pbc .SPgITW_tq-tag[data-tq-delivered=false]{border-color:var(--tq-wait);color:var(--tq-text-warn)}@media (pointer:coarse){.SPgITW_pbc.SPgITW_ppf .SPgITW_pp-row,.SPgITW_pbc .SPgITW_tq-file{min-height:44px}}.SPgITW_pbc.SPgITW_pbf.SPgITW_ppf .SPgITW_pp-rail{flex:none}@media (width<=520px){.SPgITW_pbc.SPgITW_pbf.SPgITW_tqf .SPgITW_bp:before{background:color-mix(in srgb, var(--dsw-alias-bg-layer-1) 96%, var(--dsw-specific-menu))}}@media (prefers-reduced-transparency:reduce){.SPgITW_pbc.SPgITW_pbf.SPgITW_tqf .SPgITW_bp:before{background:var(--dsw-alias-bg-layer-1)}}";
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
	"bal-badge": "SPgITW_bal-badge",
	"bal-glyph": "SPgITW_bal-glyph",
	"bal-lead": "SPgITW_bal-lead",
	"bal-rf": "SPgITW_bal-rf",
	"bar": "SPgITW_bar",
	"bchip": "SPgITW_bchip",
	"bchip-dot": "SPgITW_bchip-dot",
	"bchip-item": "SPgITW_bchip-item",
	"bchip-name": "SPgITW_bchip-name",
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
	"fill-v": "SPgITW_fill-v",
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
	"pbf": "SPgITW_pbf",
	"pc": "SPgITW_pc",
	"pchips": "SPgITW_pchips",
	"pnl": "SPgITW_pnl",
	"pnlk": "SPgITW_pnlk",
	"pp-allowance": "SPgITW_pp-allowance",
	"pp-empty": "SPgITW_pp-empty",
	"pp-group": "SPgITW_pp-group",
	"pp-last": "SPgITW_pp-last",
	"pp-name": "SPgITW_pp-name",
	"pp-rail": "SPgITW_pp-rail",
	"pp-row": "SPgITW_pp-row",
	"pp-rows": "SPgITW_pp-rows",
	"ppf": "SPgITW_ppf",
	"qty": "SPgITW_qty",
	"rail": "SPgITW_rail",
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
	"tq-actions": "SPgITW_tq-actions",
	"tq-agent-glyph": "SPgITW_tq-agent-glyph",
	"tq-back": "SPgITW_tq-back",
	"tq-back-chev": "SPgITW_tq-back-chev",
	"tq-bad": "SPgITW_tq-bad",
	"tq-brief": "SPgITW_tq-brief",
	"tq-caption": "SPgITW_tq-caption",
	"tq-caption-line": "SPgITW_tq-caption-line",
	"tq-chip": "SPgITW_tq-chip",
	"tq-chip-text": "SPgITW_tq-chip-text",
	"tq-chips": "SPgITW_tq-chips",
	"tq-confirm": "SPgITW_tq-confirm",
	"tq-count": "SPgITW_tq-count",
	"tq-d-after": "SPgITW_tq-d-after",
	"tq-d-control": "SPgITW_tq-d-control",
	"tq-d-control-wide": "SPgITW_tq-d-control-wide",
	"tq-d-field": "SPgITW_tq-d-field",
	"tq-d-fields": "SPgITW_tq-d-fields",
	"tq-d-has-control": "SPgITW_tq-d-has-control",
	"tq-d-head": "SPgITW_tq-d-head",
	"tq-d-hero": "SPgITW_tq-d-hero",
	"tq-d-k": "SPgITW_tq-d-k",
	"tq-d-lines": "SPgITW_tq-d-lines",
	"tq-d-name": "SPgITW_tq-d-name",
	"tq-d-notice": "SPgITW_tq-d-notice",
	"tq-d-scroll": "SPgITW_tq-d-scroll",
	"tq-d-sec": "SPgITW_tq-d-sec",
	"tq-d-sec-title": "SPgITW_tq-d-sec-title",
	"tq-d-status": "SPgITW_tq-d-status",
	"tq-d-sub": "SPgITW_tq-d-sub",
	"tq-d-summary": "SPgITW_tq-d-summary",
	"tq-d-v": "SPgITW_tq-d-v",
	"tq-d-windows": "SPgITW_tq-d-windows",
	"tq-danger": "SPgITW_tq-danger",
	"tq-detail": "SPgITW_tq-detail",
	"tq-dot": "SPgITW_tq-dot",
	"tq-empty": "SPgITW_tq-empty",
	"tq-fact": "SPgITW_tq-fact",
	"tq-field": "SPgITW_tq-field",
	"tq-file": "SPgITW_tq-file",
	"tq-file-name": "SPgITW_tq-file-name",
	"tq-fold": "SPgITW_tq-fold",
	"tq-fold-body": "SPgITW_tq-fold-body",
	"tq-fold-chev": "SPgITW_tq-fold-chev",
	"tq-fold-summary": "SPgITW_tq-fold-summary",
	"tq-foot": "SPgITW_tq-foot",
	"tq-group": "SPgITW_tq-group",
	"tq-head": "SPgITW_tq-head",
	"tq-icon-btn": "SPgITW_tq-icon-btn",
	"tq-inline": "SPgITW_tq-inline",
	"tq-inset": "SPgITW_tq-inset",
	"tq-item": "SPgITW_tq-item",
	"tq-layer": "SPgITW_tq-layer",
	"tq-lead": "SPgITW_tq-lead",
	"tq-list": "SPgITW_tq-list",
	"tq-log": "SPgITW_tq-log",
	"tq-mark": "SPgITW_tq-mark",
	"tq-mono": "SPgITW_tq-mono",
	"tq-name": "SPgITW_tq-name",
	"tq-note": "SPgITW_tq-note",
	"tq-notify": "SPgITW_tq-notify",
	"tq-notify-glyph": "SPgITW_tq-notify-glyph",
	"tq-ok": "SPgITW_tq-ok",
	"tq-picker": "SPgITW_tq-picker",
	"tq-picker-actions": "SPgITW_tq-picker-actions",
	"tq-pill": "SPgITW_tq-pill",
	"tq-pill-glyph": "SPgITW_tq-pill-glyph",
	"tq-receipt": "SPgITW_tq-receipt",
	"tq-receipt-glyph": "SPgITW_tq-receipt-glyph",
	"tq-role-glyph": "SPgITW_tq-role-glyph",
	"tq-row": "SPgITW_tq-row",
	"tq-scroll": "SPgITW_tq-scroll",
	"tq-section": "SPgITW_tq-section",
	"tq-static": "SPgITW_tq-static",
	"tq-sub": "SPgITW_tq-sub",
	"tq-tag": "SPgITW_tq-tag",
	"tq-title": "SPgITW_tq-title",
	"tq-up": "SPgITW_tq-up",
	"tq-value": "SPgITW_tq-value",
	"tq-warn": "SPgITW_tq-warn",
	"tq-well": "SPgITW_tq-well",
	"tq-wrap": "SPgITW_tq-wrap",
	"tqf": "SPgITW_tqf",
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
//#region src/providers.ts
/**
* Rows in the order the panel lists them (kcn, 2026-09-27): the paid,
* exclusive allowances first — the two subscriptions, then the balance and
* the token plan — and the free pool last. opencode sits low not because it
* is weaker but because it is free and interchangeable: its models replace
* one another inside the pool, so it is one line for the whole pool, never a
* line per model.
*/
const PROVIDER_JOIN = [
	{
		provider: "claude",
		agent: "claude",
		kind: "windows",
		tier: "paid",
		plan: "panel.plan.anthropic"
	},
	{
		provider: "codex",
		agent: "codex",
		kind: "windows",
		tier: "paid",
		plan: "panel.plan.chatgpt"
	},
	{
		provider: "deepseek",
		agent: null,
		kind: "money",
		tier: "paid",
		plan: "panel.plan.deepseek"
	},
	{
		provider: "minimax",
		agent: null,
		kind: "windows",
		tier: "paid",
		plan: "panel.plan.minimax"
	},
	{
		provider: null,
		agent: "opencode",
		kind: "pool",
		tier: "free",
		plan: "panel.plan.freePool"
	}
];
/**
* A source's place: its row's index, times two. A provider or agent without a
* row costs an unknown amount, so it is treated as scarce: after the known
* paid rows, before the free ones (the odd slot between them).
*/
function sourceRank(key) {
	const at = PROVIDER_JOIN.findIndex((join) => key.provider != null && join.provider === key.provider || key.agent != null && join.agent === key.agent);
	if (at >= 0) return at * 2;
	const free = PROVIDER_JOIN.findIndex((join) => join.tier === "free");
	return (free < 0 ? PROVIDER_JOIN.length : free) * 2 - 1;
}
/** Items that belong to an agent (tasks, slot lanes) in the panel's order; stable, so newest-first stays newest-first within an agent. */
function byAgentRank(items) {
	return items.map((item, at) => ({
		item,
		at,
		rank: sourceRank({ agent: item.agent })
	})).sort((a, b) => a.rank - b.rank || a.at - b.at).map(({ item }) => item);
}
//#endregion
//#region src/copy.ts
/** Dictionary namespace declared by every registration in this bundle. */
const LOCALE_NS = "clawock";
/**
* This plugin's copy, in the locales the browser client ships (`zh`, `en` —
* `dsh-client-locale`'s LOCALE_IDS). Keys are grouped by surface; the two
* dictionaries must carry the same key set, which `tests/decision_studio_plugin.spec.js`
* enforces so a missing translation cannot ship.
*/
const dictionaries = {
	zh: {
		"action.buy": "买入",
		"action.add": "加仓",
		"action.trim": "减仓",
		"action.sell": "卖出",
		"action.cut": "割肉",
		"action.hold": "持有",
		"action.trim_on_rebound": "反弹减仓",
		"action.t_only": "仅T+0",
		"action.add_only_on_trigger": "触发加仓",
		"action.reject": "不加",
		"action.watch": "观望",
		"action.abstain": "弃权",
		"driver.technical": "技术面",
		"driver.fundamental": "基本面",
		"driver.sentiment": "情绪面",
		"driver.mixed": "混合",
		"driver.risk_rule": "风控规则",
		"driver.catalyst": "催化",
		"driver.influencer": "影响力",
		"driver.macro": "宏观",
		"driver.peer": "同行",
		"exe.followed": "遵守了计划",
		"exe.not_followed": "没按计划",
		"exe.unknown": "未标注",
		"align.same": "与计划同向",
		"align.opposite": "与计划反向",
		"align.other": "计划未指向买卖",
		"emo.fomo": "追高冲动",
		"emo.revenge": "报复性",
		"emo.averaging_down": "摊薄冲动",
		"emo.fear": "恐慌",
		"emo.euphoria": "亢奋",
		"emo.calm": "平静",
		"emo.mixed": "混合",
		"filter.all": "全部",
		"filter.miss": "无当日计划",
		"filter.sold": "卖出复盘",
		"filter.dec": "有当日计划",
		"t1.up": "涨",
		"t1.down": "跌",
		"t1.soldEarly": "卖飞",
		"t1.soldRight": "卖对",
		"t1.flat": "持平",
		"time.today": "今天",
		"time.yesterday": "昨天",
		"time.daysAgo": "{days}天前",
		"time.date": "{month}月{day}日",
		"time.weekday.0": "周日",
		"time.weekday.1": "周一",
		"time.weekday.2": "周二",
		"time.weekday.3": "周三",
		"time.weekday.4": "周四",
		"time.weekday.5": "周五",
		"time.weekday.6": "周六",
		"trace.title": "决策轨迹",
		"trace.subtitle": "一笔真实成交 + 当时写下的计划 + 官方收盘给的结果",
		"trace.staleSuffix": " · 更新失败,显示此前快照",
		"trace.unreadable": "读不到工作区的 portfolio.json(CLAWOCK_WORKSPACE 未指向 clawock 工作区,或账本无法解析),不是没有成交",
		"trace.titleWithPlan": "决策轨迹 · {date}",
		"trace.titleNoPlan": "决策轨迹 · 无当日计划",
		"trace.planThen": "当时的计划",
		"trace.noPlanRecord": "这一天没有该标的的计划记录",
		"trace.realFill": "真实成交",
		"trace.t1Close": "T+1 收盘",
		"trace.t1Pending": "T+1 未判",
		"trace.unpaired": "这笔成交在决策账本里找不到前后 3 天的同标的计划:成交是真的,当时的判断没有留下记录。",
		"trace.sharesAt": " 股 @ ",
		"trace.shares": " 股",
		"trace.confidence": " · 信心 ",
		"trace.trigger": "触发条件: ",
		"trace.selfGrade": "账本自评: ",
		"trace.realized": "本笔已实现",
		"trace.pnl": "本笔盈亏",
		"trace.openPosition": "— 未平仓",
		"trace.floating": "该持仓当前浮动 ({ticker} 全仓,非本笔)",
		"trace.why": "为什么 ",
		"trace.emotion": "情绪 ",
		"trace.note": "备注 ",
		"trace.holding": "持仓",
		"trace.opposite": "反向",
		"trace.market.hk": "港",
		"trace.market.us": "美",
		"trace.realizedUsd": "已实现 (USD 等值)",
		"trace.realizedUsdNoRate": "已实现 (USD 等值 · HKD 未折算)",
		"trace.t1Tally": "T+1 卖飞/卖对/持平 · 判出 {rated}/{sells} 笔卖出",
		"trace.t1Sideless": " · {sideless} 笔无侧向",
		"trace.matched": "有当日计划",
		"trace.reversed": " · 反向 {reversed}",
		"trace.more": "显示更早的 {fills} 笔成交",
		"trace.less": "收起,只显示最近 {groups} 组",
		"trace.empty": "没有符合条件的成交",
		"trace.fillCount": "{count} 笔成交",
		"balance.loading": "余额加载中",
		"balance.unconfigured": "未配置",
		"balance.unconfiguredKey": "未配置 API Key",
		"balance.fetchFailed": "余额获取失败",
		"balance.windowsUsed": "配额窗口已使用",
		"balance.apiBalance": "API 余额",
		"balance.granted": "赠金 ",
		"balance.toppedUp": "充值 ",
		"balance.insufficient": "官方接口判定余额不足",
		"balance.staleWith": "刷新失败,显示最近一次: {message}",
		"balance.stale": "刷新失败,显示最近一次",
		"balance.windowAt": "窗口已使用达 {percent}%",
		"balance.lowMoney": "余额偏低,低于阈值 {amount}",
		"balance.panelTitle": "各模型服务余额",
		"balance.panelHeading": "API 余额",
		"balance.refreshAll": "刷新全部余额",
		"balance.refreshNow": "立即刷新",
		"balance.readFailed": "余额读取失败:{message}",
		"balance.reading": "正在读取各服务余额…",
		"balance.noProviders": "没有可用的余额来源",
		"balance.otherProviders": "(点击查看其他服务)",
		"balance.unknownError": "未知错误",
		"balance.windowNote": "{label} 已用 {percent}%",
		"balance.windowNoteReset": "{label} 已用 {percent}%,{reset} 重置",
		"balance.window.week": "周",
		"balance.window.days": "{n}天",
		"balance.window.hours": "{n}h",
		"balance.window.minutes": "{n}m",
		"balance.reset.today": "今天 {time}",
		"balance.reset.tomorrow": "明天 {time}",
		"balance.reset.dated": "{date} {weekday} {time}",
		"queue.name": "任务",
		"queue.panelTitle": "派发任务队列",
		"queue.panelHeading": "派发队列",
		"queue.refresh": "刷新任务队列",
		"queue.running": "在跑 {n}",
		"queue.slotsHeading": "运行槽 · 按 agent",
		"queue.lane": "{agent} {used}/{max}",
		"queue.laneNoMax": "{agent} {used}",
		"queue.lanesTitle": "运行槽按 agent 分:每个 agent 只用自己的槽,互不挤占;排队看各自那一格",
		"queue.queued": "排队 {n}",
		"queue.memoryWait": "等内存 {n}",
		"queue.quotaWait": "等额度 {n}",
		"queue.retryWait": "等重试 {n}",
		"queue.idle": "没有在跑的任务",
		"queue.readFailed": "任务队列读取失败:{message}",
		"queue.staleWith": "刷新失败,显示最近一次: {message}",
		"queue.state.running": "运行中",
		"queue.state.runningSlot": "运行中 · 槽 {slot}",
		"queue.state.starting": "启动中",
		"queue.wait.lock": "等 {agent} 锁",
		"queue.wait.slot": "等 {agent} 运行槽",
		"queue.wait.memory": "等内存",
		"queue.wait.quota": "等额度 · {time} 续跑",
		"queue.wait.quotaNoTime": "等额度",
		"queue.wait.retry": "重试等待 · {time}",
		"queue.wait.retryNoTime": "重试等待",
		"queue.meta": "{agent} · {model}",
		"queue.run": "已跑 {elapsed} · 第 {attempts} 次",
		"queue.stalls": "卡死 {n}",
		"queue.waitHeading": "排队 / 等待",
		"queue.noneRunning": "没有占用运行槽的任务",
		"queue.noneWaiting": "没有排队或等待的任务",
		"queue.recentHeading": "最近结束",
		"queue.waited": "首次排队 {time}",
		"queue.d.waited": "首次排队",
		"queue.waitUnknown": "排队耗时未记录",
		"queue.execution.ok": "执行完成",
		"queue.execution.failed": "执行失败",
		"queue.execution.cancelled": "已取消",
		"queue.execution.timeout": "已超时",
		"queue.execution.blocked": "执行受阻",
		"queue.execution.quota": "额度中止",
		"queue.execution.queued": "未启动",
		"queue.execution.unknown": "结果未明",
		"queue.report.DONE": "任务：完成",
		"queue.report.claimedDone": "任务：自报完成",
		"queue.report.PARTIAL": "任务：部分完成",
		"queue.report.BLOCKED": "任务：受阻",
		"queue.report.unknown": "任务：未报告",
		"queue.statusLegend": "前项是 runner 对执行过程的判决；“任务”是模型最终报告。执行完成但任务部分完成或受阻，表示机器运行正常、工作尚未做完。",
		"queue.olderRounds": "更早的 {n} 轮",
		"queue.supervisorLog": "监督器原始记录",
		"queue.patrol.waitSlot": "等空闲运行槽",
		"queue.patrol.giveWay": "让手工任务先行",
		"queue.patrol.memory": "内存不足，暂缓",
		"queue.patrol.memoryUnread": "读不到内存，暂缓",
		"queue.patrol.otherReason": "让路（原因见原始记录）",
		"queue.patrol.wrapUp": "收尾后让路",
		"queue.patrol.forTask": "等待中的任务 {id}",
		"queue.round.preempted": "让路取消",
		"queue.round.yielded": "让路收尾",
		"queue.round.name": "{round} · {axis}",
		"queue.chip.elapsed": "已跑 {time}",
		"queue.chip.took": "用时 {time}",
		"queue.chip.cost": "估算费用（按 API 价，非实际扣费）",
		"queue.chip.unpriced": "未定价",
		"queue.patrolHeading": "巡检",
		"queue.patrolRound": "当前轮次 {round}",
		"queue.roundsHeading": "最近几轮",
		"queue.patrol.running": "巡检运行中",
		"queue.patrol.yielding": "巡检让路中",
		"queue.patrol.waiting": "巡检等待下一轮",
		"queue.patrol.waitingUntil": "巡检 {time} 开下一轮",
		"queue.patrol.stopped": "巡检已停",
		"queue.patrol.unknown": "巡检状态未知",
		"queue.patrolState.running": "运行中",
		"queue.patrolState.yielding": "让路中",
		"queue.patrolState.waiting": "等下一轮",
		"queue.patrolState.waitingUntil": "{time} 开下一轮",
		"queue.patrolState.stopped": "已停",
		"queue.patrolState.unknown": "状态未知",
		"queue.duration.minutes": "{m} 分",
		"queue.duration.hours": "{h} 小时 {m} 分",
		"queue.ago.now": "刚刚",
		"queue.ago.minutes": "{m} 分钟前",
		"queue.ago.hours": "{h} 小时前",
		"queue.ago.days": "{d} 天前",
		"queue.wait.lockAt": "等 {agent} 锁 · 第 {n} 位",
		"queue.state.cancelling": "取消中",
		"queue.attempt": "第 {n} 次",
		"queue.slotCount": "槽 {used}/{max}",
		"queue.tag.running": "运行中",
		"queue.tag.runningSlot": "运行 · 槽 {slot}",
		"queue.tag.starting": "启动中",
		"queue.tag.cancelling": "取消中",
		"queue.tag.queued": "排队",
		"queue.tag.queuedAt": "排队 #{n}",
		"queue.tag.slot": "等运行槽",
		"queue.tag.memory": "等内存",
		"queue.tag.quota": "等额度",
		"queue.tag.retry": "重试等待",
		"queue.fact.wakes": "{time} 续跑",
		"queue.fact.startedAt": "{time} 开始",
		"queue.fact.queuedAt": "{time} 起排队",
		"queue.chip.waiting": "已等 {time}",
		"queue.fallback": "fallback",
		"queue.patrolTag": "巡检",
		"queue.noRunnerApi": "无 RUNNER_API 2：不在排队顺序里，不能调整顺序或模型",
		"queue.holderOther": "锁被 {id} 占着",
		"queue.holderUnnamed": "锁被占着，但没有登记持有者（刚好在拿锁，或不是当前 runner 起的任务）",
		"queue.quotaHint": "额度用尽，{time} 恢复（{by} 触发）；其余任务等到那时再排",
		"queue.ops.missing": "ops 入口不可用，操作已停用：{error}",
		"queue.ops.skew": "ops 入口与仓库不一致（主机 {host} / 仓库 {repo}），运行 ops/host/install_task_queue_ops.sh",
		"queue.ops.version": "ops {v}",
		"queue.ops.footer": "ops {v} · runner api {runner}",
		"queue.ch.weixin": "微信",
		"queue.ch.telegram": "Telegram",
		"queue.notify.sent": "{ch} 已送达",
		"queue.notify.failed": "{ch} 失败",
		"queue.notify.planned": "{ch} 结束时通知",
		"queue.d.place": "排队",
		"queue.d.placeValue": "{agent} 队列第 {n} 位",
		"queue.d.protected": "已等满公平窗口，不会被插队",
		"queue.d.priorityValue": "优先级 {n}",
		"queue.d.queued": "开始排队",
		"queue.d.notify": "通知",
		"queue.d.notifyNone": "不通知",
		"queue.d.runner": "Runner",
		"queue.d.session": "会话",
		"queue.d.fallbackFrom": "请求 {model}，已切换",
		"queue.d.effortDefault": "默认",
		"queue.a.top": "置顶",
		"queue.a.up": "上移",
		"queue.a.upOf": "上移 {name}",
		"queue.a.down": "下移",
		"queue.a.model": "换模型",
		"queue.a.wrapup": "体面收尾",
		"queue.a.wrapupTitle": "排队一条收尾指令：做完当前一步后提交已完成的部分并输出 STATUS",
		"queue.a.cancel": "取消",
		"queue.a.cancelConfirm": "确认取消",
		"queue.a.retry": "重试",
		"queue.a.log": "日志",
		"queue.a.save": "保存",
		"queue.a.close": "关闭",
		"queue.a.modelHint": "下一次尝试生效；正在跑的这一步不受影响。",
		"queue.a.cancelQueued": "它还没开始：取消没有损失。再点一次确认。",
		"queue.a.cancelSleeping": "它在等额度/重试：取消后不再续跑，会话保留可 resume。再点一次确认。",
		"queue.a.cancelRunning": "它正在跑：本轮进度会丢；会话 {session} 可用 --resume 续。再点一次确认。",
		"queue.a.dismissConfirm": "保留原状",
		"queue.a.reading": "读取中…",
		"queue.a.readFailed": "读取失败：{message}",
		"queue.r.failed": "没成功：{message}",
		"queue.r.cancelledQueued": "已取消（尚未开始，无损失）",
		"queue.r.cancelledRunning": "已停止，本轮进度已丢；续跑：{resume}",
		"queue.r.cancelledNoSession": "已停止（还没有会话可续）",
		"queue.r.priority": "现在排第 {n} 位（共 {total}）",
		"queue.r.model": "下一次尝试：{model} · {effort}",
		"queue.r.retry": "已作为新任务续跑：{id}",
		"queue.r.wrapup": "收尾指令已排队：当前一步结束后送达",
		"queue.back": "返回额度与队列",
		"queue.d.open": "查看任务详情",
		"queue.d.live": "进行中",
		"queue.d.ended": "已结束",
		"queue.d.agent": "Agent",
		"queue.d.model": "模型",
		"queue.d.started": "开始",
		"queue.d.elapsed": "已运行",
		"queue.d.took": "用时",
		"queue.d.endedAt": "结束",
		"queue.d.resumes": "续跑",
		"queue.d.attempts": "尝试次数",
		"queue.d.stalls": "判卡死",
		"queue.d.stallsValue": "{n} 次(静默无进展,已自动重试)",
		"queue.d.latest": "最近事件",
		"queue.d.id": "任务 ID",
		"queue.d.summary": "结果摘要",
		"queue.d.noSummary": "没有留下结果摘要",
		"panel.title": "额度 · 队列",
		"panel.aria": "各 provider 的额度与派发队列",
		"panel.refresh": "刷新额度与队列",
		"panel.plan.anthropic": "Anthropic 订阅",
		"panel.plan.chatgpt": "ChatGPT 订阅",
		"panel.plan.freePool": "无 provider · 免费池",
		"panel.plan.deepseek": "本机 API 账户",
		"panel.plan.minimax": "Token Plan · 源：OpenClaw 配置",
		"panel.pool": "池 {current} → 下一个 {next}",
		"panel.poolOrder": "（表序）",
		"panel.poolSize": "池内 {n} 个",
		"panel.poolSwap": "{n} 个免费模型同档互替",
		"panel.poolUnread": "池文件未读到（需 host 半边新版，重启 dsh 后可见）",
		"queue.verdict.done": "完成",
		"queue.verdict.partial": "部分完成",
		"queue.verdict.blocked": "受阻",
		"queue.verdict.failed": "失败",
		"queue.verdict.timeout": "超时",
		"queue.verdict.cancelled": "已取消",
		"queue.verdict.quota": "额度中止",
		"queue.verdict.noReport": "无报告",
		"queue.verdict.notStarted": "未启动",
		"queue.verdict.unknown": "未明",
		"queue.fallbackMark": "回退",
		"queue.fallbackTitle": "回退：请求的是 {requested}",
		"queue.chip.free": "免费",
		"queue.notify.unknown": "{ch} 无回执",
		"queue.receiptLegend": "以 runner 写入 result.env 的回执为准（openclaw 发送成功/失败）；无回执 = 未知，不当作已送达",
		"panel.q.idle": "闲",
		"panel.q.run": "运行 {n}",
		"panel.q.queued": "排队 {n}",
		"panel.q.quota": "等额度 {n}",
		"panel.q.wait": "等待 {n}",
		"panel.free": "免费",
		"panel.staleAt": "刷新失败（{message}），显示 {time} 的读数",
		"panel.openGroup": "打开 {name} 的额度与队列",
		"panel.railTitle": "额度 · 队列：{summary}",
		"panel.warn": "有窗口到阈值或有任务在睡额度",
		"panel.queueLoading": "正在读取派发队列…",
		"panel.queueUnavailable": "此主机没有派发队列；额度仍可查看。",
		"panel.noSources": "没有可显示的额度或派发来源。",
		"queue.wait.quotaBoth": "等到 {time}（窗口 {reset} +{pad}m 缓冲）",
		"queue.wait.quotaNoWindow": "等到 {time}（窗口重置时刻未读到）",
		"queue.d.cost": "花费",
		"queue.d.costFree": "免费（opencode 免费池）",
		"queue.d.costUnpriced": "—（该模型没有价目，不估）",
		"queue.d.costLive": "截至上一次尝试结束",
		"queue.d.tokens": "Tokens",
		"queue.d.deadline": "截止",
		"queue.a.confirmLabel": "确认 {label}",
		"queue.a.brief": "任务书",
		"queue.a.briefTitle": "在右侧文件预览打开 prompt.md（只读）",
		"queue.a.deadline": "截止 +2h",
		"queue.a.attempts": "重试 +1",
		"queue.a.resumes": "续跑 +1",
		"queue.a.deadlineConfirm": "延长 deadline 2 小时：该任务占用队列的时间变长（上限：派发 + 72h）。{when} 再点一次确认。",
		"queue.a.attemptsConfirm": "多给一次失败/卡死重试：再失败会多跑一轮。{when} 再点一次确认。",
		"queue.a.resumesConfirm": "多给一次额度续跑：每次都会重放会话上下文，有成本（缓存读）。{when} 再点一次确认。",
		"queue.a.whenNow": "它在排队/等待：几秒内生效。",
		"queue.a.whenNext": "它在跑：本次尝试的时限不变，下一次尝试起生效。",
		"queue.a.budgetOld": "这个任务的 runner 是 api {api}：deadline 与重试预算在启动时定死，改了不会生效（api 3 起的任务才支持）。",
		"queue.brief.heading": "任务书与追加",
		"queue.brief.prompt": "任务书 prompt.md · {kb} KB",
		"queue.brief.append": "追加 {stamp}",
		"queue.brief.delivered": "已投递",
		"queue.brief.pending": "待投递",
		"queue.brief.big": "原文 {kb} KB（预览里是完整文件；ops 读数已截断到 64 KB）",
		"queue.brief.noSession": "右侧预览要在会话里打开：先进入任意会话，再点一次。文件：{path}",
		"queue.brief.noService": "这个 dsh 没有文件预览栏。文件：{path}",
		"queue.brief.noDir": "插件 host 半边是旧版，没有告诉任务目录在哪；重启 dsh 后才能打开任务书。",
		"queue.brief.failed": "预览打不开：{message}。文件：{path}",
		"queue.brief.opened": "已在右侧预览打开 {file}",
		"queue.d.sec.run": "运行设置",
		"queue.d.sec.allowance": "额度",
		"queue.d.sec.time": "时间",
		"queue.d.sec.usage": "用量",
		"queue.d.sec.end": "结束任务",
		"queue.d.sec.again": "再跑一次",
		"queue.d.sec.raw": "原始记录",
		"queue.d.region": "{name} 的详情",
		"queue.a.viewGroup": "查看（只读）",
		"queue.a.confirm": "确认",
		"queue.d.notRecorded": "未记录",
		"queue.d.retries": "重试",
		"queue.d.quotaResumes": "额度续跑",
		"queue.d.usedOf": "已用 {used} / {max}",
		"queue.d.slotOf": "槽 {slot} / {max}",
		"queue.d.slotValue": "槽 {slot}",
		"queue.d.source": "额度来源",
		"queue.d.windows": "窗口",
		"queue.d.pool": "免费池",
		"queue.d.quotaOut": "额度用尽",
		"queue.d.costFreeShort": "免费",
		"queue.d.costEstimate": "按 API 价估算，非实际扣费",
		"queue.d.tokensTotal": "共 {total}",
		"queue.d.tokensSplit": "输入 {in} · 缓存写 {w} · 缓存读 {r} · 输出 {out}",
		"queue.brief.needsHost": "追加列表要等插件 host 半边更新（需重启 dsh）；任务书本身可以打开。",
		"queue.brief.none": "没有追加",
		"queue.brief.readOnly": "只读：要改请用 dispatch.sh append（运行中加 --queue）",
		"queue.r.needsHost": "主机上的插件 host 半边是旧版，这个动作要重启 dsh 后才可用。"
	},
	en: {
		"action.buy": "Buy",
		"action.add": "Add",
		"action.trim": "Trim",
		"action.sell": "Sell",
		"action.cut": "Cut",
		"action.hold": "Hold",
		"action.trim_on_rebound": "Trim on rebound",
		"action.t_only": "T+0 only",
		"action.add_only_on_trigger": "Add on trigger",
		"action.reject": "No add",
		"action.watch": "Watch",
		"action.abstain": "Abstain",
		"driver.technical": "Technical",
		"driver.fundamental": "Fundamental",
		"driver.sentiment": "Sentiment",
		"driver.mixed": "Mixed",
		"driver.risk_rule": "Risk rule",
		"driver.catalyst": "Catalyst",
		"driver.influencer": "Influencer",
		"driver.macro": "Macro",
		"driver.peer": "Peer",
		"exe.followed": "Followed the plan",
		"exe.not_followed": "Did not follow",
		"exe.unknown": "Unmarked",
		"align.same": "Same side as plan",
		"align.opposite": "Against the plan",
		"align.other": "Plan was not a trade",
		"emo.fomo": "FOMO",
		"emo.revenge": "Revenge",
		"emo.averaging_down": "Averaging down",
		"emo.fear": "Fear",
		"emo.euphoria": "Euphoria",
		"emo.calm": "Calm",
		"emo.mixed": "Mixed",
		"filter.all": "All",
		"filter.miss": "No plan that day",
		"filter.sold": "Sell reviews",
		"filter.dec": "Had a plan",
		"t1.up": "up",
		"t1.down": "down",
		"t1.soldEarly": "sold too early",
		"t1.soldRight": "sold well",
		"t1.flat": "flat",
		"time.today": "today",
		"time.yesterday": "yesterday",
		"time.daysAgo": "{days}d ago",
		"time.date": "{month}/{day}",
		"time.weekday.0": "Sun",
		"time.weekday.1": "Mon",
		"time.weekday.2": "Tue",
		"time.weekday.3": "Wed",
		"time.weekday.4": "Thu",
		"time.weekday.5": "Fri",
		"time.weekday.6": "Sat",
		"trace.title": "Decision trace",
		"trace.subtitle": "A real fill + the plan written at the time + the official close",
		"trace.staleSuffix": " · refresh failed, showing the previous snapshot",
		"trace.unreadable": "Could not read the workspace's portfolio.json (CLAWOCK_WORKSPACE does not point at a clawock workspace, or the ledger does not parse) — this is not an empty ledger",
		"trace.titleWithPlan": "Decision trace · {date}",
		"trace.titleNoPlan": "Decision trace · no plan that day",
		"trace.planThen": "The plan at the time",
		"trace.noPlanRecord": "No plan recorded for this ticker that day",
		"trace.realFill": "Real fill",
		"trace.t1Close": "T+1 close",
		"trace.t1Pending": "T+1 unjudged",
		"trace.unpaired": "No plan for this ticker within ±3 days in the decision ledger: the fill is real, the thinking left no record.",
		"trace.sharesAt": " shares @ ",
		"trace.shares": " shares",
		"trace.confidence": " · confidence ",
		"trace.trigger": "Trigger: ",
		"trace.selfGrade": "Ledger self-grade: ",
		"trace.realized": "Realized on this fill",
		"trace.pnl": "P&L on this fill",
		"trace.openPosition": "— still open",
		"trace.floating": "This position is floating ({ticker} whole book, not this fill)",
		"trace.why": "Why ",
		"trace.emotion": "Emotion ",
		"trace.note": "Note ",
		"trace.holding": "Position",
		"trace.opposite": "Against plan",
		"trace.market.hk": "HK",
		"trace.market.us": "US",
		"trace.realizedUsd": "Realized (USD equivalent)",
		"trace.realizedUsdNoRate": "Realized (USD equivalent · HKD unconverted)",
		"trace.t1Tally": "T+1 sold-early/sold-well/flat · {rated}/{sells} sells judged",
		"trace.t1Sideless": " · {sideless} with no side",
		"trace.matched": "Had a plan that day",
		"trace.reversed": " · {reversed} against plan",
		"trace.more": "Show {fills} earlier fills",
		"trace.less": "Collapse to the latest {groups} groups",
		"trace.empty": "No fill matches this filter",
		"trace.fillCount": "{count} fills",
		"balance.loading": "Loading balance",
		"balance.unconfigured": "Not set",
		"balance.unconfiguredKey": "No API key configured",
		"balance.fetchFailed": "Balance unavailable",
		"balance.windowsUsed": "Quota windows in use",
		"balance.apiBalance": "API balance",
		"balance.granted": "Granted ",
		"balance.toppedUp": "Topped up ",
		"balance.insufficient": "The provider reports insufficient balance",
		"balance.staleWith": "Refresh failed, showing the last reading: {message}",
		"balance.stale": "Refresh failed, showing the last reading",
		"balance.windowAt": "A window is at {percent}% used",
		"balance.lowMoney": "Balance low, below the {amount} threshold",
		"balance.panelTitle": "Model service balances",
		"balance.panelHeading": "API balance",
		"balance.refreshAll": "Refresh all balances",
		"balance.refreshNow": "Refresh now",
		"balance.readFailed": "Balance read failed: {message}",
		"balance.reading": "Reading balances…",
		"balance.noProviders": "No balance source is available",
		"balance.otherProviders": "(click for other services)",
		"balance.unknownError": "unknown error",
		"balance.windowNote": "{label} {percent}% used",
		"balance.windowNoteReset": "{label} {percent}% used, resets {reset}",
		"balance.window.week": "week",
		"balance.window.days": "{n}d",
		"balance.window.hours": "{n}h",
		"balance.window.minutes": "{n}m",
		"balance.reset.today": "today {time}",
		"balance.reset.tomorrow": "tomorrow {time}",
		"balance.reset.dated": "{date} {weekday} {time}",
		"queue.name": "Tasks",
		"queue.panelTitle": "Dispatch task queue",
		"queue.panelHeading": "Dispatch queue",
		"queue.refresh": "Refresh the task queue",
		"queue.running": "{n} running",
		"queue.slotsHeading": "Run slots · per agent",
		"queue.lane": "{agent} {used}/{max}",
		"queue.laneNoMax": "{agent} {used}",
		"queue.lanesTitle": "Run slots are per agent: each agent only uses its own, so a queue is about that agent alone",
		"queue.queued": "{n} queued",
		"queue.memoryWait": "{n} waiting on memory",
		"queue.quotaWait": "{n} waiting on quota",
		"queue.retryWait": "{n} waiting to retry",
		"queue.idle": "No task running",
		"queue.readFailed": "Task queue read failed: {message}",
		"queue.staleWith": "Refresh failed, showing the last read: {message}",
		"queue.state.running": "running",
		"queue.state.runningSlot": "running · slot {slot}",
		"queue.state.starting": "starting",
		"queue.wait.lock": "waiting for the {agent} lock",
		"queue.wait.slot": "waiting for a {agent} run slot",
		"queue.wait.memory": "waiting for memory",
		"queue.wait.quota": "quota wait · resumes {time}",
		"queue.wait.quotaNoTime": "quota wait",
		"queue.wait.retry": "retry wait · {time}",
		"queue.wait.retryNoTime": "retry wait",
		"queue.meta": "{agent} · {model}",
		"queue.run": "{elapsed} · attempt {attempts}",
		"queue.stalls": "{n} stalled",
		"queue.waitHeading": "Queued / waiting",
		"queue.noneRunning": "No task holds a slot",
		"queue.noneWaiting": "Nothing queued or waiting",
		"queue.recentHeading": "Recently ended",
		"queue.waited": "first queue wait {time}",
		"queue.d.waited": "Queue wait",
		"queue.waitUnknown": "queue wait not recorded",
		"queue.execution.ok": "Execution complete",
		"queue.execution.failed": "Execution failed",
		"queue.execution.cancelled": "Cancelled",
		"queue.execution.timeout": "Timed out",
		"queue.execution.blocked": "Execution blocked",
		"queue.execution.quota": "Stopped on quota",
		"queue.execution.queued": "Never started",
		"queue.execution.unknown": "Result unknown",
		"queue.report.DONE": "Task: complete",
		"queue.report.claimedDone": "Task: reports complete",
		"queue.report.PARTIAL": "Task: partial",
		"queue.report.BLOCKED": "Task: blocked",
		"queue.report.unknown": "Task: no report",
		"queue.statusLegend": "The first status is the runner’s execution verdict. “Task” is the model’s final report. Execution can complete while the task remains partial or blocked.",
		"queue.olderRounds": "{n} earlier rounds",
		"queue.supervisorLog": "Raw supervisor log",
		"queue.patrol.waitSlot": "Waiting for a free run slot",
		"queue.patrol.giveWay": "Giving way to manual tasks",
		"queue.patrol.memory": "Low memory, deferred",
		"queue.patrol.memoryUnread": "Memory unreadable, deferred",
		"queue.patrol.otherReason": "Giving way (reason in the raw log)",
		"queue.patrol.wrapUp": "Wrapping up to give way",
		"queue.patrol.forTask": "Waiting task {id}",
		"queue.round.preempted": "Cancelled to give way",
		"queue.round.yielded": "Wrapped up to give way",
		"queue.round.name": "{round} · {axis}",
		"queue.chip.elapsed": "running {time}",
		"queue.chip.took": "took {time}",
		"queue.chip.cost": "Estimate at API prices, not a bill",
		"queue.chip.unpriced": "unpriced",
		"queue.patrolHeading": "Patrol",
		"queue.patrolRound": "current round {round}",
		"queue.roundsHeading": "Recent rounds",
		"queue.patrol.running": "patrol running",
		"queue.patrol.yielding": "patrol giving way",
		"queue.patrol.waiting": "patrol between rounds",
		"queue.patrol.waitingUntil": "patrol next round {time}",
		"queue.patrol.stopped": "patrol stopped",
		"queue.patrol.unknown": "patrol state unknown",
		"queue.patrolState.running": "running",
		"queue.patrolState.yielding": "giving way",
		"queue.patrolState.waiting": "idle",
		"queue.patrolState.waitingUntil": "next round {time}",
		"queue.patrolState.stopped": "stopped",
		"queue.patrolState.unknown": "state unknown",
		"queue.duration.minutes": "{m}m",
		"queue.duration.hours": "{h}h {m}m",
		"queue.ago.now": "just now",
		"queue.ago.minutes": "{m}m ago",
		"queue.ago.hours": "{h}h ago",
		"queue.ago.days": "{d}d ago",
		"queue.wait.lockAt": "waiting for the {agent} lock · #{n}",
		"queue.state.cancelling": "cancelling",
		"queue.attempt": "attempt {n}",
		"queue.slotCount": "slot {used}/{max}",
		"queue.tag.running": "running",
		"queue.tag.runningSlot": "running #{slot}",
		"queue.tag.starting": "starting",
		"queue.tag.cancelling": "cancelling",
		"queue.tag.queued": "queued",
		"queue.tag.queuedAt": "queued #{n}",
		"queue.tag.slot": "slot wait",
		"queue.tag.memory": "memory wait",
		"queue.tag.quota": "quota wait",
		"queue.tag.retry": "retry wait",
		"queue.fact.wakes": "resumes {time}",
		"queue.fact.startedAt": "started {time}",
		"queue.fact.queuedAt": "queued since {time}",
		"queue.chip.waiting": "waiting {time}",
		"queue.fallback": "fallback",
		"queue.patrolTag": "patrol",
		"queue.noRunnerApi": "No RUNNER_API 2: not in the queue order; its order and model cannot change",
		"queue.holderOther": "The lock is held by {id}",
		"queue.holderUnnamed": "The lock is held, but no holder is registered (one taking it right now, or a task the current runner did not start)",
		"queue.quotaHint": "Quota is out until {time} ({by} hit it); the others wait for it",
		"queue.ops.missing": "The ops entry is unavailable, actions are off: {error}",
		"queue.ops.skew": "The ops entry differs from the repository (host {host} / repo {repo}): run ops/host/install_task_queue_ops.sh",
		"queue.ops.version": "ops {v}",
		"queue.ops.footer": "ops {v} · runner api {runner}",
		"queue.ch.weixin": "WeChat",
		"queue.ch.telegram": "Telegram",
		"queue.notify.sent": "{ch} delivered",
		"queue.notify.failed": "{ch} failed",
		"queue.notify.planned": "{ch} on finish",
		"queue.d.place": "Queue",
		"queue.d.placeValue": "#{n} in the {agent} queue",
		"queue.d.protected": "past the fair wait, cannot be overtaken",
		"queue.d.priorityValue": "priority {n}",
		"queue.d.queued": "Queued",
		"queue.d.notify": "Notify",
		"queue.d.notifyNone": "none",
		"queue.d.runner": "Runner",
		"queue.d.session": "Session",
		"queue.d.fallbackFrom": "asked for {model}, switched",
		"queue.d.effortDefault": "default",
		"queue.a.top": "To top",
		"queue.a.up": "Move up",
		"queue.a.upOf": "Move {name} up",
		"queue.a.down": "Move down",
		"queue.a.model": "Model",
		"queue.a.wrapup": "Wrap up",
		"queue.a.wrapupTitle": "Queue a wrap-up instruction: after the current step, land what is done and report STATUS",
		"queue.a.cancel": "Cancel",
		"queue.a.cancelConfirm": "Confirm cancel",
		"queue.a.retry": "Retry",
		"queue.a.log": "Log",
		"queue.a.save": "Save",
		"queue.a.close": "Close",
		"queue.a.modelHint": "Applies to the next attempt; the step running now keeps its model.",
		"queue.a.cancelQueued": "It has not started: cancelling costs nothing. Tap again to confirm.",
		"queue.a.cancelSleeping": "It waits for quota or a retry: it will not resume; the session stays resumable. Tap again to confirm.",
		"queue.a.cancelRunning": "It is running: this step's progress is lost; session {session} can be resumed. Tap again to confirm.",
		"queue.a.dismissConfirm": "Keep unchanged",
		"queue.a.reading": "Loading…",
		"queue.a.readFailed": "Read failed: {message}",
		"queue.r.failed": "Did not work: {message}",
		"queue.r.cancelledQueued": "Cancelled (had not started, nothing lost)",
		"queue.r.cancelledRunning": "Stopped, this step's progress is lost; resume: {resume}",
		"queue.r.cancelledNoSession": "Stopped (no session yet)",
		"queue.r.priority": "Now #{n} of {total}",
		"queue.r.model": "Next attempt: {model} · {effort}",
		"queue.r.retry": "Continuing as a new task: {id}",
		"queue.r.wrapup": "Wrap-up queued: delivered when the current step ends",
		"queue.back": "Back to quota and queue",
		"queue.d.open": "Show task details",
		"queue.d.live": "Live",
		"queue.d.ended": "Ended",
		"queue.d.agent": "Agent",
		"queue.d.model": "Model",
		"queue.d.started": "Started",
		"queue.d.elapsed": "Running for",
		"queue.d.took": "Took",
		"queue.d.endedAt": "Finished",
		"queue.d.resumes": "Wakes at",
		"queue.d.attempts": "Attempts",
		"queue.d.stalls": "Stalled",
		"queue.d.stallsValue": "{n} (silent with no progress, retried automatically)",
		"queue.d.latest": "Latest event",
		"queue.d.id": "Task ID",
		"queue.d.summary": "Closing report",
		"queue.d.noSummary": "No closing report was left",
		"panel.title": "Quota · queue",
		"panel.aria": "Each provider's quota and the dispatch queue",
		"panel.refresh": "Refresh quotas and the queue",
		"panel.plan.anthropic": "Anthropic subscription",
		"panel.plan.chatgpt": "ChatGPT subscription",
		"panel.plan.freePool": "No provider · free pool",
		"panel.plan.deepseek": "This host's API account",
		"panel.plan.minimax": "Token Plan · key from the OpenClaw config",
		"panel.pool": "pool {current} → next {next}",
		"panel.poolOrder": " (file order)",
		"panel.poolSize": "{n} in pool",
		"panel.poolSwap": "{n} free models, each a stand-in for the next",
		"panel.poolUnread": "pool file not read (needs the newer host half, after a dsh restart)",
		"queue.verdict.done": "done",
		"queue.verdict.partial": "partial",
		"queue.verdict.blocked": "blocked",
		"queue.verdict.failed": "failed",
		"queue.verdict.timeout": "timed out",
		"queue.verdict.cancelled": "cancelled",
		"queue.verdict.quota": "quota stop",
		"queue.verdict.noReport": "no report",
		"queue.verdict.notStarted": "not started",
		"queue.verdict.unknown": "unknown",
		"queue.fallbackMark": "fallback",
		"queue.fallbackTitle": "fallback: {requested} was requested",
		"queue.chip.free": "free",
		"queue.notify.unknown": "{ch}: no receipt",
		"queue.receiptLegend": "From the receipt the runner writes to result.env (openclaw send succeeded / failed); no receipt = unknown, never taken as delivered",
		"panel.q.idle": "idle",
		"panel.q.run": "{n} running",
		"panel.q.queued": "{n} queued",
		"panel.q.quota": "{n} on quota",
		"panel.q.wait": "{n} waiting",
		"panel.free": "free",
		"panel.staleAt": "Refresh failed ({message}); showing the reading of {time}",
		"panel.openGroup": "Open {name}'s quota and queue",
		"panel.railTitle": "Quota · queue: {summary}",
		"panel.warn": "a window is at its threshold or a task sleeps on quota",
		"panel.queueLoading": "Reading the dispatch queue…",
		"panel.queueUnavailable": "This host has no dispatch queue; quotas are still available.",
		"panel.noSources": "No quota or dispatch source is available.",
		"queue.wait.quotaBoth": "until {time} (window {reset} + {pad}m margin)",
		"queue.wait.quotaNoWindow": "until {time} (window reset not read)",
		"queue.d.cost": "Cost",
		"queue.d.costFree": "free (opencode free pool)",
		"queue.d.costUnpriced": "— (no price for this model, not estimated)",
		"queue.d.costLive": "as of the last finished attempt",
		"queue.d.tokens": "Tokens",
		"queue.d.deadline": "Deadline",
		"queue.a.confirmLabel": "Confirm {label}",
		"queue.a.brief": "Brief",
		"queue.a.briefTitle": "Open prompt.md in the file preview (read-only)",
		"queue.a.deadline": "Deadline +2h",
		"queue.a.attempts": "Retry +1",
		"queue.a.resumes": "Resume +1",
		"queue.a.deadlineConfirm": "Two more hours: the task holds its place in the queue longer (ceiling: dispatch + 72h). {when} Tap again to confirm.",
		"queue.a.attemptsConfirm": "One more retry after a failure or stall: another failure runs one more round. {when} Tap again to confirm.",
		"queue.a.resumesConfirm": "One more quota resume: each replays the session's context, which costs cache reads. {when} Tap again to confirm.",
		"queue.a.whenNow": "It is queued or waiting: applies within seconds.",
		"queue.a.whenNext": "It is running: this attempt keeps its time cap; applies from the next attempt.",
		"queue.a.budgetOld": "This task's runner is api {api}: its deadline and retry budgets were fixed at start, a change would not apply (tasks from api 3 on accept it).",
		"queue.brief.heading": "Brief and appends",
		"queue.brief.prompt": "Brief prompt.md · {kb} KB",
		"queue.brief.append": "Append {stamp}",
		"queue.brief.delivered": "delivered",
		"queue.brief.pending": "pending",
		"queue.brief.big": "{kb} KB (the preview shows the whole file; the ops read is capped at 64 KB)",
		"queue.brief.noSession": "The preview opens inside a conversation: open any conversation, then tap again. File: {path}",
		"queue.brief.noService": "This dsh has no file preview. File: {path}",
		"queue.brief.noDir": "The plugin's host half is older and does not say where task directories are: the brief opens after a dsh restart.",
		"queue.brief.failed": "The preview did not open: {message}. File: {path}",
		"queue.brief.opened": "Opened {file} in the preview",
		"queue.d.sec.run": "Run settings",
		"queue.d.sec.allowance": "Allowance",
		"queue.d.sec.time": "Timeline",
		"queue.d.sec.usage": "Usage",
		"queue.d.sec.end": "End the task",
		"queue.d.sec.again": "Run again",
		"queue.d.sec.raw": "Raw record",
		"queue.d.region": "Details of {name}",
		"queue.a.viewGroup": "View (read-only)",
		"queue.a.confirm": "Confirm",
		"queue.d.notRecorded": "not recorded",
		"queue.d.retries": "Retries",
		"queue.d.quotaResumes": "Resumes",
		"queue.d.usedOf": "{used} of {max} used",
		"queue.d.slotOf": "slot {slot} of {max}",
		"queue.d.slotValue": "slot {slot}",
		"queue.d.source": "Paid by",
		"queue.d.windows": "Windows",
		"queue.d.pool": "Free pool",
		"queue.d.quotaOut": "Out of quota",
		"queue.d.costFreeShort": "free",
		"queue.d.costEstimate": "estimated at API prices, not billed",
		"queue.d.tokensTotal": "{total} total",
		"queue.d.tokensSplit": "in {in} · cache write {w} · cache read {r} · out {out}",
		"queue.brief.needsHost": "The appends list needs the updated host half (a dsh restart); the brief itself opens now.",
		"queue.brief.none": "No appends",
		"queue.brief.readOnly": "Read-only: change it with dispatch.sh append (--queue while it runs)",
		"queue.r.needsHost": "The plugin's host half on this host is older: this action works after a dsh restart."
	}
};
/**
* Bind a dictionary to a lookup shaped exactly like the host's `t` seat, with
* `{name}` interpolation. The host supplies the real one through the slot
* registration (`locale: LOCALE_NS`); this factory exists so a render can be
* exercised without a locale service — the same seam the tests use.
*/
function createTranslator(dict) {
	return (key, params) => {
		const template = dict[key];
		if (template === void 0) return key;
		if (params === void 0) return template;
		return template.replace(/\{(\w+)\}/g, (whole, name) => Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : whole);
	};
}
/**
* Window length in minutes → the label in the active locale, host string as
* fallback. The structured fields are typed `| null` but read `== null`: a
* host that predates them omits the key entirely, so the value that actually
* arrives is `undefined`. Checking only for null rendered `NaN m` against a
* previous-version host — the exact half-deployed case this fallback exists
* for, caught by the projection test rather than in the browser.
*/
function windowLabelOf(t, window) {
	const mins = window.durationMins;
	if (mins == null || mins <= 0) return window.label;
	if (mins === 10080) return t("balance.window.week");
	if (mins % 1440 === 0) return t("balance.window.days", { n: mins / 1440 });
	if (mins % 60 === 0) return t("balance.window.hours", { n: mins / 60 });
	return t("balance.window.minutes", { n: Math.round(mins) });
}
/** The reset instant → the stamp in the active locale, host string as fallback. */
function resetStampOf(t, window, now) {
	const ms = window.resetAtMs;
	if (ms == null) return window.resetAt;
	const at = new Date(ms);
	const time = String(at.getHours()).padStart(2, "0") + ":" + String(at.getMinutes()).padStart(2, "0");
	const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
	const days = Math.round((startOfDay(at) - startOfDay(new Date(now))) / 864e5);
	if (days === 0) return t("balance.reset.today", { time });
	if (days === 1) return t("balance.reset.tomorrow", { time });
	return t("balance.reset.dated", {
		date: at.getMonth() + 1 + "/" + at.getDate(),
		weekday: t("time.weekday." + at.getDay()),
		time
	});
}
/** Every window of a snapshot, named and stamped for the active locale. */
function windowsOf(t, result, now) {
	return (result.snapshot?.windows ?? []).map((w) => ({
		label: windowLabelOf(t, w),
		percent: w.percent,
		reset: resetStampOf(t, w, now)
	}));
}
//#endregion
//#region src/panel.ts
/**
* The task chip's provider panel as data: every row it shows (a provider's
* allowance, a live task, an ended one, a patrol round), its words, its state
* role and its place — without React or the DOM. client.ts draws these rows in
* dsh's sidebar; text.ts prints the same rows for a chat (OpenClaw's
* `/dispatch-list`). One view model, two renderers: the chat reply cannot say
* something the chip does not, or say it in other words.
*
* The parts a renderer draws for itself are named, not built here: a row's lead
* glyph (`RowLead`), the fallback mark and the delivery receipts (`Fact`).
*/
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
function _rowDisplay(result, t, now = Date.now()) {
	if (result === null) return {
		tone: "none",
		value: "—",
		sub: null,
		reset: null,
		level: null,
		title: t("balance.loading")
	};
	if (!result.configured) return {
		tone: "none",
		value: t("balance.unconfigured"),
		sub: null,
		reset: null,
		level: null,
		title: result.message ?? t("balance.unconfiguredKey")
	};
	if (result.snapshot === null) return {
		tone: "none",
		value: "—",
		sub: null,
		reset: null,
		level: null,
		title: result.message ?? t("balance.fetchFailed")
	};
	const snapshot = result.snapshot;
	const isPct = snapshot.unit === "pct";
	const symbol = isPct ? "" : snapshot.currency === "USD" ? "$" : snapshot.currency === "CNY" ? "¥" : "";
	const pctWins = isPct && Array.isArray(snapshot.windows) ? snapshot.windows.filter((w) => w.percent !== null) : [];
	const parsed = Number.parseFloat(snapshot.totalBalance);
	const value = isFinite(parsed) ? isPct ? String(Math.round(parsed)) + "%" : symbol + parsed.toLocaleString(void 0, { maximumFractionDigits: 2 }) : pctWins.length > 0 ? String(Math.round(pctWins[0].percent)) + "%" : snapshot.totalBalance === "" ? "—" : symbol + snapshot.totalBalance;
	const second = pctWins.length > 1 ? pctWins[1] : null;
	const wins = windowsOf(t, result, now);
	const firstReset = wins.length > 0 ? wins[0].reset : "";
	const reset = pctWins.length > 0 && firstReset !== "" ? firstReset : null;
	const secondWin = wins.length > 1 ? wins[1] : null;
	const sub = secondWin !== null && second !== null ? "· " + secondWin.label + " " + Math.round(second.percent) + "%" + (secondWin.reset !== "" ? " ↻" + secondWin.reset : "") : null;
	const tone = result.status === "stale" ? "stale" : result.low || !snapshot.isAvailable ? "low" : "ok";
	const quotaTail = wins.length === 0 ? [] : snapshot.note.split(" · ").slice(snapshot.windows.length).filter((note) => note !== "");
	const quotaLine = wins.length === 0 ? snapshot.note !== "" ? snapshot.note : t("balance.windowsUsed") : [...wins.filter((w) => w.percent !== null).map((w) => w.reset === "" ? t("balance.windowNote", {
		label: w.label,
		percent: Math.round(w.percent)
	}) : t("balance.windowNoteReset", {
		label: w.label,
		percent: Math.round(w.percent),
		reset: w.reset
	})), ...quotaTail].join(" · ");
	const parts = [
		snapshot.unit === "pct" ? quotaLine : t("balance.apiBalance"),
		!isPct && snapshot.grantedBalance !== "" ? t("balance.granted") + symbol + snapshot.grantedBalance : null,
		!isPct && snapshot.toppedUpBalance !== "" ? t("balance.toppedUp") + symbol + snapshot.toppedUpBalance : null,
		snapshot.isAvailable || isPct ? null : t("balance.insufficient"),
		result.status === "stale" && result.message !== null ? t("balance.staleWith", { message: result.message }) : null
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
function _balanceNote(result, t) {
	if (result === null) return null;
	if (!result.configured) return result.message ?? t("balance.unconfiguredKey");
	if (result.snapshot === null) return result.message ?? t("balance.fetchFailed");
	if (result.status === "stale") return result.message !== null ? t("balance.staleWith", { message: result.message }) : t("balance.stale");
	if (!result.snapshot.isAvailable) return result.snapshot.unit === "pct" ? null : t("balance.insufficient");
	if (result.low) {
		if (result.snapshot.unit === "pct") return (result.snapshot.windows ?? []).length > 0 ? null : t("balance.windowAt", { percent: 100 - result.threshold });
		return t("balance.lowMoney", { amount: (result.snapshot.currency === "USD" ? "$" : result.snapshot.currency === "CNY" ? "¥" : "") + result.threshold });
	}
	return null;
}
/** A live task queued for something another task of its agent holds (the backlog patrol yields to). */
const queuedFor = (task) => task.waiting === "lock" || task.waiting === "slot";
/**
* Which run slot a live task holds: `SLOT=<agent>-<n>` (slots are per agent).
* Anything else is shown verbatim under the task's own agent. (The shared
* `slot-1..2` of the runners from before 2026-09-25, a bare number, had a
* bucket of its own until 2026-09-27, when none was left.)
*/
function _slotOf(task) {
	if (task.slot === "") return null;
	const lane = /^([a-z][a-z0-9]*)-(\d+)$/.exec(task.slot);
	return lane ? {
		agent: lane[1],
		slot: lane[2]
	} : {
		agent: task.agent,
		slot: task.slot
	};
}
/**
* Each agent's run slots, in the panel's order (providers.ts), limits.env's
* agents and any agent seen holding one that limits.env does not name. A full lane with a task of that agent queued
* is amber: that is the queue's reason at a glance. A host older than
* slotLimits sends none: the lanes then come from the held slots alone,
* without a maximum.
*/
function _slotLanes(result) {
	const held = result.active.map(_slotOf).filter((slot) => slot !== null);
	const limits = new Map((result.slotLimits ?? []).map((limit) => [limit.agent, limit.max]));
	for (const slot of held) if (!limits.has(slot.agent)) limits.set(slot.agent, -1);
	return byAgentRank([...limits].map(([agent, limit]) => ({
		agent,
		limit
	}))).map(({ agent, limit }) => {
		const used = held.filter((slot) => slot.agent === agent).length;
		const max = limit >= 0 ? limit : null;
		const queued = result.active.some((task) => task.agent === agent && queuedFor(task));
		return {
			agent,
			used,
			max,
			tone: max !== null && used >= max && queued ? "stale" : used > 0 ? "ok" : "none"
		};
	});
}
function laneText(t, lane) {
	return lane.max === null ? t("queue.laneNoMax", {
		agent: lane.agent,
		used: lane.used
	}) : t("queue.lane", {
		agent: lane.agent,
		used: lane.used,
		max: lane.max
	});
}
function durationOf(t, ms) {
	const mins = Math.max(0, Math.floor(ms / 6e4));
	return mins < 60 ? t("queue.duration.minutes", { m: mins }) : t("queue.duration.hours", {
		h: Math.floor(mins / 60),
		m: mins % 60
	});
}
function agoOf(t, ms) {
	const mins = Math.max(0, Math.floor(ms / 6e4));
	if (mins < 1) return t("queue.ago.now");
	if (mins < 60) return t("queue.ago.minutes", { m: mins });
	if (mins < 2880) return t("queue.ago.hours", { h: Math.floor(mins / 60) });
	return t("queue.ago.days", { d: Math.floor(mins / 1440) });
}
/**
* One live task's status phrase and its tone. One colour, one meaning:
* 'ok' (the host's business blue) = holding its agent's lock and running,
* 'stale' (the host's warn) = waiting for something (the lock, a slot,
* memory, a quota reset, a retry), 'none' = neither yet (starting).
*/
function _taskStatus(task, t, now = Date.now(), windows) {
	const stamp = (ms) => resetStampOf(t, {
		resetAt: "",
		resetAtMs: ms
	}, now);
	const at = (key, ms) => ms === null ? t(key + "NoTime") : t(key, { time: stamp(ms) });
	if (task.cancelling) return {
		tone: "none",
		text: t("queue.state.cancelling")
	};
	switch (task.waiting) {
		case "lock": return {
			tone: "stale",
			text: task.position ? t("queue.wait.lockAt", {
				agent: task.agent,
				n: task.position
			}) : t("queue.wait.lock", { agent: task.agent })
		};
		case "slot": return {
			tone: "stale",
			text: t("queue.wait.slot", { agent: task.agent })
		};
		case "memory": return {
			tone: "stale",
			text: t("queue.wait.memory")
		};
		case "quota": {
			if (task.wakeAtMs === null || windows === void 0) return {
				tone: "stale",
				text: at("queue.wait.quota", task.wakeAtMs)
			};
			const wake = task.wakeAtMs;
			const resets = windows.map((w) => w.resetAtMs ?? null).filter((ms) => ms !== null && ms <= wake + 6e4 && wake - ms < 216e5);
			if (resets.length === 0) return {
				tone: "stale",
				text: t("queue.wait.quotaNoWindow", { time: stamp(wake) })
			};
			const reset = Math.max(...resets);
			return {
				tone: "stale",
				text: t("queue.wait.quotaBoth", {
					time: stamp(wake),
					reset: stamp(reset),
					pad: Math.max(0, Math.round((wake - reset) / 6e4))
				})
			};
		}
		case "retry": return {
			tone: "stale",
			text: at("queue.wait.retry", task.wakeAtMs)
		};
	}
	const slot = _slotOf(task);
	if (slot === null) return {
		tone: "none",
		text: t("queue.state.starting")
	};
	return {
		tone: "ok",
		text: slot.slot === "1" ? t("queue.state.running") : t("queue.state.runningSlot", { slot: slot.slot })
	};
}
/** Keep the runner's execution verdict and the model's report in separate, named slots. */
function executionText(state, t) {
	return t("queue.execution." + ({
		ok: "ok",
		partial: "ok",
		unverified: "ok",
		failed: "failed",
		cancelled: "cancelled",
		timeout: "timeout",
		blocked: "blocked",
		quota: "quota",
		queued: "queued"
	}[state] ?? "unknown"));
}
function reportText(outcome, t, executionState = "ok") {
	if (outcome === "DONE" && ![
		"ok",
		"partial",
		"unverified"
	].includes(executionState)) return t("queue.report.claimedDone");
	return t("queue.report." + ([
		"DONE",
		"PARTIAL",
		"BLOCKED"
	].includes(outcome) ? outcome : "unknown"));
}
/**
* An ended task's tone. Done is not blue (blue means running now) and not a
* dot at all: ended rows speak in words. Not-done amber, failed red.
*/
function endedTone(task) {
	if (task.state === "failed" || task.state === "timeout") return "low";
	if ([
		"partial",
		"unverified",
		"blocked",
		"quota"
	].includes(task.state) || task.state === "ok" && task.outcome !== "DONE" || task.outcome === "BLOCKED") return "stale";
	return "none";
}
function patrolPhraseOf(result, t, now) {
	const patrol = result.patrol;
	if (patrol.phase === "waiting" && patrol.untilMs !== null) return t("queue.patrol.waitingUntil", { time: resetStampOf(t, {
		resetAt: "",
		resetAtMs: patrol.untilMs
	}, now) });
	return t("queue.patrol." + patrol.phase);
}
/** The ops entry answered, and its installed copy is the repository's. '' when fine, else why not. */
function opsProblem(result, t) {
	const ops = result.ops;
	if (ops === void 0) return "";
	if (!ops.available) return t("queue.ops.missing", { error: ops.error });
	if (ops.repoVersion !== "" && ops.version !== ops.repoVersion) return t("queue.ops.skew", {
		host: ops.version,
		repo: ops.repoVersion
	});
	return "";
}
/**
* The chip's headline, the host badge's two parts: the label, and a count
* (running · queued) at the trailing edge. No n/max: slots are per agent, so a
* free slot of one agent is no room for another's task — the per-agent lanes
* are in the title and on each group of the panel. The glyph badge carries
* the one tone that matters most: red when the read failed, amber when a task
* waits, blue when something runs.
*/
function _queueHeadline(result, t, now = Date.now()) {
	const queued = result.active.filter(queuedFor).length;
	const memory = result.active.filter((task) => task.waiting === "memory").length;
	const quota = result.active.filter((task) => task.waiting === "quota").length;
	const retry = result.active.filter((task) => task.waiting === "retry").length;
	const waits = [
		queued > 0 ? t("queue.queued", { n: queued }) : null,
		memory > 0 ? t("queue.memoryWait", { n: memory }) : null,
		quota > 0 ? t("queue.quotaWait", { n: quota }) : null,
		retry > 0 ? t("queue.retryWait", { n: retry }) : null
	].filter((part) => part !== null);
	const parts = [...waits, patrolPhraseOf(result, t, now)];
	const value = result.active.length === 0 ? t("queue.idle") : t("queue.running", { n: result.running });
	const slots = _slotLanes(result).map((lane) => laneText(t, lane)).join(" · ");
	const waiting = queued + memory + quota + retry;
	const tone = result.status === "stale" || result.status === "failed" ? "low" : waiting > 0 ? "stale" : result.running > 0 ? "ok" : "none";
	const ops = result.ops?.available ? t("queue.ops.version", { v: result.ops.version }) : "";
	return {
		tone,
		value,
		sub: waits.join(" · "),
		busy: queued > 0,
		title: [
			t("queue.name"),
			value,
			slots,
			parts.join(" · "),
			opsProblem(result, t) || ops
		].filter((part) => part !== "").join(" · ")
	};
}
/** Executor names as their makers write them. */
const AGENT_LABELS = {
	claude: "Claude Code",
	codex: "Codex",
	opencode: "OpenCode"
};
const _agentLabel = (agent) => AGENT_LABELS[agent] ?? agent;
/**
* The model layer, read off the model id itself (never a hand-kept model
* list), as its maker names it in full: `claude-opus-5-5` → Claude Opus 5.5 ·
* `claude-haiku-4-5-20251001` → Claude Haiku 4.5 · `gpt-6-sol` → GPT-6 Sol ·
* `opencode/nemotron-3-ultra-free` → Nemotron 3 Ultra. No letter tile in
* front (kcn, 2026-09-27: the two-letter stand-in was noise); the room goes
* to the whole name.
*/
function _modelView(id) {
	if (id === "") return {
		label: "—",
		family: ""
	};
	const bare = id.includes("/") ? id.slice(id.lastIndexOf("/") + 1) : id;
	const title = (word) => word.charAt(0).toUpperCase() + word.slice(1);
	const claude = /^claude-([a-z]+)(?:-(\d+))?(?:-(\d{1,2}))?(?:-\d{8})?$/.exec(bare);
	if (claude) {
		const version = [claude[2], claude[3]].filter(Boolean).join(".");
		return {
			label: "Claude " + title(claude[1]) + (version ? " " + version : ""),
			family: "claude"
		};
	}
	const gpt = /^gpt-([\d.]+)(?:-([a-z]+))?$/.exec(bare);
	if (gpt) return {
		label: "GPT-" + gpt[1] + (gpt[2] ? " " + title(gpt[2]) : ""),
		family: "gpt"
	};
	if (/^[a-z]+$/.test(bare) && !id.includes("/")) return {
		label: title(bare),
		family: bare
	};
	const words = bare.replace(/-(free|contributor)(?=-|$)/g, "").split("-").filter((word) => word !== "");
	return {
		label: words.map((word) => /^[a-z]/.test(word) ? title(word) : word).join(" "),
		family: words[0] ?? bare
	};
}
/** "Opus 5.5 · high", with the model the task will run on while it waits and the one it ran on after. */
function modelLine(task, _live) {
	const requested = task.modelRequested ?? task.model;
	const ran = task.attempts > 0 && (task.modelUsed ?? "") !== "";
	const used = ran ? task.modelUsed ?? "" : "";
	return {
		model: ran ? used : requested || task.model,
		effort: (ran ? task.effortUsed : "") || task.effortRequested || "",
		fallback: ran && requested !== "" && used !== requested
	};
}
function _notifyState(task, ch, live) {
	if ((task.notifyFailed ?? []).includes(ch)) return "failed";
	if ((task.notified ?? []).includes(ch)) return "sent";
	return live ? "planned" : "unknown";
}
function notifyChannels(task) {
	return [.../* @__PURE__ */ new Set([
		...task.notify ?? [],
		...task.notified ?? [],
		...task.notifyFailed ?? []
	])];
}
const STATE_ROLES = {
	run: {
		bed: "fill",
		glyph: [{
			d: "M5 2a3 3 0 1 1 0 6a3 3 0 1 1 0-6Z",
			paint: "fill"
		}]
	},
	queue: {
		bed: "edge",
		glyph: [{
			d: "M5 2.2a2.8 2.8 0 1 1 0 5.6a2.8 2.8 0 1 1 0-5.6Z",
			paint: "stroke"
		}]
	},
	sleep: {
		bed: "fill",
		glyph: [{
			d: "M6.6 1.8A3.4 3.4 0 1 0 8.4 7.6A2.8 2.8 0 0 1 6.6 1.8Z",
			paint: "fill"
		}]
	},
	wait: {
		bed: "edge",
		glyph: [{
			d: "M2.8 1.8H7.2M2.8 8.2H7.2M3.4 1.8C3.4 4 6.6 4 6.6 5S3.4 6 3.4 8.2M6.6 1.8C6.6 4 3.4 4 3.4 5S6.6 6 6.6 8.2",
			paint: "stroke"
		}]
	},
	done: {
		bed: "fill",
		glyph: [{
			d: "M2.3 5.2L4.2 7.1L7.8 3",
			paint: "stroke"
		}]
	},
	partial: {
		bed: "fill",
		glyph: [{
			d: "M5 2.2a2.8 2.8 0 1 1 0 5.6a2.8 2.8 0 1 1 0-5.6Z",
			paint: "stroke"
		}, {
			d: "M5 2.2A2.8 2.8 0 0 0 5 7.8Z",
			paint: "fill"
		}]
	},
	fail: {
		bed: "fill",
		glyph: [{
			d: "M2.8 2.8L7.2 7.2M7.2 2.8L2.8 7.2",
			paint: "stroke"
		}]
	},
	off: {
		bed: "edge",
		glyph: [{
			d: "M2.6 5H7.4",
			paint: "stroke"
		}]
	},
	unknown: {
		bed: "dashed",
		glyph: [{
			d: "M3.5 3.6a1.6 1.6 0 1 1 2.2 1.5C5.2 5.3 5 5.6 5 6.1M5 7.9V8",
			paint: "stroke"
		}]
	},
	fallback: {
		bed: "edge",
		glyph: [{
			d: "M7.6 5.6A2.7 2.7 0 1 1 6.9 2.9M7.4 1.4V3.3H5.5",
			paint: "stroke"
		}]
	}
};
/**
* An ended task's (or round's) ONE state: the runner's verdict and the
* model's report folded into the role that most needs the reader. Both axes
* stay readable: the chip's title says both, the detail layer shows both.
*/
function _endedState(state, outcome, t) {
	const title = executionText(state, t) + (outcome === "" && state !== "ok" ? "" : " · " + reportText(outcome, t, state));
	const word = state === "failed" ? "failed" : state === "timeout" ? "timeout" : state === "cancelled" ? "cancelled" : state === "queued" ? "notStarted" : state === "quota" ? "quota" : state === "blocked" || outcome === "BLOCKED" ? "blocked" : ![
		"ok",
		"partial",
		"unverified"
	].includes(state) ? "unknown" : outcome === "DONE" ? "done" : outcome === "PARTIAL" ? "partial" : "noReport";
	const role = {
		failed: "fail",
		timeout: "fail",
		cancelled: "off",
		notStarted: "off",
		quota: "partial",
		blocked: "partial",
		done: "done",
		partial: "partial",
		noReport: "unknown",
		unknown: "unknown"
	}[word];
	return {
		text: t("queue.verdict." + word),
		role,
		title
	};
}
/**
* THE row grid (2026-09-28 redesign, kcn: 「很多地方都没有对齐显示导致 chip 过多显示杂乱」).
* Every line of the open panel — a source's head, a section head, a live
* task, an ended task, a patrol round — sits on the same five tracks
* (styles.module.css `--tq-grid`), and every fact has ONE fixed cell:
*
*            lead   when       took       rest        aside
*   line 1   glyph  name ─────────────────────────   state chip | value
*   line 2          model (+ fallback mark) ───────   receipts | tries
*   line 3          when       took                    cost
*
* `when`, `took` and `aside` are fixed widths, so a time, a duration, a cost,
* a state are on one vertical line in every row that has them; a row without
* a fact leaves its cell empty, never shifts the next one in. A head
* (source/section) has a caption line in line 2 instead of facts.
*
* RESIDENT_CHIPS: a row carries at most ONE chip, its state. Everything else
* is words in a fixed cell or a mark (receipts, fallback). What has no cell
* here is not squeezed in, wrapped or ellipsised: it lives in the detail layer
* one tap away (the report axis on its own, attempts' budget, the first queue
* wait, the patrol tag, the session). ROW_KINDS says which facts each kind
* shows; FACT_CELL where each one sits; the spec checks every rendered row
* against both, and that no row has a second chip.
*/
const FACT_ORDER = [
	"model",
	"tries",
	"receipt",
	"when",
	"took",
	"cost"
];
const RESIDENT_CHIPS = 1;
/** Each fact's one cell: its line and its track (styles.module.css places `[data-tq-fact=…]` accordingly). */
const FACT_CELL = {
	model: {
		line: 2,
		track: "main"
	},
	tries: {
		line: 2,
		track: "aside"
	},
	receipt: {
		line: 2,
		track: "aside"
	},
	when: {
		line: 3,
		track: "when"
	},
	took: {
		line: 3,
		track: "took"
	},
	cost: {
		line: 3,
		track: "aside"
	}
};
const ROW_KINDS = {
	source: {
		lead: true,
		value: true,
		facts: []
	},
	head: {
		lead: true,
		value: false,
		facts: []
	},
	task: {
		lead: true,
		value: false,
		facts: [
			"model",
			"tries",
			"when",
			"took",
			"cost"
		]
	},
	ended: {
		lead: true,
		value: false,
		facts: [
			"model",
			"receipt",
			"when",
			"took",
			"cost"
		]
	},
	round: {
		lead: true,
		value: false,
		facts: ["when", "took"]
	}
};
/** A clock for a fixed cell: "19:40" today, "10/4 19:40" another day. */
function clockOf(ms, now) {
	const d = new Date(ms);
	const n = new Date(now);
	const hm = String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
	return d.toDateString() === n.toDateString() ? hm : `${d.getMonth() + 1}/${d.getDate()} ${hm}`;
}
/**
* A live task's state chip: the short word (the group head already names the
* agent), its role, and the whole phrase (_taskStatus: which lock, the wake
* and the window it waits for) as the chip's title. A wake time is the 'when'
* cell, where an ended task keeps when it ended.
*/
function _taskState(task, t, now = Date.now(), windows) {
	const status = _taskStatus(task, t, now, windows);
	const stamp = (ms) => resetStampOf(t, {
		resetAt: "",
		resetAtMs: ms
	}, now);
	const since = task.startedAtMs ?? task.queuedAtMs;
	const when = (task.waiting === "quota" || task.waiting === "retry") && task.wakeAtMs !== null ? {
		text: clockOf(task.wakeAtMs, now),
		said: t("queue.fact.wakes", { time: stamp(task.wakeAtMs) }),
		voice: "warn"
	} : since != null ? {
		text: clockOf(since, now),
		said: t(_slotOf(task) === null ? "queue.fact.queuedAt" : "queue.fact.startedAt", { time: stamp(since) })
	} : null;
	const slot = _slotOf(task);
	const word = task.cancelling ? "cancelling" : task.waiting === "lock" ? task.position ? "queuedAt" : "queued" : task.waiting === "slot" ? "slot" : task.waiting === "memory" ? "memory" : task.waiting === "quota" ? "quota" : task.waiting === "retry" ? "retry" : slot === null ? "starting" : slot.slot === "1" ? "running" : "runningSlot";
	const role = word === "running" || word === "runningSlot" ? "run" : word === "queued" || word === "queuedAt" || word === "slot" ? "queue" : word === "quota" ? "sleep" : word === "cancelling" ? "off" : "wait";
	return {
		chip: {
			text: t("queue.tag." + word, {
				n: task.position ?? 0,
				slot: slot?.slot ?? ""
			}),
			role,
			title: status.text
		},
		when
	};
}
/** The model cell: the full model name and effort, and the fallback mark when it ran on another model. */
function modelFact(task, live, t) {
	const m = modelLine(task, live);
	if (m.model === "") return null;
	const text = _modelView(m.model).label + (m.effort ? " · " + m.effort : "");
	const requested = task.modelRequested ?? "";
	return {
		text,
		title: m.model,
		said: text + (m.fallback ? " · " + t("queue.fallbackTitle", { requested: _modelView(requested).label }) : ""),
		mark: m.fallback ? {
			role: "fallback",
			text: t("queue.fallbackMark"),
			title: t("queue.fallbackTitle", { requested: _modelView(requested).label })
		} : null
	};
}
/** The cost cell: the API-price estimate, 'free', or '—' when the model has no price row (title says which). */
function costFact(task, t, live) {
	const cost = _costOf(task);
	if (cost === null) return null;
	const legend = t("queue.chip.cost") + (live ? " · " + t("queue.d.costLive") : "");
	return cost.kind === "unpriced" ? {
		text: "—",
		said: t("queue.chip.unpriced"),
		title: t("queue.chip.unpriced") + " · " + legend,
		voice: "quiet"
	} : {
		text: cost.kind === "free" ? t("queue.chip.free") : cost.short,
		said: legend + " " + cost.short,
		title: legend
	};
}
/** A live task as a row: state chip; model, tries; when it wakes, how long, cost so far. */
function taskRow(task, t, now, open, windows) {
	const state = _taskState(task, t, now, windows);
	const since = task.queuedAtMs ?? task.startedAtMs;
	const running = _slotOf(task) !== null;
	const tries = [task.attempts > 1 ? t("queue.attempt", { n: task.attempts }) : null, task.stalls ? t("queue.stalls", { n: task.stalls }) : null].filter((part) => part !== null);
	return {
		kind: "task",
		key: task.id,
		lead: {
			agent: task.agent,
			size: 12
		},
		name: task.name,
		state: state.chip,
		facts: {
			model: modelFact(task, true, t),
			tries: tries.length === 0 ? null : {
				text: tries.join(" · "),
				voice: task.stalls ? "warn" : void 0
			},
			when: state.when,
			took: since == null ? null : {
				text: durationOf(t, now - since),
				said: t(running ? "queue.chip.elapsed" : "queue.chip.waiting", { time: durationOf(t, now - since) })
			},
			cost: costFact(task, t, true)
		},
		open: () => {
			open(task.id);
		},
		attrs: {
			"data-tq-task": task.id,
			"data-tq-waiting": task.waiting
		}
	};
}
/** An ended task as a row: its one verdict; model and receipts; when, how long, what it cost. */
function endedRow(task, t, now, open) {
	const stamp = (ms) => resetStampOf(t, {
		resetAt: "",
		resetAtMs: ms
	}, now);
	return {
		kind: "ended",
		key: task.id,
		lead: {
			agent: task.agent,
			size: 12
		},
		name: task.name,
		state: _endedState(task.state, task.outcome, t),
		facts: {
			model: modelFact(task, false, t),
			receipt: notifyChannels(task).length === 0 ? null : {
				text: "",
				receipts: notifyChannels(task).map((ch) => ({
					ch,
					state: _notifyState(task, ch, false)
				})),
				said: notifyChannels(task).map((ch) => t("queue.notify." + _notifyState(task, ch, false), { ch: t("queue.ch." + ch) })).join(" · ")
			},
			when: task.updatedAtMs === null ? null : {
				text: agoOf(t, now - task.updatedAtMs),
				title: t("queue.d.endedAt") + " " + stamp(task.updatedAtMs)
			},
			took: task.startedAtMs === null || task.updatedAtMs === null ? null : {
				text: durationOf(t, task.updatedAtMs - task.startedAtMs),
				said: t("queue.chip.took", { time: durationOf(t, task.updatedAtMs - task.startedAtMs) })
			},
			cost: costFact(task, t, false)
		},
		open: () => {
			open(task.id);
		},
		attrs: {
			"data-tq-task": task.id,
			"data-tq-waiting": ""
		}
	};
}
/** A finished patrol round as a row (rounds.tsv: `[preempted:|yielded:]STATE[/OUTCOME]`). */
function roundRow(round, t, now) {
	const how = /^(preempted|yielded):/.exec(round.result)?.[1] ?? "";
	const [state = "", outcome = ""] = round.result.slice(how === "" ? 0 : how.length + 1).split("/");
	const ended = localStampMs(round.endedAt);
	return {
		kind: "round",
		key: "round-" + round.endedAt + round.round,
		lead: { section: "patrol" },
		name: round.axis === "" ? round.round : t("queue.round.name", {
			round: round.round,
			axis: round.axis
		}),
		state: how === "preempted" ? {
			text: t("queue.round.preempted"),
			role: "partial",
			title: round.result
		} : how === "yielded" ? {
			text: t("queue.round.yielded"),
			role: "off",
			title: round.result
		} : {
			..._endedState(state, outcome, t),
			title: round.result
		},
		facts: {
			when: ended === null ? null : {
				text: agoOf(t, now - ended),
				title: t("queue.d.endedAt") + " " + round.endedAt
			},
			took: round.seconds === null ? null : {
				text: durationOf(t, round.seconds * 1e3),
				said: t("queue.chip.took", { time: durationOf(t, round.seconds * 1e3) })
			}
		},
		attrs: { "data-tq-round": round.round }
	};
}
/** A task the queue may reorder: waiting for the lock, current runner, not patrol, not protected. */
const reorderable = (task) => task.waiting === "lock" && !task.patrol && !task.protected && (task.runnerApi ?? 1) >= 2;
/** Live tasks of one agent in the order they hold / will take its lock. */
function groupOrder(tasks, queue) {
	const rank = (task) => {
		if (task.slot !== "" || queue?.holder === task.id) return 0;
		const at = queue?.order.indexOf(task.id) ?? -1;
		return at >= 0 ? 1 + at : 1e3;
	};
	return [...tasks].sort((a, b) => rank(a) - rank(b) || (a.queuedAtMs ?? a.startedAtMs ?? 0) - (b.queuedAtMs ?? b.startedAtMs ?? 0));
}
/**
* The panel's sources in providers.ts's order (sourceRank: the paid,
* exclusive allowances first, the free pool last, anything without a row
* among the paid ones). A joined row with a dispatch agent renders with its
* queue; an agent the queue reports that no row names gets a line of its own;
* a provider without an agent renders when the balance answer has it. Agent
* rows need a dispatcher (C3 ②: without one only providers render); a
* provider row needs its provider.
*/
function _panelSources(providers, queue) {
	const dispatcher = queue !== null && queue.available;
	const byId = new Map(providers.map((row) => [row.provider, row]));
	const out = [];
	const placed = /* @__PURE__ */ new Set();
	for (const join of PROVIDER_JOIN) {
		const provider = join.provider === null ? null : byId.get(join.provider) ?? null;
		if (join.agent === null ? provider === null : provider === null && !dispatcher) continue;
		const key = join.provider ?? join.agent;
		out.push({
			key,
			label: provider?.label ?? _agentLabel(join.agent ?? key),
			join,
			provider,
			agent: dispatcher ? join.agent : null
		});
		placed.add(key);
	}
	if (dispatcher) {
		const agents = [.../* @__PURE__ */ new Set([...(queue.slotLimits ?? []).map((l) => l.agent), ...queue.active.map((t) => t.agent)])];
		for (const agent of agents) {
			if (agent === "" || placed.has(agent) || PROVIDER_JOIN.some((j) => j.agent === agent)) continue;
			out.push({
				key: agent,
				label: _agentLabel(agent),
				join: null,
				provider: null,
				agent
			});
			placed.add(agent);
		}
	}
	for (const provider of providers) {
		if (placed.has(provider.provider)) continue;
		out.push({
			key: provider.provider,
			label: provider.label,
			join: null,
			provider,
			agent: null
		});
	}
	return out.map((source, at) => ({
		source,
		at,
		rank: sourceRank({
			provider: source.provider?.provider ?? source.join?.provider,
			agent: source.agent ?? source.join?.agent
		})
	})).sort((a, b) => a.rank - b.rank || a.at - b.at).map(({ source }) => source);
}
/** Where the free pool is: the model the latest opencode task used, and the next one in file order. */
function _poolPosition(result) {
	const pool = result?.opencodePool ?? [];
	const used = [...result?.active ?? [], ...result?.recent ?? []].filter((task) => task.agent === "opencode").find((task) => (task.modelUsed ?? "") !== "" && task.attempts > 0)?.modelUsed ?? "";
	if (pool.length === 0) return used === "" ? null : {
		current: used,
		next: "",
		fromOrder: false
	};
	const at = pool.indexOf(used);
	if (at < 0) return {
		current: pool[0],
		next: pool[1] ?? pool[0],
		fromOrder: true
	};
	return {
		current: used,
		next: pool[(at + 1) % pool.length],
		fromOrder: false
	};
}
/**
* A queue's state chip, the same on the folded line and on its group's head:
* the ONE state that most needs the reader, with its count — asleep on quota,
* then queued behind the lock or a slot, then another wait, then running. A
* wait outranks running because a queue implies its holder runs. Idle is no
* chip at all. `text` is every count (the line's aria-label and title).
*/
function _queueState(t, tasks) {
	const run = tasks.filter((task) => task.slot !== "").length;
	const queued = tasks.filter(queuedFor).length;
	const quota = tasks.filter((task) => task.waiting === "quota").length;
	const other = tasks.filter((task) => task.waiting === "retry" || task.waiting === "memory").length;
	const present = [
		[
			"panel.q.quota",
			quota,
			"sleep"
		],
		[
			"panel.q.queued",
			queued,
			"queue"
		],
		[
			"panel.q.wait",
			other,
			"wait"
		],
		[
			"panel.q.run",
			run,
			"run"
		]
	].filter(([, n]) => n > 0);
	const text = present.length === 0 ? t("panel.q.idle") : present.map(([key, n]) => t(key, { n })).join(" · ");
	const top = present[0];
	return {
		text,
		chip: top === void 0 ? null : {
			text: t(top[0], { n: top[1] }),
			role: top[2],
			title: text
		}
	};
}
/**
* A source's value column: the allowance headline (used % of the first
* window, or the balance) and its tone; for the free pool, "free" — where
* the rotation stands is a fact of its group. `reset` (the headline window's,
* resetStampOf) is read out in the line's label; the clocks themselves are
* drawn once, on the group's window bars.
*/
function sourceReading(source, row, queue, t) {
	if (row !== void 0) return {
		value: row.view.value,
		reset: row.view.reset === null ? null : "↻ " + row.view.reset,
		tone: row.view.tone,
		level: row.view.level,
		title: row.view.title
	};
	if (source.join?.kind === "pool") {
		const pos = _poolPosition(queue);
		const size = queue?.opencodePool?.length ?? 0;
		return {
			value: t("panel.free"),
			reset: null,
			tone: "none",
			level: null,
			title: (pos === null ? t("panel.poolUnread") : t("panel.pool", {
				current: pos.current,
				next: pos.next || "—"
			}) + (pos.fromOrder ? t("panel.poolOrder") : "")) + (size > 1 ? " · " + t("panel.poolSwap", { n: size }) : "")
		};
	}
	return {
		value: "—",
		reset: null,
		tone: "none",
		level: null,
		title: ""
	};
}
/** The patrol phase's role: running blue, giving way amber (a wait), between rounds off, stopped red. */
const PATROL_ROLE = {
	running: "run",
	yielding: "wait",
	waiting: "off",
	stopped: "fail",
	unknown: "unknown"
};
/** rounds.tsv's local "YYYY-MM-DD HH:MM:SS" as epoch ms, null when it is not one. */
function localStampMs(stamp) {
	const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$/.exec(stamp.trim());
	return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] ?? 0)).getTime() : null;
}
/**
* Why the supervisor gives way, read off its journal line. The patterns are
* the reasons the supervisor can actually write — `others_need_slot` and
* `round_blocks_someone` in ops/host/patrol.sh, `memory_pressure_reason` in
* ops/host/agent-dispatch/resource-pressure.sh — and the spec instantiates
* every one of those templates from the files themselves (#2071):
*   manual = a manual task waits for the lock or a slot the patrol would use
*            (the id is that task, shown so the reader knows whom it waits for);
*   slot   = the patrol's own admission: its agent's run slots are all taken;
*   memory = admission deferred on memory headroom, pressure or telemetry.
* `asking <round> to wrap up …: <demand>` is the grace before a preemption.
*/
function _patrolReason(detail) {
	const wrap = /^asking \S+ to wrap up within \d+s: (.*)$/.exec(detail);
	const why = wrap?.[1] ?? detail.replace(/^(?:waiting: |preempting \S+?(?: after a \d+s wrap-up grace)?: )/, "");
	const manual = /^(\S+) is (?:waiting for (?:an \S+ run slot|its agent lock|the \S+ lock)|queued behind the round's \S+ lock)/.exec(why);
	return {
		kind: manual ? "manual" : /^the \S+ run slot is busy$/.test(why) ? "slot" : /^memory telemetry unavailable/.test(why) ? "memoryUnread" : /^memory (?:headroom low|pressure):/.test(why) ? "memory" : "other",
		task: manual?.[1] ?? "",
		wrapUp: wrap !== null
	};
}
/** The supervisor's live status as the patrol head's caption: when the next round is, what it runs now, or why it gives way. */
function patrolCaption(result, t, now) {
	const patrol = result.patrol;
	const reason = _patrolReason(patrol.detail);
	const current = result.active.find((task) => task.id === patrol.round);
	const dispatched = /round (\S+) \(([^)]+)\)/.exec(patrol.detail);
	const axis = dispatched?.[2] ?? /^patrol-(.+)-\d{8}-\d{6}$/.exec(patrol.round)?.[1] ?? "";
	const out = [];
	if (patrol.phase === "waiting" && patrol.untilMs !== null) out.push({ text: t("queue.patrolState.waitingUntil", { time: resetStampOf(t, {
		resetAt: "",
		resetAtMs: patrol.untilMs
	}, now) }) });
	if (patrol.phase === "yielding" || reason.wrapUp) {
		const why = reason.kind === "manual" ? t("queue.patrol.giveWay") : reason.kind === "slot" ? t("queue.patrol.waitSlot") : reason.kind === "memory" ? t("queue.patrol.memory") : reason.kind === "memoryUnread" ? t("queue.patrol.memoryUnread") : t("queue.patrol.otherReason");
		if (reason.wrapUp) out.push({
			text: t("queue.patrol.wrapUp"),
			voice: "warn"
		});
		out.push({
			text: why,
			voice: "warn",
			title: patrol.detail
		});
		if (reason.task !== "") out.push({
			text: reason.task,
			title: t("queue.patrol.forTask", { id: reason.task })
		});
	}
	if (patrol.phase === "running" || patrol.phase === "yielding" && current !== void 0) {
		const m = current === void 0 ? null : modelLine(current, true);
		if (dispatched || axis) out.push({
			text: dispatched ? t("queue.round.name", {
				round: dispatched[1],
				axis
			}) : axis,
			title: patrol.round
		});
		if (current?.startedAtMs != null) out.push({ text: t("queue.chip.elapsed", { time: durationOf(t, now - current.startedAtMs) }) });
		if (m !== null && m.model !== "") out.push({
			text: _modelView(m.model).label,
			title: m.model
		});
	}
	return out;
}
/** The cost cell: an API-price estimate, 'free', or '—' when the model is unpriced; null when nothing was recorded. */
function _costOf(task) {
	if (task.tokensTotal == null) return null;
	const cost = task.costUsd ?? "";
	if (cost === "free") return {
		short: "free",
		kind: "free"
	};
	if (/^\d+(\.\d+)?$/.test(cost)) return {
		short: "$" + cost,
		kind: "usd"
	};
	return {
		short: "—",
		kind: "unpriced"
	};
}
/**
* A source as a row: the sidebar's folded line and its group's head in the
* panel are this one view (the same glyph, name and value in the same
* columns), so the line a reader taps is the line the panel opens on. The
* folded line adds the queue's one state chip (its tasks are not on screen);
* the head adds its caption — the plan, the run slots, the pool — in words.
*/
function sourceView(source, row, result, t) {
	const reading = sourceReading(source, row, result, t);
	const queue = source.agent === null || result === null || !result.available ? null : _queueState(t, result.active.filter((task) => task.agent === source.agent));
	const lane = source.agent === null || result === null || !result.available ? void 0 : _slotLanes(result).find((l) => l.agent === source.agent);
	const pool = source.join?.kind === "pool" ? _poolPosition(result) : null;
	const poolSize = result?.opencodePool?.length ?? 0;
	return {
		kind: "source",
		key: source.key,
		lead: { source },
		name: source.label,
		value: {
			text: reading.value,
			tone: reading.tone,
			level: reading.level
		},
		state: queue?.chip ?? null,
		facts: {},
		caption: [
			{ text: source.join?.plan === void 0 ? "" : t(source.join.plan) },
			lane === void 0 ? { text: "" } : {
				text: t("queue.slotCount", {
					used: lane.used,
					max: lane.max ?? "—"
				}),
				voice: lane.tone === "stale" ? "warn" : void 0,
				title: t("queue.lanesTitle")
			},
			source.join?.kind !== "pool" ? { text: "" } : pool === null ? { text: t("panel.poolUnread") } : {
				text: t("panel.pool", {
					current: _modelView(pool.current).label,
					next: pool.next === "" ? "—" : _modelView(pool.next).label
				}) + (pool.fromOrder ? t("panel.poolOrder") : ""),
				title: reading.title
			},
			poolSize > 1 && source.join?.kind === "pool" ? {
				text: t("panel.poolSize", { n: poolSize }),
				title: t("panel.poolSwap", { n: poolSize })
			} : { text: "" }
		],
		reading,
		queue
	};
}
/** Provider rows with their display projection: what every surface of the cell reads. */
function balanceRows(result, t, now) {
	return (result?.providers ?? []).map((provider) => ({
		...provider,
		view: _rowDisplay(provider.result, t, now),
		note: _balanceNote(provider.result, t)
	}));
}
/** The provider windows of an agent (a quota wait names the reset it waits for). */
function agentWindows(rows, agent) {
	const join = PROVIDER_JOIN.find((j) => j.agent === agent);
	return (join?.provider ? rows.get(join.provider) : void 0)?.result.snapshot?.windows;
}
function allowanceDetail(row, t, now) {
	const wins = row.result.snapshot === null ? [] : windowsOf(t, row.result, now);
	if (wins.length > 0) return {
		kind: "windows",
		windows: wins.map((w) => {
			const fill = w.percent === null ? null : Math.max(0, Math.min(100, Math.round(w.percent)));
			return {
				label: w.label,
				percent: w.percent,
				fill,
				reset: w.reset,
				state: row.view.tone === "stale" ? "stale" : _usedLevel(fill, row.result.threshold)
			};
		})
	};
	if (row.note !== null) return null;
	const title = row.view.title;
	if (title === "") return null;
	const prefix = t("balance.apiBalance") + " · ";
	return {
		kind: "text",
		text: title.startsWith(prefix) ? title.slice(prefix.length) : title
	};
}
function panelGroup(source, result, rows, t, now, open) {
	const row = source.provider === null ? void 0 : rows.get(source.provider.provider);
	const agent = source.agent;
	const tasks = agent === null || result === null ? [] : result.active.filter((task) => task.agent === agent);
	const queue = agent === null ? void 0 : (result?.queues ?? []).find((q) => q.agent === agent);
	const notes = [];
	if (queue?.held && tasks.every((task) => task.id !== queue.holder)) notes.push(queue.holder !== "" ? t("queue.holderOther", { id: queue.holder }) : t("queue.holderUnnamed"));
	if (queue?.quotaUntilMs) notes.push(t("queue.quotaHint", {
		time: resetStampOf(t, {
			resetAt: "",
			resetAtMs: queue.quotaUntilMs
		}, now),
		by: queue.quotaBy
	}));
	const snapshotAt = row?.result.snapshot?.asOf ? Date.parse(row.result.snapshot.asOf) : NaN;
	const balanceNote = row === void 0 || row.note === null ? null : row.result.status === "stale" && Number.isFinite(snapshotAt) ? t("panel.staleAt", {
		message: row.result.message ?? "—",
		time: resetStampOf(t, {
			resetAt: "",
			resetAtMs: snapshotAt
		}, now)
	}) : row.note;
	const { reading: _reading, queue: _queue, ...view } = sourceView(source, row, result, t);
	return {
		source,
		head: {
			...view,
			state: null,
			key: "head-" + source.key,
			attrs: { "data-pp-head": source.key }
		},
		row,
		balanceNote,
		detail: row === void 0 ? null : allowanceDetail(row, t, now),
		notes,
		tasks: groupOrder(tasks, queue).map((task) => ({
			task,
			row: taskRow(task, t, now, open, agentWindows(rows, task.agent))
		}))
	};
}
/** Ended work, newest first across agents: every ended task is resident (see RESIDENT_ROUNDS). */
function recentSection(result, t, now, open) {
	if (result === null || !result.available || result.recent.length === 0) return null;
	return {
		head: {
			kind: "head",
			key: "head-recent",
			lead: { section: "recent" },
			name: t("queue.recentHeading"),
			state: null,
			facts: {}
		},
		rows: result.recent.map((task) => endedRow(task, t, now, open))
	};
}
/**
* Patrol: a section head (the phase as its state chip, the live status as its
* caption), the newest round resident, the earlier rounds and the raw journal
* line folded (RESIDENT_ROUNDS).
*/
function patrolSection(result, t, now) {
	if (result === null || !result.available) return null;
	const patrol = result.patrol;
	return {
		head: {
			kind: "head",
			key: "head-patrol",
			lead: { section: "patrol" },
			name: t("queue.patrolHeading"),
			state: {
				text: t("queue.patrolState." + patrol.phase),
				role: PATROL_ROLE[patrol.phase] ?? "unknown",
				title: patrolPhraseOf(result, t, now)
			},
			facts: {},
			caption: patrolCaption(result, t, now),
			attrs: { "data-tq-patrol": patrol.phase }
		},
		rounds: (patrol.rounds ?? []).map((round) => roundRow(round, t, now)),
		detail: patrol.detail
	};
}
/** The ops entry's footer: its version and runner api, or why it is missing / skewed. */
function opsFooter(result, t) {
	if (result === null || !result.available || result.ops === void 0) return null;
	const skew = opsProblem(result, t);
	const ops = result.ops;
	return {
		text: skew !== "" ? skew : t("queue.ops.footer", {
			v: ops.version,
			runner: ops.runnerApi
		}),
		bad: skew !== "",
		version: ops.available ? ops.version : "missing"
	};
}
/**
* Why a half of the cell is not (fully) there: a failed or stale queue read, a
* host without the dispatcher, a failed balance read. `error` is a transport
* failure (the fetch never answered); an in-band failure arrives in the result.
*/
function panelNotices(input, t) {
	const { queue, queueError, balances, balanceError, rowCount } = input;
	const queueProblem = queueError ?? (queue !== null && (queue.status === "stale" || queue.status === "failed") ? queue.message : null);
	const out = [];
	if (queueProblem !== null && queueProblem !== "") out.push({
		key: "qerr",
		bad: true,
		text: t(queue === null || queue.status === "failed" ? "queue.readFailed" : "queue.staleWith", { message: queueProblem })
	});
	if (queueProblem === null && queue === null) out.push({
		key: "qloading",
		bad: false,
		text: t("panel.queueLoading")
	});
	if (queueProblem === null && queue !== null && !queue.available) out.push({
		key: "qunavailable",
		bad: false,
		text: t("panel.queueUnavailable")
	});
	if (balanceError !== null) out.push({
		key: "berr",
		bad: true,
		text: rowCount === 0 ? t("balance.readFailed", { message: balanceError }) : t("balance.staleWith", { message: balanceError })
	});
	return out;
}
function panelModel(input, t, now, open = () => {}) {
	const rows = balanceRows(input.balances, t, now);
	const byProvider = new Map(rows.map((row) => [row.provider, row]));
	const sources = _panelSources(input.balances?.providers ?? [], input.queue);
	return {
		title: t("panel.title"),
		notices: panelNotices({
			...input,
			rowCount: rows.length
		}, t),
		empty: sources.length === 0 && input.balanceError === null ? input.balances === null ? t("balance.reading") : t("panel.noSources") : null,
		groups: sources.map((source) => panelGroup(source, input.queue, byProvider, t, now, open)),
		recent: recentSection(input.queue, t, now, open),
		patrol: patrolSection(input.queue, t, now),
		footer: opsFooter(input.queue, t)
	};
}
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
const { createElement, useEffect, useId, useRef, useState } = React;
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
/**
* The T+1 verdict in the active locale. `verdictKind` is the stable code; a
* host that predates it sends only the rendered text, which is passed through
* rather than dropped — the same fallback rule as the balance windows.
*/
function verdictOf(t, t1) {
	const kind = t1.verdictKind;
	if (kind == null) return t1.verdict;
	return t("t1." + kind);
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
/** Action code → dictionary key. The words live in the dictionary, not here. */
const ACT = {
	buy: "action.buy",
	add: "action.add",
	trim: "action.trim",
	sell: "action.sell",
	cut: "action.cut",
	hold: "action.hold",
	hold_and_watch: "action.hold",
	trim_on_rebound: "action.trim_on_rebound",
	t_only: "action.t_only",
	add_only_on_trigger: "action.add_only_on_trigger",
	reject: "action.reject",
	watch: "action.watch",
	abstain: "action.abstain"
};
const DRV = {
	technical: "driver.technical",
	fundamental: "driver.fundamental",
	sentiment: "driver.sentiment",
	mixed: "driver.mixed",
	risk_rule: "driver.risk_rule",
	catalyst: "driver.catalyst",
	influencer: "driver.influencer",
	macro: "driver.macro",
	peer: "driver.peer"
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
	followed: "exe.followed",
	not_followed: "exe.not_followed",
	unknown: "exe.unknown"
};
/** The plan-vs-fill relation, stated instead of left to be inferred. */
const ALIGN = {
	same: ["align.same", "follow"],
	opposite: ["align.opposite", "skip"],
	other: ["align.other", ""]
};
const EMO = {
	fomo: "emo.fomo",
	revenge: "emo.revenge",
	averaging_down: "emo.averaging_down",
	fear: "emo.fear",
	euphoria: "emo.euphoria",
	calm: "emo.calm",
	mixed: "emo.mixed"
};
const FILTER_LABEL = {
	all: "filter.all",
	miss: "filter.miss",
	sold: "filter.sold",
	dec: "filter.dec"
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
/** Dashboard-parity money formatter (test seam). */
function _fmtMoney(value, currency = "") {
	if (value === null || !isFinite(value)) return "—";
	return (currency === "USD" ? "$" : currency === "HKD" ? "HK$" : "") + (Math.abs(value) >= 1e3 ? value.toLocaleString("en-US", { maximumFractionDigits: 0 }) : value.toLocaleString("en-US", { maximumFractionDigits: 2 }));
}
/** A fill price as written, or '—' when the ledger carried none (#1590). */
function fmtPrice(value, sym = "") {
	if (value === null || !isFinite(value)) return "—";
	return sym + value;
}
/** Dashboard-parity percentage formatter (test seam). */
function _fmtPct(value, digits = 2) {
	if (value === null || !isFinite(value)) return "—";
	return (value >= 0 ? "+" : "") + value.toFixed(digits) + "%";
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
	const t = props.t;
	const trace = props.trace;
	const decision = trace.decision;
	const sym = trace.currency === "HKD" ? "HK$" : "$";
	/** Action code → the word, falling back to the raw code the host sent. */
	const act = (code) => code === null ? "" : ACT[code] === void 0 ? code : t(ACT[code]);
	const fillText = act(trace.action) + " " + trace.shares + t("trace.sharesAt") + fmtPrice(trace.price, sym);
	if (decision === null) {
		const t1miss = trace.t1 === null ? null : h("div", { className: cx("tnode", t1NodeClass(trace.t1.tone)) }, h("div", { className: cx("tw") }, trace.t1.date), h("div", { className: cx("n") }, t("trace.t1Close")), h("div", { className: cx("v") }, (trace.t1.delta >= 0 ? "+" : "") + trace.t1.delta + "% · " + verdictOf(t, trace.t1)));
		return h("div", { className: cx("dbody") }, h("div", { className: cx("trhead") }, t("trace.titleNoPlan")), h("div", { className: cx("trace") }, h("div", { className: cx("tnode", "dec") }, h("div", { className: cx("n") }, t("trace.planThen")), h("div", {
			className: cx("v"),
			style: { color: "var(--cap)" }
		}, t("trace.noPlanRecord"))), h("div", { className: cx("tnode", "follow") }, h("div", { className: cx("tw") }, trace.date ?? ""), h("div", { className: cx("n") }, t("trace.realFill")), h("div", { className: cx("v") }, fillText)), t1miss), trace.note === null ? null : h("div", { className: cx("tnote") }, esc(trace.note)), h("div", { className: cx("tmiss") }, t("trace.unpaired")));
	}
	const [alignKey, alignTone] = ALIGN[decision.alignment ?? ""] ?? ["", ""];
	const alignLabel = alignKey === "" ? "" : t(alignKey);
	const planned = act(decision.action) + (decision.sizeShares === null ? "" : " " + decision.sizeShares + t("trace.shares")) + (decision.plannedPrice === null ? "" : " @ " + decision.plannedPrice) + (decision.confidence === null ? "" : t("trace.confidence") + Math.round(decision.confidence * 100) + "%") + (decision.drivenBy === null ? "" : " · " + (DRV[decision.drivenBy] === void 0 ? decision.drivenBy : t(DRV[decision.drivenBy])));
	const why = decision.rationale ?? decision.bull ?? "";
	const emotion = decision.emotion !== null && decision.emotion !== "calm" ? EMO[decision.emotion] === void 0 ? decision.emotion : t(EMO[decision.emotion]) : null;
	const chips = [];
	if (decision.condition !== null) chips.push(h("span", {
		className: cx("pc"),
		key: "c"
	}, t("trace.trigger") + decision.condition));
	if (decision.execution !== null) chips.push(h("span", {
		className: cx("pc"),
		key: "e"
	}, t("trace.selfGrade") + (EXE[decision.execution] === void 0 ? decision.execution : t(EXE[decision.execution]))));
	const t1node = trace.t1 === null ? null : h("div", { className: cx("tnode", t1NodeClass(trace.t1.tone)) }, h("div", { className: cx("tw") }, trace.t1.date), h("div", { className: cx("n") }, t("trace.t1Close")), h("div", { className: cx("v") }, (trace.t1.delta >= 0 ? "+" : "") + trace.t1.delta + "% · " + verdictOf(t, trace.t1)));
	let pnlText;
	let pnlTone;
	let pnlLabel;
	if (trace.realizedPnl !== null) {
		pnlText = _fmtMoney(trace.realizedPnl, trace.currency);
		pnlTone = trace.realizedPnl >= 0 ? "win" : "loss";
		pnlLabel = t("trace.realized");
	} else if (trace.holdPnl !== null) {
		pnlText = _fmtPct(trace.holdPnl);
		pnlTone = trace.holdPnl >= 0 ? "win" : "loss";
		pnlLabel = t("trace.floating", { ticker: trace.ticker });
	} else {
		pnlText = t("trace.openPosition");
		pnlTone = "";
		pnlLabel = t("trace.pnl");
	}
	return h("div", { className: cx("dbody") }, h("div", { className: cx("trhead") }, t("trace.titleWithPlan", { date: decision.planDate ?? "" })), h("div", { className: cx("trace") }, h("div", { className: cx("tnode", "dec") }, h("div", { className: cx("tw") }, decision.planDate ?? ""), h("div", { className: cx("n") }, t("trace.planThen")), h("div", { className: cx("v") }, planned)), h("div", { className: cx("tnode", alignTone) }, h("div", { className: cx("tw") }, trace.date ?? ""), h("div", { className: cx("n") }, t("trace.realFill")), h("div", { className: cx("v", "fill-v") }, fillText, alignLabel === "" ? null : h("span", { className: cx("pc", alignTone) }, alignLabel))), t1node, h("div", { className: cx("tnode", pnlTone) }, h("div", { className: cx("n") }, pnlLabel), h("div", { className: cx("v") }, pnlText))), chips.length === 0 ? null : h("div", { className: cx("pchips") }, chips), why === "" ? null : h("div", { className: cx("tnote", "why") }, h("span", { className: cx("k") }, t("trace.why")), esc(why)), emotion === null ? null : h("div", { className: cx("tnote", "emo") }, h("span", { className: cx("k") }, t("trace.emotion")), "⚡ " + emotion), trace.note === null ? null : h("div", { className: cx("tnote") }, h("span", { className: cx("k") }, t("trace.note")), esc(trace.note)));
}
function TraceCell(props) {
	const t = props.t;
	const trace = props.trace;
	let pnl;
	if (trace.realizedPnl !== null) pnl = h("span", { className: cx("pnl", trace.realizedPnl >= 0 ? "up" : "down") }, _fmtMoney(trace.realizedPnl, trace.currency));
	else if (trace.holdPnl !== null) pnl = h("span", { className: cx("pnl", trace.holdPnl >= 0 ? "up" : "down") }, h("span", { className: cx("pnlk") }, t("trace.holding")), _fmtPct(trace.holdPnl));
	else pnl = h("span", { className: cx("pnl", "na") }, "—");
	let t1tag;
	if (trace.t1 !== null) {
		const tone = t1ChipClass(trace.t1.tone);
		const label = "T+1 " + (trace.t1.delta >= 0 ? "+" : "") + trace.t1.delta + "% " + verdictOf(t, trace.t1);
		t1tag = h("span", {
			className: cx("t1", tone),
			"data-tone": tone
		}, label);
	} else t1tag = h("span", {
		className: cx("t1", "flat"),
		"data-tone": "flat"
	}, t("trace.t1Pending"));
	let alignTag = null;
	if (trace.decision?.alignment === "opposite") alignTag = h("span", {
		className: cx("al", "opp"),
		"data-align": "opposite"
	}, t("trace.opposite"));
	return h("div", {
		className: cx("cell", trace.decision !== null && "hasdec", props.open && "open"),
		"data-cell": "trace",
		role: "button",
		tabIndex: 0,
		"aria-expanded": props.open,
		onClick: props.onToggle,
		onKeyDown: props.onKeyDown
	}, h("div", { className: cx("main") }, h("span", { className: cx("dotm") }), h("span", { className: cx("tk") }, trace.ticker, h("span", { className: cx("mkt", trace.market === "HK" && "hk") }, trace.market === "HK" ? t("trace.market.hk") : t("trace.market.us"))), h(Chip, null, ACT[trace.action] === void 0 ? trace.action : t(ACT[trace.action])), h("span", { className: cx("qty") }, trace.shares + " @" + fmtPrice(trace.price)), h("span", { className: cx("sp") }), pnl), h("div", { className: cx("sub") }, t1tag, alignTag, h("span", { className: cx("date") }, (trace.date ?? "").slice(5)), h("span", { className: cx("chev") }, "▾")), h("div", { className: cx("detail") }, h("div", { className: cx("dinner") }, props.open ? h(TraceDetail, {
		trace,
		t
	}) : null)));
}
/** Stable row identities are derived before filtering, so switching filters
* cannot remount the same trade and discard its expanded state (#1603). */
function _traceKeys(traces) {
	const occurrences = /* @__PURE__ */ new Map();
	const keys = /* @__PURE__ */ new Map();
	for (const trace of traces) {
		const base = trace.ticker + trace.date + trace.shares + ":" + trace.action;
		const occurrence = occurrences.get(base) ?? 0;
		occurrences.set(base, occurrence + 1);
		keys.set(trace, base + ":" + occurrence);
	}
	return keys;
}
/** Skeleton row for the cold-start loading state (no cache yet). */
function SkeletonRow() {
	return h("div", { className: cx("skel") }, h("div", { className: cx("skel-dot") }), h("div", { className: cx("skel-bar", "w40") }), h("div", { className: cx("skel-bar", "w20") }));
}
function messageOf(error) {
	return error instanceof Error ? error.message : String(error);
}
/**
* The host answered, but read no ledger. `readPortfolio` reports a missing or
* unparseable portfolio.json as an empty book with `lastUpdated: null`, and
* every ledger writer stamps `last_updated`, so a null there is "could not
* read", not "no fills" — which the tab used to print as $0 and 0/0 (#2180).
*/
var LedgerUnreadable = class extends Error {};
function todayIso() {
	const now = /* @__PURE__ */ new Date();
	return now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" + String(now.getDate()).padStart(2, "0");
}
function relativeDay(iso, today, t) {
	if (iso === today) return t("time.today");
	const at = (date) => (/* @__PURE__ */ new Date(date + "T00:00:00")).getTime();
	const days = Math.round((at(today) - at(iso)) / 864e5);
	if (days === 1) return t("time.yesterday");
	if (days >= 2 && days <= 7) return t("time.daysAgo", { days });
	return t("time.date", {
		month: parseInt(iso.slice(5, 7)),
		day: parseInt(iso.slice(8, 10))
	});
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
function renderRowDetail(row, t, now) {
	return renderAllowance(allowanceDetail(row, t, now));
}
/** panel.ts's AllowanceDetail as the window lines (label · used · reset over a hairline bar) or the money split. */
function renderAllowance(detail) {
	if (detail === null) return null;
	if (detail.kind === "text") return h("div", { className: cx("bp-sub") }, detail.text);
	return h("div", { className: cx("bp-wins") }, detail.windows.map((w) => h("div", {
		className: cx("bp-win"),
		key: w.label
	}, h("div", { className: cx("bp-win-line") }, h("span", { className: cx("bp-win-label") }, w.label), h("span", { className: cx("bp-win-pct") }, w.percent === null ? "—" : Math.round(w.percent) + "%"), h("span", { className: cx("bp-win-reset") }, w.reset === "" ? "" : "↻ " + w.reset)), h("div", { className: cx("bp-win-bar") }, h("div", {
		className: cx("bp-win-fill"),
		style: w.fill === null ? { width: "0%" } : { width: w.fill + "%" },
		"data-balance-state": w.state
	})))));
}
/**
* The balance channel every surface shares: cached-first state, the mount
* fetch, the refreshMs poll, the #870 refresh flash and the pinned headline.
* Lifted out of the header chip verbatim so the sidebar button and the
* global panel keep exactly its behaviour. `pollKey` re-arms the fetch the
* way the chip's `sessionId` dependency did; root-scoped surfaces pass a
* constant. A registration that supplies `subscribeBalances` also hears
* answers fetched by its sibling surface (the panel's manual refresh updates
* the foot button at once).
*/
function useProviderBalances(props, pollKey) {
	const mountedRef = useRef(true);
	const [data, setData] = useState(() => ({
		result: props.cachedBalances(),
		loading: false,
		error: null
	}));
	const selected = props.useStore((state) => state.selected);
	const select = (provider) => {
		props.actions.select(provider);
	};
	const [flash, setFlash] = useState(null);
	const flashTimerRef = useRef(null);
	const runBalances = (force) => {
		props.fetchBalances(force).then((result) => {
			if (!mountedRef.current) return;
			setData({
				result,
				loading: false,
				error: null
			});
			if (force) {
				setFlash(result.providers.some((p) => p.result.status === "fresh") ? "ok" : "same");
				if (flashTimerRef.current !== null) clearTimeout(flashTimerRef.current);
				flashTimerRef.current = setTimeout(() => {
					setFlash(null);
				}, 1200);
			}
		}, (err) => {
			if (!mountedRef.current) return;
			const error = (err instanceof Error ? err.message : String(err)) || props.t("balance.unknownError");
			setData((current) => ({
				...current,
				loading: false,
				error
			}));
		});
	};
	useEffect(() => {
		mountedRef.current = true;
		runBalances(false);
		const unsubscribe = props.subscribeBalances === void 0 ? null : props.subscribeBalances((result) => {
			if (mountedRef.current) setData((current) => ({
				...current,
				result,
				error: null
			}));
		});
		return () => {
			mountedRef.current = false;
			if (unsubscribe !== null) unsubscribe();
			if (flashTimerRef.current !== null) clearTimeout(flashTimerRef.current);
		};
	}, [pollKey]);
	useEffect(() => {
		const intervalMs = Math.max(6e4, data.result?.refreshMs ?? 6e4);
		const visible = () => typeof document === "undefined" || document.visibilityState === "visible";
		let hiddenSince = 0;
		const timer = setInterval(() => {
			if (visible()) runBalances(false);
		}, intervalMs);
		const onVisibility = () => {
			if (!visible()) {
				hiddenSince = Date.now();
				return;
			}
			if (hiddenSince !== 0 && Date.now() - hiddenSince >= intervalMs) runBalances(false);
			hiddenSince = 0;
		};
		if (typeof document !== "undefined") document.addEventListener("visibilitychange", onVisibility);
		return () => {
			clearInterval(timer);
			if (typeof document !== "undefined") document.removeEventListener("visibilitychange", onVisibility);
		};
	}, [data.result?.refreshMs, pollKey]);
	const now = Date.now();
	const rows = balanceRows(data.result, props.t, now);
	const primary = rows.find((row) => row.provider === selected) ?? rows[0];
	const refresh = () => {
		setData((current) => ({
			...current,
			loading: true
		}));
		runBalances(true);
	};
	return {
		data,
		rows,
		primary,
		select,
		flash,
		refresh,
		empty: rows.length === 0 && data.error !== null && !data.loading ? {
			tone: "stale",
			title: props.t("balance.readFailed", { message: data.error })
		} : {
			tone: "none",
			title: props.t(data.result === null ? "balance.loading" : "balance.noProviders")
		}
	};
}
/**
* The sidebar-foot glyph: a quota gauge drawn with the geometry and stroke of
* the host's own `IconGaugeOutline16` (ui-primitives, MIT; redrawn inline
* because client bundles may not import another plugin's modules), so it sits
* in the same icon language as Settings and the Cordis badge beside it.
* Status rides a small badge notched out of the bottom-right corner instead
* of the whole icon being a coloured disc: round = ok, rounded square = low,
* hollow ring = stale (the number is not trustworthy), no badge while there
* is nothing to judge. Each state remains legible without relying on hue.
* The notch is an SVG mask, not a painted ring, so it stays clean over the
* host's plain row and its hover wash.
*/
function renderFootStatusBadge(tone) {
	const attrs = {
		className: cx("bal-badge"),
		"data-balance-state": tone
	};
	if (tone === "low") return h("rect", {
		...attrs,
		x: 10.15,
		y: 10.15,
		width: 5.2,
		height: 5.2,
		rx: 1.1
	});
	if (tone === "ok" || tone === "stale") return h("circle", {
		...attrs,
		cx: 12.75,
		cy: 12.75,
		r: tone === "stale" ? 2.05 : 2.6
	});
	return null;
}
function renderBalanceGlyph(tone, size, instanceId) {
	const badge = tone === "ok" || tone === "low" || tone === "stale";
	const notch = "clawock-balance-notch-" + instanceId;
	return h("svg", {
		className: cx("bal-glyph"),
		width: size,
		height: size,
		viewBox: "0 0 16 16",
		fill: "none",
		"aria-hidden": "true"
	}, badge ? h("defs", null, h("mask", {
		id: notch,
		maskUnits: "userSpaceOnUse",
		x: 0,
		y: 0,
		width: 16,
		height: 16
	}, h("rect", {
		x: 0,
		y: 0,
		width: 16,
		height: 16,
		fill: "white"
	}), h("circle", {
		cx: 12.75,
		cy: 12.75,
		r: 3.9,
		fill: "black"
	}))) : null, h("g", { mask: badge ? "url(#" + notch + ")" : void 0 }, h("path", {
		d: "M3.49 13.26A6.375 6.375 0 1 1 12.51 13.26",
		stroke: "currentColor",
		strokeWidth: 1.25,
		strokeLinecap: "round"
	}), h("path", {
		d: "M8 8.75L11.4 5.35",
		stroke: "currentColor",
		strokeWidth: 1.25,
		strokeLinecap: "round"
	}), h("circle", {
		cx: 8,
		cy: 8.75,
		r: 1.55,
		fill: "currentColor"
	})), renderFootStatusBadge(tone));
}
/** The headline reading: dot (or the foot glyph) · value · reset · weekly sub-reading. */
function renderBalanceHeadline(primary, withLabel, glyph = false, emptyTone = "none", instanceId = "") {
	const lead = (tone) => glyph ? h("span", { className: cx("bal-lead") }, renderBalanceGlyph(tone, 16, instanceId)) : h("span", { className: cx("bchip-dot") });
	return primary === void 0 ? h("span", { className: cx("bchip-item") }, lead(emptyTone), "—") : h("span", {
		className: cx("bchip-item"),
		"data-pb-provider": primary.provider,
		"data-pb-role": "chip",
		"data-balance-state": primary.view.tone
	}, lead(primary.view.tone), withLabel ? h("span", { className: cx("bchip-name") }, primary.label) : null, h("span", {
		className: cx("bchip-v"),
		"data-balance-state": primary.view.tone,
		"data-used-level": primary.view.level === null ? void 0 : primary.view.level
	}, primary.view.value), primary.view.reset === null ? null : h("span", { className: cx("bchip-reset") }, "↻ " + primary.view.reset), primary.view.sub === null ? null : h("span", {
		className: cx("bchip-sub"),
		"aria-hidden": "true"
	}, primary.view.sub));
}
/** The panel body: title + refresh, then every provider row (click = pin). */
function renderBalancePanelBody(state, t) {
	const { data, rows, primary, select, flash, refresh } = state;
	return [
		h("div", {
			className: cx("bp-head"),
			key: "head"
		}, h("span", { className: cx("bp-title") }, t("balance.panelHeading")), h("button", {
			type: "button",
			className: cx("bal-rf", data.loading && "spin", flash === "ok" && "flash-ok", flash === "same" && "flash-same"),
			"data-refresh": "true",
			"aria-label": t("balance.refreshAll"),
			title: t("balance.refreshNow"),
			onClick: refresh
		}, flash === "ok" ? "✓" : "↻")),
		rows.length > 0 && data.error !== null && !data.loading ? h("div", {
			className: cx("bp-note", "warn"),
			key: "error",
			role: "status"
		}, t("balance.staleWith", { message: data.error })) : null,
		rows.length === 0 ? h("div", {
			className: cx("bp-empty"),
			key: "empty",
			role: "status"
		}, data.error !== null && !data.loading ? t("balance.readFailed", { message: data.error }) : t("balance.reading")) : h("div", { key: "rows" }, rows.map((row) => h("button", {
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
		}, row.note) : null, renderRowDetail(row, t, Date.now())])))
	];
}
function ProviderBalanceChip(props) {
	const t = props.t;
	const state = useProviderBalances(props, props.sessionId);
	const { rows, primary } = state;
	const [open, setOpen] = useState(false);
	const instanceId = useId();
	const rootRef = useRef(null);
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
	return h("span", {
		className: cx("pbc"),
		ref: rootRef
	}, h("button", {
		type: "button",
		className: cx("bchip"),
		"data-balance-state": primary !== void 0 ? primary.view.tone : state.empty.tone,
		"data-pb-provider": primary !== void 0 ? primary.provider : "",
		"aria-expanded": open,
		"aria-haspopup": "dialog",
		"aria-label": t("balance.panelTitle"),
		title: primary !== void 0 ? primary.label + " · " + primary.view.title + (rows.length > 1 ? t("balance.otherProviders") : "") : state.empty.title,
		onClick: () => {
			setOpen(!open);
		}
	}, renderBalanceHeadline(primary, false, false, state.empty.tone, instanceId)), h("div", panelAttrs(open, t("balance.panelTitle")), renderBalancePanelBody(state, t)));
}
/** Foot-action id of the balance surface (a stable DOM contract for probes). */
const BALANCE_PANEL = "clawock-provider-balance";
/**
* The shared popover attributes. The closed panel is hidden with opacity +
* `pointer-events:none` (so the open/close transition keeps working), and
* `inert` is what actually removes it from interaction: opacity alone leaves
* every row button and the refresh control in the tab order, so a keyboard
* user tabbing through the sidebar used to land on five invisible controls.
*
* `inert` is written as `''`, never `true`. The host ships React 18
* (@types/react ~18.3, react ^18.2), where `inert` is not yet a known boolean
* attribute: `inert={true}` is dropped without a warning in the production
* build, which is how the first version of this fix rendered an attribute-less
* panel and changed nothing. React 19 added the boolean form; the empty-string
* form works on both, and is the idiom already used for `data-active` below.
*/
function panelAttrs(open, label, extra) {
	return {
		className: cx("bp"),
		"data-open": open ? "true" : "false",
		role: open ? "dialog" : "none",
		"aria-label": label,
		inert: open ? void 0 : "",
		...extra
	};
}
/** Gap the popover keeps from the viewport top, and the least room it is ever given. */
const POPOVER_TOP_GAP = 12;
const POPOVER_MIN_ROOM = 240;
/**
* The foot popover's open state and anchor, shared by every foot row. While
* open: re-anchor on resize, Escape closes, a pointerdown outside the root
* closes (document/window exist only in the browser — tests have no DOM).
* `back` lets a popover with a nested layer take Escape first: it returns
* true when it closed that layer, and the popover stays open.
*/
function useFootPopover(back) {
	const [open, setOpen] = useState(false);
	const [anchor, setAnchor] = useState(null);
	const rootRef = useRef(null);
	const backRef = useRef(back);
	backRef.current = back;
	const place = () => {
		const root = rootRef.current;
		if (root === null || typeof window === "undefined") return;
		const rect = root.getBoundingClientRect();
		setAnchor({
			left: rect.left,
			bottom: window.innerHeight - rect.top + 8,
			room: Math.max(POPOVER_MIN_ROOM, rect.top - 8 - POPOVER_TOP_GAP)
		});
	};
	useEffect(() => {
		if (!open || typeof document === "undefined") return void 0;
		const onKey = (event) => {
			if (event.key !== "Escape") return;
			if (backRef.current?.() === true) return;
			setOpen(false);
		};
		const onDown = (event) => {
			const root = rootRef.current;
			if (root !== null && event.target instanceof Node && !root.contains(event.target)) setOpen(false);
		};
		document.addEventListener("keydown", onKey);
		document.addEventListener("pointerdown", onDown, true);
		window.addEventListener("resize", place);
		return () => {
			document.removeEventListener("keydown", onKey);
			document.removeEventListener("pointerdown", onDown, true);
			window.removeEventListener("resize", place);
		};
	}, [open]);
	return {
		open,
		setOpen,
		anchor,
		place,
		rootRef
	};
}
/** Cached-first read, the mount fetch and the poll, like useProviderBalances in miniature. */
function useTaskQueue(props) {
	const mountedRef = useRef(true);
	const [data, setData] = useState(() => ({
		result: props.cachedTaskQueue(),
		loading: false,
		error: null
	}));
	const read = (force) => {
		props.fetchTaskQueue(force).then((result) => {
			if (mountedRef.current) setData({
				result,
				loading: false,
				error: null
			});
		}, (err) => {
			if (!mountedRef.current) return;
			const error = (err instanceof Error ? err.message : String(err)) || props.t("balance.unknownError");
			setData((current) => ({
				...current,
				loading: false,
				error
			}));
		});
	};
	useEffect(() => {
		mountedRef.current = true;
		read(false);
		return () => {
			mountedRef.current = false;
		};
	}, []);
	useEffect(() => {
		const visible = () => typeof document === "undefined" || document.visibilityState === "visible";
		const timer = setInterval(() => {
			if (visible()) read(false);
		}, Math.max(5e3, data.result?.refreshMs ?? 15e3));
		const onVisible = () => {
			if (visible()) read(false);
		};
		if (typeof document !== "undefined") document.addEventListener("visibilitychange", onVisible);
		return () => {
			clearInterval(timer);
			if (typeof document !== "undefined") document.removeEventListener("visibilitychange", onVisible);
		};
	}, [data.result?.refreshMs]);
	const refresh = () => {
		setData((current) => ({
			...current,
			loading: true
		}));
		read(true);
	};
	return {
		data,
		refresh
	};
}
/**
* The executor layer: a 14px outline glyph in the host's icon stroke, one
* shape per CLI. All three are plugin-drawn pictograms, not vendor marks:
* Claude a spark, Codex a terminal prompt, OpenCode brackets. The Codex
* prompt identifies the coding CLI without pretending a generic hexagon is
* OpenAI artwork. Monochrome label ink keeps these separate from status.
*/
function renderAgentGlyph(agent, size = 14) {
	const stroke = {
		stroke: "currentColor",
		strokeWidth: 1.25,
		strokeLinecap: "round",
		strokeLinejoin: "round",
		fill: "none"
	};
	const shape = agent === "claude" ? h("path", {
		...stroke,
		d: "M7 1.8V12.2M1.8 7H12.2M3.3 3.3L10.7 10.7M10.7 3.3L3.3 10.7"
	}) : agent === "codex" ? h("path", {
		...stroke,
		d: "M2.5 3.5L6.3 7L2.5 10.5M7.5 10.5H11.5"
	}) : agent === "opencode" ? h("path", {
		...stroke,
		d: "M5 2H2.5V12H5M9 2H11.5V12H9"
	}) : h("circle", {
		...stroke,
		cx: 7,
		cy: 7,
		r: 5
	});
	return h("svg", {
		className: cx("tq-agent-glyph"),
		width: size,
		height: size,
		viewBox: "0 0 14 14",
		"aria-hidden": "true",
		"data-tq-agent": agent
	}, shape);
}
const RECEIPT_GLYPH = {
	sent: "M1.6 5.2L3.6 7.2L8.4 2.4",
	failed: "M2.2 2.2L7.8 7.8M7.8 2.2L2.2 7.8",
	unknown: "M3.3 3.4a1.7 1.7 0 1 1 2.3 1.6C5.1 5.2 5 5.5 5 6M5 8v.1",
	planned: "M2.2 5H7.8"
};
function renderNotifyIcons(task, t, live) {
	return renderReceipts(notifyChannels(task).map((ch) => ({
		ch,
		state: _notifyState(task, ch, live)
	})), t);
}
function renderReceipts(receipts, t) {
	if (receipts.length === 0) return null;
	const said = receipts.map(({ ch, state }) => t("queue.notify." + state, { ch: t("queue.ch." + ch) })).join(" · ");
	return h("span", {
		className: cx("tq-notify"),
		role: "img",
		"aria-label": said,
		title: said + " — " + t("queue.receiptLegend")
	}, receipts.map(({ ch, state }) => {
		return h("span", {
			key: ch,
			className: cx("tq-receipt"),
			"data-tq-notify": ch,
			"data-state": state
		}, h("svg", {
			className: cx("tq-notify-glyph"),
			width: 12,
			height: 12,
			viewBox: "0 0 12 12",
			"aria-hidden": "true"
		}, ch === "telegram" ? h("path", {
			d: "M1.5 5.6L10.5 2L8.9 10L6.1 7.9L4.8 9.3L4.7 7L8.4 3.9L3.9 6.5Z",
			fill: "currentColor"
		}) : ch === "weixin" ? h("path", {
			d: "M4.6 2C2.6 2 1 3.3 1 5c0 .9.5 1.7 1.2 2.3L1.9 8.6l1.5-.8c.4.1.8.2 1.2.2h.2A2.8 2.8 0 0 1 7.6 5.3c.5 0 .9.1 1.3.2C8.6 3.5 6.8 2 4.6 2ZM7.6 6.1c-1.5 0-2.7 1-2.7 2.2s1.2 2.2 2.7 2.2c.3 0 .6 0 .9-.1l1.2.6-.3-1c.6-.4 1-1 1-1.7 0-1.2-1.2-2.2-2.8-2.2Z",
			fill: "currentColor"
		}) : h("circle", {
			cx: 6,
			cy: 6,
			r: 3,
			fill: "currentColor"
		})), h("svg", {
			className: cx("tq-receipt-glyph"),
			width: 10,
			height: 10,
			viewBox: "0 0 10 10",
			"aria-hidden": "true"
		}, h("path", {
			d: RECEIPT_GLYPH[state],
			stroke: "currentColor",
			strokeWidth: 1.4,
			fill: "none",
			strokeLinecap: "round",
			strokeLinejoin: "round"
		})));
	}));
}
function renderRoleGlyph(role) {
	return h("svg", {
		className: cx("tq-role-glyph"),
		width: 10,
		height: 10,
		viewBox: "0 0 10 10",
		"aria-hidden": "true"
	}, STATE_ROLES[role].glyph.map((part, i) => part.paint === "fill" ? h("path", {
		key: i,
		d: part.d,
		fill: "currentColor"
	}) : h("path", {
		key: i,
		d: part.d,
		stroke: "currentColor",
		strokeWidth: 1.3,
		fill: "none",
		strokeLinecap: "round",
		strokeLinejoin: "round"
	})));
}
/** THE chip: a row's one state, in its role (bed + glyph + word). */
function renderChip(chip, opts = {}) {
	return h("span", {
		className: cx("tq-chip"),
		key: opts.key ?? opts.slot ?? chip.text,
		"data-role": chip.role,
		"data-bed": STATE_ROLES[chip.role].bed,
		"data-tq-chip": opts.slot,
		title: chip.title ?? chip.text
	}, renderRoleGlyph(chip.role), h("span", { className: cx("tq-chip-text") }, chip.text));
}
/** A row's cells in grid order, and the sentence it reads as. */
function rowCells(view, t) {
	const kind = ROW_KINDS[view.kind];
	const slots = FACT_ORDER.filter((slot) => kind.facts.includes(slot) && view.facts[slot] != null);
	const value = kind.value && view.value != null ? view.value : null;
	const caption = (view.caption ?? []).filter((part) => part.text !== "");
	return {
		cells: [
			h("span", {
				className: cx("tq-lead"),
				key: "lead",
				"aria-hidden": "true"
			}, kind.lead && view.lead != null ? renderLead(view.lead) : null),
			h("span", {
				className: cx("tq-name"),
				key: "name"
			}, view.name),
			value === null ? null : h("span", {
				className: cx("tq-value"),
				key: "value",
				"data-balance-state": value.tone,
				"data-used-level": value.level ?? void 0
			}, value.text),
			view.state === null ? null : renderChip(view.state, { slot: "status" }),
			...slots.map((slot) => {
				const fact = view.facts[slot];
				return h("span", {
					className: cx("tq-fact"),
					key: slot,
					"data-tq-fact": slot,
					"data-voice": fact.voice,
					title: fact.title ?? fact.said
				}, fact.receipts != null ? renderReceipts(fact.receipts, t) : fact.text, fact.mark == null ? null : h("span", {
					className: cx("tq-mark"),
					"data-role": fact.mark.role,
					title: fact.mark.title
				}, renderRoleGlyph(fact.mark.role), fact.mark.text));
			}),
			caption.length === 0 ? null : h("span", {
				className: cx("tq-caption-line"),
				key: "caption"
			}, ...caption.map((part, i) => h("span", {
				key: i,
				"data-voice": part.voice,
				title: part.title
			}, (i > 0 ? " · " : "") + part.text)))
		].filter((cell) => cell !== null),
		said: [
			view.name,
			value?.text,
			view.state?.title ?? view.state?.text,
			...slots.map((slot) => view.facts[slot].said ?? view.facts[slot].text),
			...caption.map((part) => part.text)
		].filter((part) => part != null && part !== "").join(" · ")
	};
}
/**
* One row of the panel on the grid above: a button when it opens the detail
* layer, else a read-only group (a head is neither: its section is labelled).
* `after` is a sibling beside the row (the move-up button, laid over the
* empty lead track so the row keeps its full width) — never a button inside
* a button.
*/
function renderRow(view, t, after = null) {
	const { cells, said } = rowCells(view, t);
	const head = view.kind === "source" || view.kind === "head";
	const common = {
		className: cx("tq-row", view.open === void 0 && "tq-static"),
		"data-tq-row": view.kind,
		...view.attrs ?? {}
	};
	return h("div", {
		className: cx("tq-item"),
		key: view.key,
		"data-tq-item": view.key
	}, view.open === void 0 ? h("div", head ? common : {
		...common,
		role: "group",
		"aria-label": said
	}, ...cells) : h("button", {
		...common,
		type: "button",
		"aria-label": said + " · " + t("queue.d.open"),
		title: said,
		onClick: view.open
	}, ...cells), after);
}
/**
* The one fold control both sections use: a native <details> whose summary is
* a pill (hairline, chevron that turns, press and focus feedback, a 44px
* target under a finger). Opening is immediate — no height animation.
*/
function renderFold(kind, label, children) {
	return h("details", {
		className: cx("tq-fold"),
		key: "fold-" + kind,
		"data-tq-fold": kind
	}, h("summary", { className: cx("tq-fold-summary") }, h("svg", {
		className: cx("tq-fold-chev"),
		width: 12,
		height: 12,
		viewBox: "0 0 12 12",
		"aria-hidden": "true"
	}, h("path", {
		d: "M4.5 2.5L8 6L4.5 9.5",
		stroke: "currentColor",
		strokeWidth: 1.4,
		fill: "none",
		strokeLinecap: "round",
		strokeLinejoin: "round"
	})), h("span", null, label)), h("div", { className: cx("tq-fold-body") }, ...children));
}
/**
* Brand marks the host itself ships, drawn in the glyph ink: DeepSeek's whale
* is dsh's own logo (the same path its sidebar header draws), so the plugin
* carries no artwork the host does not already show.
*/
const DEEPSEEK_WHALE = "M22.9168 1.43018C22.6713 1.31018 22.5658 1.53918 22.4223 1.65519C22.3733 1.69269 22.3318 1.74169 22.2903 1.78669C21.9317 2.1697 21.5127 2.42121 20.9657 2.39121C20.1657 2.34621 19.4827 2.59771 18.8787 3.20973C18.7502 2.45521 18.3236 2.0047 17.6746 1.71569C17.3351 1.56568 16.9916 1.41518 16.7536 1.08867C16.5876 0.856163 16.5421 0.597155 16.4591 0.341647C16.4061 0.187643 16.3536 0.0301382 16.1761 0.00363739C15.9836 -0.0263635 15.9081 0.135141 15.8326 0.270145C15.5306 0.822162 15.4136 1.43018 15.4251 2.0462C15.4516 3.43174 16.0366 4.53527 17.1991 5.3203C17.3311 5.4103 17.3651 5.5003 17.3236 5.63181C17.2441 5.90231 17.1501 6.16482 17.0671 6.43533C17.0141 6.60784 16.9351 6.64584 16.7501 6.57033C16.1121 6.30383 15.5611 5.90931 15.074 5.4328C14.2475 4.63328 13.5 3.75075 12.568 3.05973C12.349 2.89822 12.13 2.74822 11.9034 2.60522C10.9524 1.68169 12.028 0.923165 12.277 0.833162C12.5375 0.739159 12.3675 0.41615 11.5259 0.42015C10.6844 0.42365 9.91439 0.705658 8.93286 1.08117C8.78935 1.13767 8.63835 1.17867 8.48384 1.21267C7.59332 1.04367 6.66829 1.00617 5.70226 1.11517C3.88321 1.31768 2.43016 2.1777 1.36213 3.64575C0.0790928 5.4103 -0.222916 7.41536 0.146595 9.50642C0.535106 11.7105 1.66014 13.535 3.38869 14.9616C5.18125 16.4406 7.24581 17.1657 9.60138 17.0266C11.0319 16.9441 12.6245 16.7526 14.421 15.2321C14.874 15.4576 15.3496 15.5476 16.1381 15.6151C16.7456 15.6716 17.3306 15.5851 17.7836 15.4911C18.4931 15.3411 18.4441 14.6841 18.1876 14.5636C16.1081 13.595 16.5646 13.9891 16.1496 13.67C17.2061 12.42 18.8202 10.1979 19.3182 7.17235C19.3672 6.83834 19.4297 6.36783 19.4222 6.09732C19.4182 5.93231 19.4562 5.86831 19.6447 5.84931C20.1657 5.78931 20.6712 5.64681 21.1357 5.3913C22.4833 4.65528 23.0268 3.44624 23.1548 1.9972C23.1738 1.77569 23.1508 1.54668 22.9168 1.43018ZM11.1749 14.4736C9.15936 12.889 8.18184 12.3675 7.77832 12.39C7.40081 12.4125 7.46881 12.8445 7.55182 13.126C7.63882 13.404 7.75182 13.5955 7.91033 13.8396C8.01983 14.0011 8.09533 14.2411 7.80083 14.4216C7.15181 14.8231 6.02327 14.2866 5.97027 14.2601C4.65673 13.4865 3.5587 12.4655 2.78467 11.069C2.03715 9.72493 1.60314 8.28289 1.53164 6.74384C1.51264 6.37233 1.62214 6.24082 1.99215 6.17332C2.47916 6.08332 2.98118 6.06432 3.46769 6.13582C5.52476 6.43633 7.27581 7.35586 8.74385 8.8129C9.58188 9.64243 10.2159 10.634 10.8689 11.6025C11.5634 12.631 12.3105 13.611 13.262 14.4146C13.598 14.6961 13.866 14.9101 14.1225 15.0681C13.349 15.1546 12.058 15.1731 11.1749 14.4746L11.1749 14.4736ZM12.141 8.25988C12.141 8.09488 12.273 7.96338 12.439 7.96338C12.4765 7.96338 12.5105 7.97088 12.541 7.98188C12.5825 7.99688 12.6205 8.01938 12.6505 8.05338C12.7035 8.10588 12.7335 8.18088 12.7335 8.25988C12.7335 8.42489 12.6015 8.55639 12.4355 8.55639C12.2695 8.55639 12.141 8.42489 12.141 8.25988ZM15.1415 9.79893C14.949 9.87793 14.7565 9.94544 14.5715 9.95294C14.2845 9.96794 13.9715 9.85143 13.8015 9.70893C13.5375 9.48742 13.3485 9.36342 13.2695 8.97691C13.2355 8.8119 13.2545 8.55639 13.2845 8.40989C13.3525 8.09438 13.277 7.89187 13.0545 7.70787C12.8735 7.55786 12.643 7.51636 12.39 7.51636C12.2955 7.51636 12.209 7.47486 12.1445 7.44136C12.039 7.38886 11.9519 7.25735 12.035 7.09585C12.0615 7.04335 12.19 6.91584 12.22 6.89334C12.5635 6.69784 12.9595 6.76184 13.326 6.90834C13.6655 7.04735 13.9225 7.30236 14.292 7.66287C14.6695 8.09838 14.7375 8.21838 14.9525 8.54539C15.1225 8.8009 15.277 9.06341 15.3831 9.36392C15.4471 9.55142 15.3641 9.70493 15.1415 9.79893Z";
/**
* The provider identity layer for a row with no agent glyph: 14px, the
* executor glyphs' ink. DeepSeek is its whale; the rest keep a letterform-free
* outline — MiniMax a wave, anything else a plain ring.
*/
function renderSourceGlyph(source) {
	if (source.agent !== null || source.join?.agent) return renderAgentGlyph(source.agent ?? source.join.agent);
	if (source.key === "deepseek") return h("svg", {
		className: cx("tq-agent-glyph"),
		width: 14,
		height: 14,
		viewBox: "0 -3.06 23.16 23.16",
		"aria-hidden": "true",
		"data-pp-provider": source.key
	}, h("path", {
		d: DEEPSEEK_WHALE,
		fill: "currentColor"
	}));
	const stroke = {
		stroke: "currentColor",
		strokeWidth: 1.25,
		strokeLinecap: "round",
		strokeLinejoin: "round",
		fill: "none"
	};
	const shape = source.join?.kind === "windows" ? h("path", {
		...stroke,
		d: "M1.8 9.5L4 4.5L7 9.5L10 4.5L12.2 9.5"
	}) : h("circle", {
		...stroke,
		cx: 7,
		cy: 7,
		r: 5
	});
	return h("svg", {
		className: cx("tq-agent-glyph"),
		width: 14,
		height: 14,
		viewBox: "0 0 14 14",
		"aria-hidden": "true",
		"data-pp-provider": source.key
	}, shape);
}
/** A row's lead track (panel.ts RowLead) as its glyph. */
function renderLead(lead) {
	if ("agent" in lead) return renderAgentGlyph(lead.agent, lead.size);
	if ("section" in lead) return renderSectionGlyph(lead.section);
	return renderSourceGlyph(lead.source);
}
/** Section glyphs in the executor glyphs' 14px outline: a clock turning back (just ended), a shield (patrol). */
function renderSectionGlyph(kind, size = 14) {
	const stroke = {
		stroke: "currentColor",
		strokeWidth: 1.25,
		strokeLinecap: "round",
		strokeLinejoin: "round",
		fill: "none"
	};
	return h("svg", {
		className: cx("tq-agent-glyph"),
		width: size,
		height: size,
		viewBox: "0 0 14 14",
		"aria-hidden": "true"
	}, kind === "recent" ? h("path", {
		...stroke,
		d: "M2.6 7.6A4.5 4.5 0 1 0 3.9 3.8M3.6 1.6V4.1H6.1M7 4.6V7.2L8.7 8.3"
	}) : h("path", {
		...stroke,
		d: "M7 1.8L11.4 3.4V6.9C11.4 9.5 9.6 11.4 7 12.2C4.4 11.4 2.6 9.5 2.6 6.9V3.4ZM5 7L6.4 8.4L9.1 5.7"
	}));
}
/** A list of rows on the inset well: the one surface every task, ended task and round sits on. */
function renderWell(key, rows) {
	const present = rows.filter((row) => row !== null);
	return present.length === 0 ? null : h("div", {
		className: cx("tq-well"),
		key: "well-" + key,
		"data-tq-well": key
	}, ...present);
}
/**
* Patrol: a section head (the phase as its state chip, the live status as its
* caption), the newest round on the well, then — folded, by the one rule
* above — the earlier rounds and the raw journal line.
*/
function renderPatrolSection(patrol, t) {
	const rounds = patrol.rounds;
	return h("section", {
		className: cx("tq-group", "tq-section"),
		key: "patrol",
		"data-tq-group": "patrol"
	}, renderRow(patrol.head, t), renderWell("rounds", rounds.slice(0, 1).map((round) => renderRow(round, t))), rounds.length <= 1 ? null : renderFold("rounds", t("queue.olderRounds", { n: rounds.length - 1 }), [renderWell("older", rounds.slice(1).map((round) => renderRow(round, t)))]), patrol.detail === "" ? null : renderFold("journal", t("queue.supervisorLog"), [h("div", {
		className: cx("tq-log"),
		key: "log"
	}, patrol.detail)]));
}
/**
* One provider group of the open panel (2026-09-28, kcn: 「任务现在和 provider
* 那个上下好像都不明显了」). Two levels, never mixed: the allowance is the
* group's head on the panel itself (14px strong name and reading, the caption,
* the window bars on the name's edge); the queue that allowance feeds is a
* list on an inset well starting on that same edge, one step down in type
* and in weight. A reader tells the two apart by surface and indent before
* reading a word.
*/
function renderSourceGroup(group, t, ui) {
	const { source, row, balanceNote } = group;
	const detail = renderAllowance(group.detail);
	return h("section", {
		className: cx("tq-group", "pp-group"),
		key: "g-" + source.key,
		"data-pp-group": source.key,
		"data-tq-group": source.agent ?? void 0,
		"aria-label": source.label,
		tabIndex: -1
	}, renderRow(group.head, t), balanceNote === null && detail === null ? null : h("div", {
		className: cx("pp-allowance", "tq-inset"),
		"data-pb-provider": row.provider,
		"data-pb-role": "panel",
		"data-balance-state": row.view.tone
	}, balanceNote === null ? null : h("div", { className: cx("tq-sub", "tq-wrap", "bp-note", row.view.tone === "stale" ? "warn" : "bad") }, balanceNote), detail), ...group.notes.map((note, i) => h("div", {
		className: cx("tq-sub", "tq-wrap", "tq-note", "tq-inset"),
		key: "n" + i
	}, note)), renderWell(source.key, group.tasks.map(({ task, row: view }) => renderRow(view, t, ui.writable && reorderable(task) && (task.position ?? 0) > 1 ? h("button", {
		type: "button",
		className: cx("tq-icon-btn", "tq-up"),
		"data-tq-up": task.id,
		disabled: ui.busy !== null,
		"aria-label": t("queue.a.upOf", { name: task.name }),
		title: t("queue.a.up"),
		onClick: () => {
			ui.act("priority", task, "up");
		}
	}, h("svg", {
		width: 14,
		height: 14,
		viewBox: "0 0 14 14",
		"aria-hidden": "true"
	}, h("path", {
		d: "M7 11.5V2.5M3 6.5L7 2.5L11 6.5",
		stroke: "currentColor",
		strokeWidth: 1.4,
		fill: "none",
		strokeLinecap: "round",
		strokeLinejoin: "round"
	}))) : null))));
}
/**
* The open panel: title + one refresh for both halves, then a group per
* source in _panelSources order, then what just ended, patrol, and the ops
* entry's version. Each half keeps its own read: a failed balance read never
* hides the queue, and a host without the dispatcher shows providers only.
*/
function renderProviderPanelBody(model, queueState, balanceState, t, ui, notice) {
	const loading = queueState.data.loading || balanceState.data.loading;
	return [h("div", {
		className: cx("tq-head"),
		key: "head"
	}, h("span", { className: cx("tq-title") }, model.title), h("button", {
		type: "button",
		className: cx("tq-icon-btn", loading && "spin"),
		"data-refresh": "true",
		"aria-label": t("panel.refresh"),
		"aria-busy": loading ? "true" : void 0,
		title: t("panel.refresh"),
		onClick: () => {
			queueState.refresh();
			balanceState.refresh();
		}
	}, h("svg", {
		width: 14,
		height: 14,
		viewBox: "0 0 14 14",
		"aria-hidden": "true"
	}, h("path", {
		d: "M11.5 7A4.5 4.5 0 1 1 10 3.6M11.5 1.8V4.4H8.9",
		stroke: "currentColor",
		strokeWidth: 1.3,
		fill: "none",
		strokeLinecap: "round",
		strokeLinejoin: "round"
	})))), h("div", {
		className: cx("tq-scroll"),
		key: "scroll"
	}, [
		notice === null ? null : h("div", {
			className: cx("tq-sub", "tq-wrap", "tq-note", notice.ok ? "tq-ok" : "tq-bad"),
			key: "notice",
			role: "status"
		}, notice.text),
		...model.notices.map((note) => h("div", {
			className: note.bad ? cx("tq-sub", "tq-wrap", "tq-note", "tq-bad") : cx("tq-sub", "tq-note"),
			key: note.key,
			role: "status"
		}, note.text)),
		model.empty === null ? null : h("div", {
			className: cx("tq-sub", "tq-empty"),
			key: "empty",
			role: "status"
		}, model.empty),
		...model.groups.map((group) => renderSourceGroup(group, t, ui)),
		model.recent === null ? null : h("section", {
			className: cx("tq-group", "tq-section"),
			key: "recent",
			"data-tq-group": "recent"
		}, renderRow(model.recent.head, t), renderWell("recent", model.recent.rows.map((row) => renderRow(row, t)))),
		model.patrol === null ? null : renderPatrolSection(model.patrol, t),
		model.footer === null ? null : h("div", {
			className: cx("tq-sub", "tq-foot", model.footer.bad && "tq-bad"),
			key: "ops",
			"data-tq-ops": model.footer.version
		}, model.footer.text)
	])];
}
/** A task's current copy by id: live first, then recently ended (it may have just finished). */
function findTask(result, id) {
	const live = result.active.find((task) => task.id === id);
	if (live !== void 0) return {
		task: live,
		live: true
	};
	const ended = result.recent.find((task) => task.id === id);
	return ended === void 0 ? null : {
		task: ended,
		live: false
	};
}
/** `4200` → `4.2k`, `83123861` → `83.1M`: token counts read at a glance, exact value in the aria text. */
function _fmtTokens(n) {
	if (n < 1e3) return String(n);
	if (n < 1e6) return (n / 1e3).toFixed(n < 1e4 ? 1 : 0) + "k";
	return (n / 1e6).toFixed(n < 1e7 ? 2 : 1) + "M";
}
/**
* The file-preview address of a path read through one session — dsh-util-workspace-path's
* `sessionFileAddress` grammar (an absolute path keeps its leading `/`, hence `…/<id>//root/…`).
* The preview claims only this scope: `file/absolute/…` answered "no registered tab type claims"
* on the live host (2026-09-27), so the brief opens in the conversation's own sidebar.
*/
function _sessionFileAddress(sessionId, path) {
	const seg = (part) => encodeURIComponent(part).replace(/%3A/gi, ":");
	return "dsh-resource://file/session/" + seg(sessionId) + "/" + path.split("/").map(seg).join("/");
}
const DETAIL_SECTIONS = {
	live: [
		"status",
		"view",
		"run",
		"allowance",
		"time",
		"usage",
		"notify",
		"end",
		"raw"
	],
	ended: [
		"status",
		"summary",
		"view",
		"run",
		"allowance",
		"time",
		"usage",
		"notify",
		"end",
		"raw"
	]
};
const DETAIL_FIELDS = {
	run: [
		"model",
		"place",
		"deadline",
		"retries",
		"resumes"
	],
	allowance: [
		"agent",
		"source",
		"windows",
		"pool",
		"quota"
	],
	time: [
		"queued",
		"waited",
		"started",
		"took",
		"wakes",
		"ended"
	],
	usage: [
		"attempts",
		"stalls",
		"cost",
		"tokens"
	],
	notify: ["notify"],
	raw: [
		"latest",
		"runner",
		"session",
		"id"
	]
};
const DETAIL_FOLDED = ["raw"];
const DETAIL_ACTIONS = {
	brief: {
		kind: "view",
		home: "view"
	},
	log: {
		kind: "view",
		home: "view"
	},
	model: {
		kind: "write",
		home: "run.model"
	},
	top: {
		kind: "write",
		home: "run.place"
	},
	up: {
		kind: "write",
		home: "run.place"
	},
	down: {
		kind: "write",
		home: "run.place"
	},
	deadline: {
		kind: "write",
		home: "run.deadline"
	},
	attempts: {
		kind: "write",
		home: "run.retries"
	},
	resumes: {
		kind: "write",
		home: "run.resumes"
	},
	wrapup: {
		kind: "write",
		home: "end"
	},
	cancel: {
		kind: "danger",
		home: "end"
	},
	retry: {
		kind: "write",
		home: "end"
	}
};
/** A control in the detail layer: its kind (DETAIL_ACTIONS) is its look; a confirmation arms it. */
function actionPill(key, label, onClick, opts = {}) {
	const kind = opts.kind ?? DETAIL_ACTIONS[key]?.kind ?? "write";
	return h("button", {
		type: "button",
		key,
		className: cx("tq-pill", kind === "danger" && "tq-danger"),
		"data-tq-action": key,
		"data-tq-kind": kind,
		"data-armed": opts.armed ? "true" : void 0,
		disabled: opts.disabled === true,
		title: opts.title,
		"aria-label": opts.said,
		onClick
	}, key === "brief" || key === "log" ? renderViewGlyph(key) : null, h("span", null, label));
}
/** The read-only pills' glyphs, in the executor glyphs' outline: a page (the brief), lines (the log). */
function renderViewGlyph(key) {
	const stroke = {
		stroke: "currentColor",
		strokeWidth: 1.2,
		strokeLinecap: "round",
		strokeLinejoin: "round",
		fill: "none"
	};
	return h("svg", {
		className: cx("tq-pill-glyph"),
		width: 12,
		height: 12,
		viewBox: "0 0 12 12",
		"aria-hidden": "true"
	}, key === "brief" ? h("path", {
		...stroke,
		d: "M3 1.5H7.2L9.5 3.8V10.5H3ZM7 1.6V4H9.4M4.6 6.2H7.9M4.6 8.2H7.9"
	}) : h("path", {
		...stroke,
		d: "M2 3H10M2 6H10M2 9H7"
	}));
}
/** One field on the row grid: dt on the name's edge, dd over took…rest, its control in aside. */
function renderField(field) {
	const control = field.control == null || field.control.length === 0 ? null : field.control;
	return h("div", {
		className: cx("tq-d-field", control !== null && !field.wide && "tq-d-has-control"),
		key: field.key,
		"data-tq-field": field.key
	}, h("dt", { className: cx("tq-d-k") }, field.label), h("dd", {
		className: cx("tq-d-v", field.mono === true && "tq-mono"),
		"data-voice": field.voice
	}, field.value), field.sub == null || field.sub === "" ? null : h("dd", { className: cx("tq-d-sub") }, field.sub), control === null ? null : h("dd", { className: cx("tq-d-control", field.wide && "tq-d-control-wide") }, ...control), field.after == null ? null : h("dd", { className: cx("tq-d-after") }, field.after));
}
/** A section: its caption (a heading for a screen reader's rotor) and its fields as one description list. */
function renderSection(id, title, body) {
	const present = body.filter((node) => node !== null && node !== void 0 && node !== false);
	if (present.length === 0) return null;
	return h("div", {
		className: cx("tq-d-sec"),
		key: id,
		"data-tq-section": id
	}, title === null ? null : h("div", {
		className: cx("tq-d-sec-title"),
		role: "heading",
		"aria-level": 3
	}, title), ...present);
}
function renderFields(fields) {
	const present = fields.filter((field) => field !== null && field.value != null && field.value !== "");
	return present.length === 0 ? null : h("dl", {
		className: cx("tq-d-fields"),
		key: "dl"
	}, ...present.map(renderField));
}
/**
* The detail layer one task row opens, laid over the list inside the same
* popover: the back bar stays put; everything else scrolls, in DETAIL_SECTIONS
* order. Dangerous writes confirm in place and say what they cost: cancelling
* a queued task is free; a running one loses the step in flight (its session
* can be resumed); a model change applies to the next attempt. The answer to
* a write lands in the layer's resident foot, in view wherever the reader
* scrolled to.
*/
function renderTaskDetail(found, t, now, back, backRef, ui, notice) {
	const { task, live } = found;
	const stamp = (ms) => ms == null ? null : resetStampOf(t, {
		resetAt: "",
		resetAtMs: ms
	}, now);
	const status = live ? _taskStatus(task, t, now, ui.windowsOf(task.agent)) : {
		tone: endedTone(task),
		text: executionText(task.state, t) + " · " + reportText(task.outcome, t, task.state)
	};
	const chip = live ? _taskState(task, t, now, ui.windowsOf(task.agent)).chip : _endedState(task.state, task.outcome, t);
	const cost = _costOf(task);
	const m = modelLine(task, live);
	const requested = task.modelRequested ?? "";
	const slot = _slotOf(task);
	const busy = ui.busy !== null;
	const reading = ui.readPending !== null;
	const running = live && (slot !== null || task.attempts > 0 && task.waiting !== "lock");
	const writable = ui.writable && live && !task.cancelling;
	const budgets = writable && !task.patrol;
	const old = (task.runnerApi ?? 1) < 3;
	const confirming = (action) => ui.confirm === action + ":" + task.id;
	const when = running ? t("queue.a.whenNext") : t("queue.a.whenNow");
	const confirmNote = (action, text) => !confirming(action) ? null : h("div", {
		className: cx("tq-note", "tq-warn", "tq-confirm"),
		role: "alert",
		"data-tq-confirm": task.id
	}, h("span", null, text), actionPill("dismiss-confirm", t("queue.a.dismissConfirm"), () => {
		ui.askConfirm(null);
	}, { kind: "view" }));
	const budget = (action, label, short, arg) => !budgets ? null : [actionPill(action, confirming(action) ? t("queue.a.confirm") : short, () => {
		if (confirming(action)) {
			ui.askConfirm(null);
			ui.act(action, task, arg);
		} else ui.askConfirm(action + ":" + task.id);
	}, {
		disabled: busy || old,
		armed: confirming(action),
		said: confirming(action) ? t("queue.a.confirmLabel", { label }) : label
	})];
	const picker = ui.picker;
	const pickerView = picker === null ? null : h("div", {
		className: cx("tq-picker"),
		"data-tq-picker": task.id
	}, picker.allowed ? [
		h("label", {
			className: cx("tq-field"),
			key: "m"
		}, h("span", null, t("queue.d.model")), h("select", {
			value: picker.model,
			onChange: (event) => {
				const model = event.target.value;
				const efforts = picker.efforts[model] ?? [];
				ui.setPicker({
					...picker,
					model,
					effort: efforts.includes(picker.effort) ? picker.effort : ""
				});
			}
		}, picker.models.map((model) => h("option", {
			key: model,
			value: model
		}, _modelView(model).label + " (" + model + ")")))),
		h("label", {
			className: cx("tq-field"),
			key: "e"
		}, h("span", null, picker.flag), h("select", {
			value: picker.effort,
			disabled: (picker.efforts[picker.model] ?? []).length === 0,
			onChange: (event) => {
				ui.setPicker({
					...picker,
					effort: event.target.value
				});
			}
		}, [h("option", {
			key: "",
			value: ""
		}, t("queue.d.effortDefault")), ...(picker.efforts[picker.model] ?? []).map((effort) => h("option", {
			key: effort,
			value: effort
		}, effort))])),
		h("div", {
			className: cx("tq-picker-actions"),
			key: "save"
		}, actionPill("save", t("queue.a.save"), () => {
			ui.setPicker(null);
			ui.act("model", task, picker.model + "|" + (picker.effort === "" ? "default" : picker.effort));
		}, { disabled: busy }), actionPill("close", t("queue.a.close"), () => {
			ui.setPicker(null);
		}, { kind: "view" })),
		h("div", {
			className: cx("tq-caption"),
			key: "hint"
		}, t("queue.a.modelHint"))
	] : h("div", { className: cx("tq-note") }, picker.reason));
	const place = live && task.waiting === "lock" && task.position ? t("queue.d.placeValue", {
		n: task.position,
		agent: task.agent
	}) : null;
	const placeSub = [task.protected ? t("queue.d.protected") : null, task.priority ? t("queue.d.priorityValue", { n: task.priority }) : null].filter((part) => part !== null).join(" · ");
	const reorder = writable && reorderable(task);
	const run = renderFields([
		m.model === "" ? null : {
			key: "model",
			label: t("queue.d.model"),
			value: h("span", null, _modelView(m.model).label + (m.effort ? " · " + m.effort : ""), m.fallback ? h("span", {
				className: cx("tq-mark"),
				"data-role": "fallback"
			}, renderRoleGlyph("fallback"), t("queue.d.fallbackFrom", { model: _modelView(requested).label })) : null),
			control: writable && (task.runnerApi ?? 2) >= 2 && !task.patrol ? [actionPill("model", ui.readPending === "choices" ? t("queue.a.reading") : t("queue.a.model"), () => {
				ui.openPicker(task);
			}, { disabled: busy || reading })] : null,
			after: pickerView
		},
		place === null ? null : {
			key: "place",
			label: t("queue.d.place"),
			value: place,
			sub: placeSub,
			wide: true,
			control: !reorder ? null : [
				actionPill("top", t("queue.a.top"), () => {
					ui.act("priority", task, "top");
				}, { disabled: busy || task.position === 1 }),
				actionPill("up", t("queue.a.up"), () => {
					ui.act("priority", task, "up");
				}, { disabled: busy || task.position === 1 }),
				actionPill("down", t("queue.a.down"), () => {
					ui.act("priority", task, "down");
				}, { disabled: busy })
			]
		},
		live && (task.deadlineAtMs || budgets) ? {
			key: "deadline",
			label: t("queue.d.deadline"),
			value: stamp(task.deadlineAtMs) ?? t("queue.d.notRecorded"),
			control: budget("deadline", t("queue.a.deadline"), "+2h", "+2h"),
			after: confirmNote("deadline", t("queue.a.deadlineConfirm", { when }))
		} : null,
		task.maxAttempts != null || budgets ? {
			key: "retries",
			label: t("queue.d.retries"),
			value: task.maxAttempts == null ? t("queue.d.notRecorded") : t("queue.d.usedOf", {
				used: task.attempts,
				max: task.maxAttempts
			}),
			control: budget("attempts", t("queue.a.attempts"), "+1", String((task.maxAttempts ?? 3) + 1)),
			after: confirmNote("attempts", t("queue.a.attemptsConfirm", { when }))
		} : null,
		task.quotaResumes != null || budgets ? {
			key: "resumes",
			label: t("queue.d.quotaResumes"),
			value: task.quotaResumes == null ? t("queue.d.notRecorded") : t("queue.d.usedOf", {
				used: task.quotaResumesUsed ?? 0,
				max: task.quotaResumes
			}),
			control: budget("resumes", t("queue.a.resumes"), "+1", String((task.quotaResumes ?? 3) + 1)),
			after: confirmNote("resumes", t("queue.a.resumesConfirm", { when }))
		} : null
	]);
	const budgetOld = budgets && old ? h("div", {
		className: cx("tq-note", "tq-d-note"),
		key: "old"
	}, t("queue.a.budgetOld", { api: task.runnerApi ?? 1 })) : null;
	const source = ui.sourceOf(task.agent);
	const windows = !live || source.row === void 0 ? null : renderRowDetail(source.row, t, now);
	const allowance = renderFields([
		{
			key: "agent",
			label: t("queue.d.agent"),
			value: h("span", { className: cx("tq-inline") }, renderAgentGlyph(task.agent, 12), _agentLabel(task.agent)),
			sub: slot === null ? null : source.lane?.max ? t("queue.d.slotOf", {
				slot: slot.slot,
				max: source.lane.max
			}) : t("queue.d.slotValue", { slot: slot.slot })
		},
		source.plan === null ? null : {
			key: "source",
			label: t("queue.d.source"),
			value: t(source.plan),
			sub: source.row?.note ?? null,
			voice: source.row?.note ? "warn" : void 0
		},
		windows === null ? null : {
			key: "windows",
			label: t("queue.d.windows"),
			value: h("div", { className: cx("pp-allowance", "tq-d-windows") }, windows)
		},
		!live || source.pool === void 0 ? null : {
			key: "pool",
			label: t("queue.d.pool"),
			value: source.pool === null ? t("panel.poolUnread") : t("panel.pool", {
				current: _modelView(source.pool.current).label,
				next: source.pool.next === "" ? "—" : _modelView(source.pool.next).label
			}) + (source.pool.fromOrder ? t("panel.poolOrder") : ""),
			sub: source.poolSize > 1 ? t("panel.poolSwap", { n: source.poolSize }) : null
		},
		live && source.quotaUntilMs ? {
			key: "quota",
			label: t("queue.d.quotaOut"),
			voice: "warn",
			value: t("queue.quotaHint", {
				time: stamp(source.quotaUntilMs) ?? "",
				by: source.quotaBy
			})
		} : null
	]);
	const took = live ? task.startedAtMs === null ? null : durationOf(t, now - task.startedAtMs) : task.startedAtMs !== null && task.updatedAtMs !== null ? durationOf(t, task.updatedAtMs - task.startedAtMs) : null;
	const time = renderFields([
		{
			key: "queued",
			label: t("queue.d.queued"),
			value: stamp(task.queuedAtMs)
		},
		live ? task.waitMs == null ? null : {
			key: "waited",
			label: t("queue.d.waited"),
			value: durationOf(t, task.waitMs)
		} : {
			key: "waited",
			label: t("queue.d.waited"),
			value: task.waitMs == null ? t("queue.waitUnknown") : durationOf(t, task.waitMs)
		},
		{
			key: "started",
			label: t("queue.d.started"),
			value: stamp(task.startedAtMs)
		},
		{
			key: "took",
			label: t(live ? "queue.d.elapsed" : "queue.d.took"),
			value: took
		},
		live ? {
			key: "wakes",
			label: t("queue.d.resumes"),
			value: stamp(task.wakeAtMs)
		} : null,
		live || task.updatedAtMs === null ? null : {
			key: "ended",
			label: t("queue.d.endedAt"),
			value: stamp(task.updatedAtMs) + " · " + agoOf(t, now - task.updatedAtMs)
		}
	]);
	const usage = renderFields([
		task.maxAttempts == null ? {
			key: "attempts",
			label: t("queue.d.attempts"),
			value: String(task.attempts)
		} : null,
		task.stalls ? {
			key: "stalls",
			label: t("queue.d.stalls"),
			value: t("queue.d.stallsValue", { n: task.stalls }),
			voice: "warn"
		} : null,
		cost === null ? null : {
			key: "cost",
			label: t("queue.d.cost"),
			value: cost.kind === "usd" ? "$" + (task.costUsd ?? "") : cost.kind === "free" ? t("queue.d.costFreeShort") : "—",
			sub: (cost.kind === "usd" ? t("queue.d.costEstimate") : cost.kind === "free" ? t("queue.d.costFree") : t("queue.d.costUnpriced")) + (live ? " · " + t("queue.d.costLive") : "")
		},
		task.tokensTotal == null ? null : {
			key: "tokens",
			label: t("queue.d.tokens"),
			value: t("queue.d.tokensTotal", { total: _fmtTokens(task.tokensTotal) }),
			sub: t("queue.d.tokensSplit", {
				in: _fmtTokens(task.tokensIn ?? 0),
				w: _fmtTokens(task.tokensCacheW ?? 0),
				r: _fmtTokens(task.tokensCacheR ?? 0),
				out: _fmtTokens(task.tokensOut ?? 0)
			})
		}
	]);
	const channels = notifyChannels(task);
	const notify = renderFields([{
		key: "notify",
		label: t("queue.d.notify"),
		value: channels.length === 0 ? t("queue.d.notifyNone") : h("span", { className: cx("tq-d-lines") }, channels.map((ch) => {
			const only = {
				...task,
				notify: [ch],
				notified: (task.notified ?? []).filter((c) => c === ch),
				notifyFailed: (task.notifyFailed ?? []).filter((c) => c === ch)
			};
			const said = t("queue.notify." + _notifyState(task, ch, live), { ch: t("queue.ch." + ch) });
			return h("span", {
				className: cx("tq-inline"),
				key: ch,
				"data-tq-channel": ch
			}, renderNotifyIcons(only, t, live), h("span", { "aria-hidden": "true" }, said));
		}))
	}]);
	const end = [];
	if (writable && running && task.session) end.push(actionPill("wrapup", t("queue.a.wrapup"), () => {
		ui.act("wrapup", task);
	}, {
		disabled: busy,
		title: t("queue.a.wrapupTitle")
	}));
	if (writable) end.push(actionPill("cancel", confirming("cancel") ? t("queue.a.cancelConfirm") : t("queue.a.cancel"), () => {
		if (confirming("cancel")) {
			ui.askConfirm(null);
			ui.act("cancel", task);
		} else ui.askConfirm("cancel:" + task.id);
	}, {
		disabled: busy,
		armed: confirming("cancel")
	}));
	if (ui.writable && !live && task.session && !(task.state === "ok" && (task.outcome === "DONE" || task.outcome === ""))) end.push(actionPill("retry", t("queue.a.retry"), () => {
		ui.act("retry", task);
	}, { disabled: busy }));
	const cancelText = running ? t("queue.a.cancelRunning", { session: task.session || "—" }) : task.waiting === "quota" || task.waiting === "retry" ? t("queue.a.cancelSleeping") : t("queue.a.cancelQueued");
	const view = [actionPill("brief", ui.readPending === "brief" ? t("queue.a.reading") : t("queue.a.brief"), () => {
		ui.openBrief(task);
	}, {
		disabled: reading,
		title: t("queue.a.briefTitle")
	})];
	if (ui.writable) view.push(actionPill("log", ui.readPending === "log" ? t("queue.a.reading") : t("queue.a.log"), () => {
		ui.loadLog(task);
	}, { disabled: reading }));
	const brief = ui.brief !== null && ui.brief.id === task.id ? ui.brief : null;
	const kb = (bytes) => (bytes / 1024).toFixed(bytes < 10240 ? 1 : 0);
	const raw = renderFields([
		live && task.lastEvent ? {
			key: "latest",
			label: t("queue.d.latest"),
			value: task.lastEvent + (task.lastEventAtMs == null ? "" : " · " + stamp(task.lastEventAtMs)),
			mono: true
		} : null,
		{
			key: "runner",
			label: t("queue.d.runner"),
			value: live && (task.runnerApi ?? 2) < 2 ? t("queue.noRunnerApi") : task.runnerApi == null ? null : "api " + task.runnerApi,
			voice: live && (task.runnerApi ?? 2) < 2 ? "warn" : void 0
		},
		{
			key: "session",
			label: t("queue.d.session"),
			value: task.session || null,
			mono: true
		},
		{
			key: "id",
			label: t("queue.d.id"),
			value: task.id,
			mono: true
		}
	]);
	const sections = {
		status: h("div", {
			className: cx("tq-d-sec", "tq-d-hero"),
			key: "status",
			"data-tq-section": "status"
		}, h("span", {
			className: cx("tq-lead"),
			"aria-hidden": "true"
		}, renderAgentGlyph(task.agent)), h("span", {
			className: cx("tq-d-name"),
			role: "heading",
			"aria-level": 2
		}, task.name), renderChip(chip, { slot: "status" }), status.text === chip.text ? null : h("div", {
			className: cx("tq-d-status"),
			"data-balance-state": status.tone,
			title: live ? void 0 : t("queue.statusLegend")
		}, status.text)),
		summary: live ? null : renderSection("summary", t("queue.d.summary"), [task.summary ? h("div", {
			className: cx("tq-d-summary"),
			key: "summary"
		}, task.summary) : h("div", {
			className: cx("tq-empty"),
			key: "summary"
		}, t("queue.d.noSummary"))]),
		view: renderSection("view", null, [
			h("div", {
				className: cx("tq-actions"),
				key: "pills",
				role: "group",
				"aria-label": t("queue.a.viewGroup")
			}, ...view),
			brief === null ? null : h("div", {
				className: cx("tq-brief"),
				key: "brief",
				"data-tq-brief": task.id,
				role: "group",
				"aria-label": t("queue.brief.heading")
			}, h("div", { className: cx("tq-caption") }, t("queue.brief.heading") + " · " + t("queue.brief.readOnly")), h("button", {
				type: "button",
				className: cx("tq-file"),
				"data-tq-file": brief.path,
				onClick: () => {
					ui.openPath(brief.path);
				}
			}, h("span", { className: cx("tq-file-name") }, brief.needsHost ? "prompt.md" : t("queue.brief.prompt", { kb: kb(brief.bytes) })), brief.truncated ? h("span", { className: cx("tq-tag") }, t("queue.brief.big", { kb: kb(brief.bytes) })) : null), brief.needsHost ? h("div", { className: cx("tq-note") }, t("queue.brief.needsHost")) : brief.appends.length === 0 ? h("div", { className: cx("tq-empty") }, t("queue.brief.none")) : brief.appends.map((a) => h("button", {
				type: "button",
				key: a.file,
				className: cx("tq-file"),
				"data-tq-file": a.path,
				onClick: () => {
					ui.openPath(a.path);
				}
			}, h("span", { className: cx("tq-file-name") }, t("queue.brief.append", { stamp: a.stamp || a.file })), h("span", {
				className: cx("tq-tag"),
				"data-tq-delivered": a.delivered ? "true" : "false"
			}, t(a.delivered ? "queue.brief.delivered" : "queue.brief.pending"))))),
			ui.log === null ? null : h("pre", {
				className: cx("tq-log"),
				key: "log",
				"data-tq-log": task.id,
				tabIndex: 0,
				role: "region",
				"aria-label": t("queue.a.log")
			}, ui.log.join("\n"))
		]),
		run: renderSection("run", t("queue.d.sec.run"), [run, budgetOld]),
		allowance: renderSection("allowance", t("queue.d.sec.allowance"), [allowance]),
		time: renderSection("time", t("queue.d.sec.time"), [time]),
		usage: renderSection("usage", t("queue.d.sec.usage"), [usage]),
		notify: renderSection("notify", null, [notify]),
		end: renderSection("end", t(live ? "queue.d.sec.end" : "queue.d.sec.again"), end.length === 0 ? [] : [h("div", {
			className: cx("tq-actions"),
			key: "pills",
			role: "group",
			"aria-label": t(live ? "queue.d.sec.end" : "queue.d.sec.again")
		}, ...end), confirming("cancel") ? h("div", {
			className: cx("tq-note", "tq-warn", "tq-confirm"),
			key: "confirm",
			role: "alert",
			"data-tq-confirm": task.id
		}, h("span", null, cancelText), actionPill("dismiss-confirm", t("queue.a.dismissConfirm"), () => {
			ui.askConfirm(null);
		}, { kind: "view" })) : null]),
		raw: raw === null ? null : h("div", {
			className: cx("tq-d-sec"),
			key: "raw",
			"data-tq-section": "raw"
		}, renderFold("raw", t("queue.d.sec.raw"), [raw]))
	};
	return h("div", {
		className: cx("tq-detail"),
		"data-tq-detail": task.id,
		role: "group",
		"aria-label": task.name
	}, h("div", { className: cx("tq-head", "tq-d-head") }, h("button", {
		type: "button",
		className: cx("tq-back"),
		"data-tq-back": "true",
		"aria-label": t("queue.back"),
		title: t("queue.back"),
		ref: backRef,
		onClick: back
	}, h("span", {
		className: cx("tq-back-chev"),
		"aria-hidden": "true"
	}), t("panel.title")), h("span", { className: cx("tq-caption") }, t(live ? "queue.d.live" : "queue.d.ended"))), h("div", {
		className: cx("tq-scroll", "tq-d-scroll"),
		role: "region",
		"aria-label": t("queue.d.region", { name: task.name })
	}, ...DETAIL_SECTIONS[live ? "live" : "ended"].map((id) => sections[id])), h("div", {
		className: cx("tq-d-notice", notice !== null && (notice.ok ? "tq-ok" : "tq-bad")),
		role: "status",
		"data-tq-notice": notice === null ? void 0 : "true"
	}, notice === null ? null : notice.text));
}
/** What one action's answer says, in the reader's words (the ops entry's own message otherwise). */
function _describeAction(result, t) {
	let detail = {};
	try {
		detail = JSON.parse(result.detail || "{}");
	} catch {
		detail = {};
	}
	if (!result.ok) return t("queue.r.failed", { message: result.message || String(result.code) });
	switch (result.action) {
		case "cancel":
			if (detail.was === "queued") return t("queue.r.cancelledQueued");
			return detail.session ? t("queue.r.cancelledRunning", { resume: String(detail.resume ?? "") }) : t("queue.r.cancelledNoSession");
		case "priority": {
			const queue = Array.isArray(detail.queue) ? detail.queue : [];
			return detail.changed === false ? String(detail.message ?? "") : t("queue.r.priority", {
				n: String(detail.position ?? "—"),
				total: queue.length
			});
		}
		case "model": return t("queue.r.model", {
			model: String(detail.model_next ?? ""),
			effort: String(detail.effort_next || "—")
		});
		case "retry": return t("queue.r.retry", { id: String(detail.new_id ?? "") });
		case "wrapup": return t("queue.r.wrapup");
		default: return result.message;
	}
}
/** How long an in-place confirmation waits for its second tap. */
const CONFIRM_MS = 5e3;
/**
* The sidebar-foot provider panel (2026-09-27): the balance chip and the
* dispatch queue as ONE cell, `provider-balance`. Folded, it is one line per
* source — provider or agent name first, its reading and reset, then who
* burns that allowance (the agent's queue) or where its key comes from. Any
* line opens the panel on that source's group: the allowance (windows with
* their resets, or money), then the queue that allowance feeds. The rail
* keeps one glyph whose badge warns when a window is at its threshold or a
* task sleeps on quota. Both halves keep their own read and cadence.
*/
function ProviderPanelSidebarAction(props) {
	const t = props.t;
	const balanceState = useProviderBalances(props, BALANCE_PANEL);
	const queueState = useTaskQueue(props);
	const [detailId, setDetailId] = useState(null);
	const [busy, setBusy] = useState(null);
	const [notice, setNotice] = useState(null);
	const [confirm, setConfirm] = useState(null);
	const [picker, setPicker] = useState(null);
	const [log, setLog] = useState(null);
	const [brief, setBrief] = useState(null);
	const [readPending, setReadPending] = useState(null);
	const [focusKey, setFocusKey] = useState(null);
	const detailRequest = useRef(0);
	const activeDetail = useRef(null);
	useEffect(() => () => {
		detailRequest.current += 1;
		activeDetail.current = null;
	}, []);
	const lastSeen = useRef(null);
	const backRef = useRef(null);
	const openerRef = useRef(null);
	const closeDetail = () => {
		if (confirm !== null) {
			setConfirm(null);
			return true;
		}
		if (detailId === null) return false;
		const id = detailId;
		detailRequest.current += 1;
		activeDetail.current = null;
		setDetailId(null);
		setPicker(null);
		setLog(null);
		setConfirm(null);
		setBrief(null);
		setReadPending(null);
		if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") window.requestAnimationFrame(() => {
			rootRef.current?.querySelector("[data-tq-task=\"" + CSS.escape(id) + "\"]")?.focus({ preventScroll: false });
		});
		return true;
	};
	const { open, setOpen, anchor, place, rootRef } = useFootPopover(closeDetail);
	const instanceId = useId();
	useEffect(() => {
		if (open) return;
		detailRequest.current += 1;
		activeDetail.current = null;
		setDetailId(null);
		setNotice(null);
		setConfirm(null);
		setBrief(null);
		setPicker(null);
		setLog(null);
		setReadPending(null);
		if (typeof document !== "undefined" && rootRef.current !== null && openerRef.current !== null && (document.activeElement === document.body || rootRef.current.contains(document.activeElement))) openerRef.current.focus({ preventScroll: true });
	}, [open]);
	useEffect(() => {
		if (!open || focusKey === null || typeof window === "undefined" || typeof window.requestAnimationFrame !== "function") return;
		window.requestAnimationFrame(() => {
			rootRef.current?.querySelector("[data-pp-group=\"" + CSS.escape(focusKey) + "\"]")?.focus({ preventScroll: false });
		});
	}, [open, focusKey]);
	useEffect(() => {
		if (detailId !== null) backRef.current?.focus({ preventScroll: true });
	}, [detailId]);
	useEffect(() => {
		if (confirm === null) return void 0;
		const timer = setTimeout(() => {
			setConfirm(null);
		}, CONFIRM_MS);
		return () => clearTimeout(timer);
	}, [confirm]);
	const run = props.runQueueAction;
	const needsHost = (result) => !result.ok && /unknown action/.test(result.message);
	const act = (action, task, arg = "") => {
		if (run === void 0 || busy !== null) return;
		setBusy(action + ":" + task.id);
		setNotice(null);
		run(action, task.id, arg).then((result) => {
			setBusy(null);
			setNotice({
				ok: result.ok,
				text: needsHost(result) ? t("queue.r.needsHost") : _describeAction(result, t)
			});
			queueState.refresh();
		}, (err) => {
			setBusy(null);
			setNotice({
				ok: false,
				text: t("queue.r.failed", { message: err instanceof Error ? err.message : String(err) })
			});
		});
	};
	const openPath = (path) => {
		const opened = props.openFile === void 0 ? {
			ok: false,
			reason: "no-service"
		} : props.openFile(path);
		const file = path.slice(path.lastIndexOf("/") + 1);
		setNotice(opened.ok ? {
			ok: true,
			text: t("queue.brief.opened", { file })
		} : {
			ok: false,
			text: opened.reason === "no-session" ? t("queue.brief.noSession", { path }) : opened.reason === "no-service" ? t("queue.brief.noService", { path }) : t("queue.brief.failed", {
				message: opened.message ?? "",
				path
			})
		});
	};
	const openBrief = (task) => {
		const logDir = queueState.data.result?.logDir;
		const fallback = logDir ? logDir.replace(/\/+$/, "") + "/" + task.id + "/prompt.md" : null;
		setConfirm(null);
		const noDir = () => {
			setNotice({
				ok: false,
				text: t("queue.brief.noDir")
			});
		};
		if (run === void 0) {
			if (fallback === null) {
				noDir();
				return;
			}
			setBrief({
				id: task.id,
				path: fallback,
				bytes: 0,
				truncated: false,
				appends: [],
				needsHost: true
			});
			openPath(fallback);
			return;
		}
		const request = detailRequest.current;
		setReadPending("brief");
		run("brief", task.id, "").then((result) => {
			if (request !== detailRequest.current || activeDetail.current !== task.id) return;
			setReadPending(null);
			let detail = {};
			try {
				detail = JSON.parse(result.detail || "{}");
			} catch {
				detail = {};
			}
			if (!result.ok && !needsHost(result)) {
				setNotice({
					ok: false,
					text: t("queue.a.readFailed", { message: result.message })
				});
				return;
			}
			const path = (result.ok ? detail.path : void 0) ?? fallback;
			if (path === null) {
				noDir();
				return;
			}
			const view = result.ok ? {
				id: task.id,
				path,
				bytes: detail.brief_bytes ?? 0,
				truncated: detail.truncated === true,
				appends: detail.appends ?? [],
				needsHost: false
			} : {
				id: task.id,
				path,
				bytes: 0,
				truncated: false,
				appends: [],
				needsHost: true
			};
			setBrief(view);
			openPath(view.path);
		}, (err) => {
			if (request !== detailRequest.current || activeDetail.current !== task.id) return;
			setReadPending(null);
			setNotice({
				ok: false,
				text: t("queue.a.readFailed", { message: err instanceof Error ? err.message : String(err) })
			});
		});
	};
	const openPicker = (task) => {
		if (run === void 0) return;
		setConfirm(null);
		const request = detailRequest.current;
		setLog(null);
		setPicker(null);
		setReadPending("choices");
		run("choices", task.id, "").then((result) => {
			if (request !== detailRequest.current || activeDetail.current !== task.id) return;
			setReadPending(null);
			let detail = {};
			try {
				detail = JSON.parse(result.detail || "{}");
			} catch {
				detail = {};
			}
			setPicker({
				models: detail.models ?? [],
				efforts: detail.efforts ?? {},
				flag: detail.effort_flag ?? "effort",
				model: detail.requested?.model ?? task.modelRequested ?? task.model,
				effort: detail.requested?.effort ?? "",
				allowed: result.ok && detail.allowed === true,
				reason: result.ok ? detail.reason ?? "" : result.message
			});
		}, (err) => {
			if (request !== detailRequest.current || activeDetail.current !== task.id) return;
			setReadPending(null);
			setNotice({
				ok: false,
				text: t("queue.a.readFailed", { message: err instanceof Error ? err.message : String(err) })
			});
		});
	};
	const loadLog = (task) => {
		if (run === void 0) return;
		setConfirm(null);
		const request = detailRequest.current;
		setPicker(null);
		setReadPending("log");
		run("log", task.id, "").then((result) => {
			if (request !== detailRequest.current || activeDetail.current !== task.id) return;
			setReadPending(null);
			let lines = [];
			try {
				lines = JSON.parse(result.detail || "{}").lines ?? [];
			} catch {
				lines = [];
			}
			setLog(result.ok ? lines : [result.message]);
		}, (err) => {
			if (request !== detailRequest.current || activeDetail.current !== task.id) return;
			setReadPending(null);
			setNotice({
				ok: false,
				text: t("queue.a.readFailed", { message: err instanceof Error ? err.message : String(err) })
			});
		});
	};
	const now = Date.now();
	const result = queueState.data.result;
	const dispatcher = result !== null && result.available;
	const rows = new Map(balanceState.rows.map((row) => [row.provider, row]));
	const sources = _panelSources(balanceState.data.result?.providers ?? [], result);
	const windowsOf = (agent) => agentWindows(rows, agent);
	const sourceOf = (agent) => {
		const join = PROVIDER_JOIN.find((j) => j.agent === agent);
		const queue = (result?.queues ?? []).find((q) => q.agent === agent);
		return {
			plan: join?.plan ?? null,
			row: join?.provider ? rows.get(join.provider) : void 0,
			pool: join?.kind === "pool" ? _poolPosition(result) : void 0,
			poolSize: join?.kind === "pool" ? result?.opencodePool?.length ?? 0 : 0,
			lane: dispatcher ? _slotLanes(result).find((l) => l.agent === agent) : void 0,
			quotaUntilMs: queue?.quotaUntilMs ?? null,
			quotaBy: queue?.quotaBy ?? ""
		};
	};
	const found = !dispatcher || detailId === null ? null : findTask(result, detailId) ?? (lastSeen.current?.task.id === detailId ? lastSeen.current : null);
	lastSeen.current = found;
	const ui = {
		open: (id) => {
			detailRequest.current += 1;
			activeDetail.current = id;
			setDetailId(id);
			setNotice(null);
			setPicker(null);
			setLog(null);
			setConfirm(null);
			setBrief(null);
			setReadPending(null);
		},
		act,
		busy,
		writable: run !== void 0 && dispatcher && result.ops?.available === true,
		confirm,
		askConfirm: setConfirm,
		picker,
		openPicker,
		setPicker,
		log,
		loadLog,
		brief,
		readPending,
		openBrief,
		openPath,
		windowsOf,
		sourceOf,
		rows
	};
	const lines = sources.map((source) => {
		const view = sourceView(source, source.provider === null ? void 0 : rows.get(source.provider.provider), result, t);
		return {
			source,
			view,
			reading: view.reading,
			text: view.queue?.text ?? ""
		};
	});
	const warn = lines.some((line) => line.reading.tone === "low" || line.reading.level === "low") || dispatcher && result.active.some((task) => task.waiting === "quota");
	const failed = queueState.data.error !== null && result === null || balanceState.data.error !== null && balanceState.rows.length === 0 || lines.some((line) => line.reading.tone === "stale");
	const railTone = warn ? "low" : failed ? "stale" : "none";
	const summary = lines.map((line) => [
		line.source.label,
		line.reading.value,
		line.reading.reset ?? "",
		line.text
	].filter((part) => part !== "").join(" ")).join(" · ");
	const toggle = (key, opener) => {
		openerRef.current = opener;
		setFocusKey(key);
		if (!open) place();
		setOpen(!open);
	};
	return h("div", {
		className: cx("pbc", "pbf", "tqf", "ppf", !props.wide && "rail"),
		ref: rootRef,
		"data-pp-warn": warn ? "true" : void 0
	}, props.wide ? h("div", {
		className: cx("pp-rows"),
		role: "group",
		"aria-label": t("panel.aria"),
		"data-clawock-action": BALANCE_PANEL
	}, lines.length === 0 ? h("button", {
		type: "button",
		className: cx("pp-row", "pp-empty"),
		"data-pp-row": "",
		"aria-expanded": open,
		"aria-haspopup": "dialog",
		"data-active": open ? "" : void 0,
		onClick: (event) => {
			toggle(null, event.currentTarget);
		}
	}, h("span", { className: cx("pp-name") }, t("panel.title")), h("span", { className: cx("tq-sub", "pp-last") }, balanceState.empty.title)) : lines.map(({ source, view, reading, text }) => h("button", {
		type: "button",
		key: source.key,
		className: cx("pp-row"),
		"data-tq-row": "source",
		"data-pp-row": source.key,
		"data-pb-provider": source.provider?.provider,
		"data-pb-role": source.provider === null ? void 0 : "chip",
		"data-balance-state": reading.tone,
		"data-active": open && focusKey === source.key ? "" : void 0,
		"aria-expanded": open,
		"aria-haspopup": "dialog",
		"aria-label": [
			source.label,
			reading.value,
			reading.reset ?? "",
			text,
			t("panel.openGroup", { name: source.label })
		].filter((part) => part !== "").join(" · "),
		title: reading.title,
		onClick: (event) => {
			toggle(source.key, event.currentTarget);
		}
	}, ...rowCells({
		...view,
		caption: []
	}, t).cells))) : h("button", {
		type: "button",
		className: cx("bchip", "pp-rail"),
		"data-clawock-action": BALANCE_PANEL,
		"data-balance-state": railTone,
		"data-active": open ? "" : void 0,
		"aria-expanded": open,
		"aria-haspopup": "dialog",
		"aria-label": t("panel.railTitle", { summary: (warn ? t("panel.warn") + " · " : "") + summary }),
		title: t("panel.railTitle", { summary }),
		onClick: (event) => {
			toggle(null, event.currentTarget);
		}
	}, h("span", {
		className: cx("bal-lead"),
		"data-balance-state": railTone
	}, renderBalanceGlyph(railTone, 18, instanceId))), h("div", panelAttrs(open, t("panel.aria"), {
		"data-clawock-popover": BALANCE_PANEL,
		...anchor === null ? {} : { style: {
			left: anchor.left + "px",
			bottom: anchor.bottom + "px",
			maxHeight: anchor.room + "px"
		} }
	}), h("div", {
		className: cx("tq-list"),
		key: "list",
		inert: found !== null ? "" : void 0,
		"aria-hidden": found !== null ? "true" : void 0
	}, renderProviderPanelBody(panelModel({
		balances: balanceState.data.result,
		balanceError: balanceState.data.error,
		queue: result,
		queueError: queueState.data.error
	}, t, now, ui.open), queueState, balanceState, t, ui, found === null ? notice : null)), found === null ? null : h("div", {
		className: cx("tq-layer"),
		key: "detail"
	}, renderTaskDetail(found, t, now, () => {
		closeDetail();
	}, backRef, ui, notice))));
}
function DecisionMind(props) {
	const t = props.t;
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
			else {
				const message = error instanceof LedgerUnreadable ? t("trace.unreadable") : messageOf(error);
				setData({
					trades: [],
					rate: null,
					loading: false,
					error: message,
					stale: false
				});
			}
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
	}, h("div", { className: cx("top") }, h("div", { className: cx("tin") }, h("div", { className: cx("tt") }, t("trace.title"), h("span", { className: cx("ts") }, t("trace.subtitle"))))), h("div", { className: cx("list") }, h(SkeletonRow, { key: "sk1" }), h(SkeletonRow, { key: "sk2" }), h(SkeletonRow, { key: "sk3" })));
	const traces = data.trades.map(_displayEntry);
	let filtered = traces;
	if (filter === "miss") filtered = traces.filter((trace) => trace.decision === null);
	if (filter === "sold") filtered = traces.filter((trace) => trace.side === "reduce");
	if (filter === "dec") filtered = traces.filter((trace) => trace.decision !== null);
	const sumRealized = (currency) => traces.filter((trace) => trace.realizedPnl !== null && trace.currency === currency).reduce((sum, trace) => sum + (trace.realizedPnl ?? 0), 0);
	const rate = data.rate;
	const hkdRealized = sumRealized("HKD");
	const totalUsd = sumRealized("USD") + (rate === null ? 0 : hkdRealized / rate);
	const totalLabel = rate === null && hkdRealized !== 0 ? t("trace.realizedUsdNoRate") : t("trace.realizedUsd");
	const sells = traces.filter((trace) => trace.side === "reduce");
	const sideless = traces.filter((trace) => trace.side === null).length;
	const sellsRated = sells.filter((trace) => trace.t1 !== null).length;
	const verdictIs = (trace, kind, text) => trace.t1 === null ? false : trace.t1.verdictKind == null ? trace.t1.verdict === text : trace.t1.verdictKind === kind;
	const soldEarly = sells.filter((trace) => verdictIs(trace, "soldEarly", "卖飞")).length;
	const soldRight = sells.filter((trace) => verdictIs(trace, "soldRight", "卖对")).length;
	const soldFlat = sells.filter((trace) => verdictIs(trace, "flat", "持平")).length;
	const matched = traces.filter((trace) => trace.decision !== null).length;
	const reversed = traces.filter((trace) => trace.decision?.alignment === "opposite").length;
	const groups = {};
	const traceKeys = _traceKeys(traces);
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
		}, h("span", { className: cx("chev") }, folded ? "▸" : "▾"), relativeDay(date, today, t), h("span", null, date), h("span", { className: cx("n") }, rows.length)), folded ? null : h("div", { className: cx("group") }, rows.map((trace) => {
			const key = traceKeys.get(trace);
			return h(TraceCell, {
				key,
				trace,
				t,
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
	}, t("trace.more", { fills: moreFills }));
	else if (visibleDateCount > DEFAULT_VISIBLE_DATES) moreButton = h("button", {
		key: "more",
		className: cx("trace-more"),
		onClick: () => {
			actions.resetDates();
		}
	}, t("trace.less", { groups: DEFAULT_VISIBLE_DATES }));
	let body;
	if (filtered.length === 0) body = h("div", { className: cx("empty") }, t("trace.empty"));
	else {
		const kids = visibleDates.map(renderDate);
		if (moreButton !== null) kids.push(moreButton);
		body = h("div", null, kids);
	}
	const stats = h("div", { className: cx("stats") }, h("div", { className: cx("sg") }, h("span", { className: cx("sl") }, totalLabel), h("span", { className: cx("sv", "focus", totalUsd >= 0 ? "up" : "down") }, _fmtMoney(totalUsd, "USD"))), h("div", { className: cx("sg") }, h("span", { className: cx("sl") }, t("trace.t1Tally", {
		rated: sellsRated,
		sells: sells.length
	}) + (sideless === 0 ? "" : t("trace.t1Sideless", { sideless }))), h("span", { className: cx("sv") }, h("span", { className: cx("down") }, soldEarly), " / ", h("span", { className: cx("up") }, soldRight), " / ", h("span", null, soldFlat))), h("div", { className: cx("sg") }, h("span", { className: cx("sl") }, t("trace.matched") + (reversed === 0 ? "" : t("trace.reversed", { reversed }))), h("span", { className: cx("sv") }, matched + "/" + traces.length)));
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
	}, t(FILTER_LABEL[value]))));
	return h("div", {
		className: cx("dmt"),
		ref: rootRef
	}, h("div", { className: cx("top") }, h("div", { className: cx("tin") }, h("div", { className: cx("tt") }, t("trace.title"), h("span", { className: cx("ts") }, t("trace.subtitle") + (data.stale ? t("trace.staleSuffix") : "")), h("span", { className: cx("rate") }, t("trace.fillCount", { count: traces.length }) + (rate === null ? "" : " · @" + rate))), stats)), h("div", { className: cx("bar") }, h("div", { className: cx("bin") }, filters)), h("div", { className: cx("list") }, body));
}
/**
* `layout` is listed even though the plugin only *probes* it, and that is not
* an oversight — it is the one thing `ctx.get` cannot do here. The probe runs
* inside `apply`, and `ctx.get` does not wait: it returns `undefined` when the
* providing fiber has not activated yet, so the chip silently fell back to the
* session-header seat (verified live, 2026-09-19 — `[data-clawock-action]`
* count 0 while the header chip rendered). `inject` is the mechanism that
* holds the plugin until the service exists.
*
* The cost is real and accepted: on a host with no `layout` at all, the whole
* client half waits and the Decision Mind tab does not mount either. Every
* shipped host provides it, and the alternative trades a hypothetical
* older-host degradation for a measured one on the host we run.
*/
const inject = [
	"slots",
	"remote",
	"layout",
	"locale"
];
/** Register the Decision Mind tab into the conversation view ring. */
async function apply(ctx) {
	ctx.effect(() => ctx.locale.register(LOCALE_NS, dictionaries), "clawock-dsh: dictionaries");
	await ctx.remote.$mount(TYPERT_REMOTE);
	const studioRemote = ctx.get("remote.clawockStudio");
	const layout = ctx.layout;
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
			if (result.lastUpdated === null) throw new LedgerUnreadable("portfolio.json unreadable");
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
	const balanceListeners = /* @__PURE__ */ new Set();
	const balancesInjected = () => ({
		cachedBalances: () => cachedBalances,
		fetchBalances: async (force) => {
			const result = await call("balance", [force]);
			cachedBalances = result;
			for (const listener of balanceListeners) listener(result);
			return result;
		},
		subscribeBalances: (listener) => {
			balanceListeners.add(listener);
			return () => {
				balanceListeners.delete(listener);
			};
		}
	});
	const store = createDecisionMindStore();
	ctx.slots.inject("conversation.view", () => ctx.slots.register({
		name: "conversation.view",
		id: "decision-studio",
		order: 30,
		label: () => "Decision Mind",
		store,
		locale: LOCALE_NS,
		inject: injected
	}, DecisionMind));
	const balancesStore = createBalanceStore();
	if (typeof layout?.selectPanel === "function") {
		let cachedTaskQueue = null;
		const openFile = (path) => {
			const sidebar = ctx.get("sidebarRight");
			if (sidebar === void 0 || typeof sidebar.openResource !== "function") return {
				ok: false,
				reason: "no-service"
			};
			const session = sidebar.mounted?.getSnapshot();
			if (typeof session !== "string" || session === "") return {
				ok: false,
				reason: "no-session"
			};
			try {
				sidebar.openResource(_sessionFileAddress(session, path));
				return { ok: true };
			} catch (err) {
				return {
					ok: false,
					reason: "error",
					message: err instanceof Error ? err.message : String(err)
				};
			}
		};
		ctx.slots.inject("sidebar.footer.action", () => ctx.slots.register({
			name: "sidebar.footer.action",
			id: "provider-balance",
			store: balancesStore,
			locale: LOCALE_NS,
			inject: () => ({
				...balancesInjected(),
				cachedTaskQueue: () => cachedTaskQueue,
				fetchTaskQueue: async (force) => {
					cachedTaskQueue = await call("taskQueue", [force]);
					return cachedTaskQueue;
				},
				runQueueAction: typeof studioRemote.queueAction === "function" ? (action, id, arg) => call("queueAction", [
					action,
					id,
					arg
				]) : void 0,
				openFile
			})
		}, ProviderPanelSidebarAction));
	} else ctx.slots.inject("conversation.session.header.utilities", () => ctx.slots.register({
		name: "conversation.session.header.utilities",
		id: "provider-balance",
		order: 90,
		store: balancesStore,
		locale: LOCALE_NS,
		inject: balancesInjected
	}, ProviderBalanceChip));
}
//#endregion

    Object.assign(exports, { BALANCE_PANEL, DETAIL_ACTIONS, DETAIL_FIELDS, DETAIL_FOLDED, DETAIL_SECTIONS, DecisionMind, FACT_CELL, FACT_ORDER, LOCALE_NS, ProviderBalanceChip, ProviderPanelSidebarAction, RESIDENT_CHIPS, ROW_KINDS, STATE_ROLES, _agentLabel, _balanceNote, _costOf, _describeAction, _displayEntry, _endedState, _fmtMoney, _fmtPct, _fmtTokens, _modelView, _notifyState, _panelSources, _patrolReason, _poolPosition, _queueHeadline, _queueState, _rowDisplay, _sessionFileAddress, _slotLanes, _slotOf, _taskState, _taskStatus, _traceKeys, _usedLevel, apply, createBalanceStore, createDecisionMindStore, createTranslator, dictionaries, inject, resetStampOf, t1ChipClass, t1NodeClass, verdictOf, windowLabelOf, windowsOf });
    return module.exports;
  }
});
