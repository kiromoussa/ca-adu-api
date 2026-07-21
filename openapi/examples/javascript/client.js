// Shared minimal client helper for the ADU Atlas API, used by the other
// examples in this directory. Plain JavaScript (ESM), Node 18+ or any
// modern browser with global fetch. No external dependencies.
//
// Pick ONE auth mode. Never send RapidAPI headers and X-API-Key together.

// The RapidAPI Hub endpoint paths were registered WITHOUT the /v1 prefix (the
// origin's /v1 base path lives in the provider's Base URL setting on the
// Hub, invisible to consumers). property-feasibility4.p.rapidapi.com/feasibility
// maps to https://adu-atlas-api.onrender.com/v1/feasibility on the origin.
const RAPIDAPI_BASE_URL = "https://property-feasibility4.p.rapidapi.com";
const DIRECT_BASE_URL = "https://api.aduatlas.example.com";
const DEFAULT_RAPIDAPI_HOST = "property-feasibility4.p.rapidapi.com";

export function buildHeaders(config) {
  if (config.mode === "rapidapi") {
    if (!config.rapidApiKey) {
      throw new Error("rapidApiKey is required when mode is 'rapidapi'");
    }
    return {
      "Content-Type": "application/json",
      "X-RapidAPI-Key": config.rapidApiKey,
      "X-RapidAPI-Host": config.rapidApiHost || DEFAULT_RAPIDAPI_HOST,
    };
  }
  if (!config.apiKey) {
    throw new Error("apiKey is required when mode is 'direct'");
  }
  return {
    "Content-Type": "application/json",
    "X-API-Key": config.apiKey,
  };
}

export function baseUrl(config) {
  if (config.baseUrl) return config.baseUrl;
  return config.mode === "rapidapi" ? RAPIDAPI_BASE_URL : DIRECT_BASE_URL;
}

export class AduAtlasApiError extends Error {
  constructor(status, body) {
    super(body.error.message);
    this.name = "AduAtlasApiError";
    this.status = status;
    this.code = body.error.code;
    this.requestId = body.error.request_id || null;
    this.details = body.error.details || null;
  }
}

// Every example in this directory writes paths with the /v1 prefix (the
// origin's real path). RapidAPI's Hub-registered endpoint paths omit that
// prefix, so this strips it automatically when mode is "rapidapi".
export function consumerPath(config, path) {
  if (config.mode === "rapidapi" && path.startsWith("/v1/")) {
    return path.slice("/v1".length);
  }
  return path;
}

export async function aduAtlasRequest(config, path, init = {}) {
  const res = await fetch(`${baseUrl(config)}${consumerPath(config, path)}`, {
    ...init,
    headers: {
      ...buildHeaders(config),
      ...(init.headers || {}),
    },
  });

  const body = await res.json();

  if (!res.ok) {
    throw new AduAtlasApiError(res.status, body);
  }

  return body;
}
